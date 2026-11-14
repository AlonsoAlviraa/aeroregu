"""OpenTelemetry-compatible metrics and Prometheus 0.0.4 exposition for runtime telemetry."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

_DEFAULT_LATENCY_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


@dataclass
class _HistogramState:
    buckets: dict[float, int] = field(
        default_factory=lambda: {b: 0 for b in _DEFAULT_LATENCY_BUCKETS}
    )
    count: int = 0
    total_seconds: float = 0.0
    max_seconds: float = 0.0
    samples: list[float] = field(default_factory=list)

    def observe(self, seconds: float) -> None:
        val = max(0.0, float(seconds))
        self.count += 1
        self.total_seconds += val
        if val > self.max_seconds:
            self.max_seconds = val
        for bound in _DEFAULT_LATENCY_BUCKETS:
            if val <= bound:
                self.buckets[bound] += 1
        # Keep bounded tail window for accurate p50/p95 computation without unbounded memory
        self.samples.append(val)
        if len(self.samples) > 1000:
            del self.samples[: len(self.samples) - 1000]

    def quantile(self, q: float) -> float:
        if not self.samples:
            return 0.0
        ordered = sorted(self.samples)
        idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
        return ordered[idx]


class TelemetryRegistry:
    """Thread-safe observability sink emitting OpenTelemetry-style snapshots & Prometheus text."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._smt_histograms: dict[tuple[str, str], _HistogramState] = {}
        self._abstain_counts: dict[tuple[str, str], int] = defaultdict(int)
        self._verification_total: int = 0
        self._llm_tokens: dict[tuple[str, str, str], int] = defaultdict(int)
        self._daemon_jobs: dict[tuple[str, str], int] = defaultdict(int)
        self._webhook_deliveries: dict[str, int] = defaultdict(int)
        self._discrepancies: dict[str, int] = defaultdict(int)
        self._created_monotonic = time.monotonic()

    def reset(self) -> None:
        with self._lock:
            self._smt_histograms.clear()
            self._abstain_counts.clear()
            self._verification_total = 0
            self._llm_tokens.clear()
            self._daemon_jobs.clear()
            self._webhook_deliveries.clear()
            self._discrepancies.clear()

    def record_smt_latency(self, solver: str, status: str, duration_seconds: float) -> None:
        with self._lock:
            key = (str(solver), str(status).lower())
            hist = self._smt_histograms.get(key)
            if hist is None:
                hist = _HistogramState()
                self._smt_histograms[key] = hist
            hist.observe(duration_seconds)

    def record_verification(self, *, stage: str, abstained: bool, reason: str = "") -> None:
        with self._lock:
            self._verification_total += 1
            if abstained:
                key = (str(stage), str(reason or "unspecified"))
                self._abstain_counts[key] += 1

    def record_llm_tokens(
        self,
        *,
        tier: str,
        agent_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        clean_tier = "edge" if str(tier).lower() in {"edge", "local", "ollama"} else "cloud"
        with self._lock:
            if input_tokens > 0:
                self._llm_tokens[(clean_tier, str(agent_id), "input")] += int(input_tokens)
            if output_tokens > 0:
                self._llm_tokens[(clean_tier, str(agent_id), "output")] += int(output_tokens)

    def record_daemon_job(self, job_type: str, status: str) -> None:
        with self._lock:
            self._daemon_jobs[(str(job_type), str(status))] += 1

    def record_webhook_delivery(self, status: str) -> None:
        with self._lock:
            self._webhook_deliveries[str(status)] += 1

    def record_discrepancy(self, severity: str) -> None:
        with self._lock:
            self._discrepancies[str(severity).upper()] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            smt_summary: dict[str, Any] = {}
            all_samples: list[float] = []
            for (solver, status), hist in sorted(self._smt_histograms.items()):
                all_samples.extend(hist.samples)
                smt_summary[f"{solver}:{status}"] = {
                    "solver": solver,
                    "status": status,
                    "count": hist.count,
                    "avg_ms": round((hist.total_seconds / hist.count) * 1000.0, 3)
                    if hist.count
                    else 0.0,
                    "p50_ms": round(hist.quantile(0.50) * 1000.0, 3),
                    "p95_ms": round(hist.quantile(0.95) * 1000.0, 3),
                    "max_ms": round(hist.max_seconds * 1000.0, 3),
                }

            all_ordered = sorted(all_samples)
            global_p95_ms = (
                round(
                    all_ordered[
                        min(len(all_ordered) - 1, int(round(0.95 * (len(all_ordered) - 1))))
                    ]
                    * 1000.0,
                    3,
                )
                if all_ordered
                else 0.0
            )

            total_abstains = sum(self._abstain_counts.values())
            denom = max(self._verification_total, total_abstains)
            abstain_rate = round(total_abstains / denom, 4) if denom > 0 else 0.0

            edge_tokens = sum(
                val for (tier, _, _), val in self._llm_tokens.items() if tier == "edge"
            )
            cloud_tokens = sum(
                val for (tier, _, _), val in self._llm_tokens.items() if tier == "cloud"
            )
            by_agent: dict[str, dict[str, int]] = {}
            for (tier, agent_id, direction), val in sorted(self._llm_tokens.items()):
                bucket = by_agent.setdefault(
                    agent_id, {"edge": 0, "cloud": 0, "input": 0, "output": 0}
                )
                bucket[tier] += val
                bucket[direction] += val

            return {
                "otel_service_name": "evidence-layer",
                "uptime_seconds": round(time.monotonic() - self._created_monotonic, 2),
                "smt_solver": {
                    "series": smt_summary,
                    "global_p95_ms": global_p95_ms,
                    "total_checks": sum(h.count for h in self._smt_histograms.values()),
                },
                "abstain": {
                    "total": total_abstains,
                    "verifications_total": self._verification_total,
                    "rate": abstain_rate,
                    "by_stage_reason": {
                        f"{st}:{rs}": cnt for (st, rs), cnt in sorted(self._abstain_counts.items())
                    },
                },
                "tokens": {
                    "edge_total": edge_tokens,
                    "cloud_total": cloud_tokens,
                    "total": edge_tokens + cloud_tokens,
                    "by_agent": by_agent,
                },
                "daemon_jobs": {
                    f"{jt}:{st}": cnt for (jt, st), cnt in sorted(self._daemon_jobs.items())
                },
                "webhooks": dict(sorted(self._webhook_deliveries.items())),
                "cross_artifact_discrepancies": dict(sorted(self._discrepancies.items())),
            }

    @staticmethod
    def _esc(val: str) -> str:
        return val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    def render_prometheus(self) -> str:
        """Render Prometheus 0.0.4 text exposition format."""
        lines: list[str] = []
        with self._lock:
            lines.append(
                "# HELP aeroregu_smt_solver_duration_seconds SMT solver latency in seconds."
            )
            lines.append("# TYPE aeroregu_smt_solver_duration_seconds histogram")
            for (solver, status), hist in sorted(self._smt_histograms.items()):
                s_esc = self._esc(solver)
                st_esc = self._esc(status)
                metric = "aeroregu_smt_solver_duration_seconds"
                for bound in _DEFAULT_LATENCY_BUCKETS:
                    lines.append(
                        f'{metric}_bucket{{solver="{s_esc}",status="{st_esc}",le="{bound}"}} '
                        f"{hist.buckets[bound]}"
                    )
                lines.append(
                    f'{metric}_bucket{{solver="{s_esc}",status="{st_esc}",le="+Inf"}} {hist.count}'
                )
                lines.append(
                    f'{metric}_sum{{solver="{s_esc}",status="{st_esc}"}} {hist.total_seconds:.6f}'
                )
                lines.append(f'{metric}_count{{solver="{s_esc}",status="{st_esc}"}} {hist.count}')

            lines.append("# HELP aeroregu_verifications_total Total verification checks recorded.")
            lines.append("# TYPE aeroregu_verifications_total counter")
            lines.append(f"aeroregu_verifications_total {self._verification_total}")

            lines.append("# HELP aeroregu_abstain_total Total fail-closed abstentions.")
            lines.append("# TYPE aeroregu_abstain_total counter")
            for (stage, reason), cnt in sorted(self._abstain_counts.items()):
                s_l = self._esc(stage)
                r_l = self._esc(reason)
                lines.append(f'aeroregu_abstain_total{{stage="{s_l}",reason="{r_l}"}} {cnt}')

            total_abstains = sum(self._abstain_counts.values())
            denom = max(self._verification_total, total_abstains)
            rate = (total_abstains / denom) if denom > 0 else 0.0
            lines.append("# HELP aeroregu_abstain_rate Current fail-closed abstain ratio (0..1).")
            lines.append("# TYPE aeroregu_abstain_rate gauge")
            lines.append(f"aeroregu_abstain_rate {rate:.6f}")

            lines.append(
                "# HELP aeroregu_llm_tokens_total Total LLM tokens processed "
                "(split by tier edge vs cloud)."
            )
            lines.append("# TYPE aeroregu_llm_tokens_total counter")
            for (tier, agent_id, direction), cnt in sorted(self._llm_tokens.items()):
                t_l = self._esc(tier)
                a_l = self._esc(agent_id)
                d_l = self._esc(direction)
                lines.append(
                    f'aeroregu_llm_tokens_total{{tier="{t_l}",agent="{a_l}",'
                    f'direction="{d_l}"}} {cnt}'
                )

            lines.append("# HELP aeroregu_daemon_jobs_total Background daemon jobs.")
            lines.append("# TYPE aeroregu_daemon_jobs_total counter")
            for (jt, st), cnt in sorted(self._daemon_jobs.items()):
                lines.append(
                    f'aeroregu_daemon_jobs_total{{job_type="{self._esc(jt)}",'
                    f'status="{self._esc(st)}"}} {cnt}'
                )

            lines.append("# HELP aeroregu_webhook_deliveries_total Webhook deliveries by status.")
            lines.append("# TYPE aeroregu_webhook_deliveries_total counter")
            for st, cnt in sorted(self._webhook_deliveries.items()):
                lines.append(f'aeroregu_webhook_deliveries_total{{status="{self._esc(st)}"}} {cnt}')

            lines.append(
                "# HELP aeroregu_cross_artifact_discrepancies_total "
                "Detected cross-artifact inconsistencies."
            )
            lines.append("# TYPE aeroregu_cross_artifact_discrepancies_total counter")
            for sev, cnt in sorted(self._discrepancies.items()):
                lines.append(
                    f"aeroregu_cross_artifact_discrepancies_total"
                    f'{{severity="{self._esc(sev)}"}} {cnt}'
                )

        return "\n".join(lines) + "\n"


_GLOBAL_TELEMETRY = TelemetryRegistry()


def get_telemetry() -> TelemetryRegistry:
    """Return process-wide telemetry registry."""
    return _GLOBAL_TELEMETRY
