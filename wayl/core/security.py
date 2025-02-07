from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import JWTError, jwt
from typing import Optional, Dict
from redis import Redis
import secrets
from ..config.settings import settings
import logging
from fastapi import HTTPException, status
import asyncio

import hashlib
import bcrypt
from typing import Optional
import re

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class SecurityManager:
    def __init__(self, redis_client: Optional[Redis] = None):
        self.redis = redis_client
        self.token_blacklist_prefix = "token_blacklist:"
        self.rate_limit_prefix = "rate_limit:"
        self._lock = asyncio.Lock()
        self._local_storage: Dict[str, str] = {}

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)

    def get_password_hash(self, password: str) -> str:
        return pwd_context.hash(password)

    async def create_access_token(
            self,
            data: Dict,
            expires_delta: Optional[timedelta] = None
    ) -> str:
        to_encode = data.copy()
        expire = datetime.utcnow() + (
            expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        to_encode.update({"exp": expire})
        token = jwt.encode(
            to_encode,
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM
        )

        if self.redis:
            await self._store_token_metadata(token, data.get("sub"))
        return token

    async def verify_token(self, token: str) -> Optional[Dict]:
        try:
            if await self.is_token_blacklisted(token):
                return None

            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM]
            )

            if payload.get("exp") < datetime.utcnow().timestamp():
                await self.blacklist_token(token)
                return None

            return payload

        except JWTError:
            return None

    async def blacklist_token(self, token: str):
        async with self._lock:
            if self.redis:
                await self.redis.setex(
                    f"{self.token_blacklist_prefix}{token}",
                    settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                    "1"
                )
            else:
                self._local_storage[f"{self.token_blacklist_prefix}{token}"] = "1"

    async def is_token_blacklisted(self, token: str) -> bool:
        if self.redis:
            return bool(await self.redis.get(f"{self.token_blacklist_prefix}{token}"))
        return bool(self._local_storage.get(f"{self.token_blacklist_prefix}{token}"))

    def generate_api_key(self) -> str:
        return secrets.token_urlsafe(32)

    async def store_api_key(
        self,
        api_key: str,
        user_id: str,
        expires_in_days: int = 30
    ):
        if self.redis:
            await self.redis.setex(
                f"api_key:{api_key}",
                expires_in_days * 24 * 60 * 60,
                user_id
            )
        else:
            self._local_storage[f"api_key:{api_key}"] = user_id

    async def validate_api_key(self, api_key: str) -> Optional[str]:
        if self.redis:
            return await self.redis.get(f"api_key:{api_key}")
        return self._local_storage.get(f"api_key:{api_key}")

    async def revoke_api_key(self, api_key: str):
        if self.redis:
            await self.redis.delete(f"api_key:{api_key}")
        else:
            self._local_storage.pop(f"api_key:{api_key}", None)

    async def rotate_secret_key(self) -> str:
        old_key = settings.SECRET_KEY
        new_key = secrets.token_urlsafe(64)
        settings.SECRET_KEY = new_key
        return old_key

    async def check_rate_limit(
        self,
        key: str,
        limit: int,
        window: int = 60
    ) -> bool:
        async with self._lock:
            if self.redis:
                current = await self.redis.get(f"{self.rate_limit_prefix}{key}")
                if current and int(current) >= limit:
                    return False

                pipe = self.redis.pipeline()
                pipe.incr(f"{self.rate_limit_prefix}{key}")
                pipe.expire(f"{self.rate_limit_prefix}{key}", window)
                await pipe.execute()
            else:
                current = self._local_storage.get(f"{self.rate_limit_prefix}{key}", 0)
                if current >= limit:
                    return False
                self._local_storage[f"{self.rate_limit_prefix}{key}"] = current + 1

            return True

    async def _store_token_metadata(self, token: str, user_id: str):
        if self.redis:
            await self.redis.setex(
                f"token_meta:{token}",
                settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                str(user_id)
            )

    def validate_password_strength(self, password: str) -> bool:
        """
        Password must:
        - Be at least 8 characters long
        - Contain at least one uppercase letter
        - Contain at least one lowercase letter
        - Contain at least one number
        - Contain at least one special character
        """
        if len(password) < 8:
            return False
        if not re.search(r"[A-Z]", password):
            return False
        if not re.search(r"[a-z]", password):
            return False
        if not re.search(r"\d", password):
            return False
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            return False
        return True

    def hash_api_key(self, api_key: str) -> str:
        """Create a secure hash of the API key"""
        return hashlib.blake2b(api_key.encode()).hexdigest()

    async def rotate_all_user_tokens(self, user_id: str) -> None:
        """Invalidate all tokens for a user"""
        if self.redis:
            pattern = f"user_token:{user_id}:*"
            keys = await self.redis.keys(pattern)
            if keys:
                await self.redis.delete(*keys)

    def generate_secure_token(self, length: int = 32) -> str:
        """Generate a cryptographically secure token"""
        return secrets.token_urlsafe(length)

    def _hash_password(self, password: str) -> str:
        """Internal method to hash passwords with bcrypt"""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode(), salt).decode()

