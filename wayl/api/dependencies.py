from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from redis import Redis
from jose import JWTError, jwt
from typing import Optional
from ..db.models import User
from ..db.crud import get_user
from ..config.settings import settings
from ..services.payment_service import PaymentService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
redis_client = Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    password=settings.REDIS_PASSWORD,
    db=settings.REDIS_DB,
    decode_responses=True
)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = await get_user(user_id)
    if user is None:
        raise credentials_exception

    return user


def get_redis() -> Redis:
    return redis_client


async def validate_token_balance(
        user_id: str,
        minimum_balance: Optional[float] = None,
        payment_service: PaymentService = Depends()
) -> None:
    token_info = await payment_service.get_token_info(user_id)

    if minimum_balance and token_info["balance"] < minimum_balance:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "Insufficient token balance",
                "required": minimum_balance,
                "current": token_info["balance"]
            }
        )

    if token_info["level"] == 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token balance too low for API access"
        )


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user


async def check_api_key(api_key: str = Depends(oauth2_scheme)) -> None:
    key = redis_client.get(f"api_key:{api_key}")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )