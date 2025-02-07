from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from ..db.crud import get_user
from ..core.security import SecurityManager
from ..db.models import User
from typing import Optional

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
security = SecurityManager()


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = await security.verify_token(token)
        if payload is None:
            raise credentials_exception

        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except:
        raise credentials_exception

    user = await get_user(user_id)
    if user is None:
        raise credentials_exception

    return user


async def get_optional_user(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[User]:
    if not token:
        return None
    try:
        return await get_current_user(token)
    except HTTPException:
        return None