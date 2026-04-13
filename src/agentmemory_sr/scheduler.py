"""FSRS-6 scheduler wrapper. Thin layer over the fsrs library."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fsrs import Card as FSRSCard
from fsrs import Rating, Scheduler, State

from .models import FSRS_STATE_MAP, GRADE_TO_FSRS, Grade, Memory, MemoryState

LEECH_THRESHOLD = 8


def create_scheduler() -> Scheduler:
    return Scheduler()


def memory_to_fsrs_card(memory: Memory) -> FSRSCard:
    """Convert our Memory model to an fsrs Card for scheduling.

    fsrs v6 has no "New" state — cards start at Learning(1).
    Our MemoryState.NEW maps to a fresh fsrs Card (state=Learning, step=0).
    """
    card = FSRSCard()
    if memory.fsrs_card_id is not None:
        card.card_id = memory.fsrs_card_id
    if memory.stability is not None:
        card.stability = memory.stability
    if memory.difficulty is not None:
        card.difficulty = memory.difficulty
    card.due = memory.due
    card.last_review = memory.last_review

    # Map our state to fsrs State enum
    # fsrs v6: Learning=1, Review=2, Relearning=3 (no New=0)
    state_map = {
        MemoryState.NEW: State.Learning,       # new → learning for fsrs
        MemoryState.LEARNING: State.Learning,
        MemoryState.REVIEW: State.Review,
        MemoryState.RELEARNING: State.Relearning,
    }
    card.state = state_map.get(memory.state, State.Learning)

    if memory.step is not None:
        card.step = memory.step

    return card


def apply_grade(
    scheduler: Scheduler,
    memory: Memory,
    grade: Grade,
    review_time: Optional[datetime] = None,
) -> tuple[Memory, dict]:
    """Apply a grade to a memory using FSRS-6 scheduling.

    Returns the updated memory and a dict of before/after values for logging.
    """
    if review_time is None:
        review_time = datetime.now(timezone.utc)

    card = memory_to_fsrs_card(memory)
    rating = Rating(GRADE_TO_FSRS[grade])

    # Capture before state
    before = {
        "stability": memory.stability,
        "difficulty": memory.difficulty,
        "state": memory.state,
    }

    # Run FSRS
    new_card, review_log = scheduler.review_card(card, rating, review_datetime=review_time)
    card_dict = new_card.to_dict()

    # Update memory from FSRS result
    memory.stability = card_dict["stability"]
    memory.difficulty = card_dict["difficulty"]
    memory.due = datetime.fromisoformat(card_dict["due"])
    memory.last_review = datetime.fromisoformat(card_dict["last_review"])
    memory.fsrs_card_id = card_dict["card_id"]
    memory.step = card_dict.get("step")

    # Map fsrs state back (card_dict["state"] is an int: 1=Learning, 2=Review, 3=Relearning)
    fsrs_state = card_dict["state"]
    memory.state = FSRS_STATE_MAP.get(fsrs_state, MemoryState.LEARNING)

    # Track reps and lapses ourselves
    memory.reps += 1
    if grade == Grade.AGAIN and before["state"] == MemoryState.REVIEW:
        memory.lapses += 1

    # Leech detection
    if memory.lapses >= LEECH_THRESHOLD and memory.state != MemoryState.SUSPENDED:
        memory.state = MemoryState.SUSPENDED

    memory.updated_at = review_time

    after = {
        "stability": memory.stability,
        "difficulty": memory.difficulty,
        "state": memory.state,
    }

    return memory, {"before": before, "after": after}


def get_retrievability(scheduler: Scheduler, memory: Memory, now: Optional[datetime] = None) -> float:
    """Compute current retrievability (0-1) for a memory."""
    if memory.stability is None or memory.last_review is None:
        return 1.0  # new memories are fully "retrievable"

    card = memory_to_fsrs_card(memory)
    return scheduler.get_card_retrievability(card, current_datetime=now)
