from typing import Dict, Optional, List
from uuid import UUID
from ..blockchain.token import WAYLToken
from ..db import crud
from ..db.models import PaymentRecord
from fastapi import HTTPException, Depends
import logging
from prometheus_client import Counter, Histogram
from sqlalchemy.orm import Session
from ..db.database import get_db
import time

logger = logging.getLogger(__name__)

# Metrics
payment_requests = Counter('payment_requests_total', 'Total payment requests')
payment_processing_time = Histogram('payment_processing_seconds', 'Payment processing time')
failed_payments = Counter('failed_payments_total', 'Failed payment attempts')


class PaymentService:
    def __init__(
            self,
            token_client: WAYLToken,
            db: Session = Depends(get_db)
    ):
        self.token_client = token_client
        self.db = db
        self.usage_cache = {}
        self._cached_benefits = {}

    async def get_token_info(self, user_id: UUID) -> Dict:
        try:
            user = await crud.get_user(user_id, self.db)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            balance = await self.token_client.get_token_balance(user.wallet_address)
            level = self.token_client.get_token_level(balance)
            benefits = await self._get_cached_benefits(level)
            usage = await crud.get_today_usage(user_id, self.db)

            return {
                "address": user.wallet_address,
                "balance": balance,
                "level": level,
                "benefits": benefits,
                "today_usage": {
                    "requests": usage.request_count,
                    "tokens": usage.tokens_used
                }
            }
        except Exception as e:
            logger.error(f"Error getting token info: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to get token info")

    async def check_user_limits(self, user_id: UUID):
        token_info = await self.get_token_info(user_id)
        usage = await crud.get_today_usage(user_id, self.db)

        if usage.request_count >= token_info["benefits"]["daily_requests"]:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Daily request limit exceeded",
                    "limit": token_info["benefits"]["daily_requests"],
                    "current": usage.request_count,
                    "reset_at": usage.date.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                }
            )

    async def process_payment(
            self,
            user_id: UUID,
            amount: float,
            description: str
    ) -> PaymentRecord:
        payment_requests.inc()
        start_time = time.time()

        try:
            user = await crud.get_user(user_id, self.db)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            balance = await self.token_client.get_token_balance(user.wallet_address)

            if balance < amount:
                failed_payments.inc()
                raise HTTPException(
                    status_code=402,
                    detail={
                        "error": "Insufficient token balance",
                        "required": amount,
                        "current": balance
                    }
                )

            tx_hash = await self.token_client.transfer_tokens(
                from_keypair=user.wallet_address,
                to_address=self.token_client.token_address,
                amount=amount
            )

            success = await self.token_client.process_transaction(tx_hash)
            if not success:
                failed_payments.inc()
                raise HTTPException(status_code=500, detail="Payment transaction failed")

            payment_record = await self._record_payment(user_id, amount, tx_hash, description)
            payment_processing_time.observe(time.time() - start_time)

            return payment_record

        except Exception as e:
            failed_payments.inc()
            logger.error(f"Payment processing error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Payment processing failed: {str(e)}"
            )

    async def get_payment_history(
            self,
            user_id: UUID,
            limit: int = 50,
            offset: int = 0
    ) -> List[PaymentRecord]:
        try:
            return await crud.get_user_payment_records(
                user_id=user_id,
                db=self.db,
                limit=limit,
                offset=offset
            )
        except Exception as e:
            logger.error(f"Error fetching payment history: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Failed to fetch payment history"
            )

    async def _record_payment(
            self,
            user_id: UUID,
            amount: float,
            tx_hash: str,
            description: str
    ) -> PaymentRecord:
        try:
            return await crud.create_payment_record(
                user_id=user_id,
                amount=amount,
                tx_hash=tx_hash,
                description=description,
                db=self.db
            )
        except Exception as e:
            logger.error(f"Error recording payment: {str(e)}")
            raise

    async def _get_cached_benefits(self, level: int) -> Dict:
        cache_key = f"benefits_level_{level}"
        if cache_key not in self._cached_benefits:
            self._cached_benefits[cache_key] = self.token_client.get_level_benefits(level)
        return self._cached_benefits[cache_key]

    async def update_usage_metrics(
            self,
            user_id: UUID,
            input_tokens: int,
            output_tokens: int
    ):
        total_tokens = input_tokens + output_tokens
        try:
            await crud.update_usage_record(
                user_id=user_id,
                tokens_used=total_tokens,
                db=self.db
            )
        except Exception as e:
            logger.error(f"Error updating usage metrics: {str(e)}")