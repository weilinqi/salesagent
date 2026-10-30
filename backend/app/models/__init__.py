"""
Models package
"""
# Import User first so that other models can reference it in relationships
from app.models.user import User
from app.models.profile import UserSkillLevel
from app.models.knowledge import KnowledgeDocument

from app.models.practice import (
    Scenario,
    PracticeSession,
    PracticeMessage,
    AIClientRole,
    PracticeSummary,
    PracticeReport,
    IndustryBrief,
    Notification,
)

__all__ = [
    "User",
    "UserSkillLevel",
    "KnowledgeDocument",
    "Scenario",
    "PracticeSession",
    "PracticeMessage",
    "AIClientRole",
    "PracticeSummary",
    "PracticeReport",
    "IndustryBrief",
    "Notification",
]
