# Spaced Repetition Memory

You have access to a spaced repetition memory system via the `agentmemory` CLI. Memories you store are scheduled using FSRS-6 — the same algorithm behind Anki, trained on 700M+ reviews. Useful memories get reinforced over time. Irrelevant or wrong memories fade and eventually get suspended.

Your memory is a single SQLite file. It persists across sessions.

## Commands

```bash
agentmemory add "fact or preference" --namespace general
agentmemory search "query" --top-k 5
agentmemory grade <memory_id> again|hard|good|easy
agentmemory review
agentmemory top --n 20
agentmemory health
agentmemory prompt
```

## When to Store

Store a memory when you learn something that will be useful in future conversations:

- User preferences: "prefers short emails", "hates bullet points", "uses dark mode"
- Project facts: "MRR is $25K", "deadline is April 15", "using PostgreSQL 16"
- Relationship context: "reports to Sarah", "new to the team", "expert in React"
- Decisions: "chose Stripe over Paddle", "moving to monorepo", "using FSRS not SM-2"
- Corrections: when the user corrects you, store the correct version

```bash
agentmemory add "User prefers tabs over spaces" --namespace preferences
agentmemory add "Project deadline is 2026-04-15" --namespace project --source "docs/timeline.md"
```

Use `--source` when the memory came from a specific file. The review cycle will check if the file still exists.

## When to Retrieve

Before generating a response, search for relevant context:

```bash
agentmemory search "email drafting preferences"
agentmemory search "project architecture" --namespace project
```

Results are ranked by `relevance × retrievability`. Decaying memories surface for reinforcement. Strong irrelevant memories stay quiet.

## When and How to Grade

**Grade every memory you retrieve.** This is how the system learns.

| Situation | Grade | Example |
|-----------|-------|---------|
| Memory was correct and you used it | `good` | Used "prefers short emails" to draft a concise reply |
| User explicitly confirmed the memory | `easy` | User said "yes exactly, keep it brief" |
| Memory was retrieved but wasn't useful for this task | `hard` | "Prefers dark mode" surfaced for an email task |
| Memory was wrong, outdated, or user corrected it | `again` | User said "actually MRR is $30K now" |

```bash
agentmemory grade abc123 good
agentmemory grade def456 again --context "user corrected: MRR is now $30K"
```

After grading "again", update the memory:
```bash
agentmemory add "MRR is $30K as of April 2026" --namespace business
```

The old memory will be automatically demoted via contradiction detection.

## When to Review

Run the review cycle during idle time, at session start, or on a schedule:

```bash
agentmemory review
```

This processes all due memories: checks source files, grades based on usage recency, detects leeches. You don't need to do anything manually — just run it periodically.

## Understanding Memory States

| State | Meaning |
|-------|---------|
| `new` | Just stored, not yet graded |
| `learning` | In early review cycle, graded once or twice |
| `review` | Graduated — on a spaced schedule. The happy path. |
| `relearning` | Failed a review (graded "again"), back to short intervals |
| `suspended` | Leech — failed 8+ times. Needs investigation or deletion. |

## Leech Detection

If a memory keeps getting graded "again" (8+ times), it's suspended as a leech. This means the information is volatile or the memory is poorly formed. When you see a leech:

1. Check if the information is still relevant
2. If yes, rephrase and store a new, clearer version
3. If no, leave it suspended (it won't surface again)

## Health Check

```bash
agentmemory health
```

Shows total memories, counts by state, leeches, due count, average retention. Use this to understand your memory quality over time.

## Context Injection

At session start, inject your strongest memories into context:

```bash
agentmemory prompt
```

This returns a formatted block of your top memories with strength indicators (strong/fading/weak). Add this to your system prompt.

## Principles

1. **Grade honestly.** "Again" is not punishment — it triggers relearning. Dishonest grades corrupt your scheduling.
2. **Store selectively.** Not everything is worth remembering. If it's in a file you can read, you may not need to memorize it.
3. **Review regularly.** The review cycle is how stale memories get caught and leeches get detected.
4. **Trust the algorithm.** If a memory keeps surfacing, it's because your retrievability is dropping. Grade it and move on — the interval will grow.
