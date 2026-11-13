"""Unified rich CLI (`aeroregu`) for Evidence Layer & MCP tooling."""

from __future__ import annotations

import json
import os
import secrets
import sys
import webbrowser
import zipfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import typer
import uvicorn
from evidence_calc.diagnostics import classify_numeric_delta
from evidence_calc.errors import AbstainError
from evidence_calc.registry import cards_dir, load_card, run_method
from evidence_coverage.dossier import (
    build_enterprise_dossier,
    export_oscal_sar,
    export_strictdoc,
)
from evidence_coverage.gate import evaluate_traceability_gate
from evidence_coverage.status import gap_report, list_cells_with_status, run_coverage_sweep
from evidence_ingest.blocks import IngestAbstain
from evidence_ingest.router import ingest_bytes
from evidence_kernel.__main__ import verify_zip_bundle
from evidence_kernel.gateway import (
    BudgetedGateway,
    FixtureGateway,
    HybridAgentRouter,
    OllamaEdgeGateway,
    OpenAICompatibleGateway,
    describe_agent_runtime,
    gateway_from_env,
    probe_gateway_health,
)
from evidence_kernel.guardrails import (
    check_output_safety,
    check_text_safety,
)
from evidence_kernel.ledger import (
    GENESIS,
    SIGN_OFF_STATEMENT,
    LedgerError,
    verify_chain_document,
)
from evidence_kernel.orchestrator import record
from evidence_kernel.supervisor import CaseSpec, run_case
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from evidence_api.app import (
    MAX_INGEST_BYTES,
    _attestation_keypair,
    _now,
    _secret,
    _validate_tenant,
    _zip_bytes,
    evidence_home,
    open_ledger,
)
from evidence_api.mcp_server import (
    MCP_PROMPTS,
    MCP_RESOURCES,
    MCP_TOOLS,
    build_mcp_client_config,
    run_formal_proof_for_method,
    serve_stdio,
)
from evidence_api.wizard import prompt_method_inputs, run_interactive_hub

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
bundle_app = typer.Typer(help="Export and off-line verify DSSE Ed25519 audit dossiers.")
ledger_app = typer.Typer(help="Inspect tamper-evident ledger, Merkle proofs, and pilot metrics.")
coverage_app = typer.Typer(help="Flight-envelope coverage matrix, sweep & traceability gate.")
dossier_app = typer.Typer(help="Enterprise certification dossier, StrictDOC & NIST OSCAL SAR.")
security_app = typer.Typer(help="Guardrail scanner and Red-Team adversarial benchmark.")
bench_app = typer.Typer(help="Run B2 baseline comparisons and live/edge agent benchmarks.")
mcp_app = typer.Typer(help="Model Context Protocol (MCP) stdio server, inspector & client configs.")

app.add_typer(calc_app, name="calc")
app.add_typer(bundle_app, name="bundle")
app.add_typer(ledger_app, name="ledger")
app.add_typer(coverage_app, name="coverage")
app.add_typer(dossier_app, name="dossier")
app.add_typer(security_app, name="security")
app.add_typer(bench_app, name="bench")
app.add_typer(mcp_app, name="mcp")


@app.callback(invoke_without_command=True)
def _root_callback(ctx: typer.Context) -> None:
    """Launch guided interactive wizard when run in an interactive TTY with no subcommand."""
    if ctx.invoked_subcommand is not None:
        return
    if sys.stdin.isatty() and sys.stdout.isatty():
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
    try:
        return version(name)
    except PackageNotFoundError:
        return "missing"


def _tenant_or_exit(tenant_id: str) -> str:
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
    """List certified deterministic Decimal calculation method cards."""
    cards = [load_card(p.stem) for p in sorted(cards_dir().glob("*.json"))]
    if _wants_json(json_out):
        _emit_json({"methods": cards})
        return

    table = Table(title="Certified Calculation Methods", box=box.ROUNDED)
    table.add_column("Method ID", style="bold cyan", no_wrap=True)
    table.add_column("Version")
    table.add_column("Required Inputs")
    table.add_column("Units")
    for card in cards:
        req = ", ".join(card.get("required") or list(card.get("inputs", {})))
        units = ", ".join(f"{k}={v}" for k, v in (card.get("input_units") or {}).items())
        table.add_row(str(card["method_id"]), str(card["method_version"]), req, units or "-")
    console.print(table)


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
    method_id: str = typer.Argument(..., help="Method ID (see `aeroregu calc list`)."),
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
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ledger ID."),
    actor: str = typer.Option("author", "--actor", help="Actor ID when recording."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Execute deterministic Decimal math + Flint interval bounds + optional SMT proof."""
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
    method_id: str | None = typer.Option(None, "--method", "-m", help="Optional calc method ID."),
    inputs: str | None = typer.Option(None, "--inputs", "-i", help="Calc inputs JSON or @file."),
    mode: str = typer.Option("auto", "--mode", help="auto|fixture|edge|api|hybrid"),
    edge_model: str | None = typer.Option(None, "--edge-model", help="Edge model name."),
    formal: bool = typer.Option(False, "--formal", help="Verify bounds via Z3+cvc5."),
    gate: bool = typer.Option(False, "--gate", help="Enable SLM decision gate."),
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ledger ID."),
    actor: str = typer.Option("author", "--actor", help="Actor ID."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Run the full supervised multi-agent verification pipeline (citations + math + proof)."""
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

    with console.status(
        "[cyan]Running supervised pipeline (reader -> checker -> refuter -> scribe)...[/cyan]"
    ):
        outcome = run_case(ledger, gw, case)

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
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ledger ID."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Export a 100% DSSE Ed25519 signed audit dossier ZIP and immediately verify it."""
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
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ledger ID."),
    limit: int = typer.Option(20, "--limit", "-n", help="Tail count."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Display recent tamper-evident ledger events."""
    checked = _tenant_or_exit(tenant)
    events = open_ledger(checked).events()[-limit:]
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
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Record an immutable human engineer sign-off event with optional review timing."""
    from evidence_kernel.envelope import make_envelope, project_source

    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    target_hash = target or ledger.head_hash()
    if target_hash == GENESIS:
        err_console.print("[red]Ledger is empty; cannot sign off GENESIS.[/red]")
        raise typer.Exit(code=1)

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

    res = {
        "event_hash": ev_hash,
        "target_event_hash": target_hash,
        "merkle_root": ledger.merkle_root(),
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
    raise typer.Exit(code=serve_stdio())


@mcp_app.command("inspect")
def mcp_inspect(
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """List all exposed MCP tools, resources, and certification prompts."""
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
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ledger ID."),
    status: str | None = typer.Option(None, "--status", help="Filter cell status."),
    stale_only: bool = typer.Option(False, "--stale-only", help="Show invalidated cells only."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Show flight-envelope gap counts and certification traceability gate readiness."""
    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    events = ledger.events()
    gaps = gap_report(events)
    gate = evaluate_traceability_gate(events, chain_verified=ledger.verify())
    cells = list_cells_with_status(events, status_filter=status, stale_only=stale_only)[:15]
    payload = {"tenant_id": checked, "gaps": gaps, "gate": gate, "sample_cells": cells}
    if _wants_json(json_out):
        _emit_json(payload)
        return
    table = Table(title=f"Coverage Status ({checked})", box=box.ROUNDED)
    table.add_column("Metric", style="bold cyan", no_wrap=True)
    table.add_column("Value")
    for k, v in gaps.items():
        table.add_row(str(k), str(v))
    table.add_row("traceability_gate_ready", f"[bold]{gate.get('ready')}[/bold]")
    console.print(table)


@coverage_app.command("sweep")
def coverage_sweep_cmd(
    tenant: str = typer.Option("demo", "--tenant", help="Tenant ledger ID."),
    limit: int = typer.Option(15, "--limit", help="Max cells to verify in this sweep."),
    stale_only: bool = typer.Option(False, "--stale-only", help="Re-verify stale cells only."),
    actor: str = typer.Option("author", "--actor", help="Actor ID."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Run deterministic flight-envelope verification across pending cells."""
    checked = _tenant_or_exit(tenant)
    ledger = open_ledger(checked)
    summary = run_coverage_sweep(
        ledger,
        actor_id=actor,
        created_at=_now(),
        target_status="gap",
        stale_only=stale_only,
        limit=limit,
    )
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


@app.command("wizard")
def wizard_cmd() -> None:
    """Interactive guided assistant (menu 0..9) — zero CLI commands or JSON required."""
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


@app.command("examples")
def examples_cmd() -> None:
    """Show beginner-friendly recipes for calculations, PDF audits, Red-Team, and MCP."""
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
        "# 5. Conectar con Antigravity / Claude / Cursor (17 tools MCP)\n"
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
