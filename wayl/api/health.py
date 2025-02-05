
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db.database import get_db

router = APIRouter()

@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        # Database check
        db.execute("SELECT 1")
        db_status = "healthy"
    except Exception:
        db_status = "unhealthy"

    return {
        "status": "ok" if db_status == "healthy" else "error",
        "details": {
            "database": db_status
        }
    }