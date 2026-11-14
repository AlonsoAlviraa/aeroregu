"""Exact rational and nonlinear real (QF_NRA) SMT verification via Z3 + cvc5."""

from __future__ import annotations

import itertools
import threading
from dataclasses import asdict, dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any

import cvc5
import z3
from cvc5 import Kind

from evidence_kernel.canonical import inputs_hash

_SMT_CACHE_LOCK = threading.RLock()
_SMT_PROOF_CACHE: dict[str, SMTProofResult] = {}
_MAX_SMT_CACHE_SIZE = 256


def _cached_smt_lookup(cache_key: str) -> SMTProofResult | None:
    with _SMT_CACHE_LOCK:
        return _SMT_PROOF_CACHE.get(cache_key)


def _cached_smt_store(cache_key: str, result: SMTProofResult) -> SMTProofResult:
    with _SMT_CACHE_LOCK:
        if len(_SMT_PROOF_CACHE) >= _MAX_SMT_CACHE_SIZE:
            oldest_key = next(iter(_SMT_PROOF_CACHE))
            _SMT_PROOF_CACHE.pop(oldest_key, None)
        _SMT_PROOF_CACHE[cache_key] = result
        return result


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


def compute_proof_hash(
    property_name: str,
    status: str,
    assumptions: dict[str, Any],
    assertion: str,
    counterexample: dict[str, str] | None,
) -> str:
    """Compute RFC 8785 canonical SHA-256 hash using kernel canonicalization."""
    payload = {
        "property_name": property_name,
        "status": status,
        "assumptions": assumptions,
        "assertion": assertion,
        "counterexample": counterexample,
    }
    return inputs_hash(payload)


def _to_fraction(val: str | int | Decimal | Fraction) -> Fraction:
    if isinstance(val, Fraction):
        return val
    if isinstance(val, (int, str, Decimal)):
        return Fraction(str(val))
    raise TypeError(f"Unsupported type for exact rational: {type(val)}")


def _to_z3_real(val: str | int | Decimal | Fraction) -> z3.ArithRef:
    f = _to_fraction(val)
    return z3.Q(f.numerator, f.denominator)


def _to_cvc5_real(solver: cvc5.Solver, val: str | int | Decimal | Fraction) -> cvc5.Term:
    f = _to_fraction(val)
    return solver.mkReal(f.numerator, f.denominator)


def _rat_to_decimal_str(rat_val: Any, decimals: int = 4) -> str:
    if hasattr(rat_val, "as_fraction"):
        frac = rat_val.as_fraction()
        dec = Decimal(frac.numerator) / Decimal(frac.denominator)
        return f"{dec:.{decimals}f}"
    if hasattr(rat_val, "getRealValue"):
        frac = rat_val.getRealValue()
        dec = Decimal(frac.numerator) / Decimal(frac.denominator)
        return f"{dec:.{decimals}f}"
    return str(rat_val)


def _new_cvc5_solver(timeout_ms: int) -> cvc5.Solver:
    solver = cvc5.Solver()
    solver.setLogic("QF_NRA")
    solver.setOption("produce-models", "true")
    solver.setOption("tlimit-per", str(max(1, int(timeout_ms))))
    return solver


def _cvc5_status_str(res: cvc5.Result) -> str:
    if res.isUnsat():
        return "unsat"
    if res.isSat():
        return "sat"
    return "unknown"


class SMTSolverProofEngine:
    """Dual-backend exact rational & QF_NRA SMT verification engine (Z3 + cvc5)."""

    def __init__(self, timeout_ms: int = 5000, *, cross_check: bool = True) -> None:
        self.timeout_ms = timeout_ms
        self.cross_check = cross_check

    def _reconcile_verdicts(
        self,
        *,
        property_name: str,
        assumptions: dict[str, Any],
        assertion: str,
        z3_status_str: str,
        z3_cex: dict[str, str] | None,
        z3_reason: str,
        cvc5_status_str: str | None,
        cvc5_cex: dict[str, str] | None,
        proved_reason: str,
        cex_reason: str,
    ) -> SMTProofResult:
        cross_meta: dict[str, Any] = {"z3": z3_status_str}
        if cvc5_status_str is not None:
            cross_meta["cvc5"] = cvc5_status_str

        # Fail closed on direct solver disagreement between unsat and sat
        if cvc5_status_str is not None and {z3_status_str, cvc5_status_str} == {"unsat", "sat"}:
            cross_meta["agreed"] = False
            h = compute_proof_hash(property_name, "UNKNOWN", assumptions, assertion, None)
            return SMTProofResult(
                property_name=property_name,
                proved=False,
                status="UNKNOWN",
                assumptions=assumptions,
                assertion=assertion,
                counterexample=None,
                proof_hash=h,
                solver_stats={
                    "check": "unknown",
                    "reason": "Solver disagreement between Z3 and cvc5",
                    "cross_check": cross_meta,
                },
            )

        effective_status = z3_status_str
        effective_cex = z3_cex
        if z3_status_str == "unknown" and cvc5_status_str in {"unsat", "sat"}:
            effective_status = cvc5_status_str
            effective_cex = cvc5_cex
            cross_meta["rescued_by"] = "cvc5"

        if cvc5_status_str is not None:
            cross_meta["agreed"] = (
                z3_status_str == cvc5_status_str
                or z3_status_str == "unknown"
                or cvc5_status_str == "unknown"
            )

        if effective_status == "unsat":
            h = compute_proof_hash(property_name, "PROVED_UNSAT", assumptions, assertion, None)
            return SMTProofResult(
                property_name=property_name,
                proved=True,
                status="PROVED_UNSAT",
                assumptions=assumptions,
                assertion=assertion,
                counterexample=None,
                proof_hash=h,
                solver_stats={
                    "check": "unsat",
                    "reason": proved_reason,
                    "cross_check": cross_meta,
                },
            )

        if effective_status == "sat":
            h = compute_proof_hash(
                property_name, "COUNTEREXAMPLE_FOUND", assumptions, assertion, effective_cex
            )
            return SMTProofResult(
                property_name=property_name,
                proved=False,
                status="COUNTEREXAMPLE_FOUND",
                assumptions=assumptions,
                assertion=assertion,
                counterexample=effective_cex,
                proof_hash=h,
                solver_stats={
                    "check": "sat",
                    "reason": cex_reason,
                    "cross_check": cross_meta,
                },
            )

        h = compute_proof_hash(property_name, "UNKNOWN", assumptions, assertion, None)
        return SMTProofResult(
            property_name=property_name,
            proved=False,
            status="UNKNOWN",
            assumptions=assumptions,
            assertion=assertion,
            counterexample=None,
            proof_hash=h,
            solver_stats={
                "check": "unknown",
                "reason": z3_reason,
                "cross_check": cross_meta,
            },
        )

    def prove_structural_margin(
        self,
        bounds: dict[str, tuple[str, str]],
        allowables: dict[str, str],
        safety_factor: str = "1.500",
    ) -> SMTProofResult:
        """Prove that across all continuous combinations of load and area in bounds,

        the combined stress does not exceed allowable margins.
        """
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

        cache_key = inputs_hash(
            {
                "method": "structural_margin",
                "bounds": bounds,
                "allowables": allowables,
                "safety_factor": safety_factor,
                "timeout_ms": self.timeout_ms,
                "cross_check": self.cross_check,
            }
        )
        cached = _cached_smt_lookup(cache_key)
        if cached is not None:
            return cached

        solver = z3.Solver()
        solver.set("timeout", self.timeout_ms)
        area = z3.Real("area_mm2")
        shear = z3.Real("shear_force_n")
        tensile = z3.Real("tensile_force_n")

        solver.add(
            area >= _to_z3_real(bounds["area_mm2"][0]),
            area <= _to_z3_real(bounds["area_mm2"][1]),
            shear >= _to_z3_real(bounds["shear_force_n"][0]),
            shear <= _to_z3_real(bounds["shear_force_n"][1]),
            tensile >= _to_z3_real(bounds["tensile_force_n"][0]),
            tensile <= _to_z3_real(bounds["tensile_force_n"][1]),
        )
        sf = _to_z3_real(safety_factor)
        tau_allow = _to_z3_real(allowables["shear_allowable_mpa"])
        sigma_allow = _to_z3_real(allowables["tensile_allowable_mpa"])
        lhs = ((shear * sf * sigma_allow) ** 2) + ((tensile * sf * tau_allow) ** 2)
        rhs = (area * tau_allow * sigma_allow) ** 2
        solver.add(lhs > rhs)

        z3_check = solver.check()
        z3_status_str = (
            "unsat" if z3_check == z3.unsat else ("sat" if z3_check == z3.sat else "unknown")
        )
        z3_cex = None
        if z3_check == z3.sat:
            m = solver.model()
            z3_cex = {
                "area_mm2": _rat_to_decimal_str(m[area]),
                "shear_force_n": _rat_to_decimal_str(m[shear]),
                "tensile_force_n": _rat_to_decimal_str(m[tensile]),
            }

        cvc5_status_str: str | None = None
        cvc5_cex: dict[str, str] | None = None
        if self.cross_check or z3_status_str == "unknown":
            cs = _new_cvc5_solver(self.timeout_ms)
            real = cs.getRealSort()
            c_area = cs.mkConst(real, "area_mm2")
            c_shear = cs.mkConst(real, "shear_force_n")
            c_tensile = cs.mkConst(real, "tensile_force_n")
            cs.assertFormula(cs.mkTerm(Kind.GEQ, c_area, _to_cvc5_real(cs, bounds["area_mm2"][0])))
            cs.assertFormula(cs.mkTerm(Kind.LEQ, c_area, _to_cvc5_real(cs, bounds["area_mm2"][1])))
            cs.assertFormula(
                cs.mkTerm(Kind.GEQ, c_shear, _to_cvc5_real(cs, bounds["shear_force_n"][0]))
            )
            cs.assertFormula(
                cs.mkTerm(Kind.LEQ, c_shear, _to_cvc5_real(cs, bounds["shear_force_n"][1]))
            )
            cs.assertFormula(
                cs.mkTerm(Kind.GEQ, c_tensile, _to_cvc5_real(cs, bounds["tensile_force_n"][0]))
            )
            cs.assertFormula(
                cs.mkTerm(Kind.LEQ, c_tensile, _to_cvc5_real(cs, bounds["tensile_force_n"][1]))
            )
            c_sf = _to_cvc5_real(cs, safety_factor)
            c_tau = _to_cvc5_real(cs, allowables["shear_allowable_mpa"])
            c_sig = _to_cvc5_real(cs, allowables["tensile_allowable_mpa"])
            t1 = cs.mkTerm(Kind.MULT, c_shear, c_sf, c_sig)
            t2 = cs.mkTerm(Kind.MULT, c_tensile, c_sf, c_tau)
            t3 = cs.mkTerm(Kind.MULT, c_area, c_tau, c_sig)
            c_lhs = cs.mkTerm(Kind.ADD, cs.mkTerm(Kind.MULT, t1, t1), cs.mkTerm(Kind.MULT, t2, t2))
            c_rhs = cs.mkTerm(Kind.MULT, t3, t3)
            cs.assertFormula(cs.mkTerm(Kind.GT, c_lhs, c_rhs))
            c_res = cs.checkSat()
            cvc5_status_str = _cvc5_status_str(c_res)
            if cvc5_status_str == "sat":
                cvc5_cex = {
                    "area_mm2": _rat_to_decimal_str(cs.getValue(c_area)),
                    "shear_force_n": _rat_to_decimal_str(cs.getValue(c_shear)),
                    "tensile_force_n": _rat_to_decimal_str(cs.getValue(c_tensile)),
                }

        assumptions = {
            "bounds": bounds,
            "allowables": allowables,
            "safety_factor": safety_factor,
        }
        assertion = "forall loads in bounds: ((tau*SF)^2/tau_all^2)+((sig*SF)^2/sig_all^2) <= 1"
        return _cached_smt_store(
            cache_key,
            self._reconcile_verdicts(
                property_name="structural_margin",
                assumptions=assumptions,
                assertion=assertion,
                z3_status_str=z3_status_str,
                z3_cex=z3_cex,
                z3_reason=str(solver.reason_unknown()) if z3_status_str == "unknown" else "",
                cvc5_status_str=cvc5_status_str,
                cvc5_cex=cvc5_cex,
                proved_reason="No counterexample exists in continuous domain",
                cex_reason="Structural margin violated at counterexample point",
            ),
        )

    def prove_station_equilibrium(
        self,
        bounds: dict[str, tuple[str, str]],
        stations: list[str],
        max_station_force_n: str,
        gravity_m_s2: str = "9.807",
        active_stations_min: int = 3,
        *,
        enforce_moment_equilibrium: bool = False,
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

        cache_key = inputs_hash(
            {
                "method": "station_equilibrium",
                "bounds": bounds,
                "stations": stations,
                "max_station_force_n": max_station_force_n,
                "gravity_m_s2": gravity_m_s2,
                "active_stations_min": active_stations_min,
                "enforce_moment_equilibrium": enforce_moment_equilibrium,
                "timeout_ms": self.timeout_ms,
                "cross_check": self.cross_check,
            }
        )
        cached = _cached_smt_lookup(cache_key)
        if cached is not None:
            return cached

        solver = z3.Solver()
        solver.set("timeout", self.timeout_ms)
        mass = z3.Real("mass_kg")
        load_factor = z3.Real("load_factor")
        cg_x = z3.Real("cg_x_m")

        station_decimals = sorted(Decimal(s) for s in stations)
        eff_active = min(active_stations_min, len(station_decimals))
        dropped = len(station_decimals) - eff_active
        min_station_str = str(station_decimals[dropped])
        max_station_str = str(station_decimals[eff_active - 1])

        solver.add(
            mass >= _to_z3_real(bounds["mass_kg"][0]),
            mass <= _to_z3_real(bounds["mass_kg"][1]),
            load_factor >= _to_z3_real(bounds["load_factor"][0]),
            load_factor <= _to_z3_real(bounds["load_factor"][1]),
            cg_x >= _to_z3_real(bounds["cg_x_m"][0]),
            cg_x <= _to_z3_real(bounds["cg_x_m"][1]),
        )
        req_force = mass * _to_z3_real(gravity_m_s2) * load_factor
        total_capacity = _to_z3_real(str(active_stations_min)) * _to_z3_real(max_station_force_n)
        cg_out_of_span = z3.Or(
            cg_x < _to_z3_real(min_station_str),
            cg_x > _to_z3_real(max_station_str),
        )
        z3_failures: list[Any] = [
            req_force > total_capacity,
            req_force < -total_capacity,
            cg_out_of_span,
        ]
        max_force_dec = Decimal(max_station_force_n)
        moment_checks: list[tuple[Decimal, Decimal]] = []
        if enforce_moment_equilibrium:
            for subset in itertools.combinations(station_decimals, eff_active):
                for pivot in subset:
                    cap_moment = max_force_dec * sum(abs(x - pivot) for x in subset)
                    moment_checks.append((pivot, cap_moment))
                    moment_term = req_force * (cg_x - _to_z3_real(str(pivot)))
                    cap_z3 = _to_z3_real(str(cap_moment))
                    z3_failures.append(moment_term > cap_z3)
                    z3_failures.append(moment_term < -cap_z3)
        solver.add(z3.Or(*z3_failures))

        z3_check = solver.check()
        z3_status_str = (
            "unsat" if z3_check == z3.unsat else ("sat" if z3_check == z3.sat else "unknown")
        )
        z3_cex = None
        if z3_check == z3.sat:
            m = solver.model()
            z3_cex = {
                "mass_kg": _rat_to_decimal_str(m[mass]),
                "load_factor": _rat_to_decimal_str(m[load_factor]),
                "cg_x_m": _rat_to_decimal_str(m[cg_x]),
            }

        cvc5_status_str: str | None = None
        cvc5_cex: dict[str, str] | None = None
        if self.cross_check or z3_status_str == "unknown":
            cs = _new_cvc5_solver(self.timeout_ms)
            real = cs.getRealSort()
            c_mass = cs.mkConst(real, "mass_kg")
            c_lf = cs.mkConst(real, "load_factor")
            c_cg = cs.mkConst(real, "cg_x_m")
            cs.assertFormula(cs.mkTerm(Kind.GEQ, c_mass, _to_cvc5_real(cs, bounds["mass_kg"][0])))
            cs.assertFormula(cs.mkTerm(Kind.LEQ, c_mass, _to_cvc5_real(cs, bounds["mass_kg"][1])))
            cs.assertFormula(cs.mkTerm(Kind.GEQ, c_lf, _to_cvc5_real(cs, bounds["load_factor"][0])))
            cs.assertFormula(cs.mkTerm(Kind.LEQ, c_lf, _to_cvc5_real(cs, bounds["load_factor"][1])))
            cs.assertFormula(cs.mkTerm(Kind.GEQ, c_cg, _to_cvc5_real(cs, bounds["cg_x_m"][0])))
            cs.assertFormula(cs.mkTerm(Kind.LEQ, c_cg, _to_cvc5_real(cs, bounds["cg_x_m"][1])))
            c_req = cs.mkTerm(Kind.MULT, c_mass, _to_cvc5_real(cs, gravity_m_s2), c_lf)
            c_cap = cs.mkTerm(
                Kind.MULT,
                _to_cvc5_real(cs, str(active_stations_min)),
                _to_cvc5_real(cs, max_station_force_n),
            )
            c_neg_cap = cs.mkTerm(Kind.NEG, c_cap)
            c_cg_out = cs.mkTerm(
                Kind.OR,
                cs.mkTerm(Kind.LT, c_cg, _to_cvc5_real(cs, min_station_str)),
                cs.mkTerm(Kind.GT, c_cg, _to_cvc5_real(cs, max_station_str)),
            )
            c_failures: list[Any] = [
                cs.mkTerm(Kind.GT, c_req, c_cap),
                cs.mkTerm(Kind.LT, c_req, c_neg_cap),
                c_cg_out,
            ]
            for pivot, cap_moment in moment_checks:
                arm = cs.mkTerm(Kind.SUB, c_cg, _to_cvc5_real(cs, str(pivot)))
                c_moment = cs.mkTerm(Kind.MULT, c_req, arm)
                c_m_cap = _to_cvc5_real(cs, str(cap_moment))
                c_m_neg_cap = cs.mkTerm(Kind.NEG, c_m_cap)
                c_failures.append(cs.mkTerm(Kind.GT, c_moment, c_m_cap))
                c_failures.append(cs.mkTerm(Kind.LT, c_moment, c_m_neg_cap))
            cs.assertFormula(cs.mkTerm(Kind.OR, *c_failures))
            c_res = cs.checkSat()
            cvc5_status_str = _cvc5_status_str(c_res)
            if cvc5_status_str == "sat":
                cvc5_cex = {
                    "mass_kg": _rat_to_decimal_str(cs.getValue(c_mass)),
                    "load_factor": _rat_to_decimal_str(cs.getValue(c_lf)),
                    "cg_x_m": _rat_to_decimal_str(cs.getValue(c_cg)),
                }

        assumptions = {
            "bounds": bounds,
            "stations": stations,
            "max_station_force_n": max_station_force_n,
            "gravity_m_s2": gravity_m_s2,
            "active_stations_min": active_stations_min,
            "enforce_moment_equilibrium": enforce_moment_equilibrium,
        }
        assertion = "forall (mass, nz, cg) in bounds: |req_force| <= capacity and cg in active span"
        if enforce_moment_equilibrium:
            assertion += " and moment equilibrium feasible"
        return _cached_smt_store(
            cache_key,
            self._reconcile_verdicts(
                property_name="station_equilibrium",
                assumptions=assumptions,
                assertion=assertion,
                z3_status_str=z3_status_str,
                z3_cex=z3_cex,
                z3_reason=str(solver.reason_unknown()) if z3_status_str == "unknown" else "",
                cvc5_status_str=cvc5_status_str,
                cvc5_cex=cvc5_cex,
                proved_reason="Equilibrium authority proved across entire envelope",
                cex_reason="Control envelope violated at counterexample point",
            ),
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

        cache_key = inputs_hash(
            {
                "method": "hover_power",
                "thrust_bounds_n": thrust_bounds_n,
                "disk_area_m2": disk_area_m2,
                "air_density_kg_m3": air_density_kg_m3,
                "figure_of_merit": figure_of_merit,
                "max_power_available_kw": max_power_available_kw,
                "timeout_ms": self.timeout_ms,
                "cross_check": self.cross_check,
            }
        )
        cached = _cached_smt_lookup(cache_key)
        if cached is not None:
            return cached

        solver = z3.Solver()
        solver.set("timeout", self.timeout_ms)
        thrust = z3.Real("thrust_n")
        solver.add(
            thrust >= _to_z3_real(thrust_bounds_n[0]),
            thrust <= _to_z3_real(thrust_bounds_n[1]),
        )
        area = _to_z3_real(disk_area_m2)
        rho = _to_z3_real(air_density_kg_m3)
        fm = _to_z3_real(figure_of_merit)
        p_avail = _to_z3_real(max_power_available_kw)
        rhs_kw_to_w = _to_z3_real("1000") * fm * p_avail
        solver.add((thrust * thrust * thrust) > (_to_z3_real("2") * rho * area * (rhs_kw_to_w**2)))

        z3_check = solver.check()
        z3_status_str = (
            "unsat" if z3_check == z3.unsat else ("sat" if z3_check == z3.sat else "unknown")
        )
        z3_cex = None
        if z3_check == z3.sat:
            m = solver.model()
            z3_cex = {"thrust_n": _rat_to_decimal_str(m[thrust])}

        cvc5_status_str: str | None = None
        cvc5_cex: dict[str, str] | None = None
        if self.cross_check or z3_status_str == "unknown":
            cs = _new_cvc5_solver(self.timeout_ms)
            c_thrust = cs.mkConst(cs.getRealSort(), "thrust_n")
            cs.assertFormula(cs.mkTerm(Kind.GEQ, c_thrust, _to_cvc5_real(cs, thrust_bounds_n[0])))
            cs.assertFormula(cs.mkTerm(Kind.LEQ, c_thrust, _to_cvc5_real(cs, thrust_bounds_n[1])))
            c_rhs_w = cs.mkTerm(
                Kind.MULT,
                _to_cvc5_real(cs, "1000"),
                _to_cvc5_real(cs, figure_of_merit),
                _to_cvc5_real(cs, max_power_available_kw),
            )
            c_rhs = cs.mkTerm(
                Kind.MULT,
                _to_cvc5_real(cs, "2"),
                _to_cvc5_real(cs, air_density_kg_m3),
                _to_cvc5_real(cs, disk_area_m2),
                c_rhs_w,
                c_rhs_w,
            )
            c_t3 = cs.mkTerm(Kind.MULT, c_thrust, c_thrust, c_thrust)
            cs.assertFormula(cs.mkTerm(Kind.GT, c_t3, c_rhs))
            c_res = cs.checkSat()
            cvc5_status_str = _cvc5_status_str(c_res)
            if cvc5_status_str == "sat":
                cvc5_cex = {"thrust_n": _rat_to_decimal_str(cs.getValue(c_thrust))}

        assumptions = {
            "thrust_bounds_n": thrust_bounds_n,
            "disk_area_m2": disk_area_m2,
            "air_density_kg_m3": air_density_kg_m3,
            "figure_of_merit": figure_of_merit,
            "max_power_available_kw": max_power_available_kw,
        }
        assertion = "forall thrust in bounds: T^3 <= 2 * rho * A * (1000 * FM * P_avail)^2"
        return _cached_smt_store(
            cache_key,
            self._reconcile_verdicts(
                property_name="hover_power_envelope",
                assumptions=assumptions,
                assertion=assertion,
                z3_status_str=z3_status_str,
                z3_cex=z3_cex,
                z3_reason=str(solver.reason_unknown()) if z3_status_str == "unknown" else "",
                cvc5_status_str=cvc5_status_str,
                cvc5_cex=cvc5_cex,
                proved_reason="Shaft power stays within available budget across thrust interval",
                cex_reason="Power budget exceeded at counterexample thrust",
            ),
        )
