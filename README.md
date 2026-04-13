# agentmemory-sr

Spaced repetition memory for AI agents. One SQLite file that makes agent memory intelligent.

Every agent memory system today treats memory as a storage problem — dump facts in a vector DB, retrieve by similarity. Nothing decays. Nothing strengthens. Nothing learns.

**agentmemory-sr** applies [FSRS-6](https://github.com/open-spaced-repetition/fsrs-rs) — the algorithm behind [Anki](https://apps.ankiweb.net/), trained on 700M+ human reviews — to agent memory. Memories that matter get reinforced over time. Noise fades naturally. Wrong memories get flagged and suspended.

## Install

```bash
pip install agentmemory-sr
```

## Quick Start

### Python

```python
from agentmemory_sr import MemoryStore

store = MemoryStore("memory.db")

# Store memories
store.add("Nick prefers short emails", namespace="preferences")
store.add("Orgo MRR is $25K", namespace="business", source="Finance/overview.md")

# Retrieve — ranked by relevance × retrievability
memories = store.retrieve("email drafting style", top_k=5)

# Grade after use — this is how the system learns
store.grade(memory.id, "good")    # used successfully
store.grade(memory.id, "again")   # wrong or outdated
store.grade(memory.id, "easy")    # user confirmed
store.grade(memory.id, "hard")    # retrieved but not useful

# Review due memories (run on cron or idle)
store.review()

# Strongest memories for context injection
store.top_memories(n=20)

# System prompt block with active memories
store.system_prompt()

# Health check
store.health()
```

### CLI

```bash
# Store
agentmemory add "Nick prefers short emails" --namespace preferences

# Search
agentmemory search "email style" --top-k 5

# Grade
agentmemory grade abc123 good

# Review due memories
agentmemory review

# Top memories
agentmemory top --n 20

# Health
agentmemory health

# System prompt for context injection
agentmemory prompt

# Install skill file for agent guidance
agentmemory install-skill ~/.openclaw/skills/
```

### Agent Skill

The package ships with a skill file that teaches agents when and how to use memory — when to store, when to grade, what the grades mean, how to handle leeches. Install it into any agent's skill directory:

```bash
agentmemory install-skill ~/.openclaw/skills/   # OpenClaw
agentmemory install-skill ~/.hermes/skills/      # Hermes
```

## How It Works

### FSRS-6 Scheduling

Each memory has two core values: **stability** (how long until recall drops to 90%) and **difficulty** (how volatile the information is). These update on every grade using the [FSRS-6 algorithm](https://github.com/open-spaced-repetition/py-fsrs) — a 21-parameter model that outperforms SM-2 for 99.6% of users.

- **Good** → stability grows, next review pushed further out
- **Easy** → big stability boost, long interval
- **Hard** → small growth, short interval
- **Again** → stability resets, memory enters relearning

### Retrieval Ranking

Search results are ranked by `relevance × retrievability`. A highly relevant but decaying memory surfaces for reinforcement. Strong but irrelevant memories stay quiet. This is the key difference from flat vector search.

### Contradiction Detection

When you store a new memory, the system checks for similar content in the same namespace. If an older memory conflicts (e.g., "MRR is $15K" vs "MRR is $25K"), the old one is automatically demoted.

### Leech Detection

A memory that keeps getting graded "again" (8+ lapses) is suspended. This flags volatile or poorly-formed memories for investigation.

### Review Cycle

`store.review()` processes all due memories:
- Checks source files if specified (does the file still exist?)
- Grades based on usage recency
- Applies FSRS scheduling
- Detects and suspends leeches

### Memory States

| State | Meaning |
|-------|---------|
| `new` | Just stored, not yet graded |
| `learning` | In early review cycle |
| `review` | Graduated — on a spaced schedule |
| `relearning` | Failed a review, back to short intervals |
| `suspended` | Leech — flagged for investigation |

## Architecture

```
agentmemory-sr/
  src/agentmemory_sr/
    store.py        # MemoryStore — the main API
    db.py           # SQLite + FTS5 storage layer
    models.py       # Pydantic data models
    scheduler.py    # FSRS-6 wrapper
    cli.py          # Click CLI
    skill.md        # Agent guidance document
  tests/
    test_store.py   # 25 tests, 0.23s
```

One SQLite file. Three tables (memories, grade_history, review_log). FSRS needs only 2 floats per memory (stability + difficulty). Retrievability computed at query time.

## Integration

Works with any agent framework that can call Python or bash:

| Path | How |
|------|-----|
| **Python library** | `from agentmemory_sr import MemoryStore` |
| **CLI via bash** | `agentmemory add/search/grade/review` |
| **Skill file** | `agentmemory install-skill <dir>` |

The skill file is the bridge between "I have a tool" and "I know how to learn." It teaches agents the when and why, not just the how.

## Why Not Just Use Mem0 / Zep / Hindsight?

Every existing agent memory system stores memories as immortal vectors. They never decay. They never strengthen through use. There's no mechanism that says "this memory is fading, surface it for reinforcement" or "this memory keeps being wrong, suspend it."

agentmemory-sr is the only MIT-licensed Python package that applies spaced repetition to agent memory. The algorithm is proven on 700M+ human reviews. We're adapting it to a new domain.

## License

MIT

## Status

v0.1.0 — alpha. The core works, the hypothesis is being validated. Contributions welcome.
