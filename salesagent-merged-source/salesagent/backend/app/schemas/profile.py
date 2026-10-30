"""
User profile and stats management
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime


class SkillLevel(BaseModel):
    """User skill self-assessment level"""
    skill_name: str
    level: int  # 1-5
    last_updated: datetime


class UserProfileStats(BaseModel):
    """User practice statistics"""
    total_sessions: int
    total_messages: int
    total_duration_minutes: int
    avg_score: float
    phases_mastered: List[str]
    skills: List[SkillLevel]


class UserProfileResponse(BaseModel):
    """Full user profile with stats"""
    user_id: str
    email: str
    username: str
    full_name: Optional[str]
    phone: Optional[str]
    avatar_url: Optional[str]
    bio: Optional[str]
    role: str
    joined_at: datetime
    last_login_at: Optional[datetime]
    stats: UserProfileStats


class SkillLevelUpdate(BaseModel):
    """Update skill self-assessment"""
    skill_name: str = Field(..., min_length=1, max_length=100)
    level: int = Field(..., ge=1, le=5, strict=True)

    @field_validator("skill_name", mode="before")
    @classmethod
    def trim_skill_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class AvatarUpdate(BaseModel):
    """Avatar URL sent in the client's JSON body."""
    avatar_url: str = Field(..., min_length=1, max_length=500)


class UserStatsResponse(BaseModel):
    """Practice statistics summary"""
    total_practice_sessions: int
    total_practice_time: int  # minutes
    average_scores: dict  # { dimension: score }
    recent_improvement: float  # percentage change
    strongest_skill: str
    weakest_skill: str
    phase_progress: dict  # { phase: completed_count }
