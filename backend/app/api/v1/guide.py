"""Usage-guide progress endpoints."""
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database import get_db
from app.models.guide import UserGuideProgress
from app.models.user import User

router = APIRouter(prefix="/guide", tags=["使用说明"])


class GuideProgressResponse(BaseModel):
    overview_seen: bool
    modules: dict[str, bool]


class GuideSeenRequest(BaseModel):
    scope: Literal["overview", "module"]
    module_id: Optional[str] = Field(default=None, max_length=80)


def _get_or_create_progress(db: Session, user_id: str) -> UserGuideProgress:
    progress = db.query(UserGuideProgress).filter(UserGuideProgress.user_id == user_id).first()
    if progress is None:
        progress = UserGuideProgress(user_id=user_id, overview_seen=False, modules={})
        db.add(progress)
        db.flush()
    return progress


def _response(progress: UserGuideProgress) -> GuideProgressResponse:
    modules = progress.modules if isinstance(progress.modules, dict) else {}
    return GuideProgressResponse(
        overview_seen=bool(progress.overview_seen),
        modules={str(key): bool(value) for key, value in modules.items()},
    )


def _apply_guide_seen(progress: UserGuideProgress, scope: str, module_id: Optional[str] = None) -> None:
    if scope == "overview":
        progress.overview_seen = True
    else:
        if not module_id:
            raise HTTPException(status_code=422, detail="缺少板块标识")
        modules = dict(progress.modules or {})
        modules[module_id] = True
        progress.modules = modules
    progress.updated_at = datetime.utcnow()


@router.get("/progress", response_model=GuideProgressResponse)
async def get_guide_progress(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    progress = _get_or_create_progress(db, current_user.id)
    db.commit()
    return _response(progress)


@router.post("/seen", response_model=GuideProgressResponse)
async def mark_guide_seen(
    payload: GuideSeenRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    progress = _get_or_create_progress(db, current_user.id)
    _apply_guide_seen(progress, payload.scope, payload.module_id)
    db.commit()
    db.refresh(progress)
    return _response(progress)