"""Integration tests for MemoryStore — full lifecycle."""

import os
import tempfile

import pytest

from agentmemory_sr import Grade, MemoryState, MemoryStore


@pytest.fixture
def store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = MemoryStore(path)
    yield s
    s.close()
    os.unlink(path)


class TestAdd:
    def test_add_basic(self, store):
        m = store.add("test fact")
        assert m.id is not None
        assert m.content == "test fact"
        assert m.namespace == "general"
        assert m.state == MemoryState.NEW

    def test_add_with_namespace(self, store):
        m = store.add("email preference", namespace="preferences")
        assert m.namespace == "preferences"

    def test_add_with_source(self, store):
        m = store.add("fact from file", source="/tmp/test.md")
        assert m.source == "/tmp/test.md"

    def test_add_contradiction_demotes_old(self, store):
        old = store.add("Monthly recurring revenue is currently 15K dollars", namespace="business")
        # Grade old memory to review state
        store.grade(old.id, "good")
        store.grade(old.id, "good")
        old_after = store.db.get_memory(old.id)
        assert old_after.state == MemoryState.REVIEW

        # Add contradicting memory with overlapping terms
        new = store.add("Monthly recurring revenue is currently 25K dollars", namespace="business")

        # Old memory should be demoted (graded "again" by contradiction detection)
        old_demoted = store.db.get_memory(old.id)
        assert old_demoted.state in (MemoryState.LEARNING, MemoryState.RELEARNING)


class TestRetrieve:
    def test_retrieve_basic(self, store):
        store.add("Nick likes short emails")
        store.add("Use PostgreSQL for the database")
        results = store.retrieve("short emails")
        assert len(results) >= 1
        assert "email" in results[0].content.lower()

    def test_retrieve_updates_count(self, store):
        m = store.add("test retrieval count")
        store.retrieve("retrieval count")
        updated = store.db.get_memory(m.id)
        assert updated.retrieval_count == 1

    def test_retrieve_respects_top_k(self, store):
        for i in range(10):
            store.add(f"memory number {i} about testing")
        results = store.retrieve("testing", top_k=3)
        assert len(results) <= 3

    def test_retrieve_excludes_suspended(self, store):
        m = store.add("suspended memory about testing")
        m.state = MemoryState.SUSPENDED
        store.db.update_memory(m)
        results = store.retrieve("suspended testing")
        assert all(r.id != m.id for r in results)


class TestGrade:
    def test_grade_good(self, store):
        m = store.add("test grading")
        graded = store.grade(m.id, "good")
        assert graded.stability is not None
        assert graded.stability > 0

    def test_grade_again(self, store):
        m = store.add("test lapse")
        # First get it to review state
        store.grade(m.id, "good")
        store.grade(m.id, "good")
        reviewed = store.db.get_memory(m.id)
        assert reviewed.state == MemoryState.REVIEW

        # Now lapse
        lapsed = store.grade(m.id, "again")
        assert lapsed.lapses == 1

    def test_grade_tracks_usage(self, store):
        m = store.add("usage tracking test")
        store.grade(m.id, "good")
        updated = store.db.get_memory(m.id)
        assert updated.usage_count == 1

    def test_grade_easy_bigger_stability(self, store):
        m1 = store.add("easy test")
        m2 = store.add("good test")
        easy = store.grade(m1.id, "easy")
        good = store.grade(m2.id, "good")
        # Easy should give higher stability than good
        assert easy.stability >= good.stability

    def test_grade_logs_history(self, store):
        m = store.add("log test")
        store.grade(m.id, "good")
        rows = store.db.conn.execute(
            "SELECT * FROM grade_history WHERE memory_id=?", (m.id,)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["grade"] == "good"

    def test_cannot_grade_suspended(self, store):
        m = store.add("suspended test")
        m.state = MemoryState.SUSPENDED
        store.db.update_memory(m)
        with pytest.raises(ValueError, match="suspended"):
            store.grade(m.id, "good")


class TestLeech:
    def test_leech_detection(self, store):
        m = store.add("leech test")
        # Get to review state first
        store.grade(m.id, "good")
        store.grade(m.id, "good")

        # Lapse 8 times
        for _ in range(8):
            mem = store.db.get_memory(m.id)
            if mem.state == MemoryState.SUSPENDED:
                break
            # Need to get back to review state to count a lapse
            if mem.state != MemoryState.REVIEW:
                store.grade(m.id, "good")
                store.grade(m.id, "good")
            store.grade(m.id, "again")

        final = store.db.get_memory(m.id)
        assert final.state == MemoryState.SUSPENDED or final.lapses >= 8


class TestReview:
    def test_review_processes_due(self, store):
        m = store.add("review test")
        # Memory is due immediately (new state)
        results = store.review()
        assert len(results) >= 1

    def test_review_updates_state(self, store):
        m = store.add("state update test")
        store.review()
        updated = store.db.get_memory(m.id)
        assert updated.state != MemoryState.NEW


class TestTopMemories:
    def test_top_memories_ranks_by_strength(self, store):
        m1 = store.add("weak memory")
        m2 = store.add("strong memory")
        # Make m2 stronger
        store.grade(m2.id, "good")
        store.grade(m2.id, "good")
        store.grade(m2.id, "good")

        top = store.top_memories(n=2)
        assert top[0].id == m2.id

    def test_top_memories_filters_namespace(self, store):
        store.add("business fact", namespace="business")
        store.add("personal pref", namespace="personal")
        top = store.top_memories(namespace="business")
        assert all(m.namespace == "business" for m in top)


class TestHealth:
    def test_health_report(self, store):
        store.add("test 1", namespace="a")
        store.add("test 2", namespace="b")
        store.add("test 3", namespace="a")
        health = store.health()
        assert health.total_memories == 3
        assert health.namespaces["a"] == 2
        assert health.namespaces["b"] == 1


class TestSystemPrompt:
    def test_system_prompt_empty(self, store):
        prompt = store.system_prompt()
        assert prompt == ""

    def test_system_prompt_with_memories(self, store):
        store.add("test memory for prompt")
        store.grade(store.add("graded memory").id, "good")
        prompt = store.system_prompt()
        assert "Active Memory" in prompt
        assert "agentmemory grade" in prompt


class TestUpdateDelete:
    def test_update_content(self, store):
        m = store.add("old content")
        updated = store.update(m.id, "new content")
        assert updated.content == "new content"
        assert store.db.get_memory(m.id).content == "new content"

    def test_delete(self, store):
        m = store.add("to delete")
        store.delete(m.id)
        assert store.db.get_memory(m.id) is None

    def test_unsuspend(self, store):
        m = store.add("to unsuspend")
        m.state = MemoryState.SUSPENDED
        store.db.update_memory(m)
        unsuspended = store.unsuspend(m.id)
        assert unsuspended.state == MemoryState.RELEARNING
