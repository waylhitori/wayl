from typing import Dict, Optional, List
from solana.rpc.api import Client
from spl.token.client import Token
from spl.token.constants import TOKEN_PROGRAM_ID
from solana.keypair import Keypair
import asyncio
import logging
from datetime import datetime
from ..config.settings import settings

logger = logging.getLogger(__name__)


class TransactionFailedException(Exception):
    pass


class WAYLToken:
    def __init__(
            self,
            token_address: str,
            rpc_url: str,
            decimals: int = 9
    ):
        self.token_address = token_address
        self.client = Client(rpc_url)
        self.decimals = decimals
        self.transaction_timeout = 60  # seconds
        self.max_retries = 3

    async def get_token_balance(self, wallet_address: str) -> float:
        try:
            response = await self.client.get_token_account_balance(wallet_address)
            amount = response['result']['value']['amount']
            return float(amount) / (10 ** self.decimals)
        except Exception as e:
            logger.error(f"Failed to get token balance: {str(e)}")
            raise Exception(f"Failed to get token balance: {str(e)}")

    async def process_transaction(
            self,
            tx_hash: str,
            retries: int = 3,
            backoff_factor: int = 2
    ) -> bool:
        for attempt in range(retries):
            try:
                start_time = datetime.now()
                while (datetime.now() - start_time).seconds < self.transaction_timeout:
                    receipt = await self.client.get_transaction_receipt(tx_hash)

                    if receipt['status'] == 1:
                        logger.info(f"Transaction {tx_hash} confirmed successfully")
                        return True
                    elif receipt['status'] == 0:
                        error_msg = f"Transaction {tx_hash} failed"
                        logger.error(error_msg)
                        raise TransactionFailedException(error_msg)

                    await asyncio.sleep(backoff_factor ** attempt)

                raise TimeoutError(f"Transaction {tx_hash} confirmation timeout")

            except Exception as e:
                if attempt == retries - 1:
                    logger.error(f"Final attempt failed for transaction {tx_hash}: {str(e)}")
                    raise
                logger.warning(f"Attempt {attempt + 1} failed, retrying...")
                continue

    async def transfer_tokens(
            self,
            from_keypair: Keypair,
            to_address: str,
            amount: float
    ) -> str:
        try:
            amount_raw = int(amount * (10 ** self.decimals))

            transaction = await Token.create_transfer_instruction(
                token_program_id=TOKEN_PROGRAM_ID,
                source=from_keypair.public_key,
                dest=to_address,
                owner=from_keypair.public_key,
                amount=amount_raw
            )

            signature = await self.client.send_transaction(
                transaction,
                from_keypair
            )

            success = await self.process_transaction(signature)
            if success:
                return signature
            raise TransactionFailedException("Token transfer failed")

        except Exception as e:
            logger.error(f"Token transfer failed: {str(e)}")
            raise

    def get_token_level(self, token_amount: float) -> int:
        levels = {
            1_000_000: 5,  # Diamond
            100_000: 4,  # Platinum
            10_000: 3,  # Gold
            1_000: 2,  # Silver
            100: 1  # Bronze
        }

        for threshold, level in sorted(levels.items(), reverse=True):
            if token_amount >= threshold:
                return level
        return 0  # Basic level

    def get_level_benefits(self, level: int) -> Dict:
        benefits = {
            0: {  # Basic
                "daily_requests": 100,
                "max_agents": 2,
                "advanced_features": False,
                "api_rate_limit": 10,
                "model_access": ["deepseek-7b"],
                "support_level": "community"
            },
            1: {  # Bronze
                "daily_requests": 1000,
                "max_agents": 5,
                "advanced_features": False,
                "api_rate_limit": 20,
                "model_access": ["deepseek-7b", "deepseek-13b"],
                "support_level": "email"
            },
            2: {  # Silver
                "daily_requests": 5000,
                "max_agents": 10,
                "advanced_features": True,
                "api_rate_limit": 50,
                "model_access": ["deepseek-7b", "deepseek-13b", "deepseek-33b"],
                "support_level": "priority"
            },
            3: {  # Gold
                "daily_requests": 20000,
                "max_agents": 25,
                "advanced_features": True,
                "api_rate_limit": 100,
                "model_access": ["deepseek-7b", "deepseek-13b", "deepseek-33b", "deepseek-67b"],
                "support_level": "dedicated"
            },
            4: {  # Platinum
                "daily_requests": 100000,
                "max_agents": 50,
                "advanced_features": True,
                "api_rate_limit": 200,
                "model_access": ["all"],
                "support_level": "enterprise"
            },
            5: {  # Diamond
                "daily_requests": "unlimited",
                "max_agents": 100,
                "advanced_features": True,
                "api_rate_limit": 500,
                "model_access": ["all"],
                "support_level": "white_glove"
            }
        }
        return benefits.get(level, benefits[0])

    async def get_transaction_history(
            self,
            address: str,
            limit: int = 50,
            offset: int = 0
    ) -> List[Dict]:
        try:
            history = []
            signatures = await self.client.get_signatures_for_address(
                address,
                limit=limit,
                before=offset
            )

            for sig in signatures['result']:
                tx = await self.client.get_transaction(
                    sig['signature'],
                    encoding="jsonParsed"
                )
                if tx['result']:
                    history.append({
                        'signature': sig['signature'],
                        'timestamp': sig['blockTime'],
                        'success': sig['err'] is None,
                        'amount': self._parse_token_amount(tx['result']),
                        'type': self._determine_transaction_type(tx['result']),
                        'fee': tx['result']['meta']['fee'] / 1e9
                    })

            return history

        except Exception as e:
            logger.error(f"Failed to get transaction history: {str(e)}")
            raise

    def _parse_token_amount(self, transaction: Dict) -> float:
        try:
            for instruction in transaction['meta']['innerInstructions']:
                if 'tokenAmount' in instruction:
                    return float(instruction['tokenAmount']['uiAmount'])
            return 0.0
        except:
            return 0.0

    def _determine_transaction_type(self, transaction: Dict) -> str:
        program_id = transaction['transaction']['message']['accountKeys'][0]
        if program_id == TOKEN_PROGRAM_ID:
            return "transfer"
        return "unknown"