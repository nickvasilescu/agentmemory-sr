"""Data models for agentmemory-sr."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MemoryState(str, Enum):
    NEW = "new"
    LEARNING = "learning"
    REVIEW = "review"
    RELEARNING = "relearning"
    SUSPENDED = "suspended"
    BURIED = "buried"


class Grade(str, Enum):
    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


# Map our grades to fsrs Rating values
GRADE_TO_FSRS = {
    Grade.AGAIN: 1,
    Grade.HARD: 2,
    Grade.GOOD: 3,
    Grade.EASY: 4,
}

# Map fsrs State enum to our state enum
# fsrs v6 has no "New" state — cards start at Learning(1) on first review
FSRS_STATE_MAP = {
    1: MemoryState.LEARNING,
    2: MemoryState.REVIEW,
    3: MemoryState.RELEARNING,
}


class Memory(BaseModel):
    id: str
    content: str
    namespace: str = "general"
    source: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # FSRS scheduling state
    stability: Optional[float] = None
    difficulty: Optional[float] = None
    due: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_review: Optional[datetime] = None
    state: MemoryState = MemoryState.NEW
    step: Optional[int] = 0
    fsrs_card_id: Optional[int] = None

    # Agent-specific tracking (not in fsrs Card)
    lapses: int = 0
    reps: int = 0
    retrieval_count: int = 0
    usage_count: int = 0
    last_retrieved: Optional[datetime] = None
    last_used: Optional[datetime] = None


class GradeEvent(BaseModel):
    id: Optional[int] = None
    memory_id: str
    grade: Grade
    graded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    context: Optional[str] = None


class ReviewResult(BaseModel):
    memory_id: str
    grade: Grade
    stability_before: Optional[float]
    stability_after: Optional[float]
    difficulty_before: Optional[float]
    difficulty_after: Optional[float]
    state_before: MemoryState
    state_after: MemoryState
    interval_before: Optional[float] = None
    interval_after: Optional[float] = None
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HealthReport(BaseModel):
    total_memories: int = 0
    by_state: dict[str, int] = Field(default_factory=dict)
    leeches: int = 0
    due_now: int = 0
    avg_stability: Optional[float] = None
    avg_difficulty: Optional[float] = None
    avg_retrievability: Optional[float] = None
    namespaces: dict[str, int] = Field(default_factory=dict)
