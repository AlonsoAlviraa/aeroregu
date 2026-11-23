"""Deterministic Clause-by-Clause RFQ Contractual Auditor & Poison-Clause Detector.

Classifies every technical, commercial, quality/DOA, and legal/IP clause into:
- SUPPORTED
- PARTIALLY_SUPPORTED_WITH_ASSUMPTION
- CHANGE_ORDER_REQUIRED
- REJECT_OR_ABSTAIN

Detects 6 high-risk aerospace subcontracting poison clauses (EN + ES bilingual):
1. UNCAPPED_LIQUIDATED_DAMAGES
2. UNLIMITED_FREE_REDESIGN
3. BACKGROUND_IP_ASSIGNMENT
4. OPEN_ENDED_AUTHORITY_PAYMENT_GATE
5. EXCESSIVE_WARRANTY_RETENTION
6. CVE_INDEPENDENCE_WAIVER

Advisory decision-support only; does NOT constitute legal counsel or compliance sign-off.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

import pymupdf

_ZERO_WIDTH_CHARS = frozenset({"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff", "\u00ad"})
_HOMOGLYPH_MAP = str.maketrans(
    {
        "\u0430": "a",  # Cyrillic a
        "\u0435": "e",  # Cyrillic ie
        "\u043e": "o",  # Cyrillic o
        "\u0440": "p",  # Cyrillic er
        "\u0441": "c",  # Cyrillic es
        "\u0445": "x",  # Cyrillic ha
        "\u0456": "i",  # Cyrillic/Ukrainian i
        "\u0443": "y",  # Cyrillic u
        "\u043a": "k",  # Cyrillic ka
        "\u043c": "m",  # Cyrillic em
        "\u0442": "t",  # Cyrillic te
        "\u0432": "b",  # Cyrillic ve
        "\u043d": "h",  # Cyrillic en
        "\u0410": "A",
        "\u0415": "E",
        "\u041e": "O",
        "\u0420": "P",
        "\u0421": "C",
        "\u0425": "X",
        "\u0406": "I",
        "\u0423": "Y",
        "\u041a": "K",
        "\u041c": "M",
        "\u0422": "T",
        "\u0412": "B",
        "\u041d": "H",
        "\u03b1": "a",  # Greek alpha
        "\u03b2": "b",  # Greek beta
        "\u03b5": "e",  # Greek epsilon
        "\u03b9": "i",  # Greek iota
        "\u03ba": "k",  # Greek kappa
        "\u03bc": "m",  # Greek mu
        "\u03bd": "v",  # Greek nu
        "\u03bf": "o",  # Greek omicron
        "\u03c1": "p",  # Greek rho
        "\u03c4": "t",  # Greek tau
        "\u03c5": "u",  # Greek upsilon
        "\u03c7": "x",  # Greek chi
        "\u0391": "A",
        "\u0392": "B",
        "\u0395": "E",
        "\u0396": "Z",
        "\u0397": "H",
        "\u0399": "I",
        "\u039a": "K",
        "\u039c": "M",
        "\u039d": "N",
        "\u039f": "O",
        "\u03a1": "P",
        "\u03a4": "T",
        "\u03a7": "X",
        "\u03a5": "Y",
    }
)


def _normalize_for_audit(text: str) -> tuple[str, bool]:
    """Strip invisible/zero-width chars and fold Cyrillic/Greek homoglyphs before auditing."""
    raw = str(text or "").replace("\x00", "")
    kept: list[str] = []
    stripped_invisible = False
    for ch in raw:
        if ch in _ZERO_WIDTH_CHARS or unicodedata.category(ch) == "Cf":
            stripped_invisible = True
            continue
        kept.append(ch)
    cleaned = "".join(kept)
    nfkc = unicodedata.normalize("NFKC", cleaned)
    folded = nfkc.translate(_HOMOGLYPH_MAP)
    had_homoglyph_or_compat = folded != cleaned
    norm_ws = " ".join(folded.split())
    return norm_ws, bool(stripped_invisible or had_homoglyph_or_compat)


CLAUSE_STATUSES: tuple[str, ...] = (
    "SUPPORTED",
    "PARTIALLY_SUPPORTED_WITH_ASSUMPTION",
    "CHANGE_ORDER_REQUIRED",
    "REJECT_OR_ABSTAIN",
)

_POISON_RULES: tuple[dict[str, Any], ...] = (
    {
        "poison_id": "UNCAPPED_LIQUIDATED_DAMAGES",
        "category": "LEGAL_IP",
        "severity": "CRITICAL",
        "default_status": "REJECT_OR_ABSTAIN",
        "pattern": re.compile(
            r"(?:uncapped\s+(?:liquidated\s+damages|ld|penalt)|"
            r"(?:liquidated\s+damages|ld|penalties|liability)\s+"
            r"(?:with\s+no|without(?:\s+any|\s+a)?|sin)\s+(?:cap|tope|l[ií]mite)|"
            r"unlimited\s+(?:liability|liquidated\s+damages|penalt|indemnity)|"
            r"da(?:ñ|n)os\s+liquidados\s+sin\s+(?:tope|l[ií]mite)|"
            r"penalizaci(?:[oó]n|ones)\s+sin\s+(?:tope|l[ií]mite)|"
            r"responsabilidad\s+ilimitada)",
            re.IGNORECASE,
        ),
        "title": "Uncapped Liquidated Damages / Unlimited Liability",
        "redline": (
            "Cap aggregate Liquidated Damages at 10% of Fixed-Price tranche and total liability "
            "at 100% of contract fees paid."
        ),
        "linked_assumption": "ASM-LEG-04",
    },
    {
        "poison_id": "UNLIMITED_FREE_REDESIGN",
        "category": "TECHNICAL",
        "severity": "HIGH",
        "default_status": "CHANGE_ORDER_REQUIRED",
        "pattern": re.compile(
            r"(?:unlimited\s+(?:redesign|design\s+iterations?|rework|loops?)|"
            r"all\s+redesigns?\s+included\s+(?:in|at)\s+(?:fixed\s+price|no\s+extra\s+cost)|"
            r"redi(?:s|se)(?:ñ|n)o\s+ilimitado|"
            r"iteraciones\s+ilimitadas\s+(?:incluidas|sin\s+coste)|"
            r"sin\s+coste\s+adicional\s+por\s+redi(?:s|se)(?:ñ|n)o)",
            re.IGNORECASE,
        ),
        "title": "Unlimited Free Redesign / Unbounded Iteration Loops",
        "redline": (
            "Limit fixed-price baseline to 2 CAD-stress loops (ASM-SCH-01); additional loops "
            "or negative-margin redesign billed via Change Order."
        ),
        "linked_assumption": "ASM-TS-02",
    },
    {
        "poison_id": "BACKGROUND_IP_ASSIGNMENT",
        "category": "LEGAL_IP",
        "severity": "CRITICAL",
        "default_status": "REJECT_OR_ABSTAIN",
        "pattern": re.compile(
            r"(?:(?:assigns?|transfers?|surrenders?|irrevocable\s+ownership)\s+(?:all\s+)?background\s+ip|"
            r"background\s+(?:intellectual\s+property|ip|tools|scripts)\s+(?:shall\s+)?(?:transfer|belong|vest)|"
            r"cesi[oó]n\s+(?:total\s+)?de\s+(?:background\s+ip|propiedad\s+intelectual\s+previa)|"
            r"transferencia\s+de\s+c[oó]digo\s+fuente\s+propio)",
            re.IGNORECASE,
        ),
        "title": "Forced Assignment of Contractor Background IP",
        "redline": (
            "Deliverable Foreground CAD/FEM/Stress Reports transfer upon final payment; "
            "Contractor Background IP, scripts, and solvers remain exclusive property (ASM-LEG-02)."
        ),
        "linked_assumption": "ASM-LEG-02",
    },
    {
        "poison_id": "OPEN_ENDED_AUTHORITY_PAYMENT_GATE",
        "category": "COMMERCIAL",
        "severity": "HIGH",
        "default_status": "CHANGE_ORDER_REQUIRED",
        "pattern": re.compile(
            r"(?:payment\s+(?:strictly\s+)?(?:contingent|gated|conditioned)\s+(?:solely\s+)?on\s+"
            r"(?:easa|faa|authority|tc|stc)\s+approval\s*(?:with\s+no|without)\s+"
            r"(?:long[- ]?stop|date|cap|deadline)|"
            r"pago\s+(?:condicionado|atado)\s+a\s+aprobaci[oó]n\s+de\s+(?:easa|faa|autoridad)"
            r"\s+sin\s+fecha\s+tope|"
            r"authority\s+approval\s+without\s+long[- ]?stop)",
            re.IGNORECASE,
        ),
        "title": "Open-Ended Payment Gate Tied to Authority Approval Without Long-Stop Date",
        "redline": (
            "Decouple final milestone from external Authority calendar; trigger payment at CVE "
            "dossier sign-off or 60-day long-stop date post-submission (ASM-COM-04)."
        ),
        "linked_assumption": "ASM-COM-04",
    },
    {
        "poison_id": "EXCESSIVE_WARRANTY_RETENTION",
        "category": "COMMERCIAL",
        "severity": "HIGH",
        "default_status": "CHANGE_ORDER_REQUIRED",
        "pattern": re.compile(
            r"(?:(?:warranty|performance|guarantee)\s+(?:retention|holdback|bond)\s*(?:of|:)?\s*"
            r"(?:1[5-9]|[2-9]\d)\s*%|"
            r"retenci[oó]n\s+de\s+garant[ií]a\s*(?:del|de|:)?\s*(?:1[5-9]|[2-9]\d)\s*%|"
            r"(?:warranty|garant[ií]a)\s+(?:period\s+of\s+|de\s+)?(?:3[0-9]|4[0-9]|[5-9]\d)\s+months?|"
            r"excessive\s+warranty\s+retention)",
            re.IGNORECASE,
        ),
        "title": "Excessive Warranty Holdback (>10%) or Extended Duration (>24 Months)",
        "redline": (
            "Cap warranty retention at <=5% (or bank guarantee) expiring 12 months from "
            "dossier acceptance, strictly limited to defects in workmanship."
        ),
        "linked_assumption": "ASM-COM-03",
    },
    {
        "poison_id": "CVE_INDEPENDENCE_WAIVER",
        "category": "QUALITY_DOA",
        "severity": "CRITICAL",
        "default_status": "REJECT_OR_ABSTAIN",
        "pattern": re.compile(
            r"(?:waives?\s+cve|skips?\s+cve|omits?\s+cve|no\s+cve\s+review|"
            r"self-certify\s+without\s+cve|exenci[oó]n\s+de\s+cve|sin\s+(?:revisi[oó]n\s+)?cve|"
            r"waiver\s+of\s+part\s*21\s*cve)",
            re.IGNORECASE,
        ),
        "title": "Waiver of Independent Part 21.A.239(b) CVE Verification",
        "redline": (
            "REJECT: Independent CVE review is non-waivable under EASA Part 21J.A.239(b) and "
            "ASM-DOA-01 / ASM-RK-02."
        ),
        "linked_assumption": "ASM-RK-02",
    },
)

_PARTIAL_PATTERNS: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (
        re.compile(
            r"(?:preliminary\s+loads|incomplete\s+idp|loads\s+tbd|idp\s+to\s+follow|"
            r"cargas\s+preliminares|b-basis\s+allowables|unfrozen\s+dmu)",
            re.IGNORECASE,
        ),
        "TECHNICAL",
        "Requires Assumption ASM-RL-01 / ASM-IDP-01: loads & DMU must freeze at KO+5 days.",
        "ASM-RL-01",
    ),
    (
        re.compile(
            r"(?:net\s*90|net\s*120|90\s*days?\s+payment|120\s*days?\s+payment|"
            r"pago\s+a\s+90\s+d[ií]as)",
            re.IGNORECASE,
        ),
        "COMMERCIAL",
        "Extended Net 90+ payment terms accepted only with working-capital financing uplift.",
        "ASM-COM-04",
    ),
    (
        re.compile(
            r"(?:itar|ear|usml|export[- ]controlled|2021/821|dual[- ]use)",
            re.IGNORECASE,
        ),
        "LEGAL_IP",
        "Requires segregated sovereign data enclave & EU/ITAR export screening (ASM-LEG-01).",
        "ASM-LEG-01",
    ),
)

_CHANGE_ORDER_PATTERNS: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (
        re.compile(
            r"(?:dual\s+authority|easa\s+and\s+faa|bilateral\s+validation|"
            r"witness\s+test|on-site\s+gvt|flight\s+test\s+range\s+included|"
            r"24/7\s+aog|weekend\s+turnaround)",
            re.IGNORECASE,
        ),
        "QUALITY_DOA",
        "Scope beyond baseline single-authority / 8h calendar requires Change Order pricing.",
        "ASM-DOA-05",
    ),
)


def _categorize_clause(text: str) -> str:
    low = text.lower()
    if any(
        k in low for k in ("ip", "liability", "damages", "itar", "ear", "law", "legal", "export")
    ):
        return "LEGAL_IP"
    if any(
        k in low
        for k in (
            "payment",
            "net ",
            "warranty",
            "retention",
            "price",
            "currency",
            "milestone",
            "euro",
            "eur",
        )
    ):
        return "COMMERCIAL"
    if any(
        k in low
        for k in (
            "part 21",
            "cve",
            "as9100",
            "en9100",
            "easa",
            "faa",
            "doa",
            "cs-27",
            "cs-29",
            "quality",
        )
    ):
        return "QUALITY_DOA"
    return "TECHNICAL"


def _extract_clauses_from_inputs(
    *,
    rfq_text: str,
    clauses: list[dict[str, Any]] | None,
    pdf_bytes: bytes | None,
    filename: str,
) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    if clauses:
        for idx, item in enumerate(clauses, start=1):
            if isinstance(item, dict):
                txt = " ".join(str(item.get("text") or "").split())
                if not txt:
                    continue
                extracted.append(
                    {
                        "clause_id": str(item.get("clause_id") or f"CL-{idx:03d}"),
                        "text": txt,
                        "page_no": item.get("page_no"),
                        "bbox": item.get("bbox"),
                        "source_file": str(item.get("source_file") or filename),
                    }
                )
        if extracted:
            return extracted

    if pdf_bytes:
        pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            seq = 0
            for p_idx in range(len(doc)):
                page = doc.load_page(p_idx)
                for blk in page.get_text("blocks") or []:
                    if len(blk) < 5:
                        continue
                    txt = " ".join(str(blk[4] or "").split())
                    if len(txt) < 10:
                        continue
                    seq += 1
                    extracted.append(
                        {
                            "clause_id": f"CL-{seq:03d}",
                            "text": txt,
                            "page_no": p_idx + 1,
                            "bbox": [round(float(blk[i]), 2) for i in range(4)],
                            "source_file": filename,
                            "source_hash": pdf_hash,
                        }
                    )
        if extracted:
            return extracted

    # Split plain RFQ text cleanly into clauses across lines, semicolons, or numbered prefixes
    raw_lines = [ln.strip() for ln in re.split(r"[\r\n]+|(?<=[.;])\s+", rfq_text) if ln.strip()]
    for idx, txt in enumerate(raw_lines, start=1):
        extracted.append(
            {
                "clause_id": f"CL-{idx:03d}",
                "text": txt,
                "page_no": None,
                "bbox": None,
                "source_file": filename,
            }
        )
    return extracted


def audit_rfq_contract_clauses(
    rfq_text: str = "",
    *,
    clauses: list[dict[str, Any]] | None = None,
    pdf_bytes: bytes | None = None,
    filename: str = "rfq.txt",
) -> dict[str, Any]:
    """Perform deterministic clause-by-clause contractual audit and poison-clause detection."""
    parsed_clauses = _extract_clauses_from_inputs(
        rfq_text=rfq_text,
        clauses=clauses,
        pdf_bytes=pdf_bytes,
        filename=filename,
    )

    matrix: list[dict[str, Any]] = []
    poison_detected: list[dict[str, Any]] = []
    recommended_redlines: list[dict[str, str]] = []
    status_counts: dict[str, int] = {s: 0 for s in CLAUSE_STATUSES}
    obfuscated_count = 0

    for cl in parsed_clauses:
        raw_txt = cl["text"].replace("\x00", "")
        txt, obfuscated = _normalize_for_audit(raw_txt)
        if obfuscated:
            obfuscated_count += 1
        matched_poisons: list[dict[str, Any]] = []
        for rule in _POISON_RULES:
            if rule["pattern"].search(txt):
                matched_poisons.append(rule)

        if matched_poisons:
            # Highest severity wins status if multiple poison hits occur in one clause
            statuses = [r["default_status"] for r in matched_poisons]
            status = (
                "REJECT_OR_ABSTAIN" if "REJECT_OR_ABSTAIN" in statuses else "CHANGE_ORDER_REQUIRED"
            )
            cat = matched_poisons[0]["category"]
            rationale = "; ".join(r["title"] for r in matched_poisons)
            redline = " | ".join(r["redline"] for r in matched_poisons)
            linked_asm = matched_poisons[0]["linked_assumption"]
            for rule in matched_poisons:
                p_rec = {
                    "clause_id": cl["clause_id"],
                    "poison_id": rule["poison_id"],
                    "severity": rule["severity"],
                    "status": rule["default_status"],
                    "title": rule["title"],
                    "excerpt": txt[:200],
                    "redline": rule["redline"],
                    "obfuscation_detected": obfuscated,
                    "page_no": cl.get("page_no"),
                    "bbox": cl.get("bbox"),
                }
                poison_detected.append(p_rec)
                recommended_redlines.append(
                    {
                        "clause_id": cl["clause_id"],
                        "poison_id": rule["poison_id"],
                        "suggested_redline": rule["redline"],
                    }
                )
        else:
            status = "SUPPORTED"
            cat = _categorize_clause(txt)
            rationale = (
                "Aligned with baseline Part 21J / rotorcraft engineering & commercial terms."
            )
            redline = ""
            linked_asm = "ASM-TS-01"

            for pat, p_cat, p_rat, p_asm in _CHANGE_ORDER_PATTERNS:
                if pat.search(txt):
                    status = "CHANGE_ORDER_REQUIRED"
                    cat = p_cat
                    rationale = p_rat
                    linked_asm = p_asm
                    redline = p_rat
                    break
            if status == "SUPPORTED":
                for pat, p_cat, p_rat, p_asm in _PARTIAL_PATTERNS:
                    if pat.search(txt):
                        status = "PARTIALLY_SUPPORTED_WITH_ASSUMPTION"
                        cat = p_cat
                        rationale = p_rat
                        linked_asm = p_asm
                        break

        status_counts[status] += 1
        matrix.append(
            {
                "clause_id": cl["clause_id"],
                "category": cat,
                "status": status,
                "text": raw_txt,
                "normalized_text": txt,
                "obfuscation_detected": obfuscated,
                "poison_flags": [r["poison_id"] for r in matched_poisons],
                "rationale": rationale,
                "linked_assumption": linked_asm,
                "suggested_redline": redline,
                "page_no": cl.get("page_no"),
                "bbox": cl.get("bbox"),
                "source_file": cl.get("source_file"),
            }
        )

    if status_counts["REJECT_OR_ABSTAIN"] > 0:
        overall_gate = "REJECT_OR_ABSTAIN"
    elif status_counts["CHANGE_ORDER_REQUIRED"] > 0:
        overall_gate = "CHANGE_ORDER_NEGOTIATION_REQUIRED"
    elif status_counts["PARTIALLY_SUPPORTED_WITH_ASSUMPTION"] > 0:
        overall_gate = "APPROVED_WITH_ASSUMPTIONS"
    else:
        overall_gate = "SUPPORTED"

    audit_sha256 = hashlib.sha256(
        json.dumps(
            {"overall_gate": overall_gate, "matrix": matrix}, sort_keys=True, ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()

    return {
        "total_clauses": len(matrix),
        "status_counts": status_counts,
        "overall_contract_gate": overall_gate,
        "has_blocking_reject_clauses": status_counts["REJECT_OR_ABSTAIN"] > 0,
        "obfuscated_clause_count": obfuscated_count,
        "poison_clauses_count": len(poison_detected),
        "poison_clauses_detected": poison_detected,
        "recommended_redlines": recommended_redlines,
        "compliance_matrix": matrix,
        "audit_sha256": audit_sha256,
        "advisory_only": (
            "Automated pre-screening aid for commercial managers and counsel. "
            "Does NOT constitute legal advice or regulatory compliance determination."
        ),
    }
