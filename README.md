# agentmemory-sr

Spaced repetition memory for AI agents. One SQLite file that makes agent memory intelligent.

## The Problem

Every agent memory system today treats memory as a storage problem — dump facts in a vector DB, retrieve by similarity. Nothing decays. Nothing strengthens. Nothing learns. Ask your agent the same question a hundred times and the memory system has zero signal about which facts matter.

**agentmemory-sr** applies [FSRS-6](https://github.com/open-spaced-repetition/fsrs-rs) — the algorithm behind [Anki](https://apps.ankiweb.net/), trained on 700M+ human reviews — to agent memory. Memories that get used strengthen over time. Noise fades naturally. Wrong memories get flagged and suspended.

## Who This Is For

- **AI agent builders** who want their agents to actually learn from interactions, not just store and retrieve
- **Claude Code users** who want persistent memory that survives across sessions and gets smarter over time
- **Anyone building with OpenClaw, Hermes, or custom agents** who needs a lightweight memory layer that works via Python or CLI

If you've ever wished your agent would stop forgetting things you've told it five times, or stop confidently repeating something you corrected three sessions ago, this is for you.

## How It's Different

| Feature | Mem0 / Zep / Hindsight | agentmemory-sr |
|---------|----------------------|----------------|
| Memory decay | Never. Memories are immortal. | FSRS-6 forgetting curve. Unused memories fade. |
| Reinforcement | None. Used 100x = same as used 0x. | Every grade strengthens or weakens the memory. |
| Wrong memories | Stay forever until manually deleted. | Graded "again" → stability resets. 8 lapses → auto-suspended. |
| Retrieval ranking | Similarity only. | Relevance x retrievability. Fading relevant memories surface for reinforcement. |
| Contradiction detection | Manual. | Automatic. New fact in same namespace demotes the old one. |
| Infrastructure | Vector DB, embeddings, API keys. | One SQLite file. Zero dependencies beyond Python. |
| License | Mixed (some AGPL, some proprietary). | MIT. |

The only comparable project is [Vestige](https://github.com/ToolUse/vestige) (AGPL, Rust). agentmemory-sr is MIT and Python.

## Install

```bash
pip install agentmemory-sr
```

## Quick Start

### Python

```python
from agentmemory_sr import MemoryStore

store = MemoryStore("memory.db")

# Store memories (always with a namespace)
store.add("Nick prefers short emails", namespace="preferences")
store.add("Orgo MRR is $25K", namespace="business", source="Finance/overview.md")

# Retrieve — ranked by relevance x retrievability
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
# Store (always use -n for namespace)
agentmemory add "Nick prefers short emails" -n preferences

# Search
agentmemory search "email style" --top-k 5

# Grade (single)
agentmemory grade abc123 good -c "answered correctly"

# Grade (batch — multiple memories at once)
agentmemory grade-batch abc123:good def456:good ghi789:easy

# Quiet mode (suppress JSON output, exit code only)
agentmemory -q grade abc123 good
agentmemory -q grade-batch abc:good def:easy

# Review due memories
agentmemory review

# Top memories
agentmemory top --n 20

# Health
agentmemory health

# System prompt for context injection
agentmemory prompt

# Install skill file for agent guidance
agentmemory install-skill ~/.claude/skills/agentmemory-sr/
```

## Claude Code Setup (Full)

The recommended setup uses three layers: a skill file (teaches the agent when/how to use memory), a SessionStart hook (auto-injects memories into context), and a validation hook (prevents the agent from using wrong CLI flags).

### 1. Install the skill

```bash
mkdir -p ~/.claude/skills/agentmemory-sr
agentmemory install-skill ~/.claude/skills/agentmemory-sr/
mv ~/.claude/skills/agentmemory-sr/agentmemory-sr.md ~/.claude/skills/agentmemory-sr/SKILL.md
```

### 2. Create the validation hook

Save to `~/.claude/hooks/validate-agentmemory.sh`:

```bash
#!/bin/bash
# Blocks invented flags, bracket tags, and missing namespace on add commands.
# Returns correct syntax so the agent self-corrects on next attempt.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only check commands where agentmemory is the actual binary being invoked
if ! echo "$COMMAND" | grep -qE '(^|&&|\|\||;)\s*agentmemory\s'; then
  exit 0
fi

AM_CMDS=$(echo "$COMMAND" | grep -oE '(^|&&|\|\||;)\s*agentmemory\s[^;&|]*' || true)
if [ -z "$AM_CMDS" ]; then
  exit 0
fi

# Block hallucinated flags
if echo "$AM_CMDS" | grep -qE -- '--tag|--category|--type|--label|--group'; then
  cat <<'DENY'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"INVALID FLAG. Use -n or --namespace. Correct: agentmemory --db ~/.agentmemory/memory.db add \"fact\" -n personal"}}
DENY
  exit 0
fi

# Block bracket tags in content
if echo "$AM_CMDS" | grep -q 'add' && echo "$AM_CMDS" | grep -qE '\[(preferences|personal|business|team|user|family|technical|project|research|travel|infrastructure)\]'; then
  cat <<'DENY'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Do not put namespace in brackets inside content. Use -n flag. Correct: agentmemory --db ~/.agentmemory/memory.db add \"fact\" -n personal"}}
DENY
  exit 0
fi

# Block add without namespace
if echo "$AM_CMDS" | grep -q 'add' && ! echo "$AM_CMDS" | grep -qE '\-n\s|\-\-namespace\s'; then
  cat <<'DENY'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Missing namespace. Correct: agentmemory --db ~/.agentmemory/memory.db add \"fact\" -n personal. Namespaces: preferences, business, team, user, family, personal, technical, project, research, travel, infrastructure"}}
DENY
  exit 0
fi

exit 0
```

Then `chmod +x ~/.claude/hooks/validate-agentmemory.sh`.

### 3. Add hooks to `~/.claude/settings.json`

Merge this into your existing settings.json (don't replace the whole file):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "jq -r '.tool_input.file_path // \"\"' | grep -q '/memory/' && echo '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"Use agentmemory-sr instead of auto-memory. Store facts with: agentmemory --db ~/.agentmemory/memory.db add \\\"fact\\\" -n namespace\"}}' || true",
            "timeout": 5
          }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/validate-agentmemory.sh",
            "timeout": 5
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "DB=\"$HOME/.agentmemory/memory.db\"; agentmemory --db \"$DB\" review >/dev/null 2>&1; MEMORIES=$(agentmemory --db \"$DB\" prompt 2>/dev/null); if [ -n \"$MEMORIES\" ]; then python3 -c \"import json,sys; m=sys.stdin.read(); print(json.dumps({'hookSpecificOutput':{'hookEventName':'SessionStart','additionalContext':m}}))\" <<< \"$MEMORIES\"; fi",
            "timeout": 10,
            "statusMessage": "Loading spaced repetition memory..."
          }
        ]
      }
    ]
  }
}
```

**What each hook does:**
- **Write|Edit hook** — Blocks the agent from writing to the built-in auto-memory (`MEMORY.md`). Forces all memory storage through agentmemory-sr.
- **Bash hook** — Validates agentmemory CLI commands. Blocks invented flags (`--tag`, `--category`), bracket tags in content (`[personal]`), and missing namespace on `add`. Returns the correct syntax so the agent self-corrects.
- **SessionStart hook** — Runs `review` (processes due memories), then `prompt` (gets top memories), and injects them into the agent's context at session start.

### 4. (Optional) Add a CLAUDE.md rule

For strongest enforcement, add the exact command syntax to your project's CLAUDE.md so it's always in context:

```markdown
- **Spaced repetition memory (`agentmemory-sr`) is your primary memory system.** Exact commands:
  - **Store:** `agentmemory --db ~/.agentmemory/memory.db add "fact" -n <namespace>` — ALWAYS use `-n`. There is no `--tag` or `--category` flag.
  - **Grade after use:** `agentmemory --db ~/.agentmemory/memory.db -q grade-batch id1:good id2:good`
  - **Search:** `agentmemory --db ~/.agentmemory/memory.db search "query" --top-k 5`
```

## How It Works

### FSRS-6 Scheduling

Each memory has two core values: **stability** (days until recall drops to 90%) and **difficulty** (how volatile the information is). These update on every grade using the [FSRS-6 algorithm](https://github.com/open-spaced-repetition/py-fsrs) — a 21-parameter model trained on 700M+ human reviews.

- **Good** — stability grows, next review pushed further out
- **Easy** — big stability boost, long interval
- **Hard** — small growth, short interval
- **Again** — stability resets, memory enters relearning

What this means in practice: a memory graded "good" five times might go from reviewing every day to every month. A memory that keeps getting graded "again" gets suspended after 8 lapses — the system flags it as unreliable.

### Retrieval Ranking

Search results are ranked by `relevance x retrievability`. A highly relevant but decaying memory surfaces for reinforcement. Strong but irrelevant memories stay quiet. This is the key difference from flat vector search — the system doesn't just find matches, it finds matches that need attention.

### Context Injection (Dual-Queue)

At session start, memories are injected into the agent's context using two queues — mirroring how Anki separates learning cards from review cards:

**Learning queue** — memories in `new`, `learning`, or `relearning` state are always shown. New memories need to be seen to build strength; hiding them until they're strong creates a chicken-and-egg problem.

**Review queue** — graduated memories (`review` state) compete by strength. Top 15 by `stability × usage × state_bonus`.

```
- (id:abc123) [family] Brother's name is Matthew (new)
- (id:def456) [preferences] Nick prefers short emails (strong)
- (id:ghi789) [business] Orgo MRR is $25K (fading)
```

Labels: `new` = never graded, `learning` = graded but not graduated, `strong` = retrievability > 80%, `fading` = 50-80%, `weak` = below 50%.

After a memory gets graded "good" twice, it graduates from the learning queue to the review queue and competes on strength like everything else.

### Contradiction Detection

When you store a new memory, the system checks for similar content in the same namespace. If an older memory conflicts (e.g., "MRR is $15K" vs "MRR is $25K"), the old one is automatically demoted.

### Leech Detection

A memory that keeps getting graded "again" (8+ lapses) is suspended. This flags volatile or poorly-formed memories for investigation rather than letting them pollute retrieval forever.

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
    test_store.py   # 25 tests, 0.21s
```

One SQLite file. Three tables (memories, grade_history, review_log). FSRS needs only 2 floats per memory (stability + difficulty). Retrievability computed at query time.

## Integration

Works with any agent framework that can call Python or bash:

| Path | How |
|------|-----|
| **Python library** | `from agentmemory_sr import MemoryStore` |
| **CLI via bash** | `agentmemory add/search/grade/review` |
| **Skill file** | `agentmemory install-skill <dir>` |
| **Hooks** | PreToolUse validation + SessionStart injection |

## Honest Caveats

- **FSRS-6 was trained on human flashcard data.** We're adapting a proven algorithm to a novel domain. The scheduling parameters are human-calibrated defaults. A future optimizer could tune them for agent usage patterns, but that needs weeks of interaction data.
- **FTS5 keyword search, not semantic.** If you store "Nick likes brief responses" and search "concise answers", it won't match. Vector/embedding search is on the roadmap for v2.
- **Grading depends on the agent.** The system only learns if the agent actually grades memories after use. The hooks and skill file push hard for this, but it's not 100% consistent in practice.

## License

MIT

## Status

v0.1.0 — working, tested, deployed. The core loop (store, retrieve, grade, review) is validated in production use with Claude Code. Contributions welcome.
