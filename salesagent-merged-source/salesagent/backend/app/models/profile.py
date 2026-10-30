"""Persistent skill self-assessments without changing the existing users table."""
from datetime import datetime
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from app.database import Base


class UserSkillLevel(Base):
    __tablename__ = "user_skill_levels"
    __table_args__ = (CheckConstraint("level >= 1 AND level <= 5", name="ck_user_skill_level"),)

    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    skill_name = Column(String(100), primary_key=True)
    level = Column(Integer, nullable=False)
    last_updated = Column(DateTime, default=datetime.utcnow, nullable=False)
