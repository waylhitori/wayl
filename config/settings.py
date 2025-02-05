
from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    # Application settings
    APP_NAME: str = "Wayl AI"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "!")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "!")

    # Blockchain
    SOLANA_RPC_URL: str = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    WAYL_TOKEN_ADDRESS: str = os.getenv("!")

    # Model settings
    MODELS_DIR: str = os.getenv("MODELS_DIR", "./models")
    MODEL_CACHE_SIZE: int = 2
    DEFAULT_MODEL: str = "deepseek!"

    # Rate limiting
    DEFAULT_RATE_LIMIT: int = 10
    RATE_LIMIT_WINDOW: int = 60  # seconds


settings = Settings()