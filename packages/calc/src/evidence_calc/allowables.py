"""Versioned MMPDS-16 & CMH-17 Rev H A-Basis / B-Basis Material Allowables Engine.

Provides cryptographically hashed, traceable aerospace allowables with exact
Decimal temperature, thickness, and environmental (CTD/RTD/ETW) knockdowns.
"""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from typing import Any

from flint import arb, ctx, fmpq

from evidence_calc.errors import AbstainError
from evidence_calc.quantize import format_quantum

_BALL_DPS = 50
_DISPLAY_QUANTUM = Decimal("0.000001")

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
    "AL-LI-2198-T8": {
        "standard": "MMPDS-16",
        "form": "Al-Li Sheet/Skin (AMS 4412)",
        "grain": "L",
        "density_kg_m3": "2690",
        "e_gpa": "77.0",
        "nu": "0.33",
        "min_thickness_mm": "1.0",
        "max_thickness_mm": "12.7",
        "min_temp_c": "-55",
        "max_temp_c": "150",
        "A": {
            "ftu_mpa": "490",
            "fty_mpa": "434",
            "fcy_mpa": "421",
            "fsu_mpa": "283",
            "fbru_e15_mpa": "724",
            "fbru_e20_mpa": "938",
            "fbry_e20_mpa": "738",
        },
        "B": {
            "ftu_mpa": "503",
            "fty_mpa": "448",
            "fcy_mpa": "434",
            "fsu_mpa": "290",
            "fbru_e15_mpa": "745",
            "fbru_e20_mpa": "965",
            "fbry_e20_mpa": "758",
        },
        "env_knockdown": {"CTD": "1.03", "RTD": "1.00", "ETW": "0.87"},
    },
    "AS4-8552-PW": {
        "standard": "CMH-17 Rev H",
        "form": "Carbon/Epoxy Plain Weave Fabric (50/50 Warp-Fill)",
        "grain": "0/90-deg",
        "density_kg_m3": "1570",
        "e_gpa": "66.5",
        "e2_gpa": "66.5",
        "g12_gpa": "4.5",
        "nu": "0.05",
        "min_thickness_mm": "0.19",
        "max_thickness_mm": "30.0",
        "min_temp_c": "-55",
        "max_temp_c": "121",
        "A": {
            "ftu_mpa": "710",
            "fty_mpa": "710",
            "fcy_mpa": "620",
            "fsu_mpa": "92",
            "f2t_mpa": "680",
            "f2c_mpa": "590",
            "oht_mpa": "315",
            "ohc_mpa": "240",
            "cai_mpa": "215",
        },
        "B": {
            "ftu_mpa": "758",
            "fty_mpa": "758",
            "fcy_mpa": "662",
            "fsu_mpa": "98",
            "f2t_mpa": "724",
            "f2c_mpa": "635",
            "oht_mpa": "338",
            "ohc_mpa": "258",
            "cai_mpa": "230",
        },
        "env_knockdown": {"CTD": "0.97", "RTD": "1.00", "ETW": "0.83"},
    },
    "T800-M21-UD": {
        "standard": "CMH-17 Rev H",
        "form": "Toughened Carbon/Epoxy Unidirectional Tape",
        "grain": "0-deg",
        "density_kg_m3": "1580",
        "e_gpa": "165.0",
        "e2_gpa": "8.8",
        "g12_gpa": "4.6",
        "nu": "0.33",
        "min_thickness_mm": "0.125",
        "max_thickness_mm": "30.0",
        "min_temp_c": "-55",
        "max_temp_c": "121",
        "A": {
            "ftu_mpa": "2410",
            "fty_mpa": "2410",
            "fcy_mpa": "1340",
            "fsu_mpa": "84",
            "f2t_mpa": "58",
            "f2c_mpa": "235",
            "oht_mpa": "455",
            "ohc_mpa": "295",
            "cai_mpa": "285",
        },
        "B": {
            "ftu_mpa": "2580",
            "fty_mpa": "2580",
            "fcy_mpa": "1445",
            "fsu_mpa": "91",
            "f2t_mpa": "63",
            "f2c_mpa": "252",
            "oht_mpa": "485",
            "ohc_mpa": "315",
            "cai_mpa": "305",
        },
        "env_knockdown": {"CTD": "0.96", "RTD": "1.00", "ETW": "0.84"},
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


def _arb_from_dec(val: Decimal) -> arb:
    """Convert an exact Decimal to a 50-digit FLINT Arb ball."""
    ctx.dps = _BALL_DPS
    frac = Fraction(format(val, "f"))
    if frac.denominator == 1:
        return arb(int(frac.numerator))
    return arb(fmpq(int(frac.numerator), int(frac.denominator)))


def _arb_bounds_decimal(ball: arb, scale: Decimal = _DISPLAY_QUANTUM) -> dict[str, str]:
    """Extract sound Decimal lower/upper bounds and midpoint from an Arb ball."""
    ctx.dps = _BALL_DPS
    mid_dec = Decimal(ball.mid().str(40, radius=False))
    rad_dec = Decimal(ball.rad().str(15, radius=False))
    sig_ulp = max(Decimal("1e-35"), abs(mid_dec) * Decimal("1e-35"))
    outward_rad = rad_dec * Decimal("1.000001") + sig_ulp
    lower_dec = (mid_dec - outward_rad).quantize(scale, rounding=ROUND_FLOOR)
    upper_dec = (mid_dec + outward_rad).quantize(scale, rounding=ROUND_CEILING)
    mid_quant = mid_dec.quantize(scale, rounding=ROUND_HALF_EVEN)
    return {
        "mid": format(mid_quant, "f"),
        "lower": format(lower_dec, "f"),
        "upper": format(upper_dec, "f"),
        "radius": format(rad_dec, "E"),
    }


def _thermal_knockdown(temp_c: Decimal) -> Decimal:
    if temp_c <= Decimal("25"):
        return Decimal("1")
    delta = temp_c - Decimal("25")
    return max(Decimal("0.72"), Decimal("1") - delta * Decimal("0.0012"))


def _thickness_knockdown(thk_mm: Decimal, min_thk: Decimal, max_thk: Decimal) -> Decimal:
    thk_mid = (min_thk + max_thk) / Decimal("2")
    if thk_mm <= thk_mid:
        return Decimal("1")
    return max(Decimal("0.93"), Decimal("1") - (thk_mm - thk_mid) * Decimal("0.0005"))


def lookup_allowable(
    material_id: str,
    *,
    basis: str = "A",
    property_name: str = "fty_mpa",
    thickness_mm: str = "10",
    temp_c: str = "23",
    environment: str = "RTD",
    include_intervals: bool = False,
    temp_uncertainty_c: str = "0",
    thickness_uncertainty_mm: str = "0",
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
    min_thk = Decimal(entry["min_thickness_mm"])
    max_thk = Decimal(entry["max_thickness_mm"])
    min_temp = Decimal(entry["min_temp_c"])
    max_temp = Decimal(entry["max_temp_c"])
    if thk < min_thk or thk > max_thk:
        raise AbstainError("allowable_outside_thickness_range")
    if temp < min_temp or temp > max_temp:
        raise AbstainError("allowable_outside_temp_range")

    env_key = environment.strip().upper()
    env_map = entry["env_knockdown"]
    if env_key not in env_map:
        raise AbstainError("unknown_environmental_condition")

    env_kd = Decimal(env_map[env_key])
    thermal_kd = _thermal_knockdown(temp)
    thk_kd = _thickness_knockdown(thk, min_thk, max_thk)

    base_val = Decimal(basis_table[prop_key])
    effective_kd = env_kd * thermal_kd * thk_kd
    allowable_val = base_val * effective_kd
    staged_allow = format_quantum(allowable_val, Decimal("0.001"))
    staged_kd = format_quantum(effective_kd, Decimal("0.0001"))

    out: dict[str, Any] = {
        "material_id": norm_mat,
        "standard": entry["standard"],
        "form": entry["form"],
        "basis": norm_basis,
        "property_name": prop_key,
        "environment": env_key,
        "base_value_mpa": format_quantum(base_val, Decimal("0.001")),
        "allowable_value_mpa": staged_allow,
        "knockdown_factor": staged_kd,
        "e_gpa": entry["e_gpa"],
        "nu": entry["nu"],
        "density_kg_m3": entry["density_kg_m3"],
        "catalog_sha256": allowable_catalog_sha256(),
    }

    if include_intervals:
        t_unc = Decimal(str(temp_uncertainty_c))
        h_unc = Decimal(str(thickness_uncertainty_mm))
        if t_unc < Decimal("0") or h_unc < Decimal("0"):
            raise AbstainError("invalid_allowable_uncertainty")
        t_lo = temp - t_unc
        t_hi = temp + t_unc
        h_lo = thk - h_unc
        h_hi = thk + h_unc
        if t_lo < min_temp or t_hi > max_temp:
            raise AbstainError("allowable_outside_temp_range")
        if h_lo < min_thk or h_hi > max_thk:
            raise AbstainError("allowable_outside_thickness_range")

        ctx.dps = _BALL_DPS
        # Monotone knockdowns over [t_lo, t_hi] and [h_lo, h_hi]: union endpoints in 50-digit Arb
        th_kd_ball = _arb_from_dec(_thermal_knockdown(t_lo)).union(
            _arb_from_dec(_thermal_knockdown(t_hi))
        )
        tk_kd_ball = _arb_from_dec(_thickness_knockdown(h_lo, min_thk, max_thk)).union(
            _arb_from_dec(_thickness_knockdown(h_hi, min_thk, max_thk))
        )
        kd_ball = _arb_from_dec(env_kd) * th_kd_ball * tk_kd_ball
        allow_ball = _arb_from_dec(base_val) * kd_ball

        allow_iv = _arb_bounds_decimal(allow_ball)
        kd_iv = _arb_bounds_decimal(kd_ball)
        allow_iv["staged"] = staged_allow
        kd_iv["staged"] = staged_kd
        out["exact_intervals"] = {
            "allowable_value_mpa": allow_iv,
            "knockdown_factor": kd_iv,
        }
        out["certified_lower_bound_mpa"] = allow_iv["lower"]
        out["uncertainty_envelope"] = {
            "temp_c_range": [format(t_lo, "f"), format(t_hi, "f")],
            "thickness_mm_range": [format(h_lo, "f"), format(h_hi, "f")],
            "ball_dps": _BALL_DPS,
        }

    return out
