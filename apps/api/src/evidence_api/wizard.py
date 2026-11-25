"""Zero-CLI-experience interactive assistant (`aeroregu wizard`) & friendly prompts."""

from __future__ import annotations

import json
import os
import secrets
import webbrowser
from pathlib import Path
from typing import Any

import uvicorn
from evidence_calc.errors import AbstainError
from evidence_calc.registry import run_method
from evidence_coverage.gate import evaluate_traceability_gate
from evidence_coverage.status import gap_report, run_coverage_sweep
from evidence_eval.redteam import run_redteam_suite
from evidence_ingest.router import ingest_bytes
from evidence_kernel.__main__ import verify_zip_bundle
from evidence_kernel.gateway import describe_agent_runtime, gateway_from_env
from evidence_kernel.guardrails import check_output_safety, check_text_safety
from evidence_kernel.supervisor import CaseSpec, run_case
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.syntax import Syntax
from rich.table import Table

from evidence_api.app import _now, _validate_tenant, _zip_bytes, evidence_home, open_ledger
from evidence_api.formal_methods import METHOD_DEFAULT_INPUTS, METHOD_FAMILIES
from evidence_api.mcp_server import (
    build_mcp_client_config,
    get_mcp_inventory_counts,
    run_formal_proof_for_method,
)

_DEFAULT_CALC_VALUES: dict[str, dict[str, Any]] = METHOD_DEFAULT_INPUTS

_FAMILY_LABELS: dict[str, str] = {
    "flight_envelope": "Flight Envelope & Mass",
    "structural_sizing": "Structural Sizing & Margins",
    "fasteners_joints": "Fasteners, Lugs & Joints",
    "composites_cmh17": "Composites (CMH-17 / Hashin / Puck / LaRC04 / CLT)",
    "fatigue_fracture": "Fatigue, Crack Growth & Fracture",
    "thin_walled_stability": "Thin-Walled Stability & Crippling",
    "rotorcraft_dynamics": "Rotorcraft Dynamics, Crash & Bird-Strike",
    "plugins": "User Declarative Plugins",
}


def _apply_material_allowable(
    defaults: dict[str, Any],
    mat_id: str,
    console: Console,
) -> dict[str, Any]:
    from evidence_calc.allowables import lookup_allowable

    out = dict(defaults)
    basis = Prompt.ask("Base MMPDS-16 / CMH-17", choices=["A", "B"], default="B", console=console)
    res = lookup_allowable(mat_id, basis=basis, property_name="fty_mpa")
    if "material_id" in res and "allowable_value_mpa" in res:
        fty = str(res["allowable_value_mpa"])
        if "yield_strength_mpa" in out:
            out["yield_strength_mpa"] = fty
        if "compressive_yield_mpa" in out:
            res_fcy = lookup_allowable(mat_id, basis=basis, property_name="fcy_mpa")
            out["compressive_yield_mpa"] = str(res_fcy.get("allowable_value_mpa", fty))
        if "modulus_mpa" in out and res.get("e_gpa"):
            out["modulus_mpa"] = str(int(float(res["e_gpa"]) * 1000))
        if "youngs_modulus_mpa" in out and res.get("e_gpa"):
            out["youngs_modulus_mpa"] = str(int(float(res["e_gpa"]) * 1000))
        console.print(
            f"[green]Material aplicado ({mat_id}, {basis}-Basis):[/green] "
            f"Fty={fty} MPa | catalog={res.get('catalog_sha256', '')[:12]}..."
        )
    return out


def prompt_method_inputs(card: dict[str, Any], console: Console) -> dict[str, Any]:
    """Prompt the user field-by-field with units and safe defaults (zero JSON needed)."""
    method_id = str(card["method_id"])
    defaults = dict(METHOD_DEFAULT_INPUTS.get(method_id, {}))
    units = card.get("input_units") or {}
    required = list(card.get("required") or list((card.get("inputs") or {}).keys()))

    console.print(
        Panel(
            f"[bold cyan]{method_id}[/bold cyan] ({card['method_version']}) "
            f"[{_FAMILY_LABELS.get(METHOD_FAMILIES.get(method_id, 'plugins'), 'Engineering')}]\n"
            f"[dim]{card.get('equation', '')}[/dim]\n"
            "Pulsa [bold]Enter[/bold] para aceptar el valor por defecto en cualquier campo.",
            title="Asistente de Datos de Calculo",
            border_style="cyan",
        )
    )
    if any(
        k in required
        for k in (
            "yield_strength_mpa",
            "compressive_yield_mpa",
            "modulus_mpa",
            "youngs_modulus_mpa",
        )
    ):
        from evidence_calc.allowables import list_materials

        if Confirm.ask(
            "¿Cargar material desde catalogo MMPDS-16 / CMH-17?",
            default=False,
            console=console,
        ):
            mats = list_materials()
            mat_id = Prompt.ask(
                f"Material ({', '.join(mats)})",
                choices=mats,
                default=mats[0],
                console=console,
            )
            defaults = _apply_material_allowable(defaults, mat_id, console)

    collected: dict[str, Any] = {}
    for key in required:
        default_val = defaults.get(key)
        unit = units.get(key)
        unit_label = f" [{unit}]" if unit else ""
        if isinstance(default_val, list):
            raw = Prompt.ask(
                f"  • {key}{unit_label} (separado por comas)",
                default=", ".join(str(x) for x in default_val),
                console=console,
            )
            items = [item.strip() for item in raw.split(",") if item.strip()]
            if key == "unit_operative":
                collected[key] = [x.lower() in {"1", "true", "si", "yes", "t"} for x in items]
            else:
                collected[key] = items
        else:
            val = Prompt.ask(
                f"  • {key}{unit_label}",
                default=str(default_val) if default_val is not None else "",
                console=console,
            )
            collected[key] = val.strip()
    return collected


def _wizard_calc(console: Console) -> None:
    from evidence_calc.registry import list_cards

    raw_cards = list_cards(include_plugins=True)
    family_order = list(_FAMILY_LABELS.keys())
    cards = sorted(
        raw_cards,
        key=lambda c: (
            family_order.index(METHOD_FAMILIES.get(str(c["method_id"]), "plugins")),
            str(c["method_id"]),
        ),
    )
    table = Table(
        title=f"Catalogo Completo ({len(cards)} Metodos Certificados + Plugins)",
        box=box.ROUNDED,
    )
    table.add_column("#", style="bold yellow", justify="right")
    table.add_column("Familia", style="magenta", no_wrap=True)
    table.add_column("Metodo", style="bold cyan", no_wrap=True)
    table.add_column("Descripcion")
    for idx, card in enumerate(cards, start=1):
        mid = str(card["method_id"])
        fam = _FAMILY_LABELS.get(METHOD_FAMILIES.get(mid, "plugins"), "Plugins")
        table.add_row(str(idx), fam, mid, str(card.get("equation", ""))[:60])
    console.print(table)

    choice = IntPrompt.ask("Numero de metodo", default=1, console=console)
    if choice < 1 or choice > len(cards):
        console.print("[yellow]Seleccion fuera de rango.[/yellow]")
        return
    card = cards[choice - 1]
    method_id = str(card["method_id"])
    inputs = prompt_method_inputs(card, console)
    formal = Confirm.ask("¿Verificar tambien con prueba matematica formal Z3 + cvc5?", default=True)
    record_ev = Confirm.ask("¿Guardar resultado en el ledger criptografico?", default=True)

    try:
        ran = run_method(method_id, inputs, include_intervals=True)
    except AbstainError as exc:
        console.print(Panel(f"[yellow]ABSTAIN:[/yellow] {exc.reason}", title="Limite o Unidad"))
        return

    res_table = Table(title=f"Resultados Exactos: {method_id}", box=box.ROUNDED)
    res_table.add_column("Salida", style="bold cyan", no_wrap=True)
    res_table.add_column("Valor Decimal", style="green")
    res_table.add_column("Intervalo Flint")
    ivs = ran.get("exact_intervals") or {}
    for k, val in ran["outputs"].items():
        iv = ivs.get(k)
        iv_txt = f"[{iv['lower']}, {iv['upper']}]" if isinstance(iv, dict) else "-"
        res_table.add_row(k, str(val), iv_txt)
    console.print(res_table)

    if formal:
        fp = run_formal_proof_for_method(method_id, inputs)
        console.print(
            Panel(
                f"Estado: [bold green]{fp.get('status')}[/bold green]\n"
                f"Propiedad: {fp.get('property_name')}\n"
                f"Hash prueba: {fp.get('proof_hash', '-')}",
                title="Prueba Formal Dual (Z3 + cvc5)",
            )
        )
    if record_ev:
        from evidence_kernel.envelope import make_envelope
        from evidence_kernel.orchestrator import record

        ledger = open_ledger("demo")
        env = make_envelope(
            sources=ran["sources"],
            method_version=ran["method_version"],
            inputs=inputs,
            confidence="deterministic",
            result=ran["outputs"],
        )
        ev_hash = record(
            ledger,
            {
                "event_type": "calc",
                "tenant_id": ledger.tenant_id,
                "actor_id": "wizard-user",
                "created_at": _now(),
                "payload": {"method_id": method_id, "inputs": inputs, "outputs": ran["outputs"]},
                "envelope": env,
            },
        )
        console.print(f"[green]Registrado en ledger 'demo':[/green] {ev_hash}")


def _wizard_audit_doc(console: Console) -> None:
    raw = Prompt.ask(
        "Ruta de archivo (PDF/DOCX/MD) o escribe/pega texto normativo (Enter para demo CS-27.301)",
        default="",
        console=console,
    ).strip()
    cleaned = raw.strip('"').strip("'")
    if not cleaned:
        sample = "CS-27.301 Flight, ground, and water design loads distribution."
        blocks = [{"text": sample, "span_start": 0, "span_end": len(sample)}]
    elif Path(cleaned).is_file():
        p = Path(cleaned)
        parsed = ingest_bytes(p.read_bytes(), p.name)
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
        console.print(
            f"[cyan]Documento ingestado:[/cyan] {len(blocks)} bloques, "
            f"{len(parsed.get('requirements', []))} requisitos detectados."
        )
    else:
        blocks = [{"text": cleaned, "span_start": 0, "span_end": len(cleaned)}]

    ledger = open_ledger("demo")
    gw = gateway_from_env("happy", constrained=True, runtime_mode="auto")
    out = run_case(
        ledger,
        gw,
        CaseSpec(
            tenant_id="demo",
            actor_id="wizard-user",
            created_at=_now(),
            blocks=blocks,
            record_requirements=True,
        ),
    )
    conf = out.envelope.get("confidence", "abstain")
    console.print(
        Panel(
            f"Confianza: [bold]{conf}[/bold]\n"
            f"Citas verificadas: {len(out.citations)}\n"
            f"Eventos registrados: {len(out.event_hashes)}\n\n"
            f"{out.paragraph or ''}",
            title="Resultado de Auditoria Supervisada",
            border_style="green" if conf != "abstain" else "yellow",
        )
    )


def _wizard_coverage(console: Console) -> None:
    tenant = _validate_tenant(Prompt.ask("Tenant", default="demo", console=console)) or "demo"
    ledger = open_ledger(tenant)
    events = ledger.events()
    gaps = gap_report(events)
    gate = evaluate_traceability_gate(events, chain_verified=ledger.verify())
    console.print(
        Panel(
            f"Total celdas: {gaps.get('total_cells', 0)}\n"
            f"Cubiertas: [green]{gaps.get('covered', 0)}[/green] | "
            f"Gaps pendientes: [yellow]{gaps.get('gap', 0)}[/yellow] | "
            f"Gate listo: {gate.get('ready')}",
            title=f"Matriz de Cobertura ({tenant})",
        )
    )
    if Confirm.ask("¿Ejecutar barrido determinista de 15 celdas ahora?", default=True):
        summary = run_coverage_sweep(
            ledger, actor_id="wizard-user", created_at=_now(), target_status="gap", limit=15
        )
        console.print(f"[green]Barrido completado:[/green] {json.dumps(summary)}")


def _wizard_bundle(console: Console) -> None:
    tenant = _validate_tenant(Prompt.ask("Tenant", default="demo", console=console)) or "demo"
    home_dir = evidence_home()
    default_zip = home_dir / f"{tenant}_audit_bundle.zip"
    target_str = Prompt.ask("Archivo .zip destino", default=str(default_zip), console=console)
    target = Path(target_str.strip('"')).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    events = open_ledger(tenant).events()
    target.write_bytes(_zip_bytes(events))
    ok, report = verify_zip_bundle(target)
    console.print(
        Panel(
            f"Archivo: {target}\n"
            f"Verificado Off-Line: [bold green]{ok}[/bold green]\n"
            f"Firma DSSE Ed25519: {report.get('dsse_signature_ok')}\n"
            f"Merkle Root: {report.get('merkle_root')}",
            title="Expediente Criptografico DSSE",
        )
    )


def _wizard_security(console: Console) -> None:
    mode = Prompt.ask(
        "Elige: [1] Escanear un texto/prompt  [2] Auditoria Red-Team completa (46 sondas)",
        choices=["1", "2"],
        default="2",
        console=console,
    )
    if mode == "1":
        txt = Prompt.ask("Texto o prompt a analizar", console=console)
        in_r = check_text_safety(txt)
        out_r = check_output_safety(txt)
        safe = in_r is None and out_r is None
        badge = "[green]SEGURO[/green]" if safe else f"[red]BLOQUEADO ({in_r or out_r})[/red]"
        console.print(f"Resultado: {badge}")
        return
    report = run_redteam_suite()
    console.print(
        Panel(
            f"Ataques bloqueados: {report['attacks_blocked']}/{report['attacks_total']} "
            f"({report['block_rate'] * 100:.2f}%)\n"
            "Secretos / PII filtrados: "
            f"{report['secret_pii_leaked']}/{report['secret_pii_probes']}\n"
            f"Falsos positivos benignos: {report['false_positives']}/{report['benign_total']}",
            title="Red-Team Security Suite",
            border_style="green" if report["meets_enterprise_target"] else "red",
        )
    )


def _wizard_mcp(console: Console) -> None:
    counts = get_mcp_inventory_counts()
    console.print(
        Panel(
            f"Servidor MCP: [bold cyan]aeroregu-evidence-layer[/bold cyan]\n"
            f"Tools IA: [bold]{counts['tools']}[/bold] | "
            f"Resources: [bold]{counts['resources']}[/bold] | "
            f"Prompts: [bold]{counts['prompts']}[/bold] | "
            f"Pruebas SMT: [bold]{counts['formal_methods']}[/bold]\n"
            "Compatible con Antigravity IDE, Claude Desktop, Cursor y VS Code.",
            title="Asistente de Conexion AI / MCP",
            border_style="magenta",
        )
    )
    client = Prompt.ask(
        "¿Para que cliente IA quieres la configuracion?",
        choices=["antigravity", "claude", "cursor", "vscode", "generic"],
        default="antigravity",
        console=console,
    )
    cfg = build_mcp_client_config(client=client)
    rendered = json.dumps(cfg, indent=2)
    console.print(Syntax(rendered, "json", theme="ansi_dark", word_wrap=True))
    if Confirm.ask("¿Guardar este JSON en un archivo ahora?", default=False):
        out_path = Path(
            Prompt.ask("Ruta del archivo", default=f"{client}_mcp.json", console=console)
        ).resolve()
        out_path.write_text(rendered + "\n", encoding="utf-8")
        console.print(f"[green]Guardado en:[/green] {out_path}")


def _wizard_web_ui(console: Console, port: int = 8000) -> None:
    if len(os.environ.get("EVIDENCE_SESSION_SECRET", "")) < 24:
        os.environ["EVIDENCE_SESSION_SECRET"] = secrets.token_urlsafe(32)
    url = f"http://127.0.0.1:{port}"
    console.print(f"[bold green]Abriendo Web UI + API + HTTP MCP en {url} ...[/bold green]")
    webbrowser.open(url)
    uvicorn.run("evidence_api.app:app", host="127.0.0.1", port=port)


def _wizard_quotation(console: Console) -> None:
    """Interactive rotorcraft multi-archetype quotation & CCN helper."""
    from evidence_coverage.composite_dag_quotation import (
        CompositeRotorcraftQuotationSpec,
        run_composite_rotorcraft_quotation,
    )
    from evidence_coverage.quotation_change_order import compute_quotation_change_order

    from evidence_api.app import open_ledger

    rfq_text = Prompt.ask(
        "Alcance RFQ del helicoptero",
        default="CS-29 HEMS rescue hoist composite frame static, F&DT & STC. Net 60.",
        console=console,
    )
    country = Prompt.ask(
        "Perfil de pais (EU_DEFAULT, FR, DE, ES, IT, UK, US, PL, IN)",
        default="ES",
        console=console,
    )
    units = IntPrompt.ask(
        "Unidades / variantes del lote (Wright-Crawford)", default=2, console=console
    )
    ledger = open_ledger("demo")
    spec = CompositeRotorcraftQuotationSpec(
        rfq_id="WIZ-RFQ-001",
        rfq_text=rfq_text,
        archetype_ids=("Q-DES-02", "Q-STR-01", "Q-STR-03", "Q-FDT-01", "Q-DOA-02"),
        country_code=country,
        unit_count=max(1, units),
    )
    dossier = run_composite_rotorcraft_quotation(ledger, spec)
    console.print(Panel(dossier["markdown_report"], title="Cotizacion Compuesta DAG + Z3 SMT"))
    if Confirm.ask(
        "Simular Change Order (CCN +1 unidad y ensayo rig Q-TST-01)?",
        default=False,
        console=console,
    ):
        rev = CompositeRotorcraftQuotationSpec(
            rfq_id="WIZ-RFQ-002",
            rfq_text=rfq_text + " Include test rig Q-TST-01 correlation.",
            archetype_ids=("Q-DES-02", "Q-STR-01", "Q-STR-03", "Q-FDT-01", "Q-DOA-02", "Q-TST-01"),
            country_code=country,
            unit_count=max(1, units) + 1,
        )
        ccn = compute_quotation_change_order(
            ledger, dossier, rev, cr_id="WIZ-CCN-001", change_reason="Interactive CCN test"
        )
        console.print(
            Panel(
                json.dumps(
                    {
                        "cr_id": ccn["cr_id"],
                        "decision_status": ccn["decision_status"],
                        "financial_delta": ccn.get("financial_delta"),
                    },
                    indent=2,
                ),
                title="Delta Change Order (CCN)",
            )
        )


def run_interactive_hub(console: Console, quickstart_cb: Any) -> None:
    """Zero-CLI interactive guided assistant menu."""
    counts = get_mcp_inventory_counts()
    menu = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    menu.add_column("Opcion", justify="right", style="bold yellow", no_wrap=True)
    menu.add_column("Accion", style="bold white")
    menu.add_column("Para que sirve", style="dim")
    rows = [
        ("1", "Inicio Rapido (Demo Guiada)", "Prueba todo en 1 clic y genera ZIP firmado"),
        (
            "2",
            "Calculadora Ingenieria",
            f"Formulas ({counts['formal_methods']} metodos por familia + Z3/cvc5 + MMPDS)",
        ),
        ("3", "Auditar PDF / Norma", "Extrae citas CS-27/CS-29 con pagina y bbox"),
        ("4", "Cobertura de Vuelo", "Ver gaps, gate de trazabilidad y hacer sweep"),
        ("5", "Exportar & Verificar ZIP", "Genera y valida firma DSSE Ed25519 off-line"),
        ("6", "Seguridad & Red-Team", "Detecta prompt injection, secretos y PII"),
        (
            "7",
            "Conectar Agente IA (MCP)",
            f"Configura {counts['tools']} tools para Antigravity/Claude/Cursor",
        ),
        ("8", "Abrir Web UI (Navegador)", "Interfaz visual web en http://127.0.0.1:8000"),
        ("9", "Diagnostico (Doctor)", "Comprueba Python, Z3, cvc5, Flint y claves"),
        (
            "10",
            "Cotizador Helicopteros & Change Orders",
            "DAG multi-arquetipo, cash-flow, CCN delta y Z3 NPV",
        ),
        ("0", "Salir", "Cerrar asistente"),
    ]
    for opt, act, desc in rows:
        menu.add_row(opt, act, desc)

    while True:
        console.print(
            Panel(
                "[bold]Bienvenido a aeroregu[/bold] — "
                "Evidence Layer para Ingenieria y Agentes IA.\n"
                "[dim]No necesitas recordar comandos: elige un numero y te guio paso a paso.\n"
                "Aviso: herramienta de apoyo al revisor humano; no determina cumplimiento.[/dim]",
                title="Asistente Interactivo",
                border_style="cyan",
            )
        )
        console.print(menu)
        try:
            choice = Prompt.ask(
                "Elige una opcion",
                choices=["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
                default="1",
                console=console,
            )
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Hasta luego.[/dim]")
            return

        if choice == "0":
            console.print("[dim]Hasta luego.[/dim]")
            return
        if choice == "1":
            quickstart_cb()
        elif choice == "2":
            _wizard_calc(console)
        elif choice == "3":
            _wizard_audit_doc(console)
        elif choice == "4":
            _wizard_coverage(console)
        elif choice == "5":
            _wizard_bundle(console)
        elif choice == "6":
            _wizard_security(console)
        elif choice == "7":
            _wizard_mcp(console)
        elif choice == "8":
            _wizard_web_ui(console)
            return
        elif choice == "9":
            rt = describe_agent_runtime()
            console.print(Panel(json.dumps(rt, indent=2), title="Estado Runtime & MCP"))
        elif choice == "10":
            _wizard_quotation(console)

        if not Confirm.ask("\n¿Quieres realizar otra accion?", default=True, console=console):
            return
