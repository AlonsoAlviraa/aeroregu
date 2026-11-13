from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any

import z3


@dataclass(frozen=True)
class SMTProofResult:
    property_name: str
    proved: bool
    status: str  # "PROVED_UNSAT", "COUNTEREXAMPLE_FOUND", "UNKNOWN"
    assumptions: dict[str, Any]
    assertion: str
    counterexample: dict[str, str] | None
    proof_hash: str
    solver_stats: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def compute_proof_hash(
    property_name: str,
    status: str,
    assumptions: dict[str, Any],
    assertion: str,
    counterexample: dict[str, str] | None,
) -> str:
    payload = {
        "property_name": property_name,
        "status": status,
        "assumptions": assumptions,
        "assertion": assertion,
        "counterexample": counterexample,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _to_z3_real(val: str | int | Decimal | Fraction) -> z3.ArithRef:
    if isinstance(val, (int, str)):
        f = Fraction(str(val))
    elif isinstance(val, Decimal):
        f = Fraction(str(val))
    elif isinstance(val, Fraction):
        f = val
    else:
        raise TypeError(f"Unsupported type for exact rational: {type(val)}")
    return z3.Q(f.numerator, f.denominator)


def _rat_to_decimal_str(rat_val: Any, decimals: int = 4) -> str:
    if hasattr(rat_val, "as_fraction"):
        frac = rat_val.as_fraction()
        dec = Decimal(frac.numerator) / Decimal(frac.denominator)
        return f"{dec:.{decimals}f}"
    return str(rat_val)


class SMTSolverProofEngine:
    """Exact rational SMT verification engine using Z3 theorem prover.

    Evaluates continuous intervals and mathematical constraints without floating-point errors.
    """

    def __init__(self, timeout_ms: int = 5000) -> None:
        self.timeout_ms = timeout_ms

    def prove_structural_margin(
        self,
        bounds: dict[str, tuple[str, str]],
        allowables: dict[str, str],
        safety_factor: str = "1.500",
    ) -> SMTProofResult:
        """Prove that across all continuous combinations of load and area in bounds,

        the combined stress does not exceed allowable margins.
        """
        solver = z3.Solver()
        solver.set("timeout", self.timeout_ms)

        area = z3.Real("area_mm2")
        shear = z3.Real("shear_force_n")
        tensile = z3.Real("tensile_force_n")

        area_min_dec = Decimal(bounds["area_mm2"][0])
        area_max_dec = Decimal(bounds["area_mm2"][1])
        shear_min_dec = Decimal(bounds["shear_force_n"][0])
        shear_max_dec = Decimal(bounds["shear_force_n"][1])
        tensile_min_dec = Decimal(bounds["tensile_force_n"][0])
        tensile_max_dec = Decimal(bounds["tensile_force_n"][1])
        if (
            area_min_dec > area_max_dec
            or shear_min_dec > shear_max_dec
            or tensile_min_dec > tensile_max_dec
        ):
            raise ValueError("interval bounds must satisfy min <= max")
        if area_min_dec <= 0:
            raise ValueError("area_mm2 lower bound must be positive")

        sf_dec = Decimal(safety_factor)
        tau_dec = Decimal(allowables["shear_allowable_mpa"])
        sigma_dec = Decimal(allowables["tensile_allowable_mpa"])
        if tau_dec <= 0 or sigma_dec <= 0 or sf_dec <= 0:
            raise ValueError("allowables and safety_factor must be positive")

        area_min = _to_z3_real(bounds["area_mm2"][0])
        area_max = _to_z3_real(bounds["area_mm2"][1])
        shear_min = _to_z3_real(bounds["shear_force_n"][0])
        shear_max = _to_z3_real(bounds["shear_force_n"][1])
        tensile_min = _to_z3_real(bounds["tensile_force_n"][0])
        tensile_max = _to_z3_real(bounds["tensile_force_n"][1])

        sf = _to_z3_real(safety_factor)
        tau_allow = _to_z3_real(allowables["shear_allowable_mpa"])
        sigma_allow = _to_z3_real(allowables["tensile_allowable_mpa"])

        # Domain bounds (continuous interval)
        solver.add(area >= area_min, area <= area_max)
        solver.add(shear >= shear_min, shear <= shear_max)
        solver.add(tensile >= tensile_min, tensile <= tensile_max)

        # Failure condition (negation of safety envelope):
        # ((shear*sf*sigma_allow)^2 + (tensile*sf*tau_allow)^2) > (area*tau_allow*sigma_allow)^2
        lhs = ((shear * sf * sigma_allow) ** 2) + ((tensile * sf * tau_allow) ** 2)
        rhs = (area * tau_allow * sigma_allow) ** 2
        solver.add(lhs > rhs)

        check_status = solver.check()
        assumptions = {
            "bounds": bounds,
            "allowables": allowables,
            "safety_factor": safety_factor,
        }
        assertion = "forall loads in bounds: ((tau*SF)^2/tau_all^2)+((sig*SF)^2/sig_all^2) <= 1"

        if check_status == z3.unsat:
            h = compute_proof_hash(
                "structural_margin", "PROVED_UNSAT", assumptions, assertion, None
            )
            return SMTProofResult(
                property_name="structural_margin",
                proved=True,
                status="PROVED_UNSAT",
                assumptions=assumptions,
                assertion=assertion,
                counterexample=None,
                proof_hash=h,
                solver_stats={
                    "check": "unsat",
                    "reason": "No counterexample exists in continuous domain",
                },
            )
        elif check_status == z3.sat:
            m = solver.model()
            cex = {
                "area_mm2": _rat_to_decimal_str(m[area]),
                "shear_force_n": _rat_to_decimal_str(m[shear]),
                "tensile_force_n": _rat_to_decimal_str(m[tensile]),
            }
            h = compute_proof_hash(
                "structural_margin", "COUNTEREXAMPLE_FOUND", assumptions, assertion, cex
            )
            return SMTProofResult(
                property_name="structural_margin",
                proved=False,
                status="COUNTEREXAMPLE_FOUND",
                assumptions=assumptions,
                assertion=assertion,
                counterexample=cex,
                proof_hash=h,
                solver_stats={
                    "check": "sat",
                    "reason": "Structural margin violated at counterexample point",
                },
            )
        else:
            h = compute_proof_hash("structural_margin", "UNKNOWN", assumptions, assertion, None)
            return SMTProofResult(
                property_name="structural_margin",
                proved=False,
                status="UNKNOWN",
                assumptions=assumptions,
                assertion=assertion,
                counterexample=None,
                proof_hash=h,
                solver_stats={"check": "unknown", "reason": str(solver.reason_unknown())},
            )

    def prove_station_equilibrium(
        self,
        bounds: dict[str, tuple[str, str]],
        stations: list[str],
        max_station_force_n: str,
        gravity_m_s2: str = "9.807",
        active_stations_min: int = 3,
    ) -> SMTProofResult:
        """Prove continuous combinations of mass, load factor, and cg_x

        can be sustained without exceeding station thrust limits or losing moment balance.
        """
        if not stations:
            raise ValueError("stations must not be empty")
        mass_min_dec = Decimal(bounds["mass_kg"][0])
        mass_max_dec = Decimal(bounds["mass_kg"][1])
        lf_min_dec = Decimal(bounds["load_factor"][0])
        lf_max_dec = Decimal(bounds["load_factor"][1])
        cg_min_dec = Decimal(bounds["cg_x_m"][0])
        cg_max_dec = Decimal(bounds["cg_x_m"][1])
        if mass_min_dec > mass_max_dec or lf_min_dec > lf_max_dec or cg_min_dec > cg_max_dec:
            raise ValueError("interval bounds must satisfy min <= max")
        if Decimal(max_station_force_n) <= 0 or active_stations_min <= 0:
            raise ValueError("max_station_force_n and active_stations_min must be positive")

        solver = z3.Solver()
        solver.set("timeout", self.timeout_ms)

        mass = z3.Real("mass_kg")
        load_factor = z3.Real("load_factor")
        cg_x = z3.Real("cg_x_m")

        mass_min = _to_z3_real(bounds["mass_kg"][0])
        mass_max = _to_z3_real(bounds["mass_kg"][1])
        lf_min = _to_z3_real(bounds["load_factor"][0])
        lf_max = _to_z3_real(bounds["load_factor"][1])
        cg_min = _to_z3_real(bounds["cg_x_m"][0])
        cg_max = _to_z3_real(bounds["cg_x_m"][1])

        grav = _to_z3_real(gravity_m_s2)
        f_max = _to_z3_real(max_station_force_n)
        active_count = _to_z3_real(str(active_stations_min))

        solver.add(mass >= mass_min, mass <= mass_max)
        solver.add(load_factor >= lf_min, load_factor <= lf_max)
        solver.add(cg_x >= cg_min, cg_x <= cg_max)

        req_force = mass * grav * load_factor
        total_capacity = active_count * f_max

        station_decimals = [Decimal(s) for s in stations]
        min_pos = _to_z3_real(str(min(station_decimals)))
        max_pos = _to_z3_real(str(max(station_decimals)))

        cg_out_of_span = z3.Or(cg_x < min_pos, cg_x > max_pos)
        thrust_exceeded = req_force > total_capacity

        solver.add(z3.Or(thrust_exceeded, cg_out_of_span))

        check_status = solver.check()
        assumptions = {
            "bounds": bounds,
            "stations": stations,
            "max_station_force_n": max_station_force_n,
            "gravity_m_s2": gravity_m_s2,
            "active_stations_min": active_stations_min,
        }
        assertion = "forall (mass, nz, cg) in bounds: req_force <= capacity and cg in station span"

        if check_status == z3.unsat:
            h = compute_proof_hash(
                "station_equilibrium", "PROVED_UNSAT", assumptions, assertion, None
            )
            return SMTProofResult(
                property_name="station_equilibrium",
                proved=True,
                status="PROVED_UNSAT",
                assumptions=assumptions,
                assertion=assertion,
                counterexample=None,
                proof_hash=h,
                solver_stats={
                    "check": "unsat",
                    "reason": "Equilibrium authority proved across entire envelope",
                },
            )
        elif check_status == z3.sat:
            m = solver.model()
            cex = {
                "mass_kg": _rat_to_decimal_str(m[mass]),
                "load_factor": _rat_to_decimal_str(m[load_factor]),
                "cg_x_m": _rat_to_decimal_str(m[cg_x]),
            }
            h = compute_proof_hash(
                "station_equilibrium", "COUNTEREXAMPLE_FOUND", assumptions, assertion, cex
            )
            return SMTProofResult(
                property_name="station_equilibrium",
                proved=False,
                status="COUNTEREXAMPLE_FOUND",
                assumptions=assumptions,
                assertion=assertion,
                counterexample=cex,
                proof_hash=h,
                solver_stats={
                    "check": "sat",
                    "reason": "Control envelope violated at counterexample point",
                },
            )
        else:
            h = compute_proof_hash("station_equilibrium", "UNKNOWN", assumptions, assertion, None)
            return SMTProofResult(
                property_name="station_equilibrium",
                proved=False,
                status="UNKNOWN",
                assumptions=assumptions,
                assertion=assertion,
                counterexample=None,
                proof_hash=h,
                solver_stats={"check": "unknown", "reason": str(solver.reason_unknown())},
            )

    def prove_hover_power_envelope(
        self,
        thrust_bounds_n: tuple[str, str],
        disk_area_m2: str,
        air_density_kg_m3: str = "1.225",
        figure_of_merit: str = "0.700",
        max_power_available_kw: str = "350.000",
    ) -> SMTProofResult:
        """Prove actuator-disk shaft power stays within available power over continuous thrust.

        Uses exact algebraic equivalence: T^3 <= 2 * rho * A * (1000 * FM * P_avail)^2.
        """
        t_min_dec = Decimal(thrust_bounds_n[0])
        t_max_dec = Decimal(thrust_bounds_n[1])
        if t_min_dec > t_max_dec or t_min_dec <= 0:
            raise ValueError("thrust_bounds_n must satisfy 0 < min <= max")
        if (
            Decimal(disk_area_m2) <= 0
            or Decimal(air_density_kg_m3) <= 0
            or Decimal(figure_of_merit) <= 0
            or Decimal(max_power_available_kw) <= 0
        ):
            raise ValueError("disk_area, air_density, figure_of_merit, and power must be positive")

        solver = z3.Solver()
        solver.set("timeout", self.timeout_ms)

        thrust = z3.Real("thrust_n")
        t_min = _to_z3_real(thrust_bounds_n[0])
        t_max = _to_z3_real(thrust_bounds_n[1])
        area = _to_z3_real(disk_area_m2)
        rho = _to_z3_real(air_density_kg_m3)
        fm = _to_z3_real(figure_of_merit)
        p_avail = _to_z3_real(max_power_available_kw)

        solver.add(thrust >= t_min, thrust <= t_max)
        # Failure condition: P_shaft > P_avail <=> T^3 > 2 * rho * A * (1000 * FM * P_avail)^2
        rhs_kw_to_w = _to_z3_real("1000") * fm * p_avail
        solver.add((thrust * thrust * thrust) > (_to_z3_real("2") * rho * area * (rhs_kw_to_w**2)))

        check_status = solver.check()
        assumptions = {
            "thrust_bounds_n": thrust_bounds_n,
            "disk_area_m2": disk_area_m2,
            "air_density_kg_m3": air_density_kg_m3,
            "figure_of_merit": figure_of_merit,
            "max_power_available_kw": max_power_available_kw,
        }
        assertion = "forall thrust in bounds: T^3 <= 2 * rho * A * (1000 * FM * P_avail)^2"

        if check_status == z3.unsat:
            h = compute_proof_hash(
                "hover_power_envelope", "PROVED_UNSAT", assumptions, assertion, None
            )
            return SMTProofResult(
                property_name="hover_power_envelope",
                proved=True,
                status="PROVED_UNSAT",
                assumptions=assumptions,
                assertion=assertion,
                counterexample=None,
                proof_hash=h,
                solver_stats={
                    "check": "unsat",
                    "reason": "Shaft power stays within available budget across thrust interval",
                },
            )
        if check_status == z3.sat:
            m = solver.model()
            cex = {"thrust_n": _rat_to_decimal_str(m[thrust])}
            h = compute_proof_hash(
                "hover_power_envelope", "COUNTEREXAMPLE_FOUND", assumptions, assertion, cex
            )
            return SMTProofResult(
                property_name="hover_power_envelope",
                proved=False,
                status="COUNTEREXAMPLE_FOUND",
                assumptions=assumptions,
                assertion=assertion,
                counterexample=cex,
                proof_hash=h,
                solver_stats={
                    "check": "sat",
                    "reason": "Power budget exceeded at counterexample thrust",
                },
            )
        h = compute_proof_hash("hover_power_envelope", "UNKNOWN", assumptions, assertion, None)
        return SMTProofResult(
            property_name="hover_power_envelope",
            proved=False,
            status="UNKNOWN",
            assumptions=assumptions,
            assertion=assertion,
            counterexample=None,
            proof_hash=h,
            solver_stats={"check": "unknown", "reason": str(solver.reason_unknown())},
        )
