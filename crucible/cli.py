"""CRUCIBLE CLI — command-line interface for all operations.

Commands:
    crucible init-db          Initialize the Neo4j knowledge graph schema
    crucible genesis          Bootstrap from seed papers
    crucible scout            Run nightly paper ingestion
    crucible dialectic        Run a full 5-phase dialectical cycle
    crucible review           Interactive human review of research briefs
    crucible status           Show system status
    crucible export-map       Export the Frontier Map
"""

from __future__ import annotations

import json
import logging
import sys

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

console = Console()


def _setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def cli(verbose: bool):
    """🔥 CRUCIBLE — Local Autonomous Research Engine"""
    _setup_logging(verbose)


@cli.command()
def init_db():
    """Initialize the Neo4j knowledge graph schema."""
    from crucible.graph import GraphStore

    graph = GraphStore()
    graph.init_schema()
    console.print("[green]✓[/green] Knowledge graph schema initialized.")
    graph.close()


@cli.command()
@click.option("--seeds", "-s", multiple=True, required=True, help="ArXiv paper IDs (e.g., 2001.08361)")
def genesis(seeds: tuple[str]):
    """Bootstrap the system from seed papers (Genesis Protocol)."""
    from crucible.genesis import GenesisProtocol

    proto = GenesisProtocol()

    console.print(f"\n🌱 Genesis Protocol — expanding {len(seeds)} seeds...\n")
    corpus = proto.generate_seed_corpus(list(seeds))

    table = Table(title="Seed Corpus")
    table.add_column("#", style="dim")
    table.add_column("Paper ID")
    table.add_column("Title", max_width=60)
    table.add_column("Citations", justify="right")

    for i, p in enumerate(corpus, 1):
        table.add_row(str(i), p["paper_id"], p["title"][:60], str(p.get("citation_count", "?")))

    console.print(table)
    console.print(f"\nCorpus saved. Review and run: [bold]crucible genesis-approve[/bold]")


@cli.command("genesis-approve")
@click.option("--exclude", "-x", multiple=True, help="Paper IDs to exclude.")
def genesis_approve(exclude: tuple[str]):
    """Approve the seed corpus and download papers."""
    from crucible.genesis import GenesisProtocol
    from crucible.parsing import DoclingParser
    from crucible.engine.scheduler import Scheduler

    proto = GenesisProtocol()
    corpus = proto.approve_corpus(exclude_ids=list(exclude) if exclude else None)
    console.print(f"[green]✓[/green] Approved {len(corpus)} papers.")

    console.print("Downloading PDFs...")
    paths = proto.download_corpus(corpus)
    console.print(f"[green]✓[/green] Downloaded {len(paths)} PDFs.")

    console.print("Parsing with Docling...")
    parser = DoclingParser()
    all_sections = []
    for path in paths:
        try:
            parsed = parser.parse_pdf(path)
            for sec in parsed.sections:
                all_sections.append({
                    "paper_id": parsed.paper_id,
                    "section_title": sec.section_title,
                    "text": sec.text,
                })
            console.print(f"  ✓ {path.name}: {len(parsed.sections)} sections")
        except Exception as e:
            console.print(f"  ✗ {path.name}: {e}", style="red")

    if all_sections:
        console.print(f"\nRunning Genesis DIALECTIC cycle on {len(all_sections)} sections...")
        scheduler = Scheduler()
        entry = scheduler.dialectic(sections=all_sections, cycle_id="genesis_001")

        from crucible.journal import JournalWriter
        journal = JournalWriter()
        journal.write_entry(entry)
        console.print("[green]✓[/green] Genesis complete. First journal entry written.")


@cli.command()
@click.option("--keywords", "-k", multiple=True, help="Search keywords.")
def scout(keywords: tuple[str]):
    """Run SCOUT mode — discover and ingest new papers."""
    from crucible.engine.scheduler import Scheduler

    scheduler = Scheduler()
    kw_list = list(keywords) if keywords else None
    scheduler.scout(keywords=kw_list)
    console.print("[green]✓[/green] SCOUT complete.")


@cli.command()
@click.option("--cycle-id", "-c", default=None, help="Custom cycle ID.")
def dialectic(cycle_id: str):
    """Run a full DIALECTIC cycle (5 phases)."""
    from crucible.engine.scheduler import Scheduler
    from crucible.journal import JournalWriter

    scheduler = Scheduler()
    entry = scheduler.dialectic(cycle_id=cycle_id)

    journal = JournalWriter()
    journal.write_entry(entry)

    briefs = entry.get("briefs", [])
    console.print(f"\n[green]✓[/green] DIALECTIC complete. {len(briefs)} research briefs generated.")

    if briefs:
        console.print("\n[bold]Research Briefs:[/bold]")
        for i, b in enumerate(briefs, 1):
            console.print(f"  {i}. {b.get('hypothesis', 'N/A')[:100]}")


@cli.command()
def review():
    """Interactive REVIEW mode — rate research briefs."""
    from crucible.engine.scheduler import Scheduler

    scheduler = Scheduler()
    scheduler.review()


@cli.command()
def status():
    """Show system status — graph stats, journal entries, frontier map."""
    from crucible.graph import GraphStore
    from crucible.journal import JournalWriter
    from crucible.frontier import FrontierMap

    console.print("\n🔥 [bold]CRUCIBLE Status[/bold]\n")

    # Graph stats
    try:
        graph = GraphStore()
        counts = graph.get_node_count()
        console.print("[bold]Knowledge Graph:[/bold]")
        console.print(f"  Claims: {counts.get('claims', 0)}")
        console.print(f"  Contradictions: {counts.get('contradictions', 0)}")
        console.print(f"  Gaps: {counts.get('gaps', 0)}")
        graph.close()
    except Exception as e:
        console.print(f"  [red]Graph unavailable:[/red] {e}")

    # Journal stats
    journal = JournalWriter()
    entries = journal.list_entries()
    console.print(f"\n[bold]Research Journal:[/bold]")
    console.print(f"  Entries: {len(entries)}")
    if entries:
        latest = journal.load_entry(entries[-1])
        console.print(f"  Latest cycle: {latest.get('cycle_id', 'N/A')}")
        console.print(f"  Latest briefs: {len(latest.get('briefs', []))}")

    # Frontier map
    try:
        fm = FrontierMap()
        summary = fm.get_summary()
        console.print(f"\n[bold]Frontier Map:[/bold]")
        console.print(f"  Settled: {summary['settled_count']}")
        console.print(f"  Contested: {summary['contested_count']}")
        console.print(f"  Terra Incognita: {summary['terra_incognita_count']}")
        console.print(f"  Themes: {summary['theme_count']}")
        console.print(f"  Cycles: {summary['total_cycles']}")
    except Exception:
        console.print(f"\n[bold]Frontier Map:[/bold] not yet created")

    console.print("")


@cli.command("export-map")
@click.option("--format", "fmt", type=click.Choice(["json", "summary"]), default="json")
@click.option("--output", "-o", default=None, help="Output file path.")
def export_map(fmt: str, output: str):
    """Export the Frontier Map."""
    from crucible.frontier import FrontierMap

    fm = FrontierMap()

    if fmt == "summary":
        summary = fm.get_summary()
        text = json.dumps(summary, indent=2)
    else:
        text = json.dumps(fm.state, indent=2, default=str)

    if output:
        with open(output, "w") as f:
            f.write(text)
        console.print(f"[green]✓[/green] Exported to {output}")
    else:
        console.print(text)


def main():
    cli()
