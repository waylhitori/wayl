from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from ...services.auth_service import AuthService
from ...db.database import get_db
from sqlalchemy.orm import Session
from ...core.security import SecurityManager
from typing import Dict
from ..schemas.auth import (
    UserCreate,
    UserResponse,
    TokenResponse,
    WalletConnect
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
        user_data: UserCreate,
        db: Session = Depends(get_db),
        auth_service: AuthService = Depends()
):
    try:
        user = await auth_service.create_user(user_data)
        return user
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/token", response_model=TokenResponse)
async def login(
        form_data: OAuth2PasswordRequestForm = Depends(),
        db: Session = Depends(get_db),
        auth_service: AuthService = Depends()
):
    user = await auth_service.authenticate_user(
        form_data.username,
        form_data.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = await auth_service.create_access_token(
        data={"sub": str(user.id)}
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": str(user.id)
    }


@router.post("/wallet/connect", response_model=Dict)
async def connect_wallet(
        wallet_data: WalletConnect,
        db: Session = Depends(get_db),
        auth_service: AuthService = Depends()
):
    try:
        result = await auth_service.connect_wallet(
            user_id=wallet_data.user_id,
            wallet_address=wallet_data.wallet_address,
            signature=wallet_data.signature
        )
        return {"status": "success", "data": result}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/api-key", response_model=Dict)
async def create_api_key(
        db: Session = Depends(get_db),
        auth_service: AuthService = Depends(),
        security: SecurityManager = Depends()
):
    api_key = security.generate_api_key()
    expires_in_days = 30

    await security.store_api_key(
        api_key=api_key,
        user_id=auth_service.current_user.id,
        expires_in_days=expires_in_days
    )

    return {
        "api_key": api_key,
        "expires_in_days": expires_in_days
    }


@router.delete("/api-key/{api_key}")
async def revoke_api_key(
        api_key: str,
        security: SecurityManager = Depends(),
        auth_service: AuthService = Depends()
):
    await security.revoke_api_key(api_key)
    return {"status": "success"}