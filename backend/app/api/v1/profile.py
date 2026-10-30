"""
User profile API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta

from app.database import get_db
from app.models.user import User
from app.models.profile import UserSkillLevel
from app.models.practice import PracticeSession, PracticeSummary
from app.schemas.auth import UserResponse
from app.schemas.profile import (
    UserProfileResponse,
    UserProfileStats,
    SkillLevel,
    SkillLevelUpdate,
    UserStatsResponse,
    AvatarUpdate,
)
from app.core.security import get_current_user

router = APIRouter(prefix="/users", tags=["用户"])


@router.get("/me/profile", response_model=UserProfileResponse)
async def get_user_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get current user full profile with statistics
    """
    # Calculate stats
    sessions = db.query(PracticeSession).filter(
        PracticeSession.user_id == current_user.id
    ).all()

    total_sessions = len(sessions)
    total_messages = sum(s.message_count or 0 for s in sessions)
    total_duration = sum(
        (s.ended_at - s.started_at).seconds / 60 if s.started_at and s.ended_at else 0
        for s in sessions
    )

    # Get recent scores — PracticeSummary 没有 user_id 列，只能通过 session 关联
    user_session_ids = [s.id for s in sessions]
    if user_session_ids:
        summaries = (
            db.query(PracticeSummary)
            .filter(PracticeSummary.session_id.in_(user_session_ids))
            .order_by(PracticeSummary.created_at.desc())
            .limit(10)
            .all()
        )
    else:
        summaries = []

    avg_scores = {}
    if summaries:
        for dim in ['communication', 'persuasion', 'closing', 'spin']:
            scores = [s.scores.get(dim, 0) for s in summaries if s.scores.get(dim)]
            avg_scores[dim] = sum(scores) / len(scores) if scores else 0
    else:
        avg_scores = {'communication': 0, 'persuasion': 0, 'closing': 0, 'spin': 0}

    # Default skills
    skills = {
        name: SkillLevel(skill_name=name, level=level, last_updated=current_user.created_at)
        for name, level in (("开场破冰", 3), ("需求挖掘", 2), ("产品呈现", 3), ("异议处理", 2), ("促成成交", 1))
    }
    for saved in db.query(UserSkillLevel).filter(UserSkillLevel.user_id == current_user.id).all():
        skills[saved.skill_name] = SkillLevel(
            skill_name=saved.skill_name, level=saved.level, last_updated=saved.last_updated,
        )

    stats = UserProfileStats(
        total_sessions=total_sessions,
        total_messages=total_messages,
        total_duration_minutes=int(total_duration),
        avg_score=sum(avg_scores.values()) / len(avg_scores) if avg_scores else 0,
        phases_mastered=['opening'],  # placeholder
        skills=list(skills.values())
    )

    return UserProfileResponse(
        user_id=current_user.id,
        email=current_user.email,
        username=current_user.username,
        full_name=current_user.full_name,
        phone=current_user.phone,
        avatar_url=current_user.avatar_url,
        bio=current_user.bio,
        role=current_user.role,
        joined_at=current_user.created_at,
        last_login_at=current_user.last_login_at,
        stats=stats
    )


@router.get("/me/stats", response_model=UserStatsResponse)
async def get_user_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get user practice statistics summary
    """
    # Last 30 days sessions
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_sessions = db.query(PracticeSession).filter(
        PracticeSession.user_id == current_user.id,
        PracticeSession.created_at >= thirty_days_ago
    ).all()

    all_sessions = db.query(PracticeSession).filter(
        PracticeSession.user_id == current_user.id
    ).all()

    # Calculate stats
    total_time = 0
    for s in recent_sessions:
        if s.started_at and s.ended_at:
            total_time += (s.ended_at - s.started_at).seconds / 60

    # Get summary data — PracticeSummary 没有 user_id 列，通过 session 关联
    user_session_ids = [s.id for s in all_sessions]
    if user_session_ids:
        recent_summaries = (
            db.query(PracticeSummary)
            .filter(PracticeSummary.session_id.in_(user_session_ids))
            .order_by(PracticeSummary.created_at.desc())
            .limit(20)
            .all()
        )
    else:
        recent_summaries = []

    avg_scores = {}
    if recent_summaries:
        for dim in ['communication', 'persuasion', 'closing', 'spin']:
            scores = [s.scores.get(dim, 0) for s in recent_summaries if s.scores.get(dim)]
            avg_scores[dim] = round(sum(scores) / len(scores), 1) if scores else 0
    else:
        avg_scores = {'communication': 0, 'persuasion': 0, 'closing': 0, 'spin': 0}

    avg_all = sum(avg_scores.values()) / len(avg_scores) if avg_scores else 0
    strongest = max(avg_scores, key=avg_scores.get) if avg_scores and any(avg_scores.values()) else 'communication'
    weakest = min(avg_scores, key=avg_scores.get) if avg_scores and any(avg_scores.values()) else 'closing'

    return UserStatsResponse(
        total_practice_sessions=len(recent_sessions),
        total_practice_time=int(total_time),
        average_scores=avg_scores,
        recent_improvement=0,  # Would need historical comparison
        strongest_skill=strongest,
        weakest_skill=weakest,
        phase_progress={
            'opening': len([s for s in recent_sessions if s.current_phase in ['discovery', 'needs', 'proposal', 'closing']]),
            'discovery': len([s for s in recent_sessions if s.current_phase in ['needs', 'proposal', 'closing']]),
            'needs': len([s for s in recent_sessions if s.current_phase in ['proposal', 'closing']]),
            'proposal': len([s for s in recent_sessions if s.current_phase == 'closing']),
            'closing': 0
        }
    )


@router.put("/me/skills", response_model=List[SkillLevel])
async def update_skills(
    updates: List[SkillLevelUpdate],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update user skill self-assessment levels
    """
    # Validate the entire JSON list before mutating anything (schema validation
    # has completed before this handler), then commit all levels together.
    saved_levels = {
        saved.skill_name: saved
        for saved in db.query(UserSkillLevel).filter(UserSkillLevel.user_id == current_user.id).all()
    }
    updated_skills = {}
    for update in updates:
        saved = saved_levels.get(update.skill_name)
        if saved is None:
            saved = UserSkillLevel(user_id=current_user.id, skill_name=update.skill_name)
            db.add(saved)
            saved_levels[update.skill_name] = saved
        saved.level = update.level
        saved.last_updated = datetime.utcnow()
        updated_skills[update.skill_name] = SkillLevel(
            skill_name=update.skill_name,
            level=update.level,
            last_updated=saved.last_updated,
        )

    db.commit()
    return list(updated_skills.values())


@router.post("/me/avatar")
async def upload_avatar(
    request: AvatarUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload/update user avatar
    """
    current_user.avatar_url = request.avatar_url
    db.commit()
    return {"message": "头像已更新", "avatar_url": request.avatar_url}
