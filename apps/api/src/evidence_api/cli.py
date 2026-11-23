"""Unified rich CLI (`aeroregu`) for Evidence Layer & MCP tooling."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

app = typer.Typer(
    name="aeroregu",
    help=(
        "Supervised Evidence Layer CLI, Interactive Assistant & MCP toolkit. "
        "Run `aeroregu wizard` or just `aeroregu` for a guided zero-CLI menu. "
        "Assists human engineers; never determines regulatory compliance."
    ),
    rich_markup_mode="rich",
)
calc_app = typer.Typer(help="Deterministic engineering calculations (Decimal + Flint + Z3/cvc5).")
bundle_app = typer.Typer(help="Export and off-line verify DSSE Ed25519 / eIDAS QES audit dossiers.")
ledger_app = typer.Typer(help="Inspect tamper-evident ledger, Merkle proofs, and pilot metrics.")
coverage_app = typer.Typer(help="Flight-envelope coverage matrix, sweep & traceability gate.")
dossier_app = typer.Typer(help="Enterprise certification dossier, StrictDOC & NIST OSCAL SAR.")
security_app = typer.Typer(help="Guardrail scanner, SBOM/CVE verification & Red-Team audit.")
bench_app = typer.Typer(help="Run B2 baseline comparisons and live/edge agent benchmarks.")
mcp_app = typer.Typer(help="Model Context Protocol (MCP) stdio server, inspector & client configs.")
cad_app = typer.Typer(help="CAD/B-Rep STEP AP242, IGES, CATIA & legacy CAE inspection.")
cae_app = typer.Typer(
    help="CAE binary stream parsers (NASTRAN .op2, HDF5 .h5, sandboxed .odb/.rst)."
)
materials_app = typer.Typer(help="Pinned MMPDS-16 & CMH-17 Rev H allowable catalog & lookup.")
plm_app = typer.Typer(
    help="Enterprise PLM sync & ECN writeback (3DEXPERIENCE/Teamcenter/Windchill)."
)
ecn_app = typer.Typer(help="Engineering Change Notice (ECN) deterministic revision diffing.")
review_app = typer.Typer(
    help="Collaborative engineering review threads linked to ledger artifacts."
)
qualification_app = typer.Typer(help="DO-330 / TQL-5 IQ/OQ qualification test aid.")
overnight_app = typer.Typer(
    help="Overnight continuous verification, cross-artifact audit & 08:00 AM briefing."
)
db_app = typer.Typer(help="PostgreSQL / SQLite persistence status & automated migrations.")
webhooks_app = typer.Typer(help="Webhook dead-letter queue (DLQ) inspection & replay.")
quote_app = typer.Typer(
    help="Multi-agent automated quotation, 7-axis assumptions & global GitHub/web scraper."
)

app.add_typer(calc_app, name="calc")
app.add_typer(bundle_app, name="bundle")
app.add_typer(ledger_app, name="ledger")
app.add_typer(coverage_app, name="coverage")
app.add_typer(dossier_app, name="dossier")
app.add_typer(security_app, name="security")
app.add_typer(bench_app, name="bench")
app.add_typer(mcp_app, name="mcp")
app.add_typer(cad_app, name="cad")
app.add_typer(cae_app, name="cae")
app.add_typer(materials_app, name="materials")
app.add_typer(plm_app, name="plm")
app.add_typer(ecn_app, name="ecn")
app.add_typer(review_app, name="review")
app.add_typer(qualification_app, name="qualification")
app.add_typer(overnight_app, name="overnight")
app.add_typer(db_app, name="db")
app.add_typer(webhooks_app, name="webhooks")
app.add_typer(quote_app, name="quote")


def _complete_method_id(incomplete: str) -> list[str]:
    try:
        from evidence_calc.registry import list_method_ids

        needle = incomplete.lower()
        return [m for m in list_method_ids() if needle in m.lower()]
    except Exception:
        return []


def _complete_tenant(incomplete: str) -> list[str]:
    candidates = ["demo", "quickstart-demo"]
    try:
        from evidence_kernel.paths import evidence_home

        tdir = evidence_home() / "tenants"
        if tdir.is_dir():
            for p in sorted(tdir.glob("*.sqlite3")):
                name = p.stem
                if name not in candidates:
                    candidates.append(name)
    except Exception:
        pass
    return [c for c in candidates if incomplete in c]


def _complete_material(incomplete: str) -> list[str]:
    try:
        from evidence_calc.allowables import list_materials

        needle = incomplete.upper()
        return [m for m in list_materials() if needle in m.upper()]
    except Exception:
        return []


@app.callback(invoke_without_command=True)
def _root_callback(ctx: typer.Context) -> None:
    """Launch guided interactive wizard when run in an interactive TTY with no subcommand."""
    if ctx.invoked_subcommand is not None:
        return
    if sys.stdin.isatty() and sys.stdout.isatty():
        from evidence_api.wizard import run_interactive_hub

        run_interactive_hub(
            console,
            lambda: quickstart_cmd(tenant="quickstart-demo", output_zip=None),
        )
        return
    console.print(ctx.get_help())
    console.print(
        "\n[bold cyan]Tip para principiantes:[/bold cyan] Ejecuta [bold]aeroregu wizard[/bold] "
        "(asistente paso a paso) o [bold]aeroregu ui[/bold] (abrir Web UI en el navegador)."
    )


console = Console()
err_console = Console(stderr=True)


def _wants_json(flag: bool) -> bool:
    fmt = os.environ.get("EVIDENCE_OUTPUT", "").strip().lower()
    if flag or fmt == "json":
        return True
    if fmt in {"rich", "text", "pretty"}:
        return False
    return not sys.stdout.isatty()


def _emit_json(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2, default=str))


def _load_json_arg(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    stripped = raw.strip()
    if stripped.startswith("@"):
        path = Path(stripped[1:]).expanduser()
        return dict(json.loads(path.read_text(encoding="utf-8")))
    potential_file = Path(stripped)
    if potential_file.is_file():
        return dict(json.loads(potential_file.read_text(encoding="utf-8")))
    return dict(json.loads(stripped))


def _pkg_ver(name: str) -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(name)
    except PackageNotFoundError:
        return "missing"


def _tenant_or_exit(tenant_id: str) -> str:
    from evidence_api.app import _validate_tenant

    checked = _validate_tenant(tenant_id)
    if checked is None:
        err_console.print(f"[red]Invalid tenant_id:[/red] {tenant_id!r}")
        raise typer.Exit(code=1)
    return checked


@app.command("doctor")
def doctor(
    probe: bool = typer.Option(False, "--probe", help="Actively probe configured Edge/API URLs."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Diagnose solvers, cryptography, agent gateways, and production readiness."""
    from evidence_kernel.gateway import describe_agent_runtime, probe_gateway_health

    from evidence_api.app import _attestation_keypair, _secret, evidence_home
    from evidence_api.mcp_server import MCP_RESOURCES, MCP_TOOLS

    runtime = describe_agent_runtime()
    probed = probe_gateway_health(target="all", timeout_s=2.0) if probe else None
    _, pub_pem = _attestation_keypair()
    home_dir = evidence_home()
    deps = {
        pkg: _pkg_ver(pkg)
        for pkg in (
            "z3-solver",
            "cvc5",
            "python-flint",
            "llguidance",
            "pymupdf",
            "cryptography",
            "rfc8785",
            "typer",
            "rich",
        )
    }
    report = {
        "python": sys.version.split()[0],
        "evidence_home": str(home_dir),
        "session_secret_configured": _secret() is not None,
        "production_mode": os.environ.get("EVIDENCE_PRODUCTION", "0") in {"1", "true", "yes"},
        "dsse_ed25519_ready": bool(pub_pem),
        "runtime": runtime,
        "probe": probed,
        "engines": deps,
        "mcp_tools": len(MCP_TOOLS),
        "mcp_resources": len(MCP_RESOURCES),
    }
    if _wants_json(json_out):
        _emit_json(report)
        return

    table = Table(title="aeroregu System & Engine Diagnostics", box=box.ROUNDED)
    table.add_column("Component", style="bold cyan")
    table.add_column("Status / Version", style="white")
    table.add_column("Notes", style="dim")

    table.add_row("Python", report["python"], f"Home: {home_dir}")
    sec_badge = "[green]configured[/green]" if _secret() else "[yellow]unset (dev CLI ok)[/yellow]"
    table.add_row("Session Secret", sec_badge, "Required for HTTP API serve")
    table.add_row("DSSE Ed25519 Key", "[green]ready[/green]", "100% signed ZIP exports")
    table.add_row(
        "Agent Gateway",
        f"[bold]{runtime['active_mode']}[/bold]",
        (
            f"Edge={runtime['edge_backend']['configured']} | "
            f"API={runtime['api_backend']['configured']}"
        ),
    )
    table.add_row(
        "MCP Server",
        f"[green]{len(MCP_TOOLS)} tools / {len(MCP_RESOURCES)} resources[/green]",
        "stdio & POST /mcp ready",
    )
    for name, ver in deps.items():
        badge = f"[green]{ver}[/green]" if ver != "missing" else "[red]missing[/red]"
        table.add_row(f"engine:{name}", badge, "verified in runtime")
    console.print(table)
    if probed:
        console.print(Panel(json.dumps(probed, indent=2), title="Live Gateway Probe"))
    console.print(
        "[dim]Next: run [bold]aeroregu quickstart[/bold] or [bold]aeroregu mcp config[/bold][/dim]"
    )


@app.command("ingest")
def ingest_cmd(
    file: Path = typer.Argument(..., exists=True, readable=True, help="PDF/DOCX/XLSX/MD/TXT."),
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ledger ID."),
    record_to_ledger: bool = typer.Option(False, "--record", help="Record requirements to ledger."),
    actor: str = typer.Option("author", "--actor", help="Actor ID when recording."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Ingest engineering/regulatory specs with exact spans, page numbers, and PDF bboxes."""
    from evidence_ingest.blocks import IngestAbstain
    from evidence_ingest.router import ingest_bytes
    from evidence_kernel.orchestrator import record

    from evidence_api.app import MAX_INGEST_BYTES, _now, open_ledger

    raw = file.read_bytes()
    if len(raw) > MAX_INGEST_BYTES:
        err_console.print(f"[red]Payload exceeds MAX_INGEST_BYTES ({MAX_INGEST_BYTES})[/red]")
        raise typer.Exit(code=1)
    try:
        parsed = ingest_bytes(raw, file.name)
    except IngestAbstain as exc:
        if _wants_json(json_out):
            _emit_json({"confidence": "abstain", "abstain_reason": exc.reason})
        else:
            console.print(f"[yellow]ABSTAIN ({exc.reason}):[/yellow] {file.name}")
        raise typer.Exit(code=2)

    recorded_hashes: list[str] = []
    if record_to_ledger and parsed["requirements"]:
        checked = _tenant_or_exit(tenant)
        ledger = open_ledger(checked)
        from evidence_kernel.envelope import make_envelope, project_source

        ts = _now()
        for req in parsed["requirements"]:
            env = make_envelope(
                sources=[project_source("ingest", "https://aeroregu.local/ingest", "ASSUMPTION")],
                method_version="ingest_requirements@1.0.0",
                inputs={
                    "id": req["id"],
                    "source_file_hash": req["source_file_hash"],
                    "span_start": req["span_start"],
                },
                confidence="quoted",
                result={"id": req["id"], "title_label": req["title_label"]},
            )
            recorded_hashes.append(
                record(
                    ledger,
                    {
                        "event_type": "requirement_recorded",
                        "tenant_id": ledger.tenant_id,
                        "actor_id": actor,
                        "created_at": ts,
                        "payload": req,
                        "envelope": env,
                    },
                )
            )

    payload = {**parsed, "recorded_event_hashes": recorded_hashes}
    if _wants_json(json_out):
        _emit_json(payload)
        return

    table = Table(
        title=f"Ingested Requirements: {file.name} ({parsed['media_type']})",
        box=box.ROUNDED,
    )
    table.add_column("ID", style="bold cyan")
    table.add_column("Label")
    table.add_column("Page", justify="right")
    table.add_column("BBox")
    table.add_column("Slice")
    table.add_column("Title / Quotation")

    for req in parsed["requirements"]:
        lbl = str(req["title_label"])
        lbl_fmt = f"[green]{lbl}[/green]" if lbl == "VERIFIED" else f"[yellow]{lbl}[/yellow]"
        page = str(req.get("page_no") or "-")
        bbox = ", ".join(req["bbox"]) if req.get("bbox") else "-"
        span = f"[{req['span_start']}:{req['span_end']}]"
        quote = str(req.get("quotation") or req.get("title") or "")[:64]
        table.add_row(str(req["id"]), lbl_fmt, page, bbox, span, quote)

    console.print(table)
    console.print(
        f"[dim]Blocks: {len(parsed['blocks'])} | SHA-256: {parsed['source_hash'][:16]}... "
        f"| Recorded: {len(recorded_hashes)}[/dim]"
    )


@calc_app.command("list")
def calc_list(
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """List certified deterministic Decimal calculation method cards & user plugins."""
    from evidence_calc.registry import list_cards

    cards = list_cards()
    if _wants_json(json_out):
        _emit_json({"methods": cards})
        return

    table = Table(title="Certified Calculation Methods & Plugins", box=box.ROUNDED)
    table.add_column("Method ID", style="bold cyan", no_wrap=True)
    table.add_column("Version")
    table.add_column("Required Inputs")
    table.add_column("Units")
    for card in cards:
        req = ", ".join(card.get("required") or list(card.get("inputs", {})))
        units = ", ".join(f"{k}={v}" for k, v in (card.get("input_units") or {}).items())
        table.add_row(str(card["method_id"]), str(card["method_version"]), req, units or "-")
    console.print(table)


@calc_app.command("register")
def calc_register_cmd(
    card_file: Path = typer.Argument(..., help="Path to declarative method card JSON file."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Register a declarative AST-sandboxed Decimal user plugin card."""
    from evidence_calc.errors import AbstainError
    from evidence_calc.registry import register_custom_card

    try:
        raw = json.loads(card_file.expanduser().read_text(encoding="utf-8"))
        saved = register_custom_card(raw)
    except (OSError, json.JSONDecodeError, AbstainError) as exc:
        err_console.print(f"[red]Failed to register card:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    if _wants_json(json_out):
        _emit_json({"card": saved})
        return
    console.print(
        f"[green]Registered plugin card[/green] [bold]{saved['method_id']}[/bold] "
        f"(SHA-256 {saved['card_sha256'][:16]}...)"
    )


def _parse_kv_pairs(pairs: list[str] | None) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for item in pairs or []:
        if "=" not in item:
            raise ValueError(f"Expected KEY=VALUE for --set, got: {item!r}")
        k, v = item.split("=", 1)
        key = k.strip()
        val = v.strip()
        if "," in val and not val.startswith("["):
            parsed[key] = [x.strip() for x in val.split(",")]
        elif val.startswith("[") or val.startswith("{"):
            parsed[key] = json.loads(val)
        else:
            parsed[key] = val
    return parsed


@calc_app.command("run")
def calc_run_cmd(
    method_id: str = typer.Argument(
        ...,
        autocompletion=_complete_method_id,
        help="Method ID (see `aeroregu calc list`).",
    ),
    inputs: str | None = typer.Option(
        None,
        "--inputs",
        "-i",
        help="JSON string or @file.json (omit for interactive prompts).",
    ),
    set_values: list[str] | None = typer.Option(
        None,
        "--set",
        "-s",
        help="Key=value pair (e.g. -s mass_kg=800.000). Avoids JSON quoting!",
    ),
    stated: str | None = typer.Option(None, "--stated", help="Optional stated outputs JSON/@file."),
    normalize_units: bool = typer.Option(False, "--normalize-units", help="Convert input units."),
    intervals: bool = typer.Option(
        True, "--intervals/--no-intervals", help="Compute Flint arb bounds."
    ),
    formal: bool = typer.Option(False, "--formal", help="Run Z3 + cvc5 SMT proof."),
    record_to_ledger: bool = typer.Option(False, "--record", help="Append calc event to ledger."),
    tenant: str = typer.Option(
        "demo", "--tenant", autocompletion=_complete_tenant, help="Tenant ledger ID."
    ),
    actor: str = typer.Option("author", "--actor", help="Actor ID when recording."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Execute deterministic Decimal math + Flint interval bounds + optional SMT proof."""
    from evidence_calc.diagnostics import classify_numeric_delta
    from evidence_calc.errors import AbstainError
    from evidence_calc.registry import load_card, run_method
    from evidence_kernel.orchestrator import record

    from evidence_api.app import _now, open_ledger
    from evidence_api.mcp_server import run_formal_proof_for_method
    from evidence_api.wizard import prompt_method_inputs

    try:
        parsed_inputs = _load_json_arg(inputs) if inputs else {}
        parsed_inputs.update(_parse_kv_pairs(set_values))
    except (json.JSONDecodeError, ValueError) as exc:
        err_console.print(
            f"[red]Invalid input format:[/red] {exc}\n"
            "[yellow]Tip:[/yellow] usa `-s clave=valor` o `aeroregu wizard` para evitar JSON."
        )
        raise typer.Exit(code=1) from exc

    if not parsed_inputs:
        if sys.stdin.isatty() and sys.stdout.isatty() and not json_out:
            card = load_card(method_id)
            parsed_inputs = prompt_method_inputs(card, console)
        else:
            err_console.print(
                "[red]Faltan inputs.[/red] Usa `--inputs '{...}'`, `--set k=v`, "
                "o `aeroregu wizard` en terminal interactiva."
            )
            raise typer.Exit(code=1)

    parsed_stated = _load_json_arg(stated) if stated else None
    try:
        ran = run_method(
            method_id,
            parsed_inputs,
            normalize_units=normalize_units,
            include_intervals=intervals,
        )
    except AbstainError as exc:
        if _wants_json(json_out):
            _emit_json({"confidence": "abstain", "abstain_reason": exc.reason})
        else:
            console.print(f"[yellow]ABSTAIN:[/yellow] {exc.reason}")
        raise typer.Exit(code=2)

    out: dict[str, Any] = {
        "confidence": "deterministic",
        "method_id": method_id,
        "method_version": ran["method_version"],
        "outputs": ran["outputs"],
    }
    if intervals and ran.get("exact_intervals"):
        out["exact_intervals"] = ran["exact_intervals"]
    if normalize_units and ran.get("unit_conversions"):
        out["unit_conversions"] = ran["unit_conversions"]
    if parsed_stated is not None:
        out["delta_vs_stated"] = {
            k: classify_numeric_delta(str(ran["outputs"].get(k, "")), str(v))
            for k, v in parsed_stated.items()
            if k in ran["outputs"]
        }
    if formal:
        out["formal_proof"] = run_formal_proof_for_method(method_id, parsed_inputs)

    if record_to_ledger:
        from evidence_kernel.envelope import make_envelope

        checked = _tenant_or_exit(tenant)
        ledger = open_ledger(checked)
        env = make_envelope(
            sources=ran["sources"],
            method_version=ran["method_version"],
            inputs=ran.get("normalized_inputs", parsed_inputs),
            confidence="deterministic",
            result=ran["outputs"],
        )
        out["recorded_event_hash"] = record(
            ledger,
            {
                "event_type": "calc",
                "tenant_id": ledger.tenant_id,
                "actor_id": actor,
                "created_at": _now(),
                "payload": {
                    "method_id": method_id,
                    "inputs": ran.get("normalized_inputs", parsed_inputs),
                    "outputs": ran["outputs"],
                },
                "envelope": env,
            },
        )

    if _wants_json(json_out):
        _emit_json(out)
        return

    table = Table(
        title=f"Deterministic Calc: {method_id} ({ran['method_version']})", box=box.ROUNDED
    )
    table.add_column("Output Key", style="bold cyan")
    table.add_column("Exact Decimal", style="green")
    table.add_column("Flint Interval [lower, upper]")
    exact_iv = out.get("exact_intervals") or {}
    for k, val in ran["outputs"].items():
        iv = exact_iv.get(k)
        iv_txt = f"[{iv['lower']}, {iv['upper']}]" if isinstance(iv, dict) else "-"
        table.add_row(k, str(val), iv_txt)
    console.print(table)
    if out.get("formal_proof"):
        fp = out["formal_proof"]
        console.print(f"[green]Formal Proof:[/green] {fp['status']} ({fp['property_name']})")
    if out.get("recorded_event_hash"):
        console.print(f"[dim]Recorded ledger event: {out['recorded_event_hash']}[/dim]")


@app.command("verify-case")
def verify_case_cmd(
    file: Path | None = typer.Option(
        None, "--file", "-f", exists=True, help="Source document path."
    ),
    text: str | None = typer.Option(None, "--text", "-t", help="Raw source clause text."),
    method_id: str | None = typer.Option(
        None, "--method", "-m", autocompletion=_complete_method_id, help="Optional calc method ID."
    ),
    inputs: str | None = typer.Option(None, "--inputs", "-i", help="Calc inputs JSON or @file."),
    mode: str = typer.Option("auto", "--mode", help="auto|fixture|edge|api|hybrid"),
    edge_model: str | None = typer.Option(None, "--edge-model", help="Edge model name."),
    formal: bool = typer.Option(False, "--formal", help="Verify bounds via Z3+cvc5."),
    gate: bool = typer.Option(False, "--gate", help="Enable SLM decision gate."),
    tenant: str = typer.Option(
        "demo", "--tenant", autocompletion=_complete_tenant, help="Tenant ledger ID."
    ),
    actor: str = typer.Option("author", "--actor", help="Actor ID."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Run the full supervised multi-agent verification pipeline (citations + math + proof)."""
    from evidence_ingest.router import ingest_bytes
    from evidence_kernel.gateway import gateway_from_env
    from evidence_kernel.supervisor import CaseSpec, run_case

    from evidence_api.app import _now, open_ledger

    checked = _tenant_or_exit(tenant)
    if file is not None:
        parsed = ingest_bytes(file.read_bytes(), file.name)
        blocks = [
            {
                "text": b["text"],
                "span_start": b["span_start"],
                "span_end": b["span_end"],
                "page_no": b.get("page_no"),
                "bbox": b.get("bbox"),
                "source_hash": b.get("source_hash", parsed["source_hash"]),
            }
            for b in parsed["blocks"]
        ]
    elif text:
        blocks = [{"text": text, "span_start": 0, "span_end": len(text)}]
    else:
        err_console.print("[red]Provide --file or --text.[/red]")
        raise typer.Exit(code=1)

    calc_inputs = _load_json_arg(inputs) if inputs else None
    ledger = open_ledger(checked)
    case = CaseSpec(
        tenant_id=checked,
        actor_id=actor,
        created_at=_now(),
        blocks=blocks,
        method_id=method_id,
        calc_inputs=calc_inputs,
        use_decision_gate=gate,
        formal_verification=formal,
        record_requirements=True,
    )
    gw = gateway_from_env("happy", constrained=True, runtime_mode=mode, edge_model=edge_model)
    if _wants_json(json_out):
        outcome = run_case(ledger, gw, case)
        payload = {
            "envelope": outcome.envelope,
            "citations": outcome.citations,
            "paragraph": outcome.paragraph,
            "fault_kind": outcome.fault_kind,
            "formal_proof": outcome.formal_proof,
            "event_hashes": outcome.event_hashes,
            "agent_telemetry": outcome.agent_telemetry,
        }
        _emit_json(payload)
        if outcome.envelope.get("confidence") == "abstain":
            raise typer.Exit(code=2)
        return

    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("[cyan]Ingesting blocks & preparing ledger...[/cyan]", total=3)
        progress.advance(task_id, 1)
        progress.update(
            task_id,
            description="[cyan]Running pipeline (reader -> checker -> refuter -> scribe)...[/cyan]",
        )
        outcome = run_case(ledger, gw, case)
        progress.advance(task_id, 1)
        progress.update(task_id, description="[green]Ledger & citations verified[/green]")
        progress.advance(task_id, 1)

    conf = str(outcome.envelope.get("confidence", ""))
    if conf == "abstain":
        reason = (outcome.envelope.get("abstain") or {}).get("reason", "unknown")
        console.print(
            Panel(f"[bold yellow]ABSTAIN: {reason}[/bold yellow]", title="Verification Halted")
        )
        raise typer.Exit(code=2)

    if outcome.citations:
        ctable = Table(title="Verified Source Citations (with Page & BBox)", box=box.ROUNDED)
        ctable.add_column("ID", style="bold cyan")
        ctable.add_column("Page", justify="right")
        ctable.add_column("BBox")
        ctable.add_column("Quotation")
        for cit in outcome.citations:
            ctable.add_row(
                str(cit["id"]),
                str(cit.get("page_no") or "-"),
                ", ".join(cit["bbox"]) if cit.get("bbox") else "-",
                str(cit.get("quotation", ""))[:70],
            )
        console.print(ctable)
    console.print(
        Panel(
            outcome.paragraph or "(draft completed)",
            title=f"Verified Outcome ({conf}) | Events: {len(outcome.event_hashes)}",
            border_style="green",
        )
    )


@bundle_app.command("export")
def bundle_export(
    output: Path = typer.Argument(..., help="Output .zip bundle file path."),
    tenant: str = typer.Option(
        "demo", "--tenant", autocompletion=_complete_tenant, help="Tenant ledger ID."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Export a 100% DSSE Ed25519 signed audit dossier ZIP and immediately verify it."""
    import zipfile

    from evidence_kernel.__main__ import verify_zip_bundle

    from evidence_api.app import _zip_bytes, open_ledger

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    blob = _zip_bytes(ledger.events())
    out_path = output.expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(blob)
    ok, report = verify_zip_bundle(out_path)

    payload = {"output_path": str(out_path), "bytes": len(blob), "verified": ok, **report}
    if _wants_json(json_out):
        _emit_json(payload)
        if not ok:
            raise typer.Exit(code=1)
        return

    with zipfile.ZipFile(out_path, "r") as zf:
        files = ", ".join(zf.namelist())
    status = (
        "[bold green]SIGNED & VERIFIED[/bold green]" if ok else "[bold red]VERIFY FAILED[/bold red]"
    )
    console.print(
        Panel(
            f"Bundle: {out_path}\nStatus: {status}\nMerkle Root: {report.get('merkle_root')}\n"
            f"Events: {report.get('event_count')} | Size: {len(blob)} bytes\nContents: {files}",
            title="DSSE Ed25519 Dossier Export",
            border_style="green" if ok else "red",
        )
    )
    if not ok:
        raise typer.Exit(code=1)


@bundle_app.command("verify")
def bundle_verify(
    path: Path = typer.Argument(..., exists=True, help="Exported .zip bundle or chain.json."),
    public_key: Path | None = typer.Option(
        None, "--public-key", "-k", exists=True, help="Trusted Ed25519 PEM."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Off-line verification of ledger hash chain, Merkle root, and DSSE Ed25519 signature."""
    import zipfile

    from evidence_kernel.__main__ import verify_zip_bundle
    from evidence_kernel.ledger import verify_chain_document

    if path.suffix.lower() == ".zip" or zipfile.is_zipfile(path):
        pub_pem = public_key.read_bytes() if public_key else None
        ok, report = verify_zip_bundle(path, public_key_pem=pub_pem)
    else:
        doc = json.loads(path.read_text(encoding="utf-8"))
        ok = verify_chain_document(doc)
        report = {"bundle": str(path), "chain_ok": ok, "event_count": len(doc)}

    if _wants_json(json_out):
        _emit_json(report)
        if not ok:
            raise typer.Exit(code=1)
        return

    table = Table(title=f"Offline Dossier Verification: {path.name}", box=box.ROUNDED)
    table.add_column("Check", style="bold")
    table.add_column("Result")
    for key in ("chain_ok", "merkle_ok", "dsse_present", "dsse_signature_ok", "dsse_digest_ok"):
        if key in report:
            val = report[key]
            table.add_row(key, "[green]PASS[/green]" if val else "[red]FAIL[/red]")
    if report.get("merkle_root"):
        table.add_row("merkle_root", str(report["merkle_root"]))
    if report.get("error"):
        table.add_row("error", f"[red]{report['error']}[/red]")
    console.print(table)
    if not ok:
        raise typer.Exit(code=1)


@ledger_app.command("status")
def ledger_status(
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ledger ID."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Show ledger integrity, head hash, Merkle root, and review counts."""
    from evidence_api.app import open_ledger

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    events = ledger.events()
    signoffs = [ev for ev in events if ev["body"]["event_type"] == "human_signoff"]
    summary = {
        "tenant_id": checked,
        "chain_verified": ledger.verify(),
        "event_count": len(events),
        "head_hash": ledger.head_hash(),
        "merkle_root": ledger.merkle_root(),
        "signed_reviews": len(signoffs),
    }
    if _wants_json(json_out):
        _emit_json(summary)
        return
    console.print(Panel(json.dumps(summary, indent=2), title=f"Ledger Status ({checked})"))


@ledger_app.command("log")
def ledger_log(
    tenant: str = typer.Option(
        "demo", "--tenant", autocompletion=_complete_tenant, help="Tenant ledger ID."
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Tail count."),
    event_type: str | None = typer.Option(
        None, "--event-type", "-e", help="Filter by event_type (e.g. calc, ingest, human_signoff)."
    ),
    actor: str | None = typer.Option(None, "--actor", help="Filter by actor_id."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Display recent tamper-evident ledger events."""
    from evidence_api.app import open_ledger

    checked = _tenant_or_exit(tenant)
    events = open_ledger(checked).events()
    if event_type:
        events = [ev for ev in events if str(ev["body"].get("event_type")) == event_type]
    if actor:
        events = [ev for ev in events if str(ev["body"].get("actor_id")) == actor]
    events = events[-limit:]
    rows = [
        {
            "event_hash": ev["event_hash"],
            "event_type": ev["body"]["event_type"],
            "actor_id": ev["body"]["actor_id"],
            "confidence": ev["body"]["envelope"]["confidence"],
            "created_at": ev["body"]["created_at"],
        }
        for ev in events
    ]
    if _wants_json(json_out):
        _emit_json(rows)
        return
    table = Table(title=f"Ledger Log ({checked}, last {len(rows)})", box=box.ROUNDED)
    table.add_column("Type", style="cyan")
    table.add_column("Actor")
    table.add_column("Confidence")
    table.add_column("Timestamp")
    table.add_column("Event Hash")
    for row in rows:
        table.add_row(
            str(row["event_type"]),
            str(row["actor_id"]),
            str(row["confidence"]),
            str(row["created_at"]),
            str(row["event_hash"])[:16] + "...",
        )
    console.print(table)


@ledger_app.command("signoff")
def ledger_signoff_cmd(
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ledger ID."),
    actor: str = typer.Option("reviewer", "--actor", help="Human reviewer actor ID."),
    target: str | None = typer.Option(None, "--target", help="Target event hash (defaults head)."),
    duration_ms: int | None = typer.Option(None, "--duration-ms", help="Review duration in ms."),
    allow_self_signoff: bool = typer.Option(
        False,
        "--allow-self-signoff",
        help="Allow self sign-off in local dev mode (disallowed in production).",
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Record an immutable human engineer sign-off event with governance checks."""
    from evidence_coverage.collaboration_ecn import get_review_thread_store
    from evidence_kernel.envelope import make_envelope, project_source
    from evidence_kernel.ledger import GENESIS, SIGN_OFF_STATEMENT, LedgerError
    from evidence_kernel.orchestrator import record

    from evidence_api.app import _is_production_mode, _now, open_ledger

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    target_hash = target or ledger.head_hash()
    if target_hash == GENESIS:
        err_console.print("[red]Ledger is empty; cannot sign off GENESIS.[/red]")
        raise typer.Exit(code=1)

    events = ledger.events()
    target_ev = next((ev for ev in events if ev["event_hash"] == target_hash), None)
    if target_ev is None:
        err_console.print(f"[red]Target event not found:[/red] {target_hash}")
        raise typer.Exit(code=1)

    target_author = str(target_ev["body"].get("actor_id") or "")
    if target_author == actor and (_is_production_mode() or not allow_self_signoff):
        err_console.print(
            "[red]Separation of Duties violation:[/red] "
            f"reviewer '{actor}' cannot sign off own artifact."
        )
        raise typer.Exit(code=2)

    review_store = get_review_thread_store()
    blocking = review_store.unresolved_blocking_threads(checked, target_event_hash=target_hash)
    if blocking:
        ids = ", ".join(str(b["thread_id"]) for b in blocking)
        err_console.print(f"[red]Sign-off blocked by unresolved review threads:[/red] {ids}")
        raise typer.Exit(code=2)

    payload: dict[str, Any] = {
        "actor_id": actor,
        "target_event_hash": target_hash,
        "statement": SIGN_OFF_STATEMENT,
    }
    if duration_ms is not None:
        payload["review_duration_ms"] = duration_ms
    env = make_envelope(
        sources=[project_source("human-review", "https://aeroregu.local/signoff", "ASSUMPTION")],
        method_version="human_signoff@1.0.0",
        inputs={"target_event_hash": target_hash, "statement": SIGN_OFF_STATEMENT},
        confidence="deterministic",
        result=payload,
    )
    try:
        ev_hash = record(
            ledger,
            {
                "event_type": "human_signoff",
                "tenant_id": ledger.tenant_id,
                "actor_id": actor,
                "created_at": _now(),
                "payload": payload,
                "envelope": env,
            },
        )
    except LedgerError as exc:
        err_console.print(f"[red]Sign-off rejected:[/red] {exc}")
        raise typer.Exit(code=1)

    locked_threads = review_store.lock_threads_on_signoff(
        checked,
        target_event_hash=target_hash,
        signoff_event_hash=ev_hash,
        signed_by=actor,
    )
    res = {
        "event_hash": ev_hash,
        "target_event_hash": target_hash,
        "merkle_root": ledger.merkle_root(),
        "locked_review_threads": [item["thread_id"] for item in locked_threads],
    }
    if _wants_json(json_out):
        _emit_json(res)
        return
    console.print(f"[green]Signed off:[/green] {ev_hash} -> target {target_hash[:16]}...")


@ledger_app.command("metrics")
def ledger_metrics_cmd(
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ledger ID."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Display human pilot sign-off counts and review latency summary."""
    from evidence_api.app import open_ledger

    checked = _tenant_or_exit(tenant)
    events = open_ledger(checked).events()
    signoffs = [ev for ev in events if ev["body"]["event_type"] == "human_signoff"]
    durations = [
        int(ev["body"]["payload"]["review_duration_ms"])
        for ev in signoffs
        if isinstance(ev["body"]["payload"].get("review_duration_ms"), (int, float))
    ]
    sorted_d = sorted(durations)
    summary = {
        "tenant_id": checked,
        "signed_reviews": len(signoffs),
        "timed_reviews": len(durations),
        "avg_review_duration_ms": (sum(durations) // len(durations)) if durations else None,
        "median_review_duration_ms": sorted_d[len(sorted_d) // 2] if sorted_d else None,
        "total_ledger_events": len(events),
    }
    if _wants_json(json_out):
        _emit_json(summary)
        return
    console.print(Panel(json.dumps(summary, indent=2), title=f"Pilot Metrics ({checked})"))


@security_app.command("scan")
def security_scan(
    text: str | None = typer.Option(None, "--text", "-t", help="Text to scan."),
    file: Path | None = typer.Option(None, "--file", "-f", exists=True, help="File to scan."),
    mode: str = typer.Option("both", "--mode", help="both|input|output"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Scan prompts, documents, or LLM outputs for injection, secrets, or PII."""
    from evidence_kernel.guardrails import check_output_safety, check_text_safety

    content = file.read_text(encoding="utf-8") if file else (text or "")
    if not content:
        err_console.print("[red]Provide --text or --file.[/red]")
        raise typer.Exit(code=1)
    in_r = check_text_safety(content) if mode in {"both", "input"} else None
    out_r = check_output_safety(content) if mode in {"both", "output"} else None
    safe = in_r is None and out_r is None
    res = {"safe": safe, "input_reason": in_r, "output_reason": out_r}
    if _wants_json(json_out):
        _emit_json(res)
    else:
        badge = "[green]SAFE[/green]" if safe else f"[red]BLOCKED ({in_r or out_r})[/red]"
        console.print(f"Scan result: {badge}")
    if not safe:
        raise typer.Exit(code=2)


@security_app.command("redteam")
def security_redteam(
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Execute the 46-probe Red-Team adversarial & PII leakage suite."""
    from evidence_eval.redteam import run_redteam_suite

    report = run_redteam_suite()
    if _wants_json(json_out):
        _emit_json(report)
        if not report["meets_enterprise_target"]:
            raise typer.Exit(code=1)
        return

    table = Table(title="Red-Team Security Audit Results", box=box.ROUNDED)
    table.add_column("Metric", style="bold cyan")
    table.add_column("Measured")
    table.add_row("Attacks Blocked", f"{report['attacks_blocked']}/{report['attacks_total']}")
    table.add_row("Block Rate", f"{report['block_rate'] * 100:.2f}%")
    table.add_row(
        "Secrets / PII Leaked", f"{report['secret_pii_leaked']}/{report['secret_pii_probes']}"
    )
    table.add_row("Benign False Positives", f"{report['false_positives']}/{report['benign_total']}")
    badge = (
        "[bold green]PASS (>=95%)[/bold green]"
        if report["meets_enterprise_target"]
        else "[red]FAIL[/red]"
    )
    table.add_row("Enterprise Target", badge)
    console.print(table)
    if not report["meets_enterprise_target"]:
        raise typer.Exit(code=1)


def _bench_gw_factory(
    mode: str,
    edge_url: str,
    edge_model: str,
    api_url: str,
    api_model: str,
    timeout_s: float,
):
    from evidence_kernel.constrained import OutlinesGuidedGateway
    from evidence_kernel.gateway import (
        BudgetedGateway,
        FixtureGateway,
        HybridAgentRouter,
        OllamaEdgeGateway,
        OpenAICompatibleGateway,
    )

    def _make():
        if mode == "fixture":
            inner = FixtureGateway("happy")
        elif mode == "edge":
            inner = OutlinesGuidedGateway(
                OllamaEdgeGateway(edge_url, model=edge_model, timeout_s=timeout_s),
                max_schema_retries=2,
            )
        elif mode == "api":
            inner = OutlinesGuidedGateway(
                OpenAICompatibleGateway(api_url, model=api_model, timeout_s=timeout_s),
                max_schema_retries=2,
            )
        else:
            inner = OutlinesGuidedGateway(
                HybridAgentRouter(
                    edge_gateway=OllamaEdgeGateway(edge_url, model=edge_model, timeout_s=timeout_s),
                    api_gateway=(
                        OpenAICompatibleGateway(api_url, model=api_model, timeout_s=timeout_s)
                        if api_url
                        else None
                    ),
                ),
                max_schema_retries=2,
            )
        return BudgetedGateway(inner, max_turns=5)

    return _make


@bench_app.command("compare")
def bench_compare(
    mode: str = typer.Option("fixture", "--mode", help="fixture|edge|api|hybrid"),
    edge_url: str = typer.Option("http://127.0.0.1:11434", "--edge-url"),
    edge_model: str = typer.Option("qwen2.5:3b", "--edge-model"),
    api_url: str = typer.Option("", "--api-url"),
    api_model: str = typer.Option("local", "--api-model"),
    timeout_s: float = typer.Option(30.0, "--timeout-s"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Compare Single-Pass LLM vs Evidence Layer on exact page+bbox & numeric hallucinations."""
    from evidence_eval.agent_live_bench import compare_baseline_vs_evidence_layer

    factory = _bench_gw_factory(mode, edge_url, edge_model, api_url, api_model, timeout_s)
    report = compare_baseline_vs_evidence_layer(factory, is_live=(mode != "fixture"))
    if _wants_json(json_out):
        _emit_json(report)
        return

    table = Table(title=f"B2 Comparison ({report['mode']})", box=box.ROUNDED)
    table.add_column("Metric", style="bold cyan")
    table.add_column("Baseline LLM")
    table.add_column("Evidence Layer", style="green")
    table.add_column("Delta")
    table.add_row(
        "Exact Page+BBox Precision",
        f"{report['baseline_exact_citation_rate'] * 100:.1f}%",
        f"{report['evidence_exact_citation_rate'] * 100:.1f}%",
        f"+{report['citation_precision_gain_pp']} pp",
    )
    table.add_row(
        "Numeric Hallucinations",
        str(report["baseline_numeric_hallucinations"]),
        str(report["evidence_numeric_hallucinations"]),
        f"-{report['numeric_hallucination_reduction_pct']}%",
    )
    console.print(table)


@bench_app.command("live")
def bench_live(
    mode: str = typer.Option("fixture", "--mode", help="fixture|edge|api|hybrid"),
    edge_url: str = typer.Option("http://127.0.0.1:11434", "--edge-url"),
    edge_model: str = typer.Option("qwen2.5:3b", "--edge-model"),
    api_url: str = typer.Option("", "--api-url"),
    api_model: str = typer.Option("local", "--api-model"),
    timeout_s: float = typer.Option(30.0, "--timeout-s"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Run live/simulated agent suite measuring schema rate, citations, latency & leaks."""
    from evidence_eval.agent_live_bench import evaluate_gateway

    factory = _bench_gw_factory(mode, edge_url, edge_model, api_url, api_model, timeout_s)
    report = evaluate_gateway(factory, label=f"{mode}:{edge_model}")
    if _wants_json(json_out):
        _emit_json(report)
        return
    console.print(Panel(json.dumps(report, indent=2), title=f"Live Bench ({report['label']})"))


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Start the Model Context Protocol (MCP) JSON-RPC 2.0 server on stdin/stdout."""
    from evidence_api.mcp_server import serve_stdio

    raise typer.Exit(code=serve_stdio())


@mcp_app.command("inspect")
def mcp_inspect(
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """List all exposed MCP tools, resources, and certification prompts."""
    from evidence_api.mcp_server import MCP_PROMPTS, MCP_RESOURCES, MCP_TOOLS

    payload = {
        "tools": [{"name": t["name"], "description": t["description"]} for t in MCP_TOOLS],
        "resources": list(MCP_RESOURCES),
        "prompts": list(MCP_PROMPTS),
    }
    if _wants_json(json_out):
        _emit_json(payload)
        return

    t_table = Table(title=f"MCP Tools ({len(MCP_TOOLS)})", box=box.ROUNDED)
    t_table.add_column("Tool Name", style="bold cyan", no_wrap=True)
    t_table.add_column("Description")
    for tool in MCP_TOOLS:
        t_table.add_row(tool["name"], tool["description"])
    console.print(t_table)

    r_table = Table(title=f"MCP Resources ({len(MCP_RESOURCES)})", box=box.ROUNDED)
    r_table.add_column("URI", style="bold green", no_wrap=True)
    r_table.add_column("Name")
    r_table.add_column("MIME")
    for res in MCP_RESOURCES:
        r_table.add_row(res["uri"], res["name"], res["mimeType"])
    console.print(r_table)

    p_table = Table(title=f"MCP Prompts ({len(MCP_PROMPTS)})", box=box.ROUNDED)
    p_table.add_column("Prompt", style="bold magenta", no_wrap=True)
    p_table.add_column("Description")
    for pr in MCP_PROMPTS:
        p_table.add_row(pr["name"], pr["description"])
    console.print(p_table)


@mcp_app.command("config")
def mcp_config(
    client: str = typer.Option(
        "claude", "--client", help="claude|cursor|vscode|antigravity|generic"
    ),
    url: str | None = typer.Option(None, "--url", help="Optional HTTP base URL (uses /mcp)."),
    write: Path | None = typer.Option(None, "--write", help="Write generated JSON to file."),
    json_out: bool = typer.Option(False, "--json", help="Emit raw JSON."),
) -> None:
    """Generate (or write) ready-to-paste MCP client configuration for AI IDEs & hosts."""
    from rich.syntax import Syntax

    from evidence_api.mcp_server import build_mcp_client_config

    cfg = build_mcp_client_config(client=client, server_url=url)
    rendered = json.dumps(cfg, indent=2)
    if write is not None:
        target = write.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")
        if _wants_json(json_out):
            _emit_json({"written": str(target), "config": cfg})
            return
        console.print(f"[green]Wrote MCP config for {client}:[/green] {target}")
        return
    if _wants_json(json_out):
        _emit_json(cfg)
        return
    console.print(
        Panel(
            Syntax(rendered, "json", theme="ansi_dark", word_wrap=True),
            title=f"MCP Client Configuration ({client})",
            subtitle="stdio: `aeroregu mcp serve` | HTTP: `POST /mcp`",
        )
    )


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
    dev_secret: bool = typer.Option(
        False, "--dev-secret", help="Generate ephemeral dev EVIDENCE_SESSION_SECRET if unset."
    ),
) -> None:
    """Start the FastAPI HTTP API + Web UI + Streamable HTTP MCP endpoint."""
    import secrets

    import uvicorn

    from evidence_api.app import _secret

    if _secret() is None:
        if not dev_secret:
            err_console.print(
                "[red]EVIDENCE_SESSION_SECRET must be >=24 chars.[/red] "
                "Set it in env or pass [bold]--dev-secret[/bold] for local dev."
            )
            raise typer.Exit(code=1)
        os.environ["EVIDENCE_SESSION_SECRET"] = secrets.token_urlsafe(32)
        console.print(
            "[yellow]Generated ephemeral EVIDENCE_SESSION_SECRET for this session.[/yellow]"
        )

    console.print(
        f"[bold green]Starting aeroregu API + MCP HTTP endpoint[/bold green] "
        f"on http://{host}:{port} (MCP: POST http://{host}:{port}/mcp)"
    )
    uvicorn.run("evidence_api.app:app", host=host, port=port, reload=reload)


@app.command("quickstart")
def quickstart_cmd(
    tenant: str = typer.Option("quickstart-demo", "--tenant", help="Isolated demo tenant ID."),
    output_zip: Path | None = typer.Option(None, "--output", help="Optional ZIP path."),
) -> None:
    """Run an end-to-end guided walkthrough (ingest -> calc -> verify -> DSSE ZIP -> verify)."""
    from evidence_kernel.__main__ import verify_zip_bundle
    from evidence_kernel.gateway import gateway_from_env
    from evidence_kernel.supervisor import CaseSpec, run_case

    from evidence_api.app import _now, _zip_bytes, evidence_home, open_ledger

    checked = _tenant_or_exit(tenant)
    console.print(
        Panel(
            Text(
                "aeroregu Guided Certification Workflow\n"
                "1) Ingest CS-27.301 clause -> 2) Calc Decimal+Flint -> "
                "3) Verify Case -> 4) Export DSSE ZIP -> 5) Verify Offline",
                justify="left",
            ),
            border_style="cyan",
        )
    )
    sample = "CS-27.301 Flight, ground, and water design loads check."
    ledger = open_ledger(checked)
    gw = gateway_from_env("happy", constrained=True, runtime_mode="fixture")
    inputs = {
        "mass_kg": "800.000",
        "gravity_m_s2": "10.000",
        "load_factor": "1.000",
        "cg_x_m": "0.000",
        "unit_x_m": ["-2.000", "-1.000", "1.000", "2.000"],
        "unit_operative": [True, True, True, True],
    }
    out = run_case(
        ledger,
        gw,
        CaseSpec(
            tenant_id=checked,
            actor_id="author",
            created_at=_now(),
            blocks=[{"text": sample, "span_start": 0, "span_end": len(sample)}],
            method_id="rigid_body_point_mass",
            calc_inputs=inputs,
            record_requirements=True,
        ),
    )
    home_dir = evidence_home()
    zip_target = output_zip or (home_dir / f"{checked}_bundle.zip")
    zip_target.parent.mkdir(parents=True, exist_ok=True)
    zip_target.write_bytes(_zip_bytes(ledger.events()))
    ok, report = verify_zip_bundle(zip_target)
    console.print(
        f"[green]1-3. Case Verified:[/green] {out.envelope['confidence']} "
        f"({len(out.event_hashes)} ledger events)"
    )
    console.print(f"[green]4-5. DSSE ZIP Verified Offline:[/green] {ok} -> {zip_target}")
    console.print(f"[dim]Merkle Root: {report['merkle_root']}[/dim]")


@coverage_app.command("status")
def coverage_status_cmd(
    tenant: str = typer.Option(
        "demo", "--tenant", autocompletion=_complete_tenant, help="Tenant ledger ID."
    ),
    status: str | None = typer.Option(None, "--status", "-s", help="Filter cell status."),
    stale_only: bool = typer.Option(False, "--stale-only", help="Show invalidated cells only."),
    limit: int = typer.Option(15, "--limit", "-l", help="Max sample cells to include."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Show flight-envelope gap counts and certification traceability gate readiness."""
    from evidence_coverage.gate import evaluate_traceability_gate
    from evidence_coverage.status import gap_report, list_cells_with_status

    from evidence_api.app import open_ledger

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    events = ledger.events()
    gaps = gap_report(events)
    gate = evaluate_traceability_gate(events, chain_verified=ledger.verify())
    matched_cells = list_cells_with_status(events, status_filter=status, stale_only=stale_only)
    cells = matched_cells[:limit]
    payload = {
        "tenant_id": checked,
        "gaps": gaps,
        "gate": gate,
        "matched_count": len(matched_cells),
        "sample_cells": cells,
    }
    if _wants_json(json_out):
        _emit_json(payload)
        return
    table = Table(title=f"Coverage Status ({checked})", box=box.ROUNDED)
    table.add_column("Metric", style="bold cyan", no_wrap=True)
    table.add_column("Value")
    for k, v in gaps.items():
        table.add_row(str(k), str(v))
    table.add_row("matched_cells", str(len(matched_cells)))
    table.add_row("traceability_gate_ready", f"[bold]{gate.get('ready')}[/bold]")
    console.print(table)


@coverage_app.command("sweep")
def coverage_sweep_cmd(
    tenant: str = typer.Option(
        "demo", "--tenant", autocompletion=_complete_tenant, help="Tenant ledger ID."
    ),
    limit: int = typer.Option(15, "--limit", help="Max cells to verify in this sweep."),
    stale_only: bool = typer.Option(False, "--stale-only", help="Re-verify stale cells only."),
    actor: str = typer.Option("author", "--actor", help="Actor ID."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Run deterministic flight-envelope verification across pending cells."""
    from evidence_coverage.status import run_coverage_sweep

    from evidence_api.app import _now, open_ledger

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    if _wants_json(json_out):
        summary = run_coverage_sweep(
            ledger,
            actor_id=actor,
            created_at=_now(),
            target_status="gap",
            stale_only=stale_only,
            limit=limit,
        )
    else:
        from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            tid = progress.add_task(
                f"[cyan]Sweeping up to {limit} coverage cells for {checked}...[/cyan]",
                total=None,
            )
            summary = run_coverage_sweep(
                ledger,
                actor_id=actor,
                created_at=_now(),
                target_status="gap",
                stale_only=stale_only,
                limit=limit,
            )
            progress.update(tid, description="[green]Coverage sweep completed[/green]")
    res = {**summary, "merkle_root": ledger.merkle_root()}
    if _wants_json(json_out):
        _emit_json(res)
        return
    console.print(Panel(json.dumps(res, indent=2), title=f"Coverage Sweep Completed ({checked})"))


@dossier_app.command("export")
def dossier_export_cmd(
    fmt: str = typer.Option("summary", "--format", "-f", help="summary|strictdoc|oscal"),
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ledger ID."),
    write: Path | None = typer.Option(None, "--write", "-w", help="Optional output file."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Export certification dossier as JSON summary, StrictDOC (.sdoc), or NIST OSCAL SAR."""
    from evidence_coverage.dossier import (
        build_enterprise_dossier,
        export_oscal_sar,
        export_strictdoc,
    )

    from evidence_api.app import open_ledger

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    dossier = build_enterprise_dossier(ledger.events(), chain_verified=ledger.verify())
    if fmt == "strictdoc":
        out_str = export_strictdoc(dossier)
        if write is not None:
            write.expanduser().resolve().write_text(out_str, encoding="utf-8")
            console.print(f"[green]Wrote StrictDOC:[/green] {write}")
            return
        typer.echo(out_str)
        return
    payload = export_oscal_sar(dossier) if fmt == "oscal" else dossier
    if write is not None:
        write.expanduser().resolve().write_text(json.dumps(payload, indent=2), encoding="utf-8")
        console.print(f"[green]Wrote {fmt}:[/green] {write}")
        return
    if _wants_json(json_out) or fmt == "oscal":
        _emit_json(payload)
        return
    console.print(Panel(json.dumps(payload, indent=2)[:1800], title=f"Dossier ({checked})"))


@dossier_app.command("pdf")
def dossier_pdf_cmd(
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ledger ID."),
    write: Path = typer.Option(
        Path("aeroregu-dossier.pdf"), "--write", "-w", help="Output signed PDF path."
    ),
    enforce_distinct: bool = typer.Option(False, "--enforce-distinct"),
    json_out: bool = typer.Option(False, "--json", help="Emit metadata JSON output."),
) -> None:
    """Export a DSSE Ed25519 signed PDF dossier with visual bbox thumbnails and offline QR."""
    from evidence_coverage.pdf_report import build_signed_pdf_report
    from evidence_kernel.storage import open_blob_store

    from evidence_api.app import _attestation_keypair, evidence_home, open_ledger

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    events = ledger.events()
    priv_pem, pub_pem = _attestation_keypair()
    store = open_blob_store(evidence_home())
    pdf_sources: dict[str, bytes] = {}
    for ev in events:
        p = (ev.get("body") or {}).get("payload") or {}
        sh = str(p.get("source_hash") or p.get("source_file_hash") or "")
        if len(sh) == 64 and sh not in pdf_sources:
            try:
                raw_b = store.get_blob(sh)
                if raw_b.startswith(b"%PDF"):
                    pdf_sources[sh] = raw_b
            except Exception:
                pass
    report = build_signed_pdf_report(
        events,
        tenant_id=checked,
        chain_verified=ledger.verify(),
        private_key_pem=priv_pem,
        public_key_pem=pub_pem,
        pdf_sources=pdf_sources or None,
        enforce_distinct_reviewer=enforce_distinct,
    )
    out = write.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(report["pdf_bytes"])
    meta = {
        "output": str(out),
        "pdf_sha256": report["pdf_sha256"],
        "merkle_root": report["merkle_root"],
        "qr_payload": report["qr_payload"],
        "bbox_thumbnails_count": report["bbox_thumbnails_count"],
        "gate_status": report["gate_status"],
    }
    if _wants_json(json_out):
        _emit_json(meta)
        return
    console.print(
        f"[green]Signed PDF written to[/green] {out} "
        f"(bbox_thumbs={meta['bbox_thumbnails_count']}, merkle={meta['merkle_root'][:16]}...)"
    )


@ledger_app.command("role-set")
def ledger_role_set_cmd(
    actor_id: str = typer.Argument(..., help="Actor ID to update/create."),
    role: str = typer.Argument(..., help="Role: author | cve | admin | human"),
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ledger ID."),
) -> None:
    """Assign RBAC role (author / cve / admin) for separation of duties."""
    from evidence_api.app import open_ledger

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    ledger.set_actor_role(actor_id, role)
    console.print(f"[green]Updated role:[/green] {actor_id} -> {role} (tenant={checked})")


@ledger_app.command("webhook-add")
def ledger_webhook_add_cmd(
    url: str = typer.Argument(..., help="HTTPS webhook callback URL."),
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ledger ID."),
    events: str = typer.Option(
        "envelope_invalidated", "--events", help="Comma-separated event names."
    ),
) -> None:
    """Register an HMAC-SHA256 CI/CD webhook triggered on envelope invalidation."""
    from evidence_kernel.webhooks import new_webhook_record

    from evidence_api.app import open_ledger

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    rec = new_webhook_record(
        url=url,
        events=[e.strip() for e in events.split(",") if e.strip()],
    )
    saved = ledger.register_webhook(rec)
    _emit_json(saved)


@app.command("wizard")
def wizard_cmd() -> None:
    """Interactive guided assistant (menu 0..9) — zero CLI commands or JSON required."""
    from evidence_api.wizard import run_interactive_hub

    run_interactive_hub(
        console,
        lambda: quickstart_cmd(tenant="quickstart-demo", output_zip=None),
    )


@app.command("ui")
def ui_cmd(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open default web browser."),
) -> None:
    """Launch the visual Web UI + HTTP API + /mcp endpoint in one command."""
    import secrets
    import webbrowser

    import uvicorn

    from evidence_api.app import _secret

    if _secret() is None:
        os.environ["EVIDENCE_SESSION_SECRET"] = secrets.token_urlsafe(32)
        console.print(
            "[yellow]Generated ephemeral EVIDENCE_SESSION_SECRET for local Web UI.[/yellow]"
        )
    url = f"http://{host}:{port}"
    console.print(f"[bold green]Web UI + HTTP MCP ready at {url}[/bold green]")
    if open_browser:
        webbrowser.open(url)
    uvicorn.run("evidence_api.app:app", host=host, port=port)


@cad_app.command("inspect")
def cad_inspect_cmd(
    file: Path = typer.Argument(
        ...,
        help="STEP, IGES, CATIA XML/.CATPart/.CATProduct, .bdf/.dat, or .inp",
    ),
    auto_run: bool = typer.Option(True, "--auto-run/--no-auto-run", help="Auto-run ready cards."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Inspect a CAD/CAE model and resolve automatic Knowledgeware/FEM card bindings."""
    from evidence_calc.cad_bindings import bind_parameters_to_cards
    from evidence_ingest.blocks import IngestAbstain
    from evidence_ingest.router import ingest_bytes

    from evidence_api.app import MAX_INGEST_BYTES

    resolved = file.expanduser().resolve()
    if not resolved.is_file():
        console.print(f"[red]File not found:[/red] {resolved}")
        raise typer.Exit(1)
    raw = resolved.read_bytes()
    if len(raw) > MAX_INGEST_BYTES:
        console.print("[red]File exceeds MAX_INGEST_BYTES.[/red]")
        raise typer.Exit(1)
    try:
        parsed = ingest_bytes(raw, resolved.name)
    except IngestAbstain as exc:
        if _wants_json(json_out):
            _emit_json({"status": "abstain", "reason": exc.reason, "filename": resolved.name})
        else:
            console.print(f"[yellow]Abstain:[/yellow] {exc.reason}")
        raise typer.Exit(1)
    cad_cae = parsed.get("cad_cae")
    if not isinstance(cad_cae, dict):
        console.print("[red]Not a CAD/CAE file.[/red]")
        raise typer.Exit(1)
    bindings = bind_parameters_to_cards(
        list(cad_cae.get("parameters") or []),
        formulas=list(cad_cae.get("formulas") or []),
        auto_run=auto_run,
    )
    payload = {"filename": parsed["filename"], "cad_cae": cad_cae, "bindings": bindings}
    if _wants_json(json_out):
        _emit_json(payload)
        return
    tbl = Table(title=f"CAD/CAE Bindings ({cad_cae.get('format')})", box=box.ROUNDED)
    tbl.add_column("Method Card", style="cyan")
    tbl.add_column("Bound")
    tbl.add_column("Ready")
    tbl.add_column("Auto Run")
    for mid, info in (bindings.get("cards") or {}).items():
        exec_info = info.get("execution") or {}
        tbl.add_row(
            mid,
            f"{info.get('matched_count', 0)}/{info.get('required_count', 0)}",
            "yes"
            if info.get("ready_to_run")
            else "missing: " + ",".join(info.get("missing_required", [])),
            str(exec_info.get("confidence", "-")),
        )
    console.print(tbl)


@coverage_app.command("envelope-3d")
def coverage_envelope_3d_cmd(
    tenant: str = typer.Option("demo", "--tenant"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Export 3D V-n envelope & [X_cg, Y_cg, Z_cg] cloud summary."""
    from evidence_coverage.envelope_3d import build_vn_cg_envelope_3d

    from evidence_api.app import open_ledger

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    payload = build_vn_cg_envelope_3d(ledger.events())
    if _wants_json(json_out):
        _emit_json(payload)
        return
    cloud = payload["cg_cloud"]
    console.print(
        Panel(
            f"Slices: {len(payload['vn_envelope']['mass_slices'])}\n"
            f"Triangles: {payload['vn_envelope']['surface_mesh']['triangle_count']}\n"
            f"CG Cloud Points: {cloud['total_points']} (CAD refs: {cloud['cad_cae_points']})\n"
            f"SMT Envelope Proved: {payload['smt_proof']['envelope_proved']}",
            title=f"3D V-n & CG Cloud ({checked})",
            border_style="cyan",
        )
    )


@app.command("examples")
def examples_cmd() -> None:
    """Show beginner-friendly recipes for calculations, PDF audits, Red-Team, and MCP."""
    from rich.syntax import Syntax

    recipes = (
        "# 1. Asistente visual en terminal (sin memorizar nada)\n"
        "aeroregu wizard\n\n"
        "# 2. Abrir Web UI en el navegador en 1 comando\n"
        "aeroregu ui\n\n"
        "# 3. Calculo sin escribir JSON (evita comillas de PowerShell)\n"
        "aeroregu calc run bolt_screen -s area_mm2=100 -s shear_force_n=1000 "
        "-s tensile_force_n=2000 -s shear_allowable_mpa=150 "
        "-s tensile_allowable_mpa=250 --formal\n\n"
        "# 4. Verificar documento o norma con citas pagina + bbox\n"
        'aeroregu verify-case --text "CS-27.301 Flight loads" --formal\n\n'
        "# 5. Conectores CAD/CAE (STEP, IGES, CATIA XML, NASTRAN, ABAQUS)\n"
        "aeroregu cad inspect model.stp --json\n\n"
        "# 6. Conectar con Antigravity / Claude / Cursor (19 tools MCP)\n"
        "aeroregu mcp inspect\n"
        "aeroregu mcp config --client antigravity\n"
    )
    console.print(
        Panel(
            Syntax(recipes, "bash", theme="ansi_dark", word_wrap=True),
            title="aeroregu Quick Recipes",
            border_style="cyan",
        )
    )


@app.command("watch")
def watch_cmd(
    tenant: str = typer.Option("demo", "--tenant"),
    watch_dir: list[Path] = typer.Option([], "--watch-dir", help="Shared/PLM folder to watch."),
    git_repo: Path | None = typer.Option(None, "--git-repo", help="Git repository path to watch."),
    git_base: str = typer.Option("master", "--git-base"),
    max_tokens: int = typer.Option(250_000, "--max-tokens"),
    max_cloud_tokens: int = typer.Option(50_000, "--max-cloud-tokens"),
    max_jobs: int = typer.Option(200, "--max-jobs"),
    once: bool = typer.Option(True, "--once/--loop"),
    interval: float = typer.Option(30.0, "--interval"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Run persistent overnight verification daemon over shared folders & Git branches."""
    import time

    from evidence_coverage.overnight import run_overnight_cycle
    from evidence_kernel.daemon import OvernightBudget

    from evidence_api.app import open_ledger

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    budget = OvernightBudget(
        max_tokens_per_night=max_tokens,
        max_cloud_tokens_per_night=max_cloud_tokens,
        max_jobs_per_run=max_jobs,
    )
    while True:
        res = run_overnight_cycle(
            ledger,
            watch_dirs=list(watch_dir) if watch_dir else None,
            git_repo=git_repo,
            git_base=git_base,
            budget=budget,
            run_fuzzer=True,
        )
        if once:
            if _wants_json(json_out):
                _emit_json(res)
            else:
                brief = res["briefing"]["executive_summary"]
                console.print(
                    Panel(
                        f"Run: {res['run_id']}\n"
                        f"Jobs processed: {res['queue']['processed']}\n"
                        f"Findings open: {brief['open_items']} "
                        f"(MS<0: {brief['ms_negative_count']}, "
                        f"Cross-Artifact: {brief['cross_artifact_count']}, "
                        f"Stale: {brief['stale_cells_count']})",
                        title=f"aeroregu watch ({checked})",
                        border_style="green",
                    )
                )
            return
        time.sleep(max(1.0, interval))


@overnight_app.command("briefing")
def overnight_briefing_cmd(
    tenant: str = typer.Option("demo", "--tenant"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show risk-sorted 08:00 AM Morning Briefing queue."""
    from evidence_coverage.overnight import build_morning_briefing

    from evidence_api.app import open_ledger

    checked = _tenant_or_exit(tenant)
    brief = build_morning_briefing(open_ledger(checked))
    if _wants_json(json_out):
        _emit_json(brief)
        return
    tbl = Table(title=f"Morning Briefing 08:00 AM ({checked})", box=box.ROUNDED)
    tbl.add_column("ID")
    tbl.add_column("Risk")
    tbl.add_column("Category")
    tbl.add_column("Title")
    tbl.add_column("Status")
    for item in brief["queue"][:25]:
        tbl.add_row(
            item["finding_id"],
            str(item["risk_score"]),
            item["category"],
            item["title"][:60],
            item["status"],
        )
    console.print(tbl)


@db_app.command("migrate")
def db_migrate_cmd(
    tenant: str = typer.Option("demo", "--tenant"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Apply idempotent versioned schema migrations on active SQLite or PostgreSQL backend."""
    from evidence_api.app import open_ledger

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    applied = ledger.run_migrations() if hasattr(ledger, "run_migrations") else []
    payload = {
        "backend": getattr(ledger, "backend_name", "sqlite"),
        "newly_applied": applied,
        "schema_version": ledger.schema_version() if hasattr(ledger, "schema_version") else 0,
        "migrations": ledger.applied_migrations() if hasattr(ledger, "applied_migrations") else [],
    }
    if _wants_json(json_out):
        _emit_json(payload)
    else:
        console.print(
            Panel(
                f"Backend: {payload['backend']}\nSchema v{payload['schema_version']}",
                title=f"Persistence Migrations ({checked})",
                border_style="cyan",
            )
        )


@webhooks_app.command("dlq")
def webhooks_dlq_cmd(
    tenant: str = typer.Option("demo", "--tenant"),
    replay: bool = typer.Option(False, "--replay"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List dead-letter webhook deliveries and optionally replay them."""
    from evidence_kernel.webhooks import replay_dead_letters

    from evidence_api.app import open_ledger

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    if replay:
        out: Any = {"replayed": replay_dead_letters(ledger)}
    else:
        out = {
            "dlq": ledger.queue.list_webhook_dlq(status="dead_letter")
            if hasattr(ledger, "queue")
            else []
        }
    if _wants_json(json_out):
        _emit_json(out)
    else:
        console.print(out)


@materials_app.command("list")
def materials_list_cmd(
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """List pinned MMPDS-16 and CMH-17 engineering materials in the catalog."""
    from evidence_calc.allowables import (
        allowable_catalog_sha256,
        list_materials,
        lookup_allowable,
    )

    mats = list_materials()
    cat_hash = allowable_catalog_sha256()
    if _wants_json(json_out):
        _emit_json({"materials": mats, "catalog_sha256": cat_hash})
        return
    tbl = Table(title=f"Pinned Material Catalog ({cat_hash[:12]}...)", box=box.ROUNDED)
    tbl.add_column("Material ID", style="bold cyan", no_wrap=True)
    tbl.add_column("Standard")
    tbl.add_column("Form")
    tbl.add_column("B-Basis Fty [MPa]", justify="right")
    for mat_id in mats:
        info = lookup_allowable(mat_id, basis="B", property_name="fty_mpa")
        tbl.add_row(
            mat_id,
            str(info.get("standard", "-")),
            str(info.get("form", "-")),
            str(info.get("allowable_value_mpa", "-")),
        )
    console.print(tbl)


@materials_app.command("lookup")
def materials_lookup_cmd(
    material_id: str = typer.Argument(
        ..., autocompletion=_complete_material, help="Material ID (e.g. 7075-T651)."
    ),
    basis: str = typer.Option("B", "--basis", "-b", help="Statistical basis: A or B."),
    property_name: str = typer.Option(
        "fty_mpa", "--property", "-p", help="Property key (fty_mpa, ftu_mpa, fcy_mpa, fsu_mpa)."
    ),
    thickness_mm: str = typer.Option("10", "--thickness", help="Section thickness [mm]."),
    temp_c: str = typer.Option("23", "--temp", help="Operating temperature [C]."),
    environment: str = typer.Option("RTD", "--env", help="Environment: CTD, RTD, ETW."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Lookup pinned A-Basis / B-Basis allowable with thickness, temperature & env knockdowns."""
    from evidence_calc.allowables import lookup_allowable

    res = lookup_allowable(
        material_id,
        basis=basis,
        property_name=property_name,
        thickness_mm=thickness_mm,
        temp_c=temp_c,
        environment=environment,
    )
    if _wants_json(json_out):
        _emit_json(res)
        if res.get("abstain"):
            raise typer.Exit(code=2)
        return
    if res.get("abstain"):
        err_console.print(f"[red]Material lookup abstained:[/red] {res.get('abstain')}")
        raise typer.Exit(code=2)
    console.print(Panel(json.dumps(res, indent=2), title=f"Allowable: {material_id} ({basis})"))


@cad_app.command("brep")
def cad_brep_cmd(
    file: Path = typer.Argument(..., exists=True, help="STEP AP203/AP214/AP242 file (.stp/.step)."),
    density: float = typer.Option(2810.0, "--density", help="Material density [kg/m^3]."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Run deterministic 3D STEP B-Rep geometry, mass, CG, web thickness & clearance audit."""
    import hashlib

    from evidence_ingest.blocks import IngestAbstain
    from evidence_ingest.cad_brep import analyze_step_brep

    raw = file.expanduser().read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        res = analyze_step_brep(raw, digest, default_density_kg_m3=density)
    except IngestAbstain as exc:
        err_console.print(f"[red]STEP B-Rep analysis abstained:[/red] {exc.reason}")
        raise typer.Exit(code=2) from exc
    payload = {"filename": file.name, "source_hash": digest, **res}
    if _wants_json(json_out):
        _emit_json(payload)
        return
    console.print(
        Panel(json.dumps(payload, indent=2, default=str), title=f"CAD B-Rep: {file.name}")
    )


@cae_app.command("parse-binary")
def cae_parse_binary_cmd(
    file: Path = typer.Argument(..., exists=True, help="CAE result binary (.op2/.h5/.odb/.rst)."),
    sandbox: bool = typer.Option(
        False, "--sandbox", help="Force isolated worker (automatic for .odb/.rst)."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Parse NASTRAN .op2, HDF5 .h5, or sandboxed .odb/.rst FEA binaries into viewer meshes."""
    import hashlib

    from evidence_ingest.blocks import IngestAbstain
    from evidence_ingest.cae_binary import (
        parse_cae_h5_bytes,
        parse_nastran_op2_bytes,
        run_sandboxed_cae_worker,
    )

    raw = file.expanduser().read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    suffix = file.suffix.lower() or ".op2"
    try:
        if sandbox or suffix in {".odb", ".rst"}:
            parsed = run_sandboxed_cae_worker(raw, digest, suffix)
        elif suffix in {".h5", ".hdf5"}:
            parsed = parse_cae_h5_bytes(raw, digest)
        else:
            parsed = parse_nastran_op2_bytes(raw, digest)
    except IngestAbstain as exc:
        err_console.print(f"[red]CAE binary parser abstained:[/red] {exc.reason}")
        raise typer.Exit(code=2) from exc

    blocks_out = [b.as_dict() if hasattr(b, "as_dict") else b for b in (parsed.get("blocks") or [])]
    out = {**parsed, "blocks": blocks_out, "filename": file.name}
    if _wants_json(json_out):
        _emit_json(out)
        return
    vmesh = out.get("viewer_mesh") or {}
    console.print(
        Panel(
            f"File: {file.name}\nSource SHA-256: {digest[:16]}...\n"
            f"Nodes: {len(vmesh.get('nodes') or [])} | "
            f"Elements: {len(vmesh.get('elements') or [])} | Blocks: {len(blocks_out)}",
            title="CAE Binary Parse",
            border_style="cyan",
        )
    )


@cae_app.command("nafems-audit")
def cae_nafems_audit_cmd(
    bdf: Path = typer.Argument(..., exists=True, help="NASTRAN .bdf/.dat file."),
    f06: Path | None = typer.Option(None, "--f06", exists=True, help="Optional .f06 solver log."),
    report: Path | None = typer.Option(
        None, "--report", exists=True, help="Optional Stress Report PDF/DOCX to cross-check."
    ),
    unit_system: str | None = typer.Option(
        None, "--units", help="Explicit unit system (SI | MM_T_N_MPA)."
    ),
    require_units: bool = typer.Option(
        False, "--require-units", help="Abstain if unit system is unspecified."
    ),
    rotor_rpm: str | None = typer.Option(None, "--rotor-rpm", help="Rotor RPM for SOL 103 guard."),
    blade_count: int = typer.Option(4, "--blades", help="Number of rotor blades."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Run NAFEMS V&V manifest, BDF-vs-Report table drift & rotor modal guard on Nastran files."""
    import hashlib

    from evidence_coverage.nafems_audit import run_full_nafems_audit
    from evidence_ingest.blocks import IngestAbstain
    from evidence_ingest.fem_parsers import parse_nastran_bdf, parse_nastran_f06
    from evidence_ingest.router import ingest_bytes

    bdf_bytes = bdf.expanduser().read_bytes()
    bdf_hash = hashlib.sha256(bdf_bytes).hexdigest()
    try:
        bdf_parsed = parse_nastran_bdf(
            bdf_bytes, bdf_hash, base_dir=bdf.expanduser().parent, unit_system=unit_system
        )
        f06_parsed = None
        f06_hash = ""
        if f06 is not None:
            f06_bytes = f06.expanduser().read_bytes()
            f06_hash = hashlib.sha256(f06_bytes).hexdigest()
            f06_parsed = parse_nastran_f06(f06_bytes, f06_hash)
        report_blocks = None
        report_hash = None
        if report is not None:
            rep_bytes = report.expanduser().read_bytes()
            report_hash = hashlib.sha256(rep_bytes).hexdigest()
            rep_ing = ingest_bytes(rep_bytes, report.name)
            report_blocks = [
                b.as_dict() if hasattr(b, "as_dict") else b for b in (rep_ing.get("blocks") or [])
            ]
    except IngestAbstain as exc:
        err_console.print(f"[red]NAFEMS audit abstained:[/red] {exc.reason}")
        raise typer.Exit(code=2) from exc

    res = run_full_nafems_audit(
        bdf_parsed=bdf_parsed,
        bdf_hash=bdf_hash,
        f06_parsed=f06_parsed,
        f06_hash=f06_hash,
        report_blocks=report_blocks,
        report_hash=report_hash,
        rotor_rpm=rotor_rpm,
        blade_count=blade_count,
        require_unit_system=require_units,
    )
    if _wants_json(json_out):
        _emit_json(res)
        return
    status_str = "[green]PASS[/green]" if res["overall_pass"] else "[red]FAIL / ABSTAIN[/red]"
    console.print(
        Panel(
            f"Overall: {status_str} | Manifest: {res['manifest']['manifest_sha256'][:16]}...\n"
            f"Property drift count: {res['property_drift']['discrepancy_count']}",
            title="NAFEMS V&V Audit",
            border_style="cyan",
        )
    )


@cae_app.command("bdf-diff")
def cae_bdf_diff_cmd(
    rev_a: Path = typer.Argument(..., exists=True, help="Baseline Rev A .bdf file."),
    rev_b: Path = typer.Argument(..., exists=True, help="Updated Rev B .bdf file."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Compare two Nastran BDF revisions across PSHELL, PCOMP, SUBCASE, and CONM2 masses."""
    import hashlib

    from evidence_coverage.nafems_audit import diff_bdf_revisions_and_invalidate
    from evidence_ingest.fem_parsers import parse_nastran_bdf

    a_bytes = rev_a.expanduser().read_bytes()
    b_bytes = rev_b.expanduser().read_bytes()
    bdf_a = parse_nastran_bdf(
        a_bytes, hashlib.sha256(a_bytes).hexdigest(), base_dir=rev_a.expanduser().parent
    )
    bdf_b = parse_nastran_bdf(
        b_bytes, hashlib.sha256(b_bytes).hexdigest(), base_dir=rev_b.expanduser().parent
    )
    res = diff_bdf_revisions_and_invalidate(rev_a_bdf=bdf_a, rev_b_bdf=bdf_b, ledger=None)
    if _wants_json(json_out):
        _emit_json(res)
        return
    _emit_json(res)


@plm_app.command("sync")
def plm_sync_cmd(
    system: str = typer.Option(
        "3dexperience", "--system", help="3dexperience | teamcenter | windchill"
    ),
    item_id: str = typer.Option("WING-SPAR-ASM-01", "--item", help="PLM item/part ID."),
    revision: str = typer.Option("Rev A", "--revision", help="Revision label."),
    msn: int = typer.Option(1, "--msn", help="Aircraft MSN effectivity."),
    use_mock: bool = typer.Option(True, "--mock/--no-mock", help="Use offline mock transport."),
    base_url: str = typer.Option("https://plm.aeroregu.local", "--base-url"),
    token_url: str = typer.Option("https://plm.aeroregu.local/oauth/token", "--token-url"),
    client_id: str = typer.Option("aeroregu-svc", "--client-id"),
    client_secret: str = typer.Option("svc-secret", "--client-secret"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Pull Effectivity/EBOM tree from 3DEXPERIENCE, Teamcenter, or Windchill."""
    from evidence_ingest.plm_connectors import (
        MockPLMServerTransport,
        PLMConnectorError,
        build_plm_connector,
    )

    transport = MockPLMServerTransport() if use_mock else None
    conn = build_plm_connector(
        system.lower(),  # type: ignore[arg-type]
        base_url=base_url,
        token_url=token_url,
        client_id=client_id,
        client_secret=client_secret,
        transport=transport,
    )
    try:
        bom = conn.fetch_ebom(item_id, revision=revision, msn=msn)
    except PLMConnectorError as exc:
        err_console.print(f"[red]PLM sync failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        conn.close()
    if _wants_json(json_out):
        _emit_json(bom)
        return
    console.print(Panel(json.dumps(bom, indent=2), title=f"PLM EBOM Sync ({system})"))


@plm_app.command("writeback")
def plm_writeback_cmd(
    change_action_id: str = typer.Option(
        "ECN-2026-001", "--change-action", help="ECN / Change Action ID."
    ),
    system: str = typer.Option(
        "3dexperience", "--system", help="3dexperience | teamcenter | windchill"
    ),
    tenant: str = typer.Option(
        "demo", "--tenant", autocompletion=_complete_tenant, help="Tenant ledger ID."
    ),
    use_mock: bool = typer.Option(True, "--mock/--no-mock", help="Use offline mock transport."),
    base_url: str = typer.Option("https://plm.aeroregu.local", "--base-url"),
    token_url: str = typer.Option("https://plm.aeroregu.local/oauth/token", "--token-url"),
    client_id: str = typer.Option("aeroregu-svc", "--client-id"),
    client_secret: str = typer.Option("svc-secret", "--client-secret"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Write back cryptographic Merkle root attestation onto a PLM Change Action / ECN."""
    from evidence_ingest.plm_connectors import (
        MockPLMServerTransport,
        PLMConnectorError,
        build_plm_connector,
    )

    from evidence_api.app import open_ledger

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    transport = MockPLMServerTransport() if use_mock else None
    conn = build_plm_connector(
        system.lower(),  # type: ignore[arg-type]
        base_url=base_url,
        token_url=token_url,
        client_id=client_id,
        client_secret=client_secret,
        transport=transport,
    )
    try:
        wb = conn.writeback_merkle_attestation(
            change_action_id=change_action_id,
            merkle_root=ledger.merkle_root(),
            head_hash=ledger.head_hash(),
            chain_verified=ledger.verify(),
        )
    except PLMConnectorError as exc:
        err_console.print(f"[red]PLM writeback failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        conn.close()
    if _wants_json(json_out):
        _emit_json(wb)
        return
    console.print(Panel(json.dumps(wb, indent=2), title=f"PLM Attestation Writeback ({system})"))


@ecn_app.command("diff")
def ecn_diff_cmd(
    rev_a: str = typer.Option(..., "--rev-a", "-a", help="Rev A dossier JSON or @file.json."),
    rev_b: str = typer.Option(..., "--rev-b", "-b", help="Rev B dossier JSON or @file.json."),
    ecn_id: str = typer.Option("ECN-2026-001", "--ecn-id", help="Change notice ID."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Compare Rev A vs Rev B certification dossiers (requirements, CAD, FEM, Margins)."""
    from evidence_coverage.collaboration_ecn import compute_ecn_revision_diff

    a_data = _load_json_arg(rev_a)
    b_data = _load_json_arg(rev_b)
    diff = compute_ecn_revision_diff(a_data, b_data, ecn_id=ecn_id)
    if _wants_json(json_out):
        _emit_json(diff)
        return
    console.print(Panel(json.dumps(diff, indent=2), title=f"ECN Revision Diff ({ecn_id})"))


@review_app.command("list")
def review_list_cmd(
    tenant: str = typer.Option(
        "demo", "--tenant", autocompletion=_complete_tenant, help="Tenant ledger ID."
    ),
    target_hash: str | None = typer.Option(
        None, "--target-hash", help="Optional target ledger event hash."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """List review threads and blocking status for a tenant ledger."""
    from evidence_coverage.collaboration_ecn import get_review_thread_store

    checked = _tenant_or_exit(tenant)
    store = get_review_thread_store()
    threads = store.list_threads(checked, target_event_hash=target_hash)
    blocking = store.unresolved_blocking_threads(checked, target_event_hash=target_hash)
    payload = {"tenant_id": checked, "blocking_count": len(blocking), "threads": threads}
    if _wants_json(json_out):
        _emit_json(payload)
        return
    tbl = Table(title=f"Review Threads ({checked} | blocking={len(blocking)})", box=box.ROUNDED)
    tbl.add_column("Thread ID", style="bold cyan", no_wrap=True)
    tbl.add_column("Status")
    tbl.add_column("Author")
    tbl.add_column("Category")
    tbl.add_column("Target Event")
    for thr in threads:
        tbl.add_row(
            str(thr["thread_id"]),
            str(thr["status"]),
            str(thr["author_id"]),
            str(thr["category"]),
            str(thr["target_event_hash"])[:16] + "...",
        )
    console.print(tbl)


@review_app.command("create")
def review_create_cmd(
    target_hash: str = typer.Option(..., "--target-hash", "-t", help="Ledger event hash."),
    body: str = typer.Option(..., "--body", "-b", help="Review comment body."),
    author: str = typer.Option("author", "--actor", "-a", help="Author / CVE actor ID."),
    category: str = typer.Option("review_comment", "--category", help="Comment category."),
    initial_status: str = typer.Option("OPEN", "--status", help="OPEN or CHANGES_REQUESTED."),
    tenant: str = typer.Option(
        "demo", "--tenant", autocompletion=_complete_tenant, help="Tenant ledger ID."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Create a review thread anchored to a ledger event hash."""
    from evidence_coverage.collaboration_ecn import get_review_thread_store

    checked = _tenant_or_exit(tenant)
    try:
        thr = get_review_thread_store().create_thread(
            checked,
            target_event_hash=target_hash,
            author_id=author,
            body=body,
            category=category,
            initial_status=initial_status,
        )
    except ValueError as exc:
        err_console.print(f"[red]Failed to create thread:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    if _wants_json(json_out):
        _emit_json(thr)
        return
    console.print(
        f"[green]Created thread[/green] [bold]{thr['thread_id']}[/bold] ({thr['status']})"
    )


@review_app.command("reply")
def review_reply_cmd(
    thread_id: str = typer.Argument(..., help="Review thread ID (e.g. thr-...)."),
    body: str = typer.Option(..., "--body", "-b", help="Reply text."),
    actor: str = typer.Option("author", "--actor", "-a", help="Actor ID."),
    request_changes: bool = typer.Option(
        False, "--request-changes", help="Mark thread as CHANGES_REQUESTED."
    ),
    tenant: str = typer.Option(
        "demo", "--tenant", autocompletion=_complete_tenant, help="Tenant ledger ID."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Reply to an existing review thread."""
    from evidence_coverage.collaboration_ecn import get_review_thread_store

    checked = _tenant_or_exit(tenant)
    try:
        thr = get_review_thread_store().reply_thread(
            checked,
            thread_id,
            actor_id=actor,
            body=body,
            request_changes=request_changes,
        )
    except (KeyError, ValueError) as exc:
        err_console.print(f"[red]Reply failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    if _wants_json(json_out):
        _emit_json(thr)
        return
    console.print(
        f"[green]Updated thread[/green] [bold]{thr['thread_id']}[/bold] ({thr['status']})"
    )


@review_app.command("resolve")
def review_resolve_cmd(
    thread_id: str = typer.Argument(..., help="Review thread ID to resolve."),
    actor: str = typer.Option("cve", "--actor", "-a", help="Resolver actor ID."),
    note: str = typer.Option("Verified and resolved", "--note", help="Resolution note."),
    tenant: str = typer.Option(
        "demo", "--tenant", autocompletion=_complete_tenant, help="Tenant ledger ID."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Resolve a blocking review thread so sign-off can proceed."""
    from evidence_coverage.collaboration_ecn import get_review_thread_store

    checked = _tenant_or_exit(tenant)
    try:
        thr = get_review_thread_store().resolve_thread(
            checked,
            thread_id,
            resolver_id=actor,
            resolution_note=note,
        )
    except (KeyError, ValueError) as exc:
        err_console.print(f"[red]Resolve failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    if _wants_json(json_out):
        _emit_json(thr)
        return
    console.print(f"[green]Resolved thread[/green] [bold]{thr['thread_id']}[/bold] by {actor}")


@qualification_app.command("run")
def qualification_run_cmd(
    repo_root: Path | None = typer.Option(None, "--repo-root", help="Repository root override."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Run DO-330 / TQL-5 IQ/OQ qualification suite and return attested report."""
    from evidence_coverage.qualification_aid import run_iq_oq_qualification_suite

    root = repo_root.expanduser().resolve() if repo_root else Path(__file__).resolve().parents[4]
    report = run_iq_oq_qualification_suite(repo_root=root)
    if _wants_json(json_out):
        _emit_json(report)
        if not report.get("passed", report.get("all_passed", True)):
            raise typer.Exit(code=1)
        return
    console.print(Panel(json.dumps(report, indent=2), title="DO-330 / TQL-5 IQ/OQ Qualification"))


@security_app.command("sbom")
def security_sbom_cmd(
    repo_root: Path | None = typer.Option(None, "--repo-root", help="Repository root override."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Generate CycloneDX 1.5 dependency SBOM and CVE verification report."""
    from evidence_kernel.hsm_eidas_scim import verify_sbom_and_dependencies

    root = repo_root.expanduser().resolve() if repo_root else Path(__file__).resolve().parents[4]
    report = verify_sbom_and_dependencies(root)
    if _wants_json(json_out):
        _emit_json(report)
        return
    console.print(Panel(json.dumps(report, indent=2), title="CycloneDX 1.5 SBOM & CVE Gate"))


@security_app.command("ma-readiness")
def security_ma_readiness_cmd(
    repo_root: Path | None = typer.Option(None, "--repo-root", help="Repository root override."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Evaluate enterprise M&A IP, license & security technical readiness."""
    from evidence_coverage.ma_readiness import evaluate_ma_technical_readiness

    root = repo_root.expanduser().resolve() if repo_root else Path(__file__).resolve().parents[4]
    report = evaluate_ma_technical_readiness(root)
    if _wants_json(json_out):
        _emit_json(report)
        return
    console.print(Panel(json.dumps(report, indent=2), title="M&A Technical Readiness"))


@bundle_app.command("export-qes")
def bundle_export_qes_cmd(
    output: Path = typer.Argument(..., help="Output .zip bundle file path (writes .qes.json too)."),
    tenant: str = typer.Option(
        "demo", "--tenant", autocompletion=_complete_tenant, help="Tenant ledger ID."
    ),
    profile: str = typer.Option("CAdES-B-LT", "--profile", help="CAdES-B-LT or PAdES-B-LT."),
    actor: str = typer.Option("cve", "--actor", help="Qualified signer actor ID."),
    key_uri: str | None = typer.Option(None, "--key-uri", help="Optional HSM key URI."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Export DSSE bundle ZIP sealed with eIDAS Qualified Electronic Signature (CAdES/PAdES)."""
    import hashlib

    from evidence_kernel.hsm_eidas_scim import (
        EidasQESEnvelope,
        get_hsm_signer,
        get_qes_envelope_service,
    )

    from evidence_api.app import _zip_bytes, open_ledger

    if profile not in {"CAdES-B-LT", "PAdES-B-LT"}:
        err_console.print(f"[red]Unsupported QES profile:[/red] {profile}")
        raise typer.Exit(code=1)
    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    bundle_bytes = _zip_bytes(ledger.events())
    out_path = output.expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bundle_bytes)

    qes_svc = get_qes_envelope_service()
    envelope = qes_svc.build_envelope(
        bundle_bytes,
        signer_id=actor,
        profile=profile,
        key_uri=key_uri,
    )
    verification = EidasQESEnvelope.verify_envelope(envelope, bundle_bytes)
    slot_info = get_hsm_signer().get_slot_info(key_uri)
    qes_sidecar = out_path.with_name(out_path.name + ".qes.json")
    payload = {
        "tenant_id": checked,
        "output_path": str(out_path),
        "qes_path": str(qes_sidecar),
        "profile": profile,
        "signer_id": actor,
        "bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        "bundle_size_bytes": len(bundle_bytes),
        "qes_envelope": envelope,
        "verification": verification,
        "hsm_slot": slot_info,
    }
    qes_sidecar.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    ok = bool(verification.get("verified"))
    if _wants_json(json_out):
        _emit_json(payload)
        if not ok:
            raise typer.Exit(code=1)
        return
    console.print(
        Panel(
            f"Bundle: {out_path}\nQES Envelope: {qes_sidecar}\n"
            f"Profile: {profile} | Verified: [bold]{ok}[/bold]\n"
            f"Bundle SHA-256: {payload['bundle_sha256']}",
            title="eIDAS QES Dossier Export",
            border_style="green" if ok else "red",
        )
    )
    if not ok:
        raise typer.Exit(code=1)


@quote_app.command("generate")
def quote_generate_cmd(
    text: str | None = typer.Option(
        None, "--text", "-t", help="Raw RFQ / tender specification text."
    ),
    file: Path | None = typer.Option(None, "--file", "-f", exists=True, help="RFQ document path."),
    kind: str = typer.Option(
        "hybrid_turnkey",
        "--kind",
        help="hybrid_turnkey | aerospace_manufacturing | engineering_workpackage",
    ),
    material: str | None = typer.Option(None, "--material", help="Override material grade."),
    quantity: str | None = typer.Option(None, "--quantity", help="Override part quantity."),
    mass_kg: str | None = typer.Option(None, "--mass-kg", help="Override finished mass (kg)."),
    calc_notes: str | None = typer.Option(None, "--calc-notes", help="Override calc notes count."),
    fem_models: str | None = typer.Option(None, "--fem-models", help="Override FEM models count."),
    target_margin: str = typer.Option("22.000", "--target-margin", help="Target gross margin (%)."),
    min_margin: str = typer.Option("10.000", "--min-margin", help="Minimum Z3 floor margin (%)."),
    currency: str = typer.Option("EUR", "--currency", help="Quote currency."),
    tenant: str = typer.Option(
        "demo", "--tenant", autocompletion=_complete_tenant, help="Tenant ledger ID."
    ),
    actor: str = typer.Option("author", "--actor", help="Actor ID."),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Optional .md or .json file output path."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Generate a full 8-agent automated quotation with all 7-dimension assumptions & Z3 proof."""
    from evidence_coverage.quotation_multiagent import (
        QuotationRequestSpec,
        run_multiagent_quotation,
    )

    from evidence_api.app import _now, open_ledger

    if file is not None:
        raw_text = file.read_text(encoding="utf-8")
    elif text is not None:
        raw_text = text
    else:
        err_console.print("[red]Provide --text or --file with RFQ content.[/red]")
        raise typer.Exit(code=1)

    explicit: dict[str, Any] = {}
    if material:
        explicit["material_grade"] = material
    if quantity:
        explicit["part_quantity"] = quantity
    if mass_kg:
        explicit["finished_mass_kg"] = mass_kg
    if calc_notes:
        explicit["calc_notes_count"] = calc_notes
    if fem_models:
        explicit["fem_models_count"] = fem_models

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    spec = QuotationRequestSpec(
        rfq_text=raw_text,
        quotation_kind=kind,  # type: ignore[arg-type]
        tenant_id=checked,
        actor_id=actor,
        created_at=_now(),
        currency=currency,
        target_margin_pct=target_margin,
        min_acceptable_margin_pct=min_margin,
        explicit_params=explicit,
    )
    dossier = run_multiagent_quotation(ledger, spec)
    payload = dossier.to_dict()

    if output is not None:
        out_path = output.expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.suffix.lower() == ".json":
            out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        else:
            out_path.write_text(dossier.markdown_report, encoding="utf-8")

    if _wants_json(json_out):
        _emit_json(payload)
        if dossier.confidence == "abstain":
            raise typer.Exit(code=2)
        return

    if dossier.confidence == "abstain":
        console.print(
            Panel(
                f"[bold yellow]ABSTAIN: {dossier.abstain_reason}[/bold yellow]\n"
                f"Escalate to: {dossier.escalate_to}",
                title="Quotation Gate Halted",
            )
        )
        raise typer.Exit(code=2)

    pert = dossier.pert_summary
    summary_table = Table(
        title=f"Multi-Agent Quotation Summary — {dossier.rfq_id}", box=box.ROUNDED
    )
    summary_table.add_column("Percentile", style="bold cyan")
    summary_table.add_column("Total Cost", justify="right")
    summary_table.add_column("Quoted Price", style="bold green", justify="right")
    summary_table.add_row(
        "P50 (Expected)",
        f"{pert['total_cost_p50_eur']} {currency}",
        f"{pert['quoted_price_p50_eur']} {currency}",
    )
    summary_table.add_row(
        "P80 (Recommended)",
        f"{pert['total_cost_p80_eur']} {currency}",
        f"{pert['quoted_price_p80_eur']} {currency}",
    )
    summary_table.add_row(
        "P90 (Conservative)",
        f"{pert['total_cost_p90_eur']} {currency}",
        f"{pert['quoted_price_p90_eur']} {currency}",
    )
    console.print(summary_table)

    asm_table = Table(
        title=f"Exhaustive Assumptions Register ({len(dossier.assumptions)} items across 7 axes)",
        box=box.ROUNDED,
    )
    asm_table.add_column("ID", style="bold cyan")
    asm_table.add_column("Category")
    asm_table.add_column("Label")
    asm_table.add_column("Assumed Value")
    asm_table.add_column("Sensitivity", justify="right")
    for a in dossier.assumptions:
        asm_table.add_row(
            str(a["assumption_id"]),
            str(a["category"]),
            str(a["label"]),
            str(a["assumed_value"])[:48],
            f"+{a['cost_sensitivity_pct']}%",
        )
    console.print(asm_table)

    fp = dossier.formal_margin_proof or {}
    console.print(
        Panel(
            f"Decision: {dossier.decision_status}\n"
            f"Z3 Margin Proof: {fp.get('status', 'SKIPPED')} ({fp.get('proof_hash', '')[:16]}...)\n"
            f"Merkle Root: {dossier.merkle_root} | Events: {len(dossier.event_hashes)}",
            title="Cryptographic & Formal Verification",
            border_style="green",
        )
    )


@quote_app.command("assumptions")
def quote_assumptions_cmd(
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """List the 7-dimension assumption taxonomy, aerospace materials, and rate cards."""
    from evidence_coverage.quotation_multiagent import get_quotation_catalog

    catalog = get_quotation_catalog()
    if _wants_json(json_out):
        _emit_json(catalog)
        return

    table = Table(title="7-Dimension Quotation Assumption Taxonomy", box=box.ROUNDED)
    table.add_column("Category", style="bold cyan")
    table.add_column("Description")
    for item in catalog["assumption_categories"]:
        table.add_row(item["category"], item["description"])
    console.print(table)


@quote_app.command("scrape")
def quote_scrape_cmd(
    live: bool = typer.Option(
        False,
        "--live/--offline",
        help="Query live GitHub API & commercial sites in addition to verified catalog.",
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Optional .md or .json report output path."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Scrape & benchmark global GitHub repositories and web platforms for automated quoting."""
    from evidence_coverage.repo_web_scraper import QuotationIntelligenceScraper

    res = QuotationIntelligenceScraper().run_full_harvest(live_network=live)
    if output is not None:
        out_path = output.expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.suffix.lower() == ".json":
            out_path.write_text(json.dumps(res, indent=2), encoding="utf-8")
        else:
            out_path.write_text(res["markdown_report"], encoding="utf-8")

    if _wants_json(json_out):
        _emit_json(res)
        return

    gh = res["github"]
    wb = res["web_platforms"]
    cmp = res["comparison"]
    table = Table(
        title=(
            f"Global Quoting Landscape (GitHub: {gh['total_repositories']} | "
            f"Web Platforms: {wb['total_platforms']} | Mode: {gh['network_mode']})"
        ),
        box=box.ROUNDED,
    )
    table.add_column("Repository", style="bold cyan")
    table.add_column("Category")
    table.add_column("Axes Covered", justify="right")
    for item in cmp["top_github_comparables"]:
        table.add_row(
            str(item["repo_full_name"]),
            str(item["category"]),
            f"{item['axes_covered']}/{item['axes_total']}",
        )
    console.print(table)
    console.print(
        f"[green]aeroregu capability coverage:[/green] "
        f"{cmp['aeroregu_axes_covered']}/{cmp['aeroregu_axes_total']} axes"
    )


@quote_app.command("archetypes")
def quote_archetypes_cmd(
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """List the 18 helicopter engineering archetypes, 9 country rate cards & 6 studies."""
    from evidence_coverage.rotorcraft_quotation_catalog import get_rotorcraft_catalog

    cat = get_rotorcraft_catalog()
    if _wants_json(json_out):
        _emit_json(cat)
        return

    a_table = Table(
        title=f"Rotorcraft Engineering Quotation Archetypes ({cat['archetypes_count']})",
        box=box.ROUNDED,
    )
    a_table.add_column("ID", style="bold cyan")
    a_table.add_column("Family")
    a_table.add_column("Title")
    a_table.add_column("FP / T&M")
    a_table.add_column("PERT M (h)", justify="right")
    for a in cat["archetypes"]:
        a_table.add_row(
            a["archetype_id"],
            a["family"],
            a["title"],
            f"{a['fixed_price_share_pct']}% / {a['capped_tm_share_pct']}%",
            a["pert_total_hours"]["most_likely"],
        )
    console.print(a_table)

    c_table = Table(
        title=f"Country Rate Profiles (Default={cat['default_country_code']} + 8 Countries)",
        box=box.ROUNDED,
    )
    c_table.add_column("Code", style="bold cyan")
    c_table.add_column("Country / Hubs")
    c_table.add_column("Stress EUR/h", justify="right")
    c_table.add_column("CVE EUR/h", justify="right")
    c_table.add_column("OH / Cont", justify="right")
    for c in cat["countries"]:
        c_table.add_row(
            c["country_code"],
            f"{c['country_name']} ({c['cluster_hubs']})",
            c["rates"]["stress_rate"],
            c["rates"]["cve_rate"],
            f"{c['overhead_pct']}% / {c['contingency_pct']}%",
        )
    console.print(c_table)


@quote_app.command("helicopter")
def quote_helicopter_cmd(
    text: str | None = typer.Option(None, "--text", "-t", help="Helicopter RFQ text."),
    file: Path | None = typer.Option(None, "--file", "-f", exists=True, help="RFQ document path."),
    country: str = typer.Option(
        "EU_DEFAULT",
        "--country",
        help="Rate card: EU_DEFAULT | FR | DE | ES | IT | UK | US | PL | IN",
    ),
    archetype: str | None = typer.Option(
        None, "--archetype", help="Explicit archetype ID Q-DES-01 .. Q-TST-02."
    ),
    cert_basis: str = typer.Option(
        "CS-29", "--cert-basis", help="CS-27 | CS-29 | STC | PART21J_REPAIR"
    ),
    material: str = typer.Option(
        "HYBRID_AL_CFRP",
        "--material",
        help="ALUMINUM_2024_7075 | HYBRID_AL_CFRP | TI_6AL_4V | CFRP_PRIMARY_HONEYCOMB",
    ),
    cosysmo: str = typer.Option("NOMINAL", "--cosysmo", help="LOW | NOMINAL | ELEVATED | HIGH"),
    idp: str = typer.Option("COMPLETE", "--idp", help="COMPLETE | PARTIAL | INCOMPLETE"),
    nearshore: str = typer.Option(
        "ES", "--nearshore", help="Nearshore execution comparison country."
    ),
    target_margin: str = typer.Option("22.000", "--target-margin", help="Target margin (%)."),
    min_margin: str = typer.Option("10.000", "--min-margin", help="Z3 floor margin (%)."),
    tenant: str = typer.Option(
        "demo", "--tenant", autocompletion=_complete_tenant, help="Tenant ID."
    ),
    actor: str = typer.Option("author", "--actor", help="Actor ID."),
    bdf_file: Path | None = typer.Option(None, "--bdf-file", exists=True, help="Nastran .bdf IDP."),
    f06_file: Path | None = typer.Option(None, "--f06-file", exists=True, help="Nastran .f06 IDP."),
    step_file: Path | None = typer.Option(None, "--step-file", exists=True, help="STEP .stp IDP."),
    corpus_file: Path | None = typer.Option(
        None, "--corpus-file", exists=True, help="Historical quotes CSV/JSON/JSONL path."
    ),
    output: Path | None = typer.Option(None, "--output", "-o", help="Optional .md or .json path."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Generate a 18-archetype, 9-country helicopter engineering & stress quote."""
    from evidence_coverage.rotorcraft_quotation_catalog import (
        RotorcraftQuotationSpec,
        run_rotorcraft_department_quotation,
    )

    from evidence_api.app import _now, open_ledger

    if file is not None:
        raw_text = file.read_text(encoding="utf-8")
    elif text is not None:
        raw_text = text
    else:
        err_console.print("[red]Provide --text or --file with rotorcraft RFQ text.[/red]")
        raise typer.Exit(code=1)

    idp_attachments: dict[str, Any] = {}
    if bdf_file is not None:
        idp_attachments["bdf_path"] = str(bdf_file)
    if f06_file is not None:
        idp_attachments["f06_path"] = str(f06_file)
    if step_file is not None:
        idp_attachments["step_path"] = str(step_file)

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    spec = RotorcraftQuotationSpec(
        rfq_text=raw_text,
        country_code=country,
        archetype_id=archetype,
        cert_basis=cert_basis,
        material_family=material,
        cosysmo_complexity=cosysmo,
        idp_maturity=idp,
        target_margin_pct=target_margin,
        min_acceptable_margin_pct=min_margin,
        nearshore_country=nearshore,
        tenant_id=checked,
        actor_id=actor,
        created_at=_now(),
        idp_attachments=idp_attachments,
        historical_corpus_path=str(corpus_file) if corpus_file is not None else None,
    )
    dossier = run_rotorcraft_department_quotation(ledger, spec)
    if output is not None:
        out_path = output.expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.suffix.lower() == ".json":
            out_path.write_text(json.dumps(dossier, indent=2), encoding="utf-8")
        else:
            out_path.write_text(dossier["markdown_report"], encoding="utf-8")

    if _wants_json(json_out):
        _emit_json(dossier)
        if dossier["confidence"] == "abstain":
            raise typer.Exit(code=2)
        return

    if dossier["confidence"] == "abstain":
        err_console.print(f"[red]ABSTAIN:[/red] {dossier.get('abstain_reason')}")
        raise typer.Exit(code=2)

    arch = dossier["archetype"]
    calc = dossier["deterministic_quote"]
    pert = dossier["pert_envelope"]
    comp = dossier["multi_country_comparison"]
    console.print(
        f"[green]Archetype {arch['archetype_id']}[/green] "
        f"({dossier['country_profile']['country_code']}): "
        f"M={calc['quote_price_eur']} EUR | P80={pert['price_p80_eur']} EUR | "
        f"Z3={dossier['formal_margin_proof'].get('status')} | "
        f"Assumptions={dossier['assumptions_total_count']} "
        f"({dossier['assumptions_dimensions_count']} dims)"
    )
    t = Table(title="9-Country Rotorcraft Comparison (EUR)", box=box.ROUNDED)
    t.add_column("Country", style="bold cyan")
    t.add_column("Blended Rate", justify="right")
    t.add_column("Quote Price", justify="right")
    t.add_column("Delta vs EU", justify="right")
    for r in comp["countries"]:
        t.add_row(
            r["country_code"],
            r["blended_hourly_rate_eur"],
            r["quote_price_eur"],
            f"{r['delta_vs_eu_default_pct']}%",
        )
    console.print(t)


@quote_app.command("calibrate")
def quote_calibrate_cmd(
    archetype: str = typer.Option("Q-STR-03", "--archetype", help="Archetype ID."),
    country: str = typer.Option("EU_DEFAULT", "--country", help="Country code."),
    cert_basis: str = typer.Option("CS-29", "--cert-basis", help="CS-27 | CS-29 | STC."),
    material: str = typer.Option("HYBRID_AL_CFRP", "--material", help="Material family."),
    corpus_file: Path | None = typer.Option(
        None, "--corpus-file", exists=True, help="Historical quotes CSV/JSON/JSONL file."
    ),
    synthetic_count: int = typer.Option(
        2160, "--synthetic-count", help="Reference corpus size when no --corpus-file given."
    ),
    bdf_file: Path | None = typer.Option(None, "--bdf-file", exists=True, help="Nastran .bdf IDP."),
    f06_file: Path | None = typer.Option(None, "--f06-file", exists=True, help="Nastran .f06 IDP."),
    top_k: int = typer.Option(3, "--top-k", help="Number of nearest historical bids to match."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Ingest 2,000+ historical bids, run 80/20 PERT calibration, IDP parse & k-NN match."""
    from evidence_coverage.historical_quotation_calibrator import (
        run_historical_calibration_and_matching,
    )

    att: dict[str, Any] = {}
    if bdf_file is not None:
        att["bdf_path"] = str(bdf_file)
    if f06_file is not None:
        att["f06_path"] = str(f06_file)
    payload = run_historical_calibration_and_matching(
        archetype_id=archetype,
        country_code=country,
        cert_basis=cert_basis,
        material_family=material,
        corpus_path=corpus_file,
        synthetic_count=synthetic_count,
        idp_attachments=att,
        top_k=top_k,
    )
    cal = payload["historical_calibration"]
    nearest = payload["nearest_historical_quotes"]
    if _wants_json(json_out):
        _emit_json(payload)
        return

    co = cal["calibration_outputs"]
    bt = cal["backtesting"]
    console.print(
        f"[green]Calibrated {archetype} ({country})[/green]: N={cal['sample_size']}/"
        f"{cal['corpus_total_records']} | PERT Expected={co['calibrated_pert_expected_hours']}h "
        f"| Backtest MAPE {bt['pre_calibration_mape_pct']}% -> {bt['post_calibration_mape_pct']}%"
    )
    kt = Table(title=f"Top-{top_k} Nearest Historical Quotations", box=box.ROUNDED)
    kt.add_column("Quote ID", style="bold cyan")
    kt.add_column("Similarity", justify="right")
    kt.add_column("Quoted h", justify="right")
    kt.add_column("Burned h", justify="right")
    kt.add_column("Overrun", justify="right")
    for r in nearest:
        kt.add_row(
            r["quote_id"],
            r["similarity_score"],
            r["quoted_hours"],
            r["actual_burned_hours"],
            f"{r['overrun_pct']}%",
        )
    console.print(kt)


@quote_app.command("composite")
def quote_composite_cmd(
    text: str = typer.Option(..., "--text", "-t", help="Helicopter RFQ text."),
    archetypes: str = typer.Option(
        "Q-DES-02,Q-DES-04,Q-STR-01,Q-STR-02,Q-STR-03,Q-FDT-01,Q-DOA-02,Q-TST-01",
        "--archetypes",
        help="Comma-separated archetype IDs for composite DAG.",
    ),
    country: str = typer.Option("EU_DEFAULT", "--country", help="9-country rate profile."),
    units: int = typer.Option(1, "--units", help="Lot / MSN units for Wright-Crawford curve."),
    years: int = typer.Option(3, "--years", help="Program duration in years (1..5)."),
    learning_rate: str = typer.Option("85.000", "--learning-rate", help="Learning rate (%)."),
    payment_days: int = typer.Option(60, "--payment-days", help="Net payment terms in days."),
    bdf_file: Path | None = typer.Option(None, "--bdf-file", exists=True, help="Nastran .bdf IDP."),
    f06_file: Path | None = typer.Option(None, "--f06-file", exists=True, help="Nastran .f06 IDP."),
    step_file: Path | None = typer.Option(None, "--step-file", exists=True, help="STEP .stp IDP."),
    xlsx_out: Path | None = typer.Option(None, "--xlsx-out", help="Export formulated .xlsx path."),
    pdf_out: Path | None = typer.Option(None, "--pdf-out", help="Export DSSE-signed .pdf path."),
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ID."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Run Composite Multi-Archetype DAG (CPM + Synergy) & Multi-Year Quotation."""
    from evidence_coverage.composite_dag_quotation import (
        CompositeRotorcraftQuotationSpec,
        run_composite_rotorcraft_quotation,
    )
    from evidence_coverage.quotation_exporter import (
        export_quotation_signed_pdf,
        export_quotation_xlsx,
    )

    from evidence_api.app import _attestation_keypair, _now, open_ledger

    att: dict[str, Any] = {}
    if bdf_file is not None:
        att["bdf_path"] = str(bdf_file)
    if f06_file is not None:
        att["f06_path"] = str(f06_file)
    if step_file is not None:
        att["step_path"] = str(step_file)

    arch_tuple = tuple(a.strip() for a in archetypes.split(",") if a.strip())
    checked = _tenant_or_exit(tenant)
    spec = CompositeRotorcraftQuotationSpec(
        rfq_text=text,
        archetype_ids=arch_tuple,
        country_code=country,
        unit_count=units,
        program_years=years,
        learning_rate_pct=learning_rate,
        payment_terms_days=payment_days,
        idp_attachments=att,
        tenant_id=checked,
        created_at=_now(),
    )
    dossier = run_composite_rotorcraft_quotation(open_ledger(checked), spec)
    if xlsx_out is not None and dossier.get("confidence") != "abstain":
        export_quotation_xlsx(dossier, output_path=xlsx_out)
    if pdf_out is not None and dossier.get("confidence") != "abstain":
        priv_pem, pub_pem = _attestation_keypair()
        export_quotation_signed_pdf(
            dossier, private_key_pem=priv_pem, public_key_pem=pub_pem, output_path=pdf_out
        )

    if _wants_json(json_out):
        _emit_json(dossier)
        if dossier.get("confidence") == "abstain":
            raise typer.Exit(code=2)
        return
    if dossier.get("confidence") == "abstain":
        err_console.print(f"[red]ABSTAIN:[/red] {dossier.get('abstain_reason')}")
        raise typer.Exit(code=2)

    dag = dossier["composite_wbs_dag"]
    my = dossier["multiyear_cashflow_learning"]["outputs"]
    console.print(
        f"[green]Composite DAG ({dag['node_count']} nodes)[/green] "
        f"CP={' -> '.join(dag['critical_path_archetypes'])} ({dag['project_duration_weeks']}w) | "
        f"MultiYear={my['quoted_price_eur']} EUR | NPV={my['net_present_value_eur']} EUR | "
        f"Z3={dossier['formal_multiyear_npv_proof'].get('status')}"
    )


@quote_app.command("audit-contract")
def quote_audit_contract_cmd(
    text: str | None = typer.Option(None, "--text", "-t", help="Contract / RFQ clause text."),
    file: Path | None = typer.Option(
        None, "--file", "-f", exists=True, help="RFQ PDF or TXT path."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Run clause-by-clause contractual compliance matrix & poison-clause detection."""
    from evidence_coverage.contract_clause_auditor import audit_rfq_contract_clauses

    if file is not None:
        if file.suffix.lower() == ".pdf":
            res = audit_rfq_contract_clauses(pdf_bytes=file.read_bytes(), filename=file.name)
        else:
            res = audit_rfq_contract_clauses(
                file.read_text(encoding="utf-8", errors="ignore"), filename=file.name
            )
    elif text is not None:
        res = audit_rfq_contract_clauses(text)
    else:
        err_console.print("[red]Provide --text or --file.[/red]")
        raise typer.Exit(code=1)

    if _wants_json(json_out):
        _emit_json(res)
        return
    console.print(
        f"Gate=[bold]{res['overall_contract_gate']}[/bold] | "
        f"Clauses={res['total_clauses']} | Poisons={res['poison_clauses_count']}"
    )


@quote_app.command("deep-idp")
def quote_deep_idp_cmd(
    bdf_file: Path | None = typer.Option(None, "--bdf-file", exists=True, help="Nastran .bdf IDP."),
    op2_file: Path | None = typer.Option(
        None, "--op2-file", exists=True, help="Nastran .op2 binary."
    ),
    h5_file: Path | None = typer.Option(None, "--h5-file", exists=True, help="CAE .h5 binary."),
    f06_file: Path | None = typer.Option(None, "--f06-file", exists=True, help="Nastran .f06."),
    step_file: Path | None = typer.Option(None, "--step-file", exists=True, help="STEP solid."),
    bom_file: Path | None = typer.Option(
        None, "--bom-file", exists=True, help="BOM PDF/XLSX/DOCX."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Deep physical IDP inspection (nested INCLUDE, DOFs, OP2/H5, B-Rep BTF & BOM/Drawings)."""
    from evidence_coverage.deep_idp_quotation_extractor import extract_deep_idp_engineering_package

    att: dict[str, Any] = {}
    if bdf_file is not None:
        att["bdf_path"] = str(bdf_file)
    if op2_file is not None:
        att["op2_path"] = str(op2_file)
    if h5_file is not None:
        att["h5_path"] = str(h5_file)
    if f06_file is not None:
        att["f06_path"] = str(f06_file)
    if step_file is not None:
        att["step_path"] = str(step_file)
    if bom_file is not None:
        att["rfq_documents"] = [{"path": str(bom_file), "filename": bom_file.name}]

    res = extract_deep_idp_engineering_package(att)
    if _wants_json(json_out):
        _emit_json(res)
        return
    console.print(
        f"IDP Artifacts={len(res['artifacts_analyzed'])} | "
        f"Active DOFs={res['bdf_summary']['dof_summary']['active_dofs']} | "
        f"Buy-to-Fly={res['cad_brep_sizing']['buy_to_fly_ratio']} | "
        f"Est Solve Hours={res['estimated_solve_postproc_hours']}"
    )


@quote_app.command("kfold-calibrate")
def quote_kfold_calibrate_cmd(
    archetype: str = typer.Option("Q-STR-03", "--archetype", help="Archetype ID."),
    country: str = typer.Option("EU_DEFAULT", "--country", help="Country code."),
    k_folds: int = typer.Option(5, "--k-folds", help="Stratified folds (2..10)."),
    corpus_file: Path | None = typer.Option(
        None, "--corpus-file", exists=True, help="Historical CSV/JSON/JSONL/XLSX file."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Run stratified K-fold CV, outlier detection, drift diagnostics & Win-Rate analytics."""
    from evidence_coverage.advanced_quotation_calibration import run_advanced_calibration_suite
    from evidence_coverage.historical_quotation_calibrator import (
        generate_reference_historical_corpus,
        ingest_historical_quotations,
    )

    corpus = (
        ingest_historical_quotations(corpus_file)["records"]
        if corpus_file is not None
        else generate_reference_historical_corpus(2160)
    )
    res = run_advanced_calibration_suite(
        corpus=corpus, archetype_id=archetype, country_code=country, k_folds=k_folds
    )
    if _wants_json(json_out):
        _emit_json(res)
        return
    cv = res["kfold_cv"]
    wr = res["win_rate_calibration"]
    console.print(
        f"K-Fold ({cv['k_folds']}): MAPE {cv['global_pre_mape_pct']}% -> "
        f"{cv['global_post_mape_pct']}% | Drift={res['drift_diagnostics']['drift_status']} | "
        f"Optimal Percentile={wr['recommended_percentile']}"
    )


@quote_app.command("erp-template")
def quote_erp_template_cmd(
    fmt: str = typer.Option("xlsx", "--format", help="Template format: xlsx | csv"),
    output: Path = typer.Option(..., "--output", "-o", help="Output file path."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON summary."),
) -> None:
    """Export official ERP/SAP bulk historical quotation import template."""
    from evidence_coverage.advanced_quotation_calibration import export_erp_sap_import_template

    res = export_erp_sap_import_template(fmt=fmt, output_path=output)
    summary = {k: v for k, v in res.items() if k != "content_bytes"}
    if _wants_json(json_out):
        _emit_json(summary)
        return
    console.print(
        f"[green]ERP/SAP Template saved:[/green] {res['output_path']} ({res['sha256'][:16]}...)"
    )


@quote_app.command("change-order")
def quote_change_order_cmd(
    baseline_text: str = typer.Option(..., "--baseline-text", help="Rev A baseline RFQ text."),
    revised_text: str = typer.Option(..., "--revised-text", help="Rev B changed RFQ text."),
    baseline_archetypes: str = typer.Option(
        "Q-DES-02,Q-STR-03",
        "--baseline-archetypes",
        help="Comma-separated baseline archetypes.",
    ),
    revised_archetypes: str = typer.Option(
        "Q-DES-02,Q-STR-03,Q-FDT-01,Q-DOA-02",
        "--revised-archetypes",
        help="Comma-separated revised archetypes.",
    ),
    country: str = typer.Option("EU_DEFAULT", "--country", help="Country rate profile."),
    baseline_units: int = typer.Option(1, "--baseline-units", help="Baseline lot size."),
    revised_units: int = typer.Option(2, "--revised-units", help="Revised lot size."),
    cr_id: str = typer.Option("CCN-001", "--cr-id", help="Change Request identifier."),
    reason: str = typer.Option("Scope expansion", "--reason", help="Change reason."),
    xlsx_out: Path | None = typer.Option(None, "--xlsx-out", help="CCN .xlsx output path."),
    pdf_out: Path | None = typer.Option(None, "--pdf-out", help="CCN signed .pdf output path."),
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ID."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Compute closed-loop Rev A -> Rev B Change-Order delta quotation & CCN exports."""
    from evidence_coverage.composite_dag_quotation import (
        CompositeRotorcraftQuotationSpec,
        run_composite_rotorcraft_quotation,
    )
    from evidence_coverage.quotation_change_order import compute_quotation_change_order
    from evidence_coverage.quotation_exporter import (
        export_change_order_signed_pdf,
        export_change_order_xlsx,
    )

    from evidence_api.app import _attestation_keypair, _now, open_ledger

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    now = _now()
    base_spec = CompositeRotorcraftQuotationSpec(
        rfq_id="RFQ-REV-A",
        rfq_text=baseline_text,
        archetype_ids=tuple(a.strip() for a in baseline_archetypes.split(",") if a.strip()),
        country_code=country,
        unit_count=baseline_units,
        tenant_id=checked,
        created_at=now,
    )
    base_dossier = run_composite_rotorcraft_quotation(ledger, base_spec)
    rev_spec = CompositeRotorcraftQuotationSpec(
        rfq_id="RFQ-REV-B",
        rfq_text=revised_text,
        archetype_ids=tuple(a.strip() for a in revised_archetypes.split(",") if a.strip()),
        country_code=country,
        unit_count=revised_units,
        tenant_id=checked,
        created_at=now,
    )
    ccn = compute_quotation_change_order(
        ledger, base_dossier, rev_spec, cr_id=cr_id, change_reason=reason
    )
    if xlsx_out is not None and ccn.get("confidence") != "abstain":
        export_change_order_xlsx(ccn, output_path=xlsx_out)
    if pdf_out is not None and ccn.get("confidence") != "abstain":
        priv_pem, pub_pem = _attestation_keypair()
        export_change_order_signed_pdf(
            ccn, private_key_pem=priv_pem, public_key_pem=pub_pem, output_path=pdf_out
        )
    if _wants_json(json_out):
        _emit_json(ccn)
        if ccn.get("confidence") == "abstain":
            raise typer.Exit(code=2)
        return
    if ccn.get("confidence") == "abstain":
        err_console.print(f"[red]CCN ABSTAIN:[/red] {ccn.get('abstain_reason')}")
        raise typer.Exit(code=2)
    fin = ccn["financial_delta"]
    console.print(
        f"[green]{ccn['cr_id']}[/green] dHours={fin['delta_net_hours']} | "
        f"dMultiYear={fin['delta_multiyear_quoted_price_eur']} EUR ({fin['delta_price_pct']}%) | "
        f"dDuration={ccn['cpm_delta']['delta_duration_weeks']}w | "
        f"Status={ccn['decision_status']}"
    )


@quote_app.command("portfolio-level")
def quote_portfolio_level_cmd(
    rfq_count: int = typer.Option(2, "--rfq-count", help="Number of queued helicopter RFQs."),
    country: str = typer.Option("ES", "--country", help="Country rate profile."),
    lead_cve: int = typer.Option(2, "--lead-cve", help="Available Lead CVE headcount."),
    fdt_spec: int = typer.Option(2, "--fdt-spec", help="Available F&DT specialist headcount."),
    max_util: str = typer.Option("85.000", "--max-util", help="Target max weekly utilization (%)."),
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ID."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Level Stress Office engineering capacity across queued RFQs via RCPSP."""
    from evidence_coverage.composite_dag_quotation import (
        CompositeRotorcraftQuotationSpec,
        run_composite_rotorcraft_quotation,
    )
    from evidence_coverage.portfolio_capacity_leveler import level_portfolio_capacity

    from evidence_api.app import _now, open_ledger

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    now = _now()
    presets = [
        ("CS-29 metallic fitting static Net 60.", ("Q-DES-02", "Q-STR-02", "Q-STR-03", "Q-DOA-02")),
        ("CS-29 hoist F&DT STC Net 60.", ("Q-STR-03", "Q-FDT-01", "Q-DOA-02", "Q-TST-01")),
        ("CS-27 composite frame Net 60.", ("Q-DES-03", "Q-STR-01", "Q-STR-03", "Q-FDT-01")),
    ]
    dossiers = []
    for idx in range(max(1, rfq_count)):
        txt, archs = presets[idx % len(presets)]
        spec = CompositeRotorcraftQuotationSpec(
            rfq_id=f"RFQ-PORT-{idx + 1:02d}",
            rfq_text=txt,
            archetype_ids=archs,
            country_code=country,
            tenant_id=checked,
            created_at=now,
        )
        dossiers.append(run_composite_rotorcraft_quotation(ledger, spec))

    res = level_portfolio_capacity(
        dossiers,
        team_headcount={"LEAD_CVE": lead_cve, "FDT_SPEC": fdt_spec},
        max_utilization_pct=max_util,
    )
    if _wants_json(json_out):
        _emit_json(res)
        return
    top = res["bottleneck_roles"][0]
    console.print(
        f"[green]Portfolio RCPSP ({res['portfolio_rfq_count']} RFQs)[/green] | "
        f"OverloadedWks={res['overloaded_weeks_before_leveling']} | "
        f"TopBottleneck={top['role']} ({top['unconstrained_peak_utilization_pct']}%) | "
        f"Overflow={res['recommended_nearshore_overflow_hours']}h | "
        f"PeakCF=-{res['combined_peak_negative_cashflow_eur']} EUR"
    )


@quote_app.command("fx-hedge")
def quote_fx_hedge_cmd(
    quoted_price_eur: str = typer.Option("500000", "--price-eur", help="Quoted price (EUR)."),
    cost_eur: str = typer.Option("380000", "--cost-eur", help="Escalated base cost (EUR)."),
    billing_currency: str = typer.Option("USD", "--billing-currency", help="EUR|USD|GBP|PLN|INR."),
    cost_currency: str = typer.Option("EUR", "--cost-currency", help="EUR|USD|GBP|PLN|INR."),
    hedge_ratio_pct: str = typer.Option("85.000", "--hedge-pct", help="Forward hedge ratio (%)."),
    years: int = typer.Option(3, "--years", help="Program horizon (years)."),
    fx_band_pct: str = typer.Option("10.000", "--fx-band", help="FX shock band (+/- %)."),
    min_margin_pct: str = typer.Option("10.000", "--min-margin", help="Min net margin (%)."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Evaluate multi-currency FX forward hedging & continuous Z3 SMT margin floor proof."""
    from evidence_coverage.quotation_fx_hedging import evaluate_quotation_fx_hedging

    res = evaluate_quotation_fx_hedging(
        quoted_price_eur=quoted_price_eur,
        cost_eur=cost_eur,
        billing_currency=billing_currency,
        cost_currency=cost_currency,
        hedge_ratio_pct=hedge_ratio_pct,
        program_years=years,
        fx_shock_band_pct=fx_band_pct,
        min_acceptable_margin_pct=min_margin_pct,
    )
    if _wants_json(json_out):
        _emit_json(res)
        return
    z3p = res["formal_fx_margin_proof"]
    console.print(
        f"[green]FX Hedge ({res['billing_currency']}/{res['cost_currency']})[/green] | "
        f"Invoice={res['invoice_amount_billing_ccy']} {res['billing_currency']} | "
        f"Carry={res['hedge_carry_cost_eur']} EUR | "
        f"Z3={z3p['status']} | RecMinHedge={res['recommended_min_hedge_ratio_pct']}%"
    )


@quote_app.command("evm-postmortem")
def quote_evm_postmortem_cmd(
    rfq_text: str = typer.Option(
        "CS-29 frame static analysis Net 60.",
        "--rfq-text",
        help="Baseline RFQ text.",
    ),
    archetypes: str = typer.Option(
        "Q-DES-02,Q-STR-03,Q-DOA-02",
        "--archetypes",
        help="Comma-separated baseline archetypes.",
    ),
    country: str = typer.Option("EU_DEFAULT", "--country", help="Country rate profile."),
    actuals_file: Path | None = typer.Option(
        None,
        "--actuals-file",
        exists=True,
        help="Optional CSV/XLSX actual hours file.",
    ),
    actual_ecn_iterations: int = typer.Option(
        3,
        "--ecn-actual",
        help="Realized ECN iterations.",
    ),
    project_id: str = typer.Option("POST-001", "--project-id", help="Closed project ID."),
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ID."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Run closed-loop Bid vs Actual ERP EVM post-mortem & seal into Ledger."""
    from evidence_coverage.bid_actual_postmortem import run_bid_actual_evm_postmortem
    from evidence_coverage.composite_dag_quotation import (
        CompositeRotorcraftQuotationSpec,
        run_composite_rotorcraft_quotation,
    )

    from evidence_api.app import _now, open_ledger

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    base_dossier = run_composite_rotorcraft_quotation(
        ledger,
        CompositeRotorcraftQuotationSpec(
            rfq_id=f"BASE-{project_id}",
            rfq_text=rfq_text,
            archetype_ids=tuple(a.strip() for a in archetypes.split(",") if a.strip()),
            country_code=country,
            tenant_id=checked,
            created_at=_now(),
        ),
    )
    res = run_bid_actual_evm_postmortem(
        ledger,
        base_dossier,
        actuals=actuals_file,
        project_id=project_id,
        actual_ecn_iterations=actual_ecn_iterations,
        created_at=_now(),
    )
    if _wants_json(json_out):
        _emit_json(res)
        return
    evm = res["evm_summary"]
    console.print(
        f"[green]EVM Post-Mortem {res['project_id']}[/green] | "
        f"Health={res['health_status']} | CPI={evm['cpi']} | SPI={evm['spi']} | "
        f"VAC={evm['vac_eur']} EUR | Margin={evm['realized_margin_pct']}%"
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
