from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import JWTError, jwt
from typing import Optional, Dict
from redis import Redis
import secrets
from ..config.settings import settings
import logging

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class SecurityManager:
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.token_blacklist_prefix = "token_blacklist:"
        self.rate_limit_prefix = "rate_limit:"

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)

    def get_password_hash(self, password: str) -> str:
        return pwd_context.hash(password)

    def create_access_token(
            self,
            data: Dict,
            expires_delta: Optional[timedelta] = None
    ) -> str:
        to_encode = data.copy()
        expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
        to_encode.update({"exp": expire})
        token = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

        # Store token metadata in Redis
        self.redis.setex(
            f"token_meta:{token}",
            settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            str(data.get("sub"))
        )

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
        self.redis.setex(
            f"{self.token_blacklist_prefix}{token}",
            settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "1"
        )

    async def is_token_blacklisted(self, token: str) -> bool:
        return bool(self.redis.get(f"{self.token_blacklist_prefix}{token}"))

    def generate_api_key(self) -> str:
        return secrets.token_urlsafe(32)

    def store_api_key(self, api_key: str, user_id: str, expires_in_days: int = 30):
        self.redis.setex(
            f"api_key:{api_key}",
            expires_in_days * 24 * 60 * 60,
            user_id
        )

    async def validate_api_key(self, api_key: str) -> Optional[str]:
        return self.redis.get(f"api_key:{api_key}")

    async def revoke_api_key(self, api_key: str):
        self.redis.delete(f"api_key:{api_key}")

    def rotate_secret_key(self) -> str:
        new_key = secrets.token_urlsafe(64)
        old_key = settings.SECRET_KEY
        settings.SECRET_KEY = new_key
        return old_key

    async def check_rate_limit(
            self,
            key: str,
            limit: int,
            window: int = 60
    ) -> bool:
        current = self.redis.get(f"{self.rate_limit_prefix}{key}")
        if current and int(current) >= limit:
            return False

        pipe = self.redis.pipeline()
        pipe.incr(f"{self.rate_limit_prefix}{key}")
        pipe.expire(f"{self.rate_limit_prefix}{key}", window)
        pipe.execute()

        return True