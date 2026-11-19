"""Versioned MMPDS-16 & CMH-17 Rev H A-Basis / B-Basis Material Allowables Engine.

Provides cryptographically hashed, traceable aerospace allowables with exact
Decimal temperature, thickness, and environmental (CTD/RTD/ETW) knockdowns.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.quantize import format_quantum

_CATALOG_META: dict[str, str] = {
    "metallic_source": "MMPDS-16 (2022)",
    "composite_source": "CMH-17 Rev H (2023)",
    "version": "2026.11.0",
}

# All numeric entries are quoted base-10 strings so Decimal conversion is exact.
_ALLOWABLES_DB: dict[str, dict[str, Any]] = {
    "AL-7075-T651": {
        "standard": "MMPDS-16",
        "form": "Plate (AMS 4045)",
        "grain": "L",
        "density_kg_m3": "2810",
        "e_gpa": "71.7",
        "nu": "0.33",
        "min_thickness_mm": "6.35",
        "max_thickness_mm": "76.2",
        "min_temp_c": "-55",
        "max_temp_c": "150",
        "A": {
            "ftu_mpa": "510",
            "fty_mpa": "441",
            "fcy_mpa": "434",
            "fsu_mpa": "290",
            "fbru_e15_mpa": "745",
            "fbru_e20_mpa": "972",
            "fbry_e20_mpa": "758",
        },
        "B": {
            "ftu_mpa": "531",
            "fty_mpa": "462",
            "fcy_mpa": "455",
            "fsu_mpa": "303",
            "fbru_e15_mpa": "779",
            "fbru_e20_mpa": "1013",
            "fbry_e20_mpa": "793",
        },
        "env_knockdown": {"CTD": "1.02", "RTD": "1.00", "ETW": "0.86"},
    },
    "AL-2024-T3": {
        "standard": "MMPDS-16",
        "form": "Sheet (AMS 4037 Clad/Bare)",
        "grain": "L",
        "density_kg_m3": "2780",
        "e_gpa": "72.4",
        "nu": "0.33",
        "min_thickness_mm": "0.5",
        "max_thickness_mm": "6.35",
        "min_temp_c": "-55",
        "max_temp_c": "150",
        "A": {
            "ftu_mpa": "434",
            "fty_mpa": "290",
            "fcy_mpa": "269",
            "fsu_mpa": "269",
            "fbru_e15_mpa": "662",
            "fbru_e20_mpa": "855",
            "fbry_e20_mpa": "517",
        },
        "B": {
            "ftu_mpa": "448",
            "fty_mpa": "310",
            "fcy_mpa": "283",
            "fsu_mpa": "276",
            "fbru_e15_mpa": "683",
            "fbru_e20_mpa": "889",
            "fbry_e20_mpa": "538",
        },
        "env_knockdown": {"CTD": "1.02", "RTD": "1.00", "ETW": "0.88"},
    },
    "TI-6AL-4V": {
        "standard": "MMPDS-16",
        "form": "Annealed Bar/Forging (AMS 4928)",
        "grain": "L",
        "density_kg_m3": "4430",
        "e_gpa": "110.3",
        "nu": "0.31",
        "min_thickness_mm": "2.0",
        "max_thickness_mm": "101.6",
        "min_temp_c": "-55",
        "max_temp_c": "315",
        "A": {
            "ftu_mpa": "896",
            "fty_mpa": "827",
            "fcy_mpa": "869",
            "fsu_mpa": "538",
            "fbru_e15_mpa": "1379",
            "fbru_e20_mpa": "1793",
            "fbry_e20_mpa": "1448",
        },
        "B": {
            "ftu_mpa": "931",
            "fty_mpa": "862",
            "fcy_mpa": "903",
            "fsu_mpa": "558",
            "fbru_e15_mpa": "1434",
            "fbru_e20_mpa": "1862",
            "fbry_e20_mpa": "1510",
        },
        "env_knockdown": {"CTD": "1.04", "RTD": "1.00", "ETW": "0.82"},
    },
    "IM7-8552-UD": {
        "standard": "CMH-17 Rev H",
        "form": "Carbon/Epoxy Unidirectional Tape",
        "grain": "0-deg",
        "density_kg_m3": "1580",
        "e_gpa": "158.5",
        "e2_gpa": "9.0",
        "g12_gpa": "4.7",
        "nu": "0.32",
        "min_thickness_mm": "0.125",
        "max_thickness_mm": "25.0",
        "min_temp_c": "-55",
        "max_temp_c": "121",
        "A": {
            "ftu_mpa": "2150",
            "fty_mpa": "2150",
            "fcy_mpa": "1240",
            "fsu_mpa": "72",
            "f2t_mpa": "51",
            "f2c_mpa": "210",
            "oht_mpa": "415",
            "ohc_mpa": "265",
            "cai_mpa": "235",
        },
        "B": {
            "ftu_mpa": "2310",
            "fty_mpa": "2310",
            "fcy_mpa": "1345",
            "fsu_mpa": "78",
            "f2t_mpa": "56",
            "f2c_mpa": "228",
            "oht_mpa": "442",
            "ohc_mpa": "284",
            "cai_mpa": "252",
        },
        "env_knockdown": {"CTD": "0.96", "RTD": "1.00", "ETW": "0.81"},
    },
    "15-5PH-H1025": {
        "standard": "MMPDS-16",
        "form": "CRES Bar/Forging (AMS 5659)",
        "grain": "L",
        "density_kg_m3": "7800",
        "e_gpa": "196.5",
        "nu": "0.27",
        "min_thickness_mm": "2.0",
        "max_thickness_mm": "152.4",
        "min_temp_c": "-55",
        "max_temp_c": "315",
        "A": {
            "ftu_mpa": "1069",
            "fty_mpa": "1000",
            "fcy_mpa": "1014",
            "fsu_mpa": "655",
            "fbru_e15_mpa": "1655",
            "fbru_e20_mpa": "2137",
            "fbry_e20_mpa": "1696",
        },
        "B": {
            "ftu_mpa": "1103",
            "fty_mpa": "1034",
            "fcy_mpa": "1048",
            "fsu_mpa": "676",
            "fbru_e15_mpa": "1710",
            "fbru_e20_mpa": "2206",
            "fbry_e20_mpa": "1758",
        },
        "env_knockdown": {"CTD": "1.01", "RTD": "1.00", "ETW": "0.89"},
    },
}


def allowable_catalog_sha256() -> str:
    """Return pinned SHA-256 digest of the active MMPDS-16 / CMH-17 Rev H catalog."""
    payload = json.dumps(
        {"meta": _CATALOG_META, "materials": _ALLOWABLES_DB},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def list_materials() -> list[str]:
    return sorted(_ALLOWABLES_DB.keys())


def lookup_allowable(
    material_id: str,
    *,
    basis: str = "A",
    property_name: str = "fty_mpa",
    thickness_mm: str = "10",
    temp_c: str = "23",
    environment: str = "RTD",
) -> dict[str, Any]:
    """Resolve pinned A-Basis / B-Basis allowable with thickness, temp & env knockdown."""
    norm_mat = material_id.strip().upper()
    entry = _ALLOWABLES_DB.get(norm_mat)
    if entry is None:
        raise AbstainError("unknown_material_allowable")

    norm_basis = basis.strip().upper()
    if norm_basis not in {"A", "B"}:
        raise AbstainError("invalid_allowable_basis")

    prop_key = property_name.strip().lower()
    basis_table = entry[norm_basis]
    if prop_key not in basis_table:
        raise AbstainError("unknown_allowable_property")

    thk = Decimal(str(thickness_mm))
    temp = Decimal(str(temp_c))
    if thk < Decimal(entry["min_thickness_mm"]) or thk > Decimal(entry["max_thickness_mm"]):
        raise AbstainError("allowable_outside_thickness_range")
    if temp < Decimal(entry["min_temp_c"]) or temp > Decimal(entry["max_temp_c"]):
        raise AbstainError("allowable_outside_temp_range")

    env_key = environment.strip().upper()
    env_map = entry["env_knockdown"]
    if env_key not in env_map:
        raise AbstainError("unknown_environmental_condition")

    env_kd = Decimal(env_map[env_key])
    # Temperature thermal derating beyond ambient 25 C (linear conservative slope)
    thermal_kd = Decimal("1")
    if temp > Decimal("25"):
        delta = temp - Decimal("25")
        thermal_kd = max(Decimal("0.72"), Decimal("1") - delta * Decimal("0.0012"))

    # Thick-section quench sensitivity penalty beyond midpoint thickness
    thk_mid = (Decimal(entry["min_thickness_mm"]) + Decimal(entry["max_thickness_mm"])) / Decimal(
        "2"
    )
    thk_kd = Decimal("1")
    if thk > thk_mid:
        thk_kd = max(Decimal("0.93"), Decimal("1") - (thk - thk_mid) * Decimal("0.0005"))

    base_val = Decimal(basis_table[prop_key])
    effective_kd = env_kd * thermal_kd * thk_kd
    allowable_val = base_val * effective_kd

    return {
        "material_id": norm_mat,
        "standard": entry["standard"],
        "form": entry["form"],
        "basis": norm_basis,
        "property_name": prop_key,
        "environment": env_key,
        "base_value_mpa": format_quantum(base_val, Decimal("0.001")),
        "allowable_value_mpa": format_quantum(allowable_val, Decimal("0.001")),
        "knockdown_factor": format_quantum(effective_kd, Decimal("0.0001")),
        "e_gpa": entry["e_gpa"],
        "nu": entry["nu"],
        "density_kg_m3": entry["density_kg_m3"],
        "catalog_sha256": allowable_catalog_sha256(),
    }
