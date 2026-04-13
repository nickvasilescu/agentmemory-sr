"""MemoryStore — the main API for agentmemory-sr."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .db import MemoryDB
from .models import (
    Grade,
    GradeEvent,
    HealthReport,
    Memory,
    MemoryState,
    ReviewResult,
)
from .scheduler import apply_grade, create_scheduler, get_retrievability


class MemoryStore:
    """Spaced repetition memory for AI agents.

    One SQLite file. FSRS-6 scheduling. Memories that matter get reinforced,
    noise fades naturally.

    Usage:
        store = MemoryStore("memory.db")
        store.add("Nick prefers short emails", namespace="preferences")
        memories = store.retrieve("email style", top_k=5)
        store.grade(memories[0].id, "good")
        store.review()
    """

    def __init__(self, db_path: str | Path = "memory.db"):
        self.db = MemoryDB(db_path)
        self.scheduler = create_scheduler()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # --- Core API ---

    def add(
        self,
        content: str,
        namespace: str = "general",
        source: Optional[str] = None,
    ) -> Memory:
        """Store a new memory. Returns the created Memory object."""
        memory = Memory(
            id=uuid.uuid4().hex[:12],
            content=content,
            namespace=namespace,
            source=source,
        )

        # Check for contradictions: similar content in same namespace
        similar = self.db.find_similar(content, namespace, exclude_id=memory.id, limit=3)
        for existing in similar:
            if existing.content.lower() != content.lower() and existing.state == MemoryState.REVIEW:
                # Newer memory supersedes — demote the old one
                existing, _ = apply_grade(self.scheduler, existing, Grade.AGAIN)
                self.db.update_memory(existing)
                self.db.log_grade(GradeEvent(
                    memory_id=existing.id,
                    grade=Grade.AGAIN,
                    context=f"superseded by new memory: {memory.id}",
                ))

        self.db.insert_memory(memory)
        return memory

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        namespace: Optional[str] = None,
    ) -> list[Memory]:
        """Retrieve relevant memories ranked by relevance * retrievability.

        The key innovation: decaying memories with high relevance surface for
        reinforcement. Strong but irrelevant memories stay quiet.
        """
        now = datetime.now(timezone.utc)

        # FTS5 search
        fts_results = self.db.search_fts(query, namespace=namespace, limit=top_k * 3)

        if not fts_results:
            return []

        # Score each result: combine FTS rank with retrievability
        scored = []
        for memory_id, fts_rank in fts_results:
            memory = self.db.get_memory(memory_id)
            if memory is None:
                continue

            retrievability = get_retrievability(self.scheduler, memory, now)
            # FTS rank is negative (lower = better), normalize to 0-1
            relevance = 1.0 / (1.0 + abs(fts_rank))
            combined = relevance * retrievability

            scored.append((memory, combined, retrievability))

        # Sort by combined score (highest first)
        scored.sort(key=lambda x: x[1], reverse=True)

        # Update retrieval counts
        results = []
        for memory, score, retrievability in scored[:top_k]:
            memory.retrieval_count += 1
            memory.last_retrieved = now
            self.db.update_memory(memory)
            results.append(memory)

        return results

    def grade(
        self,
        memory_id: str,
        grade: str | Grade,
        context: Optional[str] = None,
    ) -> Memory:
        """Grade a memory after use. Updates FSRS scheduling.

        Grades:
            "again" — memory was wrong or user corrected it
            "hard"  — retrieved but not useful
            "good"  — used successfully, no correction
            "easy"  — user explicitly confirmed
        """
        if isinstance(grade, str):
            grade = Grade(grade)

        memory = self.db.get_memory(memory_id)
        if memory is None:
            raise ValueError(f"Memory {memory_id} not found")

        # Can't grade suspended/buried memories
        if memory.state in (MemoryState.SUSPENDED, MemoryState.BURIED):
            raise ValueError(f"Memory {memory_id} is {memory.state.value}, unsuspend first")

        before_state = memory.state
        before_stability = memory.stability
        before_difficulty = memory.difficulty

        # Apply FSRS scheduling
        memory, changes = apply_grade(self.scheduler, memory, grade)

        # Track usage for "good" and "easy" grades
        if grade in (Grade.GOOD, Grade.EASY):
            memory.usage_count += 1
            memory.last_used = datetime.now(timezone.utc)

        self.db.update_memory(memory)

        # Log the grade event
        self.db.log_grade(GradeEvent(
            memory_id=memory_id,
            grade=grade,
            context=context,
        ))

        # Log the review result
        self.db.log_review(ReviewResult(
            memory_id=memory_id,
            grade=grade,
            stability_before=before_stability,
            stability_after=memory.stability,
            difficulty_before=before_difficulty,
            difficulty_after=memory.difficulty,
            state_before=before_state,
            state_after=memory.state,
        ))

        return memory

    def review(self, now: Optional[datetime] = None) -> list[ReviewResult]:
        """Run the review cycle on due memories.

        For each due memory:
        - If it has a source file, check if the file still exists
        - Grade based on usage recency
        - Apply FSRS scheduling
        - Detect leeches
        """
        if now is None:
            now = datetime.now(timezone.utc)

        due_memories = self.db.get_due_memories(now)
        results = []

        for memory in due_memories:
            grade = self._auto_grade(memory, now)

            before_state = memory.state
            before_stability = memory.stability
            before_difficulty = memory.difficulty

            memory, changes = apply_grade(self.scheduler, memory, grade, review_time=now)

            if grade in (Grade.GOOD, Grade.EASY):
                memory.usage_count += 1
                memory.last_used = now

            self.db.update_memory(memory)

            result = ReviewResult(
                memory_id=memory.id,
                grade=grade,
                stability_before=before_stability,
                stability_after=memory.stability,
                difficulty_before=before_difficulty,
                difficulty_after=memory.difficulty,
                state_before=before_state,
                state_after=memory.state,
                reviewed_at=now,
            )
            self.db.log_review(result)
            self.db.log_grade(GradeEvent(
                memory_id=memory.id,
                grade=grade,
                graded_at=now,
                context="auto-review",
            ))
            results.append(result)

        return results

    def top_memories(self, n: int = 20, namespace: Optional[str] = None) -> list[Memory]:
        """Get the strongest memories for context injection.

        Ranked by strength: stability * usage_count, with review-state memories first.
        """
        all_memories = self.db.get_all_active_memories()

        if namespace:
            all_memories = [m for m in all_memories if m.namespace == namespace]

        def strength(m: Memory) -> float:
            s = m.stability or 0.0
            usage = max(m.usage_count, 1)
            state_bonus = 2.0 if m.state == MemoryState.REVIEW else 1.0
            return s * usage * state_bonus

        all_memories.sort(key=strength, reverse=True)
        return all_memories[:n]

    def system_prompt(self) -> str:
        """Generate a system prompt block with dual-queue memory injection.

        Mirrors Anki's architecture: learning-phase memories are always shown
        (they need to be seen to build strength), while review-phase memories
        compete by strength. Without this split, new memories score 0.0 in
        the strength ranking and are invisible until graded multiple times.
        """
        all_active = self.db.get_all_active_memories()

        # Learning queue: ungraduated memories — always shown
        learning = [m for m in all_active
                    if m.state in (MemoryState.NEW, MemoryState.LEARNING, MemoryState.RELEARNING)]
        learning.sort(key=lambda m: m.created_at, reverse=True)
        learning = learning[:10]
        learning_ids = {m.id for m in learning}

        # Review queue: graduated memories ranked by strength
        top = self.top_memories(n=15)
        top = [m for m in top if m.id not in learning_ids]

        if not top and not learning:
            return ""

        lines = ["## Active Memory (spaced repetition)", ""]
        lines.append("IMPORTANT: After using ANY memory below to answer a question, grade it:")
        lines.append("`agentmemory --db ~/.agentmemory/memory.db grade <id> good`")
        lines.append("")

        if learning:
            for m in learning:
                state_label = "new" if m.state == MemoryState.NEW else "learning"
                lines.append(f"- (id:{m.id}) [{m.namespace}] {m.content} ({state_label})")
            lines.append("")

        for m in top:
            r = get_retrievability(self.scheduler, m)
            strength = "strong" if r > 0.8 else "fading" if r > 0.5 else "weak"
            lines.append(f"- (id:{m.id}) [{m.namespace}] {m.content} ({strength})")

        return "\n".join(lines)

    def health(self) -> HealthReport:
        """Get memory health statistics."""
        now = datetime.now(timezone.utc)
        stats = self.db.get_health_stats(now)

        # Compute average retrievability across active memories
        active = self.db.get_all_active_memories()
        if active:
            retrievabilities = [get_retrievability(self.scheduler, m, now) for m in active]
            avg_r = sum(retrievabilities) / len(retrievabilities)
        else:
            avg_r = None

        return HealthReport(
            total_memories=stats["total"],
            by_state=stats["by_state"],
            leeches=stats["leeches"],
            due_now=stats["due_now"],
            avg_stability=stats["avg_stability"],
            avg_difficulty=stats["avg_difficulty"],
            avg_retrievability=avg_r,
            namespaces=stats["namespaces"],
        )

    def update(self, memory_id: str, content: str) -> Memory:
        """Update a memory's content. Preserves scheduling history."""
        memory = self.db.get_memory(memory_id)
        if memory is None:
            raise ValueError(f"Memory {memory_id} not found")
        memory.content = content
        memory.updated_at = datetime.now(timezone.utc)
        self.db.update_memory(memory)
        return memory

    def unsuspend(self, memory_id: str) -> Memory:
        """Unsuspend a leech memory. Resets to relearning state."""
        memory = self.db.get_memory(memory_id)
        if memory is None:
            raise ValueError(f"Memory {memory_id} not found")
        if memory.state != MemoryState.SUSPENDED:
            raise ValueError(f"Memory {memory_id} is not suspended")
        memory.state = MemoryState.RELEARNING
        memory.due = datetime.now(timezone.utc)
        memory.updated_at = datetime.now(timezone.utc)
        self.db.update_memory(memory)
        return memory

    def delete(self, memory_id: str):
        """Permanently delete a memory."""
        self.db.delete_memory(memory_id)

    # --- Internal ---

    def _auto_grade(self, memory: Memory, now: datetime) -> Grade:
        """Determine grade for auto-review of a due memory."""
        # If memory has a source file, check if it still exists
        if memory.source:
            source_path = Path(memory.source)
            if source_path.exists():
                return Grade.GOOD  # source still exists, memory likely valid
            else:
                return Grade.HARD  # source gone, uncertain

        # Grade based on usage recency
        if memory.last_used:
            days_since_use = (now - memory.last_used).total_seconds() / 86400
            if days_since_use < 14:
                return Grade.GOOD   # recently used, strong signal
            elif days_since_use < 30:
                return Grade.HARD   # somewhat stale
            else:
                return Grade.HARD   # dormant but don't penalize too hard
        else:
            # Never been used — keep at current trajectory
            return Grade.GOOD if memory.reps > 2 else Grade.HARD
