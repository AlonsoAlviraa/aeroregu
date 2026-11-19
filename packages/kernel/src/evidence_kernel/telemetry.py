"""OpenTelemetry OTLP traces/spans, metrics, and Prometheus 0.0.4 exposition."""

from __future__ import annotations

import json
import secrets
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

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
        self.samples.append(val)
        if len(self.samples) > 1000:
            del self.samples[: len(self.samples) - 1000]

    def quantile(self, q: float) -> float:
        if not self.samples:
            return 0.0
        ordered = sorted(self.samples)
        idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
        return ordered[idx]


@dataclass(frozen=True)
class OTLPSpan:
    """OpenTelemetry OTLP-compatible trace span."""

    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    stage: str
    start_time_unix_nano: int
    end_time_unix_nano: int
    duration_ms: float
    status: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def as_otlp_dict(self) -> dict[str, Any]:
        return {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "parentSpanId": self.parent_span_id or "",
            "name": self.name,
            "kind": 1,
            "startTimeUnixNano": str(self.start_time_unix_nano),
            "endTimeUnixNano": str(self.end_time_unix_nano),
            "attributes": [
                {"key": k, "value": {"stringValue": str(v)}}
                for k, v in sorted({"stage": self.stage, **self.attributes}.items())
            ],
            "status": {"code": 1 if self.status == "OK" else 2, "message": self.status},
        }


class OTLPTraceExporter:
    """Exports buffered OTLP HTTP/JSON or OTLP gRPC-equivalent trace batches."""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        service_name: str = "evidence-layer",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/") if endpoint else None
        self.service_name = service_name
        self._client = httpx.Client(transport=transport, timeout=10.0) if endpoint else None
        self.exported_batches: list[dict[str, Any]] = []

    def build_resource_spans(self, spans: list[OTLPSpan]) -> dict[str, Any]:
        return {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": self.service_name}},
                            {
                                "key": "telemetry.sdk.name",
                                "value": {"stringValue": "evidence-otlp"},
                            },
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "evidence_kernel.telemetry", "version": "1.0.0"},
                            "spans": [s.as_otlp_dict() for s in spans],
                        }
                    ],
                }
            ],
            "exported_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "span_count": len(spans),
        }

    def export(self, spans: list[OTLPSpan]) -> dict[str, Any]:
        payload = self.build_resource_spans(spans)
        self.exported_batches.append(payload)
        if self._client is not None and self.endpoint:
            resp = self._client.post(
                f"{self.endpoint}/v1/traces",
                content=json.dumps(payload, sort_keys=True),
                headers={"content-type": "application/json"},
            )
            payload["http_status"] = resp.status_code
        return payload


class TelemetryRegistry:
    """Thread-safe observability sink emitting OpenTelemetry spans/snapshots & Prometheus text."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._smt_histograms: dict[tuple[str, str], _HistogramState] = {}
        self._stage_histograms: dict[str, _HistogramState] = {}
        self._abstain_counts: dict[tuple[str, str], int] = defaultdict(int)
        self._verification_total: int = 0
        self._llm_tokens: dict[tuple[str, str, str], int] = defaultdict(int)
        self._daemon_jobs: dict[tuple[str, str], int] = defaultdict(int)
        self._webhook_deliveries: dict[str, int] = defaultdict(int)
        self._discrepancies: dict[str, int] = defaultdict(int)
        self._spans: list[OTLPSpan] = []
        self._created_monotonic = time.monotonic()

    def reset(self) -> None:
        with self._lock:
            self._smt_histograms.clear()
            self._stage_histograms.clear()
            self._abstain_counts.clear()
            self._verification_total = 0
            self._llm_tokens.clear()
            self._daemon_jobs.clear()
            self._webhook_deliveries.clear()
            self._discrepancies.clear()
            self._spans.clear()

    @contextmanager
    def start_span(
        self,
        name: str,
        *,
        stage: str = "api",
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ):
        """Record an OTLP-compatible span across API -> Worker -> Z3/cvc5 -> PG -> S3."""
        tid = trace_id or secrets.token_hex(16)
        sid = secrets.token_hex(8)
        start_ns = time.time_ns()
        start_mono = time.perf_counter()
        status = "OK"
        attrs = dict(attributes or {})
        span_ctx = {"trace_id": tid, "span_id": sid, "parent_span_id": parent_span_id}
        try:
            yield span_ctx
        except Exception as exc:
            status = f"ERROR:{type(exc).__name__}"
            attrs["error.message"] = str(exc)[:200]
            raise
        finally:
            elapsed_s = max(0.0, time.perf_counter() - start_mono)
            end_ns = time.time_ns()
            span = OTLPSpan(
                trace_id=tid,
                span_id=sid,
                parent_span_id=parent_span_id,
                name=name,
                stage=stage,
                start_time_unix_nano=start_ns,
                end_time_unix_nano=end_ns,
                duration_ms=round(elapsed_s * 1000.0, 4),
                status=status,
                attributes=attrs,
            )
            with self._lock:
                self._spans.append(span)
                if len(self._spans) > 2000:
                    del self._spans[: len(self._spans) - 2000]
                hist = self._stage_histograms.get(stage)
                if hist is None:
                    hist = _HistogramState()
                    self._stage_histograms[stage] = hist
                hist.observe(elapsed_s)

    def recent_spans(self, *, trace_id: str | None = None, limit: int = 200) -> list[OTLPSpan]:
        with self._lock:
            items = (
                [s for s in self._spans if s.trace_id == trace_id]
                if trace_id
                else list(self._spans)
            )
        return items[-max(1, min(limit, 2000)) :]

    def export_otlp(
        self,
        exporter: OTLPTraceExporter | None = None,
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        spans = self.recent_spans(trace_id=trace_id, limit=500)
        exp = exporter or OTLPTraceExporter()
        return exp.export(spans)

    def record_stage_latency(self, stage: str, duration_seconds: float) -> None:
        with self._lock:
            hist = self._stage_histograms.get(stage)
            if hist is None:
                hist = _HistogramState()
                self._stage_histograms[stage] = hist
            hist.observe(duration_seconds)

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

            stages_summary: dict[str, Any] = {}
            for stage, hist in sorted(self._stage_histograms.items()):
                stages_summary[stage] = {
                    "count": hist.count,
                    "p50_ms": round(hist.quantile(0.50) * 1000.0, 3),
                    "p95_ms": round(hist.quantile(0.95) * 1000.0, 3),
                    "p99_ms": round(hist.quantile(0.99) * 1000.0, 3),
                    "max_ms": round(hist.max_seconds * 1000.0, 3),
                }

            return {
                "otel_service_name": "evidence-layer",
                "uptime_seconds": round(time.monotonic() - self._created_monotonic, 2),
                "smt_solver": {
                    "series": smt_summary,
                    "global_p95_ms": global_p95_ms,
                    "total_checks": sum(h.count for h in self._smt_histograms.values()),
                },
                "pipeline_stages": stages_summary,
                "spans_recorded": len(self._spans),
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

            lines.append(
                "# HELP aeroregu_pipeline_stage_duration_seconds End-to-end span stage latency."
            )
            lines.append("# TYPE aeroregu_pipeline_stage_duration_seconds histogram")
            for stage, hist in sorted(self._stage_histograms.items()):
                st_esc = self._esc(stage)
                metric = "aeroregu_pipeline_stage_duration_seconds"
                for bound in _DEFAULT_LATENCY_BUCKETS:
                    lines.append(
                        f'{metric}_bucket{{stage="{st_esc}",le="{bound}"}} {hist.buckets[bound]}'
                    )
                lines.append(f'{metric}_bucket{{stage="{st_esc}",le="+Inf"}} {hist.count}')
                lines.append(f'{metric}_sum{{stage="{st_esc}"}} {hist.total_seconds:.6f}')
                lines.append(f'{metric}_count{{stage="{st_esc}"}} {hist.count}')

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
