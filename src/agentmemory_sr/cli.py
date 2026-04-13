"""CLI for agentmemory-sr. Thin wrapper over MemoryStore."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import click

from .store import MemoryStore

DEFAULT_DB = os.environ.get("AGENTMEMORY_DB", "memory.db")


def get_store(db: str) -> MemoryStore:
    return MemoryStore(db)


@click.group()
@click.option("--db", default=DEFAULT_DB, envvar="AGENTMEMORY_DB", help="Path to memory database.")
@click.pass_context
def cli(ctx, db):
    """Spaced repetition memory for AI agents."""
    ctx.ensure_object(dict)
    ctx.obj["db"] = db


@cli.command()
@click.argument("content")
@click.option("--namespace", "-n", default="general", help="Memory namespace.")
@click.option("--source", "-s", default=None, help="Source file path for verification.")
@click.pass_context
def add(ctx, content, namespace, source):
    """Store a new memory."""
    store = get_store(ctx.obj["db"])
    memory = store.add(content, namespace=namespace, source=source)
    click.echo(json.dumps({"id": memory.id, "content": memory.content, "namespace": memory.namespace}))
    store.close()


@cli.command()
@click.argument("query")
@click.option("--top-k", "-k", default=5, help="Number of results.")
@click.option("--namespace", "-n", default=None, help="Filter by namespace.")
@click.pass_context
def search(ctx, query, top_k, namespace):
    """Search memories by relevance * retrievability."""
    store = get_store(ctx.obj["db"])
    memories = store.retrieve(query, top_k=top_k, namespace=namespace)
    results = []
    for m in memories:
        from .scheduler import get_retrievability
        r = get_retrievability(store.scheduler, m)
        results.append({
            "id": m.id,
            "content": m.content,
            "namespace": m.namespace,
            "state": m.state.value,
            "retrievability": round(r, 3),
            "stability": round(m.stability, 2) if m.stability else None,
        })
    click.echo(json.dumps(results, indent=2))
    store.close()


@cli.command()
@click.argument("memory_id")
@click.argument("grade", type=click.Choice(["again", "hard", "good", "easy"]))
@click.option("--context", "-c", default=None, help="Why this grade was given.")
@click.pass_context
def grade(ctx, memory_id, grade, context):
    """Grade a memory after use."""
    store = get_store(ctx.obj["db"])
    try:
        memory = store.grade(memory_id, grade, context=context)
        click.echo(json.dumps({
            "id": memory.id,
            "grade": grade,
            "state": memory.state.value,
            "stability": round(memory.stability, 2) if memory.stability else None,
            "next_due": memory.due.isoformat(),
        }))
    except ValueError as e:
        click.echo(json.dumps({"error": str(e)}), err=True)
    store.close()


@cli.command()
@click.pass_context
def review(ctx):
    """Run review cycle on due memories."""
    store = get_store(ctx.obj["db"])
    results = store.review()
    output = []
    for r in results:
        output.append({
            "memory_id": r.memory_id,
            "grade": r.grade.value,
            "state_before": r.state_before.value,
            "state_after": r.state_after.value,
            "stability_after": round(r.stability_after, 2) if r.stability_after else None,
        })
    click.echo(json.dumps({"reviewed": len(results), "results": output}, indent=2))
    store.close()


@cli.command()
@click.option("--n", default=20, help="Number of top memories.")
@click.option("--namespace", "-ns", default=None, help="Filter by namespace.")
@click.pass_context
def top(ctx, n, namespace):
    """Get top-N strongest memories for context injection."""
    store = get_store(ctx.obj["db"])
    memories = store.top_memories(n=n, namespace=namespace)
    results = []
    for m in memories:
        results.append({
            "id": m.id,
            "content": m.content,
            "namespace": m.namespace,
            "state": m.state.value,
            "stability": round(m.stability, 2) if m.stability else None,
        })
    click.echo(json.dumps(results, indent=2))
    store.close()


@cli.command()
@click.pass_context
def health(ctx):
    """Show memory health statistics."""
    store = get_store(ctx.obj["db"])
    report = store.health()
    click.echo(json.dumps(report.model_dump(), indent=2))
    store.close()


@cli.command()
@click.pass_context
def prompt(ctx):
    """Generate system prompt block for agent context injection."""
    store = get_store(ctx.obj["db"])
    click.echo(store.system_prompt())
    store.close()


@cli.command("install-skill")
@click.argument("target_dir")
def install_skill(target_dir):
    """Copy the skill file to a target directory."""
    skill_src = Path(__file__).parent / "skill.md"
    if not skill_src.exists():
        click.echo("Error: skill.md not found in package.", err=True)
        return

    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    dest = target / "agentmemory-sr.md"
    shutil.copy2(skill_src, dest)
    click.echo(f"Skill installed to {dest}")


if __name__ == "__main__":
    cli()
