from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.meta import router as meta_router
from app.api.routes.trading import router as trading_router

router = APIRouter(prefix="/api/v1")
router.include_router(meta_router)
router.include_router(health_router)
router.include_router(trading_router)
