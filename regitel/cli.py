"""RegIntel CLI — Click-based command line interface.

Domain: Generative AI / Agentic AI governance for Tier 1 banks.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.panel import Panel
from rich.table import Table

from regitel.config import load_config
from regitel.utils.logging import console, setup_logging

load_dotenv()


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

class AppContext:
    """Holds shared application state across CLI commands."""

    def __init__(self, config_path: str | None = None, verbose: bool = False):
        self.config = load_config(config_path)
        self.verbose = verbose
        setup_logging(verbose)

    @property
    def db(self):
        from regitel.storage.database import DatabaseManager
        return DatabaseManager(self.config.storage.database)

    @property
    def vectorstore(self):
        from regitel.storage.vectorstore import VectorStoreManager
        return VectorStoreManager(
            self.config.storage.chroma_path,
            embedding_model=self.config.embedding.model,
        )


pass_ctx = click.make_pass_decorator(AppContext, ensure=True)


def _format_token_usage(usage: dict) -> str:
    """Format aggregated OpenAI token usage for CLI output."""
    if not usage:
        return "0 tokens"

    total = int(usage.get("total_tokens", 0) or 0)
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    reasoning = int(usage.get("reasoning_tokens", 0) or 0)
    cached = int(usage.get("cached_input_tokens", 0) or 0)
    llm_calls = int(usage.get("llm_calls", 0) or 0)
    searches = int(usage.get("web_search_calls", 0) or 0)

    parts = [f"{total:,} total", f"{input_tokens:,} in", f"{output_tokens:,} out"]
    if reasoning:
        parts.append(f"{reasoning:,} reasoning")
    if cached:
        parts.append(f"{cached:,} cached")
    if llm_calls or searches:
        parts.append(f"{llm_calls} LLM calls")
        parts.append(f"{searches} web searches")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

@click.group()
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Verbose output")
@click.pass_context
def cli(ctx, config_path: str | None, verbose: bool):
    """RegIntel — GenAI Governance Regulatory Intelligence for Tier 1 Banks."""
    ctx.ensure_object(dict)
    ctx.obj = AppContext(config_path=config_path, verbose=verbose)


# ---------------------------------------------------------------------------
# db commands
# ---------------------------------------------------------------------------

@cli.group()
def db():
    """Database operations."""
    pass


@db.command("init")
@click.option("--seed", is_flag=True, default=False, help="Seed jurisdiction data")
@click.pass_obj
def db_init(ctx: AppContext, seed: bool):
    """Initialize the database and vector store."""
    console.print("[info]Initializing RegIntel database...[/info]")

    # Create SQLite tables
    ctx.db.init_db()
    console.print("  [success]\u2713[/success] SQLite database created at "
                   f"[muted]{ctx.config.storage.database}[/muted]")

    # Create ChromaDB collections
    ctx.vectorstore.init_collections()
    console.print("  [success]\u2713[/success] ChromaDB collections initialized at "
                   f"[muted]{ctx.config.storage.chroma_path}[/muted]")

    if seed:
        _seed_jurisdictions(ctx)

    console.print("\n[success]Database initialized successfully.[/success]")


@db.command("stats")
@click.pass_obj
def db_stats(ctx: AppContext):
    """Show database statistics."""
    db_stats = ctx.db.get_stats()
    vs_stats = ctx.vectorstore.get_stats()

    # SQLite stats table
    table = Table(title="RegIntel Database Statistics", show_header=True)
    table.add_column("Entity", style="cyan")
    table.add_column("Count", justify="right", style="bold")

    for entity, count in db_stats.items():
        label = entity.replace("_", " ").title()
        table.add_row(label, str(count))

    console.print(table)

    # ChromaDB stats table
    vs_table = Table(title="Vector Store Collections", show_header=True)
    vs_table.add_column("Collection", style="cyan")
    vs_table.add_column("Documents", justify="right", style="bold")

    for collection, count in vs_stats.items():
        vs_table.add_row(collection, str(count))

    console.print(vs_table)

    # Database file info
    db_path = Path(ctx.config.storage.database)
    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        console.print(f"\n[muted]Database file: {db_path} ({size_mb:.2f} MB)[/muted]")


@db.command("seed")
@click.pass_obj
def db_seed(ctx: AppContext):
    """Seed the database with jurisdiction profiles."""
    _seed_jurisdictions(ctx)


@db.command("dedup")
@click.option("--apply", is_flag=True, default=False, help="Actually remove duplicates (default: dry run)")
@click.pass_obj
def db_dedup(ctx: AppContext, apply: bool):
    """Detect and merge duplicate regulations."""
    from regitel.storage.dedup import run_dedup

    mode = "APPLYING changes" if apply else "DRY RUN (use --apply to commit)"
    console.print(f"[info]Deduplication — {mode}[/info]\n")

    results = run_dedup(ctx.db, dry_run=not apply)

    if not results:
        console.print("[success]No duplicates found.[/success]")
        return

    table = Table(title=f"Duplicate Groups ({len(results)})", show_header=True, show_lines=True)
    table.add_column("Jurisdiction", style="cyan")
    table.add_column("Regulation Name")
    table.add_column("Keep", style="green")
    table.add_column("Remove", style="red")
    table.add_column("Merged Reqs", justify="right")

    total_removed = 0
    for r in results:
        removed = r.get("removed", [])
        total_removed += len(removed)
        table.add_row(
            r["jurisdiction"],
            r["name"][:50],
            r["kept"],
            "\n".join(removed),
            str(r.get("reqs_merged", 0)),
        )

    console.print(table)
    console.print(f"\n[info]Total: {len(results)} groups, {total_removed} duplicates "
                  f"{'removed' if apply else 'would be removed'}[/info]")


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------

@cli.command("status")
@click.option("--jurisdiction", "-j", default=None, help="Filter by jurisdiction ID")
@click.option("--stale", is_flag=True, default=False, help="Show only stale entries")
@click.pass_obj
def status(ctx: AppContext, jurisdiction: str | None, stale: bool):
    """View regulatory landscape status for AI governance."""
    session = ctx.db.get_session()

    try:
        jurisdictions = ctx.db.get_jurisdictions(session)

        if jurisdiction:
            jurisdictions = [j for j in jurisdictions if j.id == jurisdiction]
            if not jurisdictions:
                console.print(f"[error]Jurisdiction '{jurisdiction}' not found.[/error]")
                return

        table = Table(title="AI Governance Regulatory Landscape", show_header=True)
        table.add_column("Jurisdiction", style="cyan")
        table.add_column("Region", style="muted")
        table.add_column("Priority", justify="center")
        table.add_column("Regulations", justify="right", style="bold")
        table.add_column("AI Reqs", justify="right", style="bold")
        table.add_column("AI-Specific", justify="center")
        table.add_column("Last Researched", style="muted")

        for j in jurisdictions:
            regs = ctx.db.get_regulations_by_jurisdiction(session, j.id)
            req_count = sum(len(r.ai_governance_requirements) for r in regs)
            ai_specific_count = sum(1 for r in regs if r.ai_specific)
            last = j.last_researched_at.strftime("%Y-%m-%d") if j.last_researched_at else "Never"

            if stale and j.last_researched_at:
                continue  # Skip non-stale if --stale flag

            table.add_row(
                j.name,
                j.region,
                str(j.research_priority),
                str(len(regs)),
                str(req_count),
                f"[green]{ai_specific_count}[/green]",
                last,
            )

        console.print(table)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# changelog command
# ---------------------------------------------------------------------------

@cli.command("changelog")
@click.option("--since", default=None, help="Show changes since date (YYYY-MM-DD)")
@click.option("--unreviewed", is_flag=True, default=False, help="Show only unreviewed")
@click.option("--limit", default=50, help="Max entries to show")
@click.pass_obj
def changelog(ctx: AppContext, since: str | None, unreviewed: bool, limit: int):
    """View detected regulation changes."""
    session = ctx.db.get_session()

    try:
        since_dt = datetime.strptime(since, "%Y-%m-%d") if since else None
        changes = ctx.db.get_recent_changes(session, since=since_dt, limit=limit)

        if unreviewed:
            changes = [c for c in changes if not c.reviewed]

        if not changes:
            console.print("[muted]No changes found.[/muted]")
            return

        table = Table(title="Regulation Changes", show_header=True)
        table.add_column("Date", style="muted")
        table.add_column("Type", style="bold")
        table.add_column("Regulation", style="cyan")
        table.add_column("Summary")
        table.add_column("Reviewed", justify="center")

        for c in changes:
            type_style = {
                "new": "green",
                "updated": "yellow",
                "superseded": "red",
                "revoked": "red bold",
                "deadline_approaching": "yellow bold",
            }.get(c.change_type, "white")

            table.add_row(
                c.detected_at.strftime("%Y-%m-%d"),
                f"[{type_style}]{c.change_type}[/{type_style}]",
                c.regulation_id,
                c.summary or "",
                "\u2713" if c.reviewed else "\u2717",
            )

        console.print(table)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# export command
# ---------------------------------------------------------------------------

@cli.command("export")
@click.option("--format", "fmt", type=click.Choice(["json", "csv", "summary"]), default="json")
@click.option("--jurisdiction", "-j", default=None, help="Filter by jurisdiction ID")
@click.option("--region", "-r", default=None, help="Filter by region (eu, apac, americas, mea, global)")
@click.option("--requirement-type", default=None,
              help="Filter by requirement type (model_risk_management, data_residency, ai_inventory, explainability, third_party_risk, etc.)")
@click.option("--theme", default=None,
              help="Filter by governance theme (e.g., generative_ai, model_risk_management, data_privacy)")
@click.option("--entity-type", default=None,
              help="Filter by entity type (bank, credit_union, insurance_company, all)")
@click.option("--ai-specific", is_flag=True, default=False, help="Only AI-specific regulations")
@click.option("--applied-only", is_flag=True, default=False, help="Only existing rules applied to AI")
@click.option("--mandatory", is_flag=True, default=False, help="Only mandatory requirements")
@click.option("--output", "-o", default=None, help="Output file path (default: stdout or auto-named)")
@click.pass_obj
def export_data(
    ctx: AppContext,
    fmt: str,
    jurisdiction: str | None,
    region: str | None,
    requirement_type: str | None,
    theme: str | None,
    entity_type: str | None,
    ai_specific: bool,
    applied_only: bool,
    mandatory: bool,
    output: str | None,
):
    """Export regulation data as JSON, CSV, or text summary."""
    from pathlib import Path as P
    from regitel.query.engine import QueryEngine
    from regitel.query.export import export_json, export_csv, export_summary

    engine = QueryEngine(ctx.db)
    session = ctx.db.get_session()

    try:
        result = engine.search(
            session,
            jurisdiction=jurisdiction,
            region=region,
            requirement_type=requirement_type,
            governance_theme=theme,
            entity_type=entity_type,
            ai_specific_only=ai_specific,
            applied_only=applied_only,
            mandatory_only=mandatory,
        )

        if result.result_count == 0:
            console.print("[warning]No matching regulations found.[/warning]")
            return

        out_path = P(output) if output else None

        if fmt == "json":
            text = export_json(result, output_path=out_path)
            if not out_path:
                console.print(text)
            else:
                console.print(f"[success]Exported {result.result_count} regulations to {out_path}[/success]")
        elif fmt == "csv":
            text = export_csv(result, output_path=out_path)
            if not out_path:
                console.print(text)
            else:
                console.print(f"[success]Exported {result.result_count} regulations to {out_path}[/success]")
        elif fmt == "summary":
            text = export_summary(result)
            if out_path:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(text)
                console.print(f"[success]Exported summary to {out_path}[/success]")
            else:
                console.print(text)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# research command
# ---------------------------------------------------------------------------

@cli.command("research")
@click.option("--jurisdiction", "-j", default=None, help="Target jurisdiction")
@click.option("--full", is_flag=True, default=False, help="Full deep scan")
@click.option("--dry-run", is_flag=True, default=False, help="Use mock search (no API calls)")
@click.option("--quick", is_flag=True, default=False,
              help="Faster local-model scan: fewer queries and one repair pass")
@click.pass_obj
def research(ctx: AppContext, jurisdiction: str | None, full: bool, dry_run: bool, quick: bool):
    """Run the research pipeline to discover AI governance regulations."""
    from regitel.graphs.research_graph import run_research

    jurisdictions = [jurisdiction] if jurisdiction else None

    if dry_run:
        console.print("[warning]DRY RUN — using mock search, no API calls[/warning]\n")
    if quick:
        console.print(
            "[warning]QUICK RUN — fewer queries and one repair pass[/warning]\n"
        )

    mode = "full scan" if full else (f"jurisdiction: {jurisdiction}" if jurisdiction else "priority-1")
    console.print(f"[info]Starting AI governance research pipeline ({mode})...[/info]\n")

    try:
        result = run_research(
            config=ctx.config,
            jurisdictions=jurisdictions,
            full_scan=full,
            dry_run=dry_run,
            quick=quick,
        )

        # Display results
        changes = result.get("changes_detected", [])
        confidence = result.get("confidence_score", 0.0)
        iterations = result.get("iteration_count", 0)
        error = result.get("error")

        if error:
            console.print(f"\n[error]Pipeline error: {error}[/error]")

        console.print("\n[success]Research complete.[/success]")
        console.print(f"  Findings: {len(result.get('structured_findings', []))} regulations")
        console.print(f"  Reflection iterations: {iterations}")
        console.print(f"  Confidence: {confidence:.2f}")
        console.print(f"  Tokens: {_format_token_usage(result.get('token_usage', {}))}")

        if changes:
            console.print(f"\n  [highlight]Changes detected: {len(changes)}[/highlight]")
            ch_table = Table(show_header=True)
            ch_table.add_column("Type", style="bold")
            ch_table.add_column("Regulation", style="cyan")
            ch_table.add_column("Summary")

            for c in changes:
                style = "green" if c["change_type"] == "new" else "yellow"
                ch_table.add_row(
                    f"[{style}]{c['change_type']}[/{style}]",
                    c.get("regulation_id", ""),
                    c.get("summary", ""),
                )
            console.print(ch_table)
        else:
            console.print("\n  [muted]No new changes detected.[/muted]")

    except Exception as e:
        console.print(f"\n[error]Research pipeline failed: {e}[/error]")
        if ctx.verbose:
            import traceback
            console.print(traceback.format_exc())


# ---------------------------------------------------------------------------
# scan command (batch orchestrator)
# ---------------------------------------------------------------------------

@cli.command("scan")
@click.option("--all", "scan_all", is_flag=True, default=False,
              help="Scan ALL jurisdictions (ordered by priority)")
@click.option("--priority", "-p", type=int, default=None,
              help="Scan jurisdictions at this priority level or higher (e.g. -p 3)")
@click.option("--jurisdiction", "-j", default=None,
              help="Comma-separated jurisdiction IDs (e.g. eu,uk,singapore)")
@click.option("--dry-run", is_flag=True, default=False,
              help="Use mock search — no API calls")
@click.option("--quick", is_flag=True, default=False,
              help="Faster local-model scan: fewer queries and one repair pass")
@click.pass_obj
def scan(ctx: AppContext, scan_all: bool, priority: int | None,
         jurisdiction: str | None, dry_run: bool, quick: bool):
    """Run an isolated per-jurisdiction batch scan for AI governance regulations.

    Each jurisdiction gets its own research pipeline invocation so failures
    in one region never affect another.  A summary report is printed at the
    end with per-jurisdiction results, timings, and errors.

    \b
    Examples:
      regitel scan --all                    # every jurisdiction
      regitel scan --all --dry-run          # test run (mock search)
      regitel scan -p 1                     # priority-1 only
      regitel scan -p 3                     # priority 1-3
      regitel scan -j eu,uk,singapore       # specific jurisdictions
    """
    from regitel.graphs.batch_orchestrator import run_batch_scan

    # Resolve targets
    jids = jurisdiction.split(",") if jurisdiction else None

    if not scan_all and not priority and not jids:
        console.print("[error]Specify --all, --priority N, or -j id1,id2[/error]")
        raise SystemExit(1)

    if dry_run:
        console.print("[warning]DRY RUN — using mock search, no API calls[/warning]\n")
    if quick:
        console.print(
            "[warning]QUICK RUN — fewer queries and one repair pass[/warning]\n"
        )

    # Describe what we're about to do
    if scan_all:
        label = "all jurisdictions"
    elif priority:
        label = f"priority \u2264 {priority}"
    else:
        label = f"jurisdictions: {', '.join(jids)}"

    console.print(f"[bold]Batch AI Governance Scan[/bold] — {label}\n")

    result = run_batch_scan(
        config=ctx.config,
        jurisdictions=jids,
        priority=priority if not scan_all else None,
        dry_run=dry_run,
        quick=quick,
    )

    # \u2500\ufe0f Per-jurisdiction results table \u2500\ufe0f
    results = result.get("results", [])
    summary = result.get("summary", {})

    table = Table(
        title="Per-Jurisdiction Results",
        show_header=True,
        header_style="bold",
        title_style="bold cyan",
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Jurisdiction", style="cyan", min_width=20)
    table.add_column("Status", width=8)
    table.add_column("Findings", justify="right", width=9)
    table.add_column("New", justify="right", width=5)
    table.add_column("Updated", justify="right", width=8)
    table.add_column("Conf.", justify="right", width=6)
    table.add_column("Iters", justify="right", width=5)
    table.add_column("Time", justify="right", width=8)
    table.add_column("Error", style="red", max_width=35)

    for i, r in enumerate(results, 1):
        status_str = (
            "[green]\u2713[/green]" if r["status"] == "success"
            else "[red]\u2717[/red]"
        )
        err_short = (r.get("error_message") or "")[:35]
        table.add_row(
            str(i),
            r.get("jurisdiction_name", r["jurisdiction_id"]),
            status_str,
            str(r["findings_count"]),
            str(r["new_regulations"]),
            str(r["updated_regulations"]),
            f"{r['confidence']:.2f}",
            str(r["reflection_iterations"]),
            f"{r['duration_seconds']:.0f}s",
            err_short,
        )

    console.print(table)

    # \u2500\ufe0f Summary panel \u2500\ufe0f
    console.print()
    s = summary
    status_line = (
        f"[green]{s.get('successful', 0)} succeeded[/green]"
        f"  [red]{s.get('failed', 0)} failed[/red]"
        f"  out of {s.get('total_jurisdictions', 0)}"
    )
    console.print(f"[bold]Summary[/bold]  {status_line}")
    console.print(
        f"  Findings: {s.get('total_findings', 0)} total  "
        f"({s.get('new_regulations', 0)} new, "
        f"{s.get('updated_regulations', 0)} updated)"
    )
    console.print(f"  Avg confidence: {s.get('average_confidence', 0):.3f}")
    console.print(f"  Total time: {s.get('total_duration_seconds', 0):.0f}s")
    console.print(f"  Tokens: {_format_token_usage(s.get('token_usage', {}))}")

    failed = s.get("failed_jurisdictions", [])
    if failed:
        console.print("\n[bold red]Failed jurisdictions:[/bold red]")
        for f in failed:
            console.print(f"  [red]{f['id']}[/red]: {f['error']}")


# ---------------------------------------------------------------------------
# query command group
# ---------------------------------------------------------------------------

@cli.group("query")
def query_group():
    """Query regulations across jurisdictions."""
    pass


@query_group.command("search")
@click.option("--jurisdiction", "-j", default=None, help="Jurisdiction ID")
@click.option("--region", "-r", default=None, help="Region (eu, apac, americas, mea, global)")
@click.option("--text", "-q", default=None, help="Free-text search")
@click.option("--requirement-type", default=None,
              help="Filter by requirement type")
@click.option("--entity-type", default=None, help="Filter by entity type")
@click.option("--ai-specific", is_flag=True, default=False, help="Only AI-specific regulations")
@click.option("--applied-only", is_flag=True, default=False, help="Only existing rules applied to AI")
@click.option("--min-confidence", default=0.0, type=float, help="Minimum confidence")
@click.option("--output", "-o", default=None, help="Output file path")
@click.pass_obj
def query_search(
    ctx: AppContext,
    jurisdiction: str | None,
    region: str | None,
    text: str | None,
    requirement_type: str | None,
    entity_type: str | None,
    ai_specific: bool,
    applied_only: bool,
    min_confidence: float,
    output: str | None,
):
    """Search regulations with structured filters."""
    from pathlib import Path as P
    from regitel.query.engine import QueryEngine
    from regitel.query.export import export_json

    engine = QueryEngine(ctx.db)
    session = ctx.db.get_session()

    try:
        result = engine.search(
            session,
            text=text,
            jurisdiction=jurisdiction,
            region=region,
            requirement_type=requirement_type,
            entity_type=entity_type,
            ai_specific_only=ai_specific,
            applied_only=applied_only,
            min_confidence=min_confidence,
        )

        if result.result_count == 0:
            console.print("[warning]No matching regulations found.[/warning]")
            return

        if output:
            out_path = P(output)
            export_json(result, output_path=out_path)
            console.print(f"[success]Exported {result.result_count} results to {out_path}[/success]")
        else:
            from regitel.query.export import export_summary
            console.print(export_summary(result))

    finally:
        session.close()


@query_group.command("compare")
@click.argument("jurisdictions", required=True)
@click.option("--output", "-o", default=None, help="Output file path")
@click.pass_obj
def query_compare(ctx: AppContext, jurisdictions: str, output: str | None):
    """Compare regulations across multiple jurisdictions.

    Example: regitel query compare eu,uk,us,singapore
    """
    from pathlib import Path as P
    from regitel.query.engine import QueryEngine
    from regitel.query.export import export_json

    jids = [j.strip() for j in jurisdictions.split(",")]
    engine = QueryEngine(ctx.db)
    session = ctx.db.get_session()

    try:
        comparison = engine.compare_jurisdictions(session, jids)

        # Build a combined result for display
        all_regs = []
        for jid, regs in comparison.items():
            all_regs.extend(regs)

        console.print(f"[info]Comparing {len(jids)} jurisdictions: {', '.join(jids)}[/info]\n")

        for jid, regs in comparison.items():
            total_ai = sum(1 for r in regs if r.ai_specific)
            total_applied = sum(1 for r in regs if not r.ai_specific)
            total_reqs = sum(len(r.ai_governance_requirements) for r in regs)
            console.print(f"  [cyan]{jid}[/cyan]: {len(regs)} regulations "
                          f"({total_ai} AI-specific, {total_applied} applied) "
                          f"with {total_reqs} governance requirements")

        # Per-regulation detail
        for jid, regs in comparison.items():
            console.print(f"\n[cyan]=== {jid} ===[/cyan]")
            for reg in regs:
                _render_regulation(reg)

        if output:
            from regitel.query.export import QueryResult as QR
            combined = QR(
                query=f"compare={','.join(jids)}",
                result_count=len(all_regs),
                regulations=all_regs,
            )
            out_path = P(output)
            export_json(combined, output_path=out_path)
            console.print(f"\n[success]Exported comparison to {out_path}[/success]")

    finally:
        session.close()


# ---------------------------------------------------------------------------
# matrix command — cross-jurisdiction comparison
# ---------------------------------------------------------------------------

@cli.command("matrix")
@click.option("--requirement-type", "-t", default=None,
              help="Filter by requirement type")
@click.option("--jurisdiction", "-j", default=None,
              help="Comma-separated jurisdiction IDs (default: all)")
@click.pass_obj
def matrix(ctx: AppContext, requirement_type: str | None, jurisdiction: str | None):
    """Cross-jurisdiction comparison matrix for AI governance requirements.

    Shows a table of how each jurisdiction addresses each governance attribute,
    highlighting gaps and mandatory vs recommended distinctions.

    \b
    Examples:
      regitel matrix                         # all types, all jurisdictions
      regitel matrix -t model_risk_management  # model risk only
      regitel matrix -j eu,uk,us             # EU, UK, US only
    """
    from regitel.query.engine import QueryEngine

    jids = [j.strip() for j in jurisdiction.split(",")] if jurisdiction else None
    engine = QueryEngine(ctx.db)
    session = ctx.db.get_session()

    try:
        matrix_data = engine.governance_matrix(session)

        if requirement_type:
            matrix_data = [r for r in matrix_data if r["requirement_type"] == requirement_type]
        if jids:
            matrix_data = [r for r in matrix_data if r["jurisdiction_id"] in jids]

        if not matrix_data:
            console.print("[muted]No governance requirements found matching criteria.[/muted]")
            return

        table = Table(title="AI Governance Requirements Matrix", show_header=True, show_lines=True)
        table.add_column("Jurisdiction", style="cyan")
        table.add_column("Regulation", min_width=20)
        table.add_column("AI-Specific", justify="center")
        table.add_column("Requirement", min_width=18)
        table.add_column("Risk Tier", justify="center")
        table.add_column("Mandatory", justify="center")
        table.add_column("Deployers", justify="center")
        table.add_column("Providers", justify="center")

        for row in matrix_data:
            ai_tag = "[green]\u2713[/green]" if row.get("ai_specific") else "[muted]\u2014[/muted]"
            mand = "[green]\u2713[/green]" if row.get("mandatory") else "[muted]recommended[/muted]"
            deployers = "[green]\u2713[/green]" if row.get("applicable_to_deployers") else "[muted]\u2014[/muted]"
            providers = "[green]\u2713[/green]" if row.get("applicable_to_providers") else "[muted]\u2014[/muted]"

            table.add_row(
                row["jurisdiction_name"][:20],
                row["regulation"][:30],
                ai_tag,
                row["requirement_type"],
                row.get("risk_tier") or "\u2014",
                mand,
                deployers,
                providers,
            )

        console.print(table)

    finally:
        session.close()


# ---------------------------------------------------------------------------
# frameworks command — AI control framework comparison
# ---------------------------------------------------------------------------

@cli.command("frameworks")
@click.option("--jurisdiction", "-j", default=None,
              help="Comma-separated jurisdiction IDs (default: all)")
@click.pass_obj
def frameworks(ctx: AppContext, jurisdiction: str | None):
    """Compare AI control frameworks across jurisdictions.

    Shows inventory, explainability, human oversight, and third-party assessment
    requirements for each jurisdiction's control frameworks.

    \b
    Examples:
      regitel frameworks                      # all frameworks
      regitel frameworks -j eu,uk,us          # EU, UK, US only
    """
    from regitel.query.engine import QueryEngine

    jids = [j.strip() for j in jurisdiction.split(",")] if jurisdiction else None
    engine = QueryEngine(ctx.db)
    session = ctx.db.get_session()

    try:
        framework_data = engine.framework_summary(session)

        if jids:
            framework_data = [r for r in framework_data if r["jurisdiction_id"] in jids]

        if not framework_data:
            console.print("[muted]No control frameworks found.[/muted]")
            return

        table = Table(title="AI Control Frameworks Comparison", show_header=True, show_lines=True)
        table.add_column("Jurisdiction", style="cyan")
        table.add_column("Regulation", min_width=20)
        table.add_column("AI-Specific", justify="center")
        table.add_column("Framework", min_width=18)
        table.add_column("Inventory", justify="center")
        table.add_column("Explain.", justify="center")
        table.add_column("Human Oversight", justify="center")
        table.add_column("3rd Party", justify="center")
        table.add_column("Binding", justify="center")

        for row in framework_data:
            ai_tag = "[green]\u2713[/green]" if row.get("ai_specific") else "[muted]\u2014[/muted]"
            inv = "[green]\u2713[/green]" if row.get("inventory_required") else "[muted]\u2014[/muted]"
            expl = "[green]\u2713[/green]" if row.get("explainability_required") else "[muted]\u2014[/muted]"
            human = "[green]\u2713[/green]" if row.get("human_overview_required") else "[muted]\u2014[/muted]"
            tp = "[green]\u2713[/green]" if row.get("third_party_assessment") else "[muted]\u2014[/muted]"
            bind = "[green]\u2713[/green]" if row.get("binding") else "[yellow]voluntary[/yellow]"

            table.add_row(
                row["jurisdiction_name"][:20],
                row["regulation"][:30],
                ai_tag,
                row.get("framework_name") or "\u2014",
                inv,
                expl,
                human,
                tp,
                bind,
            )

        console.print(table)

    finally:
        session.close()


def _render_regulation(reg):
    """Render a single regulation result to the console."""
    ai_tag = " [AI-SPECIFIC]" if reg.ai_specific else ""
    title = f"{reg.short_name or reg.name}{ai_tag} [{reg.jurisdiction_name}]"
    panel_lines = []
    panel_lines.append(f"ID: {reg.id}")
    panel_lines.append(f"Type: {reg.regulation_type} | Status: {reg.status} | Confidence: {reg.confidence_score:.0%}")
    if reg.issuing_body:
        panel_lines.append(f"Issuer: {reg.issuing_body}")
    if reg.effective_date:
        panel_lines.append(f"Effective: {reg.effective_date}")
    if reg.url:
        panel_lines.append(f"URL: {reg.url}")
    if reg.governance_themes:
        panel_lines.append(f"Themes: {', '.join(reg.governance_themes)}")

    if reg.ai_governance_requirements:
        panel_lines.append(f"\nAI Governance Requirements ({len(reg.ai_governance_requirements)}):")
        for req in reg.ai_governance_requirements:
            mand = "[bold green]mandatory[/bold green]" if req.get("mandatory") else "[muted]recommended[/muted]"
            deployers = "deployers" if req.get("applicable_to_deployers") else ""
            providers = "providers" if req.get("applicable_to_providers") else ""
            audience = ", ".join(filter(None, [deployers, providers])) or "all"
            panel_lines.append(f"  \u2022 {req.get('requirement_type', '?')} ({audience}) — {mand}")
            if req.get("risk_tier"):
                panel_lines.append(f"    Risk tier: {req['risk_tier']}")
            if req.get("governance_scope"):
                panel_lines.append(f"    Scope: {', '.join(req['governance_scope'])}")
            if req.get("key_controls"):
                panel_lines.append(f"    Controls: {', '.join(req['key_controls'][:3])}")
            if req.get("notes"):
                note = req["notes"][:150] + ("..." if len(req["notes"]) > 150 else "")
                panel_lines.append(f"    [muted]{note}[/muted]")

    if reg.ai_control_frameworks:
        panel_lines.append(f"\nAI Control Frameworks ({len(reg.ai_control_frameworks)}):")
        for fw in reg.ai_control_frameworks:
            binding = "binding" if fw.get("binding") else "voluntary"
            panel_lines.append(f"  \u2022 {fw.get('framework_name', '?')} ({binding})")
            if fw.get("inventory_required"):
                panel_lines.append("    Inventory: required")
            if fw.get("explainability_required"):
                panel_lines.append("    Explainability: required")

    console.print(Panel("\n".join(panel_lines), title=title, border_style="cyan"))
    console.print()


# ---------------------------------------------------------------------------
# validate command
# ---------------------------------------------------------------------------

@cli.command("validate")
@click.option("--against-kb", "kb_path", required=True,
              type=click.Path(exists=True), help="Path to Knowledge Base root directory")
@click.option("--jurisdiction", "-j", default=None, help="Benchmark specific jurisdiction only")
@click.option("--output", "-o", default=None, help="Save detailed results as JSON")
@click.pass_obj
def validate(ctx: AppContext, kb_path: str, jurisdiction: str | None, output: str | None):
    """Benchmark system findings against the existing Knowledge Base PDFs."""
    from pathlib import Path as P
    from regitel.validate.benchmark import run_benchmark

    jurisdictions = [jurisdiction] if jurisdiction else None

    console.print(f"[info]Running benchmark against KB: {kb_path}[/info]\n")

    result = run_benchmark(
        db_manager=ctx.db,
        kb_root=P(kb_path),
        jurisdictions=jurisdictions,
        verbose=ctx.verbose,
    )

    # Summary table
    console.print("\n[bold]Benchmark Summary[/bold]\n")

    summary_table = Table(show_header=True, show_lines=True, title="Overall Metrics")
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Value", justify="right", style="bold")
    summary_table.add_row("KB documents scanned", str(result.total_kb_docs))
    summary_table.add_row("DB regulations", str(result.total_db_regs))
    summary_table.add_row("Matched (KB \u2192 DB)", str(result.total_matched))
    summary_table.add_row("Overall coverage", f"{result.overall_coverage:.0%}")
    summary_table.add_row("AI-relevant in KB", str(result.total_pentest_relevant))
    summary_table.add_row("AI-relevant matched", str(result.total_pentest_matched))
    summary_table.add_row("AI-relevant coverage", f"{result.overall_pentest_coverage:.0%}")
    console.print(summary_table)

    # Per-jurisdiction table
    jur_table = Table(
        show_header=True, show_lines=True,
        title="Per-Jurisdiction Benchmark"
    )
    jur_table.add_column("Jurisdiction", style="cyan")
    jur_table.add_column("KB Docs", justify="right")
    jur_table.add_column("DB Regs", justify="right")
    jur_table.add_column("Matched", justify="right")
    jur_table.add_column("Coverage", justify="right", style="bold")
    jur_table.add_column("AI KB", justify="right")
    jur_table.add_column("AI Match", justify="right")
    jur_table.add_column("AI Cov.", justify="right", style="bold")
    jur_table.add_column("Extras (DB only)", justify="right")

    for j in result.jurisdictions:
        cov_style = "green" if j.coverage_score >= 0.5 else ("yellow" if j.coverage_score >= 0.25 else "red")
        pc_style = "green" if j.pentest_coverage >= 0.5 else ("yellow" if j.pentest_coverage >= 0.25 else "red")
        jur_table.add_row(
            j.jurisdiction_id,
            str(j.kb_doc_count),
            str(j.db_reg_count),
            str(j.matched_count),
            f"[{cov_style}]{j.coverage_score:.0%}[/{cov_style}]",
            str(j.pentest_relevant_in_kb),
            str(j.pentest_relevant_matched),
            f"[{pc_style}]{j.pentest_coverage:.0%}[/{pc_style}]",
            str(len(j.extras)),
        )

    console.print(jur_table)

    # Gap analysis — unmatched KB docs
    ai_gaps = []
    for j in result.jurisdictions:
        for gap in j.gaps:
            if gap.pentest_relevant:
                ai_gaps.append(gap)

    if ai_gaps:
        console.print(f"\n[warning]AI-relevant KB documents NOT matched ({len(ai_gaps)}):[/warning]")
        gap_table = Table(show_header=True)
        gap_table.add_column("Jurisdiction", style="cyan")
        gap_table.add_column("PDF File")
        gap_table.add_column("Keywords")

        for gap in ai_gaps:
            gap_table.add_row(
                gap.jurisdiction_id,
                gap.pdf_file,
                ", ".join(gap.pentest_keywords[:5]),
            )
        console.print(gap_table)

    # Save detailed JSON if requested
    if output:
        from dataclasses import asdict
        import json as json_mod
        out_path = P(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_mod.dumps(asdict(result), indent=2, default=str))
        console.print(f"\n[success]Detailed results saved to {out_path}[/success]")


# ---------------------------------------------------------------------------
# orphans command
# ---------------------------------------------------------------------------

@cli.command("orphans")
@click.option("--against-kb", "kb_path", default=None,
              type=click.Path(exists=True),
              help="Path to Knowledge Base root directory (PDF library)")
@click.option("--jurisdiction", "-j", default=None,
              help="Filter to a specific jurisdiction")
@click.option("--ai-requirements", is_flag=True, default=False,
              help="Show only regulations that have AI governance requirements")
@click.option("--output", "-o", default=None,
              help="Save results as JSON")
@click.pass_obj
def orphans(ctx: AppContext, kb_path: str | None, jurisdiction: str | None,
            ai_requirements: bool, output: str | None):
    """List regulations with no matching source document.

    Without --against-kb, shows DB regulations that have no entry in the
    source_documents table (i.e. no downloaded artifact).

    With --against-kb, cross-references the database against your PDF
    library and lists regulations that have no matching PDF.

    \b
    Examples:
      regitel orphans                            # regs with no source document
      regitel orphans -j eu                      # EU only
      regitel orphans --ai-requirements          # only regs with AI governance reqs
      regitel orphans --against-kb /path/to/KB   # regs with no matching PDF
      regitel orphans -o orphans.json            # save results
    """
    from regitel.storage.database import RegulationRow, SourceDocumentRow

    session = ctx.db.get_session()

    try:
        if kb_path:
            # \u2500\ufe0f KB mode: cross-reference against PDF library \u2500\ufe0f
            from pathlib import Path as P
            from regitel.validate.benchmark import run_benchmark

            console.print(f"[info]Cross-referencing DB against KB: {kb_path}[/info]\n")
            jurisdictions = [jurisdiction] if jurisdiction else None
            result = run_benchmark(
                db_manager=ctx.db,
                kb_root=P(kb_path),
                jurisdictions=jurisdictions,
                verbose=False,
            )

            # Collect all "extras" (DB regs with no KB match)
            orphan_ids: set[str] = set()
            for jbench in result.jurisdictions:
                orphan_ids.update(jbench.extras)

            # Load full regulation rows for those IDs
            query = (
                session.query(RegulationRow)
                .filter(RegulationRow.id.in_(orphan_ids))
                .order_by(RegulationRow.jurisdiction_id, RegulationRow.name)
            )
            if ai_requirements:
                from sqlalchemy import exists
                from regitel.storage.database import AIGovernanceRequirementRow
                query = query.filter(
                    exists().where(AIGovernanceRequirementRow.regulation_id == RegulationRow.id)
                )
            orphan_regs = query.all()
            source_label = "no matching PDF in KB"

        else:
            # \u2500\ufe0f DB mode: regs with no source_documents entry \u2500\ufe0f
            from sqlalchemy import exists, not_

            console.print("[info]Regulations with no source document on file[/info]\n")
            query = (
                session.query(RegulationRow)
                .filter(
                    not_(exists().where(
                        SourceDocumentRow.regulation_id == RegulationRow.id
                    ))
                )
                .order_by(RegulationRow.jurisdiction_id, RegulationRow.name)
            )
            if jurisdiction:
                query = query.filter(RegulationRow.jurisdiction_id == jurisdiction)
            if ai_requirements:
                from regitel.storage.database import AIGovernanceRequirementRow
                query = query.filter(
                    exists().where(AIGovernanceRequirementRow.regulation_id == RegulationRow.id)
                )
            orphan_regs = query.all()
            source_label = "no source document"

        # \u2500\ufe0f Display \u2500\ufe0f
        if not orphan_regs:
            console.print("[success]No orphans found \u2014 every regulation has a matching document.[/success]")
            return

        table = Table(
            title=f"Orphan Regulations ({len(orphan_regs)} \u2014 {source_label})",
            show_header=True,
            title_style="bold yellow",
        )
        table.add_column("#", style="dim", width=4)
        table.add_column("Jurisdiction", style="cyan", min_width=12)
        table.add_column("Regulation", min_width=25)
        table.add_column("Issuing Body", min_width=12)
        table.add_column("Conf.", justify="right", width=6)
        table.add_column("URL", max_width=40, style="dim")
        table.add_column("AI-Specific", justify="center")
        table.add_column("Reqs", justify="right", width=5)

        for i, reg in enumerate(orphan_regs, 1):
            req_count = len(reg.ai_governance_requirements) if reg.ai_governance_requirements else 0
            url_short = (reg.url or "")[:40]
            conf_style = "green" if (reg.confidence_score or 0) >= 0.75 else (
                "yellow" if (reg.confidence_score or 0) >= 0.5 else "red"
            )
            ai_tag = "[green]\u2713[/green]" if reg.ai_specific else "[muted]\u2014[/muted]"
            table.add_row(
                str(i),
                reg.jurisdiction_id,
                reg.name,
                reg.issuing_body or "",
                f"[{conf_style}]{reg.confidence_score or 0:.2f}[/{conf_style}]",
                url_short,
                ai_tag,
                str(req_count),
            )

        console.print(table)

        # \u2500\ufe0f Per-jurisdiction summary \u2500\ufe0f
        from collections import Counter
        jur_counts = Counter(r.jurisdiction_id for r in orphan_regs)
        console.print("\n[bold]By jurisdiction:[/bold]")
        for jid, cnt in jur_counts.most_common():
            console.print(f"  {jid}: {cnt} orphan(s)")

        # \u2500\ufe0f JSON output \u2500\ufe0f
        if output:
            import json as json_mod
            from pathlib import Path as P
            out_data = [
                {
                    "regulation_id": r.id,
                    "jurisdiction_id": r.jurisdiction_id,
                    "name": r.name,
                    "short_name": r.short_name,
                    "issuing_body": r.issuing_body,
                    "url": r.url,
                    "confidence_score": r.confidence_score,
                    "ai_specific": r.ai_specific,
                    "governance_requirements": len(r.ai_governance_requirements) if r.ai_governance_requirements else 0,
                }
                for r in orphan_regs
            ]
            out_path = P(output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json_mod.dumps(out_data, indent=2, default=str))
            console.print(f"\n[success]Saved {len(out_data)} orphans to {out_path}[/success]")

    finally:
        session.close()


# ---------------------------------------------------------------------------
# doctor command
# ---------------------------------------------------------------------------

@cli.command("doctor")
@click.pass_obj
def doctor(ctx: AppContext):
    """Run health checks on the RegIntel system."""
    from pathlib import Path as P
    from regitel.storage.dedup import find_duplicates

    checks: list[tuple[str, bool, str]] = []

    # 1. Database exists and is readable
    db_path = P(ctx.config.storage.database)
    db_ok = db_path.exists() and db_path.stat().st_size > 0
    checks.append(("Database file", db_ok, str(db_path)))

    # 2. DB has data
    stats = ctx.db.get_stats()
    has_data = stats.get("regulations", 0) > 0
    ai_reqs = stats.get("ai_governance_requirements", 0)
    checks.append((
        "Database populated",
        has_data,
        f"{stats.get('regulations', 0)} regulations, {ai_reqs} AI governance requirements"
    ))

    # 3. All jurisdictions scanned
    session = ctx.db.get_session()
    try:
        from regitel.storage.database import JurisdictionRow
        jurs = session.query(JurisdictionRow).all()
        unscanned = [j for j in jurs if not j.last_researched_at]
        all_scanned = len(unscanned) == 0
        checks.append((
            "All jurisdictions scanned",
            all_scanned,
            f"{len(jurs) - len(unscanned)}/{len(jurs)} scanned" +
            (f" (missing: {', '.join(j.id for j in unscanned[:5])})" if unscanned else "")
        ))
    finally:
        session.close()

    # 4. Duplicates
    session2 = ctx.db.get_session()
    try:
        dupes = find_duplicates(session2)
        no_dupes = len(dupes) == 0
        checks.append((
            "No duplicate regulations",
            no_dupes,
            f"{len(dupes)} duplicate groups" if dupes else "Clean"
        ))
    finally:
        session2.close()

    # 5. OpenAI Responses configuration
    def configured(value: str | None) -> bool:
        return bool(value) and not (value.startswith("${") and value.endswith("}"))

    openai_key_ok = configured(ctx.config.llm.api_key)
    checks.append(("OpenAI API key configured", openai_key_ok, "OPENAI_API_KEY"))

    openai_model_ok = configured(ctx.config.llm.model)
    checks.append(("OpenAI model configured", openai_model_ok, ctx.config.llm.model))

    search_provider = ctx.config.research.search_provider.lower()
    checks.append(("Search provider", search_provider == "openai", search_provider))

    # 6. Low-confidence regulations
    session3 = ctx.db.get_session()
    try:
        from regitel.storage.database import RegulationRow as RR
        low_conf = session3.query(RR).filter(RR.confidence_score < 0.6).count()
        checks.append((
            "No low-confidence regulations",
            low_conf == 0,
            f"{low_conf} regulations below 0.6 confidence" if low_conf else "All above threshold"
        ))
    finally:
        session3.close()

    # Render results
    console.print("\n[bold]RegIntel Health Check[/bold]\n")
    all_ok = True
    for name, ok, detail in checks:
        icon = "[success]\u2713[/success]" if ok else "[error]\u2717[/error]"
        all_ok = all_ok and ok
        console.print(f"  {icon} {name}: [muted]{detail}[/muted]")

    console.print()
    if all_ok:
        console.print("[success]All checks passed.[/success]")
    else:
        console.print("[warning]Some checks failed \u2014 see above.[/warning]")


# ---------------------------------------------------------------------------
# embed command
# ---------------------------------------------------------------------------

@db.command("embed")
@click.option("--force", is_flag=True, default=False, help="Re-embed all (default: skip existing)")
@click.pass_obj
def db_embed(ctx: AppContext, force: bool):
    """Populate ChromaDB with regulation embeddings for semantic search."""
    from regitel.storage.embeddings import populate_embeddings

    mode = "full re-embed" if force else "incremental"
    console.print(f"[info]Embedding regulations into ChromaDB ({mode})...[/info]\n")

    stats = populate_embeddings(ctx.db, ctx.vectorstore, force=force)

    table = Table(title="Embedding Results", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right", style="bold")
    table.add_row("Regulations embedded", str(stats.regulations_embedded))
    table.add_row("Requirements embedded", str(stats.requirements_embedded))
    table.add_row("Skipped (already exists)", str(stats.skipped))
    table.add_row("Errors", str(stats.errors))
    console.print(table)


# ---------------------------------------------------------------------------
# semantic search command
# ---------------------------------------------------------------------------

@query_group.command("semantic")
@click.argument("query_text")
@click.option("--jurisdiction", "-j", default=None, help="Filter by jurisdiction")
@click.option("--collection", "-c", type=click.Choice(["regulations", "requirements"]),
              default="regulations", help="Which collection to search")
@click.option("--limit", "-n", default=10, type=int, help="Max results")
@click.pass_obj
def query_semantic(ctx: AppContext, query_text: str, jurisdiction: str | None,
                   collection: str, limit: int):
    """Search regulations using natural language (semantic similarity).

    Examples:
        regitel query semantic "AI inventory requirements for banks"
        regitel query semantic "model risk management gen AI credit scoring" -j eu
    """
    from regitel.storage.embeddings import semantic_search, REGULATION_TEXTS, PENTEST_GUIDANCE

    coll = REGULATION_TEXTS if collection == "regulations" else PENTEST_GUIDANCE

    vs = ctx.vectorstore
    vs_stats = vs.get_stats()
    total = sum(vs_stats.values())

    if total == 0:
        console.print("[warning]Vector store is empty. Run 'regitel db embed' first.[/warning]")
        return

    console.print(f'[info]Semantic search: "{query_text}"[/info]\n')

    results = semantic_search(
        vs_manager=vs,
        query=query_text,
        collection=coll,
        n_results=limit,
        jurisdiction=jurisdiction,
    )

    if not results:
        console.print("[warning]No results found.[/warning]")
        return

    console.print(f"[info]Found {len(results)} results[/info]\n")

    for i, r in enumerate(results, 1):
        score = r.get("relevance_score", 0)
        meta = r.get("metadata", {})
        jid = meta.get("jurisdiction_id", "?")
        score_style = "green" if score >= 0.5 else ("yellow" if score >= 0.3 else "red")

        # Truncate document for display
        doc = r.get("document", "")
        if len(doc) > 400:
            doc = doc[:400] + "..."

        panel = Panel(
            doc,
            title=f"#{i} — [{score_style}]{score:.0%}[/{score_style}] relevance | "
                  f"[cyan]{jid}[/cyan] | {r['id']}",
            border_style="dim",
        )
        console.print(panel)


# ---------------------------------------------------------------------------
# gap analysis command
# ---------------------------------------------------------------------------

@cli.command("gaps")
@click.option("--region", "-r", default=None, help="Filter by region")
@click.option("--min-confidence", default=0.6, type=float, help="Confidence threshold for 'covered'")
@click.option("--governance-theme", default=None,
              help="Analyze gaps for a specific theme (e.g., model_risk_management, data_residency)")
@click.pass_obj
def gap_analysis(ctx: AppContext, region: str | None, min_confidence: float, governance_theme: str | None):
    """Analyze regulatory coverage gaps for AI governance \u2014 what's missing or weak."""
    from regitel.storage.database import JurisdictionRow

    session = ctx.db.get_session()
    try:
        jurs = session.query(JurisdictionRow).order_by(JurisdictionRow.research_priority).all()
        if region:
            jurs = [j for j in jurs if j.region == region]

        console.print("[info]AI Governance Coverage Gap Analysis[/info]\n")

        # Per-jurisdiction gap analysis
        gap_table = Table(title="Jurisdiction Coverage Gaps", show_header=True, show_lines=True)
        gap_table.add_column("Jurisdiction", style="cyan")
        gap_table.add_column("Region", style="muted")
        gap_table.add_column("Regs", justify="right")
        gap_table.add_column("Confident", justify="right", style="green")
        gap_table.add_column("Low-Conf", justify="right", style="yellow")
        gap_table.add_column("AI-Specific", justify="center")
        gap_table.add_column("Frameworks", justify="center")
        gap_table.add_column("Mandatory Reqs", justify="right")
        gap_table.add_column("Missing Areas", style="red")

        # Expected requirement types per jurisdiction
        EXPECTED_TYPES = {"model_risk_management", "data_residency", "ai_inventory", "explainability", "third_party_risk"}

        total_gaps = 0
        for j in jurs:
            regs = ctx.db.get_regulations_by_jurisdiction(session, j.id)
            confident = [r for r in regs if (r.confidence_score or 0) >= min_confidence]
            low_conf = [r for r in regs if (r.confidence_score or 0) < min_confidence]

            ai_specific_count = sum(1 for r in regs if r.ai_specific)
            has_framework = any(len(r.ai_control_frameworks) > 0 for r in regs)
            mandatory_count = sum(
                1 for r in regs for req in r.ai_governance_requirements
                if req.mandatory
            )

            # Detect missing requirement types
            found_types = set()
            for r in regs:
                for req in r.ai_governance_requirements:
                    found_types.add(req.requirement_type)

            # Filter by theme if specified
            if governance_theme:
                found_types = found_types.intersection({governance_theme})
                EXPECTED_CHECK = {governance_theme}
            else:
                EXPECTED_CHECK = EXPECTED_TYPES

            missing = EXPECTED_CHECK - found_types
            missing_str = ", ".join(sorted(missing)) if missing else ""

            if not regs:
                missing_str = "NO DATA"
            elif not j.last_researched_at:
                missing_str = "NEVER SCANNED"

            if missing_str:
                total_gaps += 1

            gap_table.add_row(
                j.name,
                j.region,
                str(len(regs)),
                str(len(confident)),
                str(len(low_conf)),
                f"[green]{ai_specific_count}[/green]",
                "\u2713" if has_framework else "[red]\u2717[/red]",
                str(mandatory_count),
                missing_str,
            )

        console.print(gap_table)

        # Requirement type coverage matrix
        console.print("\n")
        req_types = ["model_risk_management", "data_residency", "ai_inventory", "explainability",
                      "third_party_risk", "transparency", "human_oversight", "fair_lending_ai",
                      "automated_decision_making", "ict_third_party"]
        if governance_theme:
            req_types = [governance_theme]

        type_table = Table(title="Governance Coverage Matrix", show_header=True, show_lines=True)
        type_table.add_column("Jurisdiction", style="cyan")
        for rt in req_types:
            type_table.add_column(rt.replace("_", "\n"), justify="center")

        for j in jurs:
            regs = ctx.db.get_regulations_by_jurisdiction(session, j.id)
            found_types = set()
            for r in regs:
                for req in r.ai_governance_requirements:
                    found_types.add(req.requirement_type)

            row = [j.id]
            for rt in req_types:
                if rt in found_types:
                    row.append("[green]\u2713[/green]")
                else:
                    row.append("[red]\u2717[/red]")
            type_table.add_row(*row)

        console.print(type_table)

        # Summary
        console.print(f"\n[info]Summary: {total_gaps} jurisdictions with coverage gaps "
                      f"(out of {len(jurs)})[/info]")

    finally:
        session.close()


# ---------------------------------------------------------------------------
# rescore command — recalibrate confidence on low-confidence regulations
# ---------------------------------------------------------------------------

@db.command("rescore")
@click.option("--threshold", default=0.6, type=float, help="Re-score regs below this confidence")
@click.option("--apply", is_flag=True, default=False, help="Apply score changes (default: dry run)")
@click.pass_obj
def db_rescore(ctx: AppContext, threshold: float, apply: bool):
    """Re-calibrate confidence scores based on data completeness."""
    from regitel.storage.database import RegulationRow

    session = ctx.db.get_session()
    try:
        regs = (
            session.query(RegulationRow)
            .filter(RegulationRow.confidence_score < threshold)
            .all()
        )

        if not regs:
            console.print(f"[success]No regulations below {threshold:.0%} confidence.[/success]")
            return

        mode = "APPLYING" if apply else "DRY RUN"
        console.print(f"[info]Re-scoring {len(regs)} regulations below {threshold:.0%} \u2014 {mode}[/info]\n")

        table = Table(show_header=True)
        table.add_column("Regulation", style="cyan")
        table.add_column("Jurisdiction")
        table.add_column("Old Score", justify="right")
        table.add_column("New Score", justify="right")
        table.add_column("Reason")

        for reg in regs:
            old = reg.confidence_score or 0.0

            # Heuristic re-scoring based on data completeness
            score = 0.3  # base
            if reg.url:
                score += 0.15
            if reg.issuing_body:
                score += 0.1
            if reg.effective_date:
                score += 0.1
            if reg.ai_governance_requirements:
                score += 0.15
                # Bonus for well-populated requirements
                for req in reg.ai_governance_requirements:
                    if req.requirement_type and req.mandatory is not None:
                        score += 0.05
                        break
            if reg.ai_control_frameworks:
                score += 0.1

            score = min(score, 0.85)  # Cap at 0.85 for heuristic scores

            reason_parts = []
            if not reg.url:
                reason_parts.append("no URL")
            if not reg.ai_governance_requirements:
                reason_parts.append("no AI reqs")
            if reg.url and reg.ai_governance_requirements:
                reason_parts.append("has URL + AI reqs")

            new_style = "green" if score > old else ("yellow" if score == old else "red")

            table.add_row(
                reg.name[:50],
                reg.jurisdiction_id,
                f"{old:.2f}",
                f"[{new_style}]{score:.2f}[/{new_style}]",
                ", ".join(reason_parts),
            )

            if apply:
                reg.confidence_score = score

        console.print(table)

        if apply:
            session.commit()
            console.print(f"\n[success]Updated {len(regs)} confidence scores.[/success]")
        else:
            console.print("\n[muted]Dry run \u2014 use --apply to commit changes.[/muted]")

    finally:
        session.close()


# ---------------------------------------------------------------------------
# Seed helper
# ---------------------------------------------------------------------------

def _seed_jurisdictions(ctx: AppContext) -> None:
    """Seed jurisdiction data from the built-in profiles."""
    from regitel.seeds import get_jurisdiction_seeds

    console.print("[info]Seeding jurisdiction data...[/info]")
    db_mgr = ctx.db
    session = db_mgr.get_session()

    try:
        count = 0
        for seed in get_jurisdiction_seeds():
            db_mgr.upsert_jurisdiction(
                session,
                id=seed["id"],
                name=seed["name"],
                region=seed["region"],
                regulatory_bodies=json.dumps(seed.get("regulatory_bodies", [])),
                research_priority=seed.get("research_priority", 5),
            )
            count += 1

        session.commit()
        console.print(f"  [success]\u2713[/success] Seeded {count} jurisdictions")
    except Exception as e:
        session.rollback()
        console.print(f"  [error]\u2717 Seed failed: {e}[/error]")
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
