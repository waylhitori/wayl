
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import router as api_router
from ..web.routes import router as web_router
from ..config.settings import settings
from ..config.logging import setup_logging

app = FastAPI(
   title=settings.APP_NAME,
   version="1.0.0",
   description="Enterprise AI Agent Platform"
)

app.add_middleware(
   CORSMiddleware,
   allow_origins=["*"],
   allow_credentials=True,
   allow_methods=["*"],
   allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)
app.include_router(web_router)

logger = setup_logging(settings.APP_NAME)