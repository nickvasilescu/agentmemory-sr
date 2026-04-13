---
name: agentmemory-sr
description: "Persistent spaced repetition memory that survives across sessions. USE THIS PROACTIVELY — it is your PRIMARY memory system, not the built-in auto-memory. At session start, memories are auto-injected via hook. Before answering ANY question about the user, preferences, people, projects, dates, facts, or decisions, check your injected memories first. When you USE a memory to answer a question, you MUST grade it (agentmemory grade <id> good). When the user teaches you something new, store it here with agentmemory add, NOT in MEMORY.md. When the user corrects you, grade the old memory 'again' and store the correction. This is how the system learns — without grading, memories never strengthen."
---

# Spaced Repetition Memory

This is your primary memory system. It uses FSRS-6 (Anki's algorithm, 700M+ reviews) to schedule memories. Useful ones strengthen over time. Stale ones fade. Wrong ones get suspended.

**This replaces the built-in auto-memory for personal facts, preferences, and project context.** Do NOT save these to MEMORY.md — save them here with `agentmemory add`.

Database: `~/.agentmemory/memory.db`

Every command: `agentmemory --db ~/.agentmemory/memory.db <command>`

## The Two Rules That Make This Work

**Rule 1: GRADE every memory you use.** When you answer a question using a memory from the session-start injection or from a search, grade it immediately. This is not optional — without grading, the FSRS scheduler has no signal and memories never strengthen or decay. The whole system depends on this.

```bash
# You answered "25" because memory said Nick is 25 → grade it
agentmemory --db ~/.agentmemory/memory.db grade 823bfb98840f good -c "answered age question"
```

**Rule 2: STORE new facts here, not in MEMORY.md.** When the user tells you something worth remembering across sessions (a date, a preference, a person's name, a decision), store it with `agentmemory add`. The built-in auto-memory is for vault-level notes. Personal facts belong in SR memory.

```bash
# User just told you their mom's birthday
agentmemory --db ~/.agentmemory/memory.db add "Mom birthday is February 15 1972" -n family
```

## Session Flow

**Start of session:** Memories are auto-injected by the SessionStart hook. Read the injected context — it contains your top memories with strength indicators (strong/fading/weak). You already know things.

**User asks a question:**
1. Check your injected memories first
2. If you find the answer → respond, then **grade the memory good** (or easy if user confirms)
3. If not found → search: `agentmemory --db ~/.agentmemory/memory.db search "query" --top-k 5`
4. If search finds it → respond, then **grade it**
5. If nothing → fall back to vault grep. If you find the answer, **store it** with `agentmemory add`

**User teaches you something new:**
1. Store it: `agentmemory --db ~/.agentmemory/memory.db add "the fact" -n namespace`
2. Grade it good immediately (you just learned it, it's fresh)

**User corrects you:**
1. Grade the wrong memory: `agentmemory --db ~/.agentmemory/memory.db grade <id> again -c "user corrected"`
2. Store the correction: `agentmemory --db ~/.agentmemory/memory.db add "corrected fact" -n namespace`
3. Contradiction detection auto-demotes the old one

## Commands

```bash
agentmemory --db ~/.agentmemory/memory.db add "fact" -n namespace
agentmemory --db ~/.agentmemory/memory.db search "query" --top-k 5
agentmemory --db ~/.agentmemory/memory.db grade <id> good|again|hard|easy -c "reason"
agentmemory --db ~/.agentmemory/memory.db review
agentmemory --db ~/.agentmemory/memory.db health
```

## Grading Reference

| What happened | Grade | Effect |
|---------------|-------|--------|
| Used the memory, it was correct | `good` | Stability grows, interval extends |
| User explicitly confirmed ("yes exactly") | `easy` | Big stability boost |
| Retrieved but wasn't useful for this task | `hard` | Small growth, shorter interval |
| Memory was wrong or user corrected it | `again` | Stability resets, relearning |

## Namespaces

preferences, business, team, user, family, technical, project, research, travel, infrastructure

## What NOT to Store Here

- Ephemeral task state (use tasks for that)
- Things that change every day (today's agenda)
- Raw vault content that's easily searchable
- Anything already in CLAUDE.md rules
