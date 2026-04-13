---
name: agentmemory-sr
description: "Persistent spaced repetition memory that survives across sessions. USE THIS PROACTIVELY — it is your PRIMARY memory system, not the built-in auto-memory. At session start, memories are auto-injected via hook. Before answering ANY question about the user, preferences, people, projects, dates, facts, or decisions, check your injected memories first. When you USE a memory to answer a question, you MUST grade it. When the user teaches you something new, store it here with agentmemory add, NOT in MEMORY.md. When the user corrects you, grade the old memory 'again' and store the correction. This is how the system learns — without grading, memories never strengthen."
---

# Spaced Repetition Memory

Primary memory system. FSRS-6 scheduling. Useful memories strengthen. Stale ones fade. Wrong ones get suspended.

**This replaces built-in auto-memory.** Do NOT save to MEMORY.md — save here with `agentmemory add`.

Database: `~/.agentmemory/memory.db`

## The Two Rules

**Rule 1: GRADE every memory you use.** After answering from memory, grade immediately. Without grading, FSRS has no signal.

**Rule 2: STORE new facts here, not in MEMORY.md.** Preferences, dates, people, decisions — all go in SR memory.

## Commands

EVERY command starts with: `agentmemory --db ~/.agentmemory/memory.db`

### Store a memory (ALWAYS use --namespace/-n)

```bash
agentmemory --db ~/.agentmemory/memory.db add "fact here" --namespace personal
agentmemory --db ~/.agentmemory/memory.db add "fact here" -n business
```

**Namespaces:** preferences, business, team, user, family, personal, technical, project, research, travel, infrastructure

Pick the most specific namespace. NEVER omit -n (defaults to "general" which is useless for filtering).

### Search

```bash
agentmemory --db ~/.agentmemory/memory.db search "query" --top-k 5
```

### Grade (single)

```bash
agentmemory --db ~/.agentmemory/memory.db grade <id> good -c "reason"
```

### Grade (batch — use this when grading multiple memories)

```bash
agentmemory --db ~/.agentmemory/memory.db grade-batch abc123:good def456:good ghi789:easy
```

This is faster than individual grade calls. Use it after answering from multiple memories.

### Quiet mode (suppress JSON output)

Add `-q` to any command to suppress output. Use for grading where you don't need the response:

```bash
agentmemory --db ~/.agentmemory/memory.db -q grade <id> good
agentmemory --db ~/.agentmemory/memory.db -q grade-batch abc:good def:good
```

### Other

```bash
agentmemory --db ~/.agentmemory/memory.db review       # process due memories
agentmemory --db ~/.agentmemory/memory.db health        # stats
agentmemory --db ~/.agentmemory/memory.db top --n 20    # strongest memories
```

## Session Flow

**Start of session:** Memories auto-injected by hook. You already know things.

**User asks a question:**
1. Check injected memories first
2. Found it → respond, then `grade-batch` all used memory IDs as good (or easy if confirmed)
3. Not found → `search "query"`
4. Search found it → respond, then grade
5. Nothing → fall back to vault. If you find the answer, `add` it with `-n namespace`

**User teaches something new:**
1. `add "the fact" -n namespace` — ALWAYS include namespace
2. Grade it good immediately

**User corrects you:**
1. `grade <old-id> again -c "user corrected"`
2. `add "corrected fact" -n namespace`

## Grading Reference

| What happened | Grade |
|---------------|-------|
| Used the memory, it was correct | `good` |
| User explicitly confirmed | `easy` |
| Retrieved but wasn't useful | `hard` |
| Memory was wrong / user corrected | `again` |

## What NOT to Store

- Ephemeral task state
- Things that change daily
- Raw vault content that's easily searchable
- Anything already in CLAUDE.md
