from typing import Optional, Dict
from uuid import UUID
from ..db import crud
from ..core.security import SecurityManager
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..db.models import User
from eth_account.messages import encode_defunct
from web3 import Web3
import logging

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(
            self,
            security: SecurityManager = Depends(),
            db: Session = Depends(get_db)
    ):
        self.security = security
        self.db = db
        self.web3 = Web3()

    async def create_user(self, user_data: Dict) -> User:
        if await crud.get_user_by_username(user_data["username"], self.db):
            raise ValueError("Username already registered")

        if await crud.get_user_by_email(user_data["email"], self.db):
            raise ValueError("Email already registered")

        hashed_password = self.security.get_password_hash(user_data["password"])
        user_data["hashed_password"] = hashed_password
        del user_data["password"]

        return await crud.create_user(user_data, self.db)

    async def authenticate_user(
            self,
            username: str,
            password: str
    ) -> Optional[User]:
        user = await crud.get_user_by_username(username, self.db)
        if not user:
            return None

        if not self.security.verify_password(password, user.hashed_password):
            return None

        return user

    async def create_access_token(self, data: Dict) -> str:
        return await self.security.create_access_token(data)

    async def connect_wallet(
            self,
            user_id: UUID,
            wallet_address: str,
            signature: str
    ) -> Dict:
        user = await crud.get_user(user_id, self.db)
        if not user:
            raise ValueError("User not found")

        if user.wallet_address:
            raise ValueError("Wallet already connected")

        # Verify wallet signature
        message = f"Connect wallet {wallet_address} to WAYL AI Platform user {user_id}"
        message_hash = encode_defunct(text=message)
        recovered_address = self.web3.eth.account.recover_message(
            message_hash,
            signature=signature
        )

        if recovered_address.lower() != wallet_address.lower():
            raise ValueError("Invalid signature")

        # Update user's wallet address
        user = await crud.update_user(
            user_id,
            {"wallet_address": wallet_address},
            self.db
        )

        return {
            "user_id": str(user.id),
            "wallet_address": wallet_address,
            "connected_at": user.updated_at.isoformat()
        }

    async def disconnect_wallet(self, user_id: UUID) -> Dict:
        user = await crud.get_user(user_id, self.db)
        if not user:
            raise ValueError("User not found")

        if not user.wallet_address:
            raise ValueError("No wallet connected")

        user = await crud.update_user(
            user_id,
            {"wallet_address": None},
            self.db
        )

        return {
            "user_id": str(user.id),
            "disconnected_at": user.updated_at.isoformat()
        }

    async def verify_api_key(self, api_key: str) -> Optional[User]:
        user_id = await self.security.validate_api_key(api_key)
        if not user_id:
            return None

        return await crud.get_user(UUID(user_id), self.db)

    async def revoke_all_tokens(self, user_id: UUID):
        user = await crud.get_user(user_id, self.db)
        if not user:
            raise ValueError("User not found")

        await self.security.revoke_all_user_tokens(str(user_id))