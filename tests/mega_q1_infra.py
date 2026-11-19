"""Q1 Mega-Test Suite: Postgres/RLS, 100k Scale, 150MB S3 WORM, 500p Parallel PDF & OTLP."""

from __future__ import annotations

import base64
import concurrent.futures
import ctypes
import ctypes.wintypes
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pymupdf
import pytest
import yaml
from evidence_api.app import create_app
from evidence_ingest.blocks import IngestAbstain
from evidence_ingest.pdf import (
    detect_page_modality,
    ingest_pdf_bytes,
    ingest_pdf_parallel,
)
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.ledger import Ledger, LedgerError
from evidence_kernel.pg_ledger import (
    PostgresConnectionPool,
    PostgresLedger,
    create_shared_sqlite_pg_connect_fn,
    postgresql_rls_and_index_ddl,
)
from evidence_kernel.storage import (
    LocalFilesystemBlobStore,
    LocalS3WORMTransport,
    S3CompatibleBlobStore,
    S3ObjectLockPolicy,
    StorageAccessDeniedError,
)
from evidence_kernel.telemetry import get_telemetry
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]


def _process_rss_mb() -> float:
    """Cross-platform current process RSS in MiB."""
    if sys.platform == "win32":

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.wintypes.DWORD),
                ("PageFaultCount", ctypes.wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        get_proc = ctypes.windll.kernel32.GetCurrentProcess
        get_proc.restype = ctypes.wintypes.HANDLE
        get_mem = ctypes.windll.psapi.GetProcessMemoryInfo
        get_mem.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
        ]
        get_mem.restype = ctypes.wintypes.BOOL
        handle = get_proc()
        if get_mem(handle, ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize / (1024.0 * 1024.0)
    try:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except Exception:
        return 0.0


def _make_sample_body(tenant: str, idx: int) -> dict[str, Any]:
    marker = f"{tenant}-{idx}"
    env = make_envelope(
        sources=[project_source("q1-mega", f"https://aeroregu.local/{idx}", "ASSUMPTION")],
        method_version="calc@1.0.0",
        inputs={"marker": marker, "margin_safety": "0.250"},
        confidence="deterministic",
        result={"marker": marker, "margin_safety": "0.250"},
    )
    return {
        "event_type": "calc",
        "tenant_id": tenant,
        "actor_id": f"author-{idx % 4}",
        "created_at": "2026-11-14T10:00:00Z",
        "payload": {"marker": marker, "margin_safety": "0.250"},
        "envelope": env,
    }


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, int(round((pct / 100.0) * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def test_q1_mega_1_32_workers_multi_tenant_rls_and_distributed_cache(tmp_path: Path) -> None:
    db_file = tmp_path / "pg_cluster.sqlite"
    ddl_list = postgresql_rls_and_index_ddl()
    ddl = "\n".join(ddl_list)
    assert "ENABLE ROW LEVEL SECURITY" in ddl
    assert "CREATE POLICY" in ddl
    assert "USING (tenant_id = current_setting('app.current_tenant', true))" in ddl
    assert "CREATE INDEX" in ddl

    connect_fn = create_shared_sqlite_pg_connect_fn(db_file)
    pool = PostgresConnectionPool(
        "postgresql://aeroregu@localhost:5432/evidence",
        connect_fn=connect_fn,
        max_size=32,
        max_retries=20,
        backoff_base_s=0.002,
    )
    tenants = ["airbus-evtol", "safran-prop", "thales-avionics"]
    ledgers = {
        t: PostgresLedger(
            "postgresql://aeroregu@localhost:5432/evidence",
            t,
            pool=pool,
            checkpoint_interval=250,
        )
        for t in tenants
    }

    def _worker_write(worker_id: int) -> int:
        t = tenants[worker_id % len(tenants)]
        local_handle = PostgresLedger(
            "postgresql://aeroregu@localhost:5432/evidence",
            t,
            pool=pool,
            checkpoint_interval=250,
        )
        written = 0
        # 32 workers * 300 events = 9,600 events across 3 tenants with concurrent contention
        batch = [_make_sample_body(t, worker_id * 1000 + j) for j in range(150)]
        local_handle.append_batch(batch[:75], chunk_size=75)
        written += 75
        local_handle.append_batch(batch[75:], chunk_size=75)
        written += 75
        return written

    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as ex:
        futs = [ex.submit(_worker_write, wid) for wid in range(32)]
        counts = [f.result() for f in concurrent.futures.as_completed(futs)]

    assert sum(counts) == 32 * 150
    for t, ldg in ledgers.items():
        summary = ldg.coverage_summary_fast()
        expected_workers = sum(1 for wid in range(32) if tenants[wid % len(tenants)] == t)
        assert summary["event_count"] == expected_workers * 150
        assert ldg.verify() is True

    # Strict RLS enforcement across tenant contexts
    airbus = ledgers["airbus-evtol"]
    with pytest.raises(LedgerError, match="rls_cross_tenant_context_denied"):
        airbus.set_tenant_context("safran-prop")

    safran_evs = ledgers["safran-prop"].events(limit=50)
    airbus_hashes = {ev["event_hash"] for ev in airbus.events(limit=50)}
    assert all(ev["body"]["tenant_id"] == "safran-prop" for ev in safran_evs)
    assert not any(ev["event_hash"] in airbus_hashes for ev in safran_evs)

    # Cross-worker DistributedCacheCoordinator invalidation
    worker_a = PostgresLedger(
        "postgresql://aeroregu@localhost:5432/evidence",
        "airbus-evtol",
        pool=pool,
    )
    worker_b = PostgresLedger(
        "postgresql://aeroregu@localhost:5432/evidence",
        "airbus-evtol",
        pool=pool,
    )
    e0 = worker_a.cache.current_epoch("coverage_summary")
    changed_before, _ = worker_a.cache.has_changed("coverage_summary", seen_epoch=e0)
    assert changed_before is False
    next_epoch = worker_b.cache.invalidate("coverage_summary", {"reason": "ecn_rev_b"})
    changed_after, seen_remote = worker_a.cache.has_changed("coverage_summary", seen_epoch=e0)
    assert changed_after is True
    assert seen_remote == next_epoch
    pool.close_all()


def test_q1_mega_2_100k_events_p95_under_150ms_and_rss_under_512mb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "scale_home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EVIDENCE_HOME", str(home))
    tenant = "airbus-evtol"
    ledger_dir = home / "tenants"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(ledger_dir / f"{tenant}.sqlite3", tenant)

    rss_before = _process_rss_mb()

    # Build 100,000 events re-using a validated template structure with unique markers
    base_env = make_envelope(
        sources=[project_source("q1-scale", "https://aeroregu.local/scale", "ASSUMPTION")],
        method_version="calc@1.0.0",
        inputs={"marker": "base", "margin_safety": "0.180"},
        confidence="deterministic",
        result={"marker": "base", "margin_safety": "0.180"},
    )
    chunk_size = 5000
    for offset in range(0, 100_000, chunk_size):
        chunk = [
            {
                "event_type": "calc",
                "tenant_id": tenant,
                "actor_id": "author-scale",
                "created_at": "2026-11-14T10:00:00Z",
                "payload": {"marker": f"cell-{offset + i}", "margin_safety": "0.180"},
                "envelope": base_env,
            }
            for i in range(chunk_size)
        ]
        ledger.append_batch(chunk, chunk_size=2500, checkpoint_interval=1000, validate_schema=False)

    assert ledger.coverage_summary_fast()["event_count"] == 100_000
    assert ledger.verify_incremental(from_latest_checkpoint=True)["ok"] is True

    app = create_app()
    client = TestClient(app)

    # First call warms merkle root & briefing caches; measure 25-call distribution including warmup
    latencies: dict[str, list[float]] = {
        "/coverage/summary": [],
        "/ledger/verify": [],
        "/overnight/briefing": [],
    }
    for ep in latencies:
        for _ in range(25):
            t0 = time.perf_counter()
            resp = client.get(ep, params={"tenant_id": tenant})
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            assert resp.status_code == 200
            data = resp.json()["result"]
            if ep == "/ledger/verify":
                assert data["chain_verified"] is True
                assert int(data["event_count"]) == 100_000
            elif ep == "/coverage/summary":
                assert int(data["event_count"]) == 100_000
            latencies[ep].append(elapsed_ms)

    rss_after = _process_rss_mb()
    rss_delta = max(0.0, rss_after - rss_before)
    assert rss_delta < 512.0, f"RSS growth exceeded 512 MB: {rss_delta:.1f} MB"

    for ep, vals in latencies.items():
        vals_sorted = sorted(vals)
        p95 = _percentile(vals_sorted, 95.0)
        assert p95 < 150.0, f"{ep} p95 {p95:.2f} ms >= 150 ms (samples={vals_sorted[-5:]})"


def test_q1_mega_3_150mb_streaming_multipart_s3_worm_and_kms(tmp_path: Path) -> None:
    transport = LocalS3WORMTransport(tmp_path / "s3_worm_root")
    store = S3CompatibleBlobStore(
        endpoint="https://minio.aeroregu.local",
        bucket="aeroregu-worm-vault",
        access_key="AKIAQ1MEGAKEY",
        secret_key="q1-mega-secret-key",
        transport=transport,
    )

    chunk_bytes = 8 * 1024 * 1024  # 8 MiB
    total_target = 150 * 1024 * 1024  # 150 MiB
    expected_hasher = hashlib.sha256()

    def _chunk_stream():
        remaining = total_target
        part_idx = 0
        while remaining > 0:
            sz = min(chunk_bytes, remaining)
            unit = f"BLK{part_idx:04d}-AERO-OP2".encode("ascii")  # 16 bytes
            pattern = unit * ((sz // len(unit)) + 1)
            piece = pattern[:sz]
            expected_hasher.update(piece)
            remaining -= sz
            part_idx += 1
            yield piece

    policy = S3ObjectLockPolicy(
        mode="COMPLIANCE",
        retain_until_iso="2036-01-01T00:00:00Z",
        kms_key_id="alias/aeroregu-certification-cmk",
    )
    meta = store.put_blob_multipart(
        _chunk_stream(),
        chunk_size=chunk_bytes,
        content_type="application/octet-stream",
        filename="wing_spar_full_fem.op2",
        retention=policy,
    )

    expected_sha = expected_hasher.hexdigest()
    assert meta["sha256"] == expected_sha
    assert meta["size_bytes"] == total_target
    assert meta["multipart"] is True
    assert meta["part_count"] == 19  # ceil(150 / 8)
    assert len(meta["part_checksums"]) == 19
    assert meta["sse_algorithm"] == "aws:kms"
    assert meta["kms_key_id"] == "alias/aeroregu-certification-cmk"
    assert meta["object_lock_mode"] == "COMPLIANCE"

    headed = store.head_blob(expected_sha)
    assert headed is not None
    assert headed["sse_algorithm"] == "aws:kms"
    assert headed["object_lock_mode"] == "COMPLIANCE"

    # WORM lock blocks DELETE and OVERWRITE with 403 AccessDenied
    with pytest.raises(StorageAccessDeniedError, match="403 AccessDenied"):
        store.delete_blob(expected_sha)
    with pytest.raises(StorageAccessDeniedError, match="403 AccessDenied"):
        store.overwrite_blob(expected_sha, b"tampered-payload")

    # Local filesystem store streaming verify check
    local_store = LocalFilesystemBlobStore(tmp_path / "local_blobs")
    local_meta = local_store.put_blob(
        b"WORM-LOCAL-STREAM-DATA",
        filename="local_worm.bin",
        retention=S3ObjectLockPolicy(
            mode="GOVERNANCE",
            retain_until_iso="2036-01-01T00:00:00Z",
            kms_key_id="alias/local-cmk",
        ),
    )
    assert local_store.verify_blob_stream(local_meta["sha256"]) is True
    with pytest.raises(StorageAccessDeniedError):
        local_store.delete_blob(local_meta["sha256"])


def _build_500_page_hybrid_pdf() -> bytes:
    """Construct a crisp 500-page hybrid vector + raster PDF in memory."""
    img = np.full((64, 160), 255, dtype=np.uint8)
    cv2.putText(img, "PID 2001", (8, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2)
    ok, png_buf = cv2.imencode(".png", img)
    assert ok
    png_bytes = bytes(png_buf)

    doc = pymupdf.open()
    for i in range(1, 501):
        page = doc.new_page(width=595, height=842)
        sep = " | " if (i % 50 == 0) else "; "
        page.insert_text(
            (48, 72),
            (
                f"AERO-STRESS-2026 Section {i}{sep}Loadcase LC-{i:03d}{sep}"
                f"MS = +0.42{sep}Req CS-23.305"
            ),
            fontsize=11,
        )
        if i % 5 == 0:
            page.insert_image(pymupdf.Rect(48, 120, 208, 184), stream=png_bytes)
    raw = doc.tobytes()
    doc.close()
    return raw


def _build_degraded_blurry_pdf() -> bytes:
    """Construct a severely blurred/low-contrast scanned raster page with no vector text."""
    flat = np.full((128, 128), 180, dtype=np.uint8)
    flat[60:64, 40:88] = 179  # near-zero contrast & variance
    blurred = cv2.GaussianBlur(flat, (15, 15), 5.0)
    ok, png_buf = cv2.imencode(".png", blurred)
    assert ok
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=400)
    page.insert_image(pymupdf.Rect(20, 20, 380, 380), stream=bytes(png_buf))
    raw = doc.tobytes()
    doc.close()
    return raw


def test_q1_mega_4_500_page_parallel_pdf_ocr_abstention_and_observability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path / "obs_home"))
    get_telemetry().reset()

    pdf_500 = _build_500_page_hybrid_pdf()
    res = ingest_pdf_parallel(
        pdf_500,
        source_uri="wing_stress_report_500p.pdf",
        max_workers=4,
        chunk_pages=25,
    )
    assert res["total_pages"] == 500
    assert len(res["verified_pages"]) == 500
    assert res["abstained_pages"] == []
    assert res["heavy_pdf_async"] is True
    assert res["pages_per_second"] > 8.0
    assert any(m == "hybrid" for m in res["modalities"].values())
    assert len(res["blocks"]) >= 500

    # Blurred/low-contrast raster scan fails deterministically with low_ocr_confidence
    degraded_pdf = _build_degraded_blurry_pdf()
    with pymupdf.open(stream=degraded_pdf, filetype="pdf") as ddoc:
        mod = detect_page_modality(ddoc.load_page(0), doc=ddoc)
        assert mod["modality"] == "raster_scan"
        assert mod["degraded_scan"] is True

    with pytest.raises(IngestAbstain) as caught:
        ingest_pdf_bytes(degraded_pdf)
    assert caught.value.reason == "low_ocr_confidence"

    par_degraded = ingest_pdf_parallel(degraded_pdf, source_uri="blurred_scan.pdf", max_workers=1)
    assert par_degraded["abstained_pages"][0]["reason"] == "low_ocr_confidence"

    # Async heavy PDF queue -> DaemonRunner -> OTLP + Prometheus + Observability
    app = create_app()
    client = TestClient(app)

    enq_resp = client.post(
        "/ingest/pdf/async",
        json={
            "tenant_id": "airbus-evtol",
            "filename": "wing_stress_500p.pdf",
            "content_base64": base64.b64encode(pdf_500).decode("ascii"),
            "max_workers": 4,
            "chunk_pages": 50,
        },
    )
    assert enq_resp.status_code == 202
    run_resp = client.post("/daemon/jobs/run", json={"tenant_id": "airbus-evtol"})
    assert run_resp.status_code == 200
    assert run_resp.json()["result"]["processed"] >= 1

    # Hit /coverage/summary & /ledger/verify to generate OTLP spans
    assert client.get("/coverage/summary", params={"tenant_id": "airbus-evtol"}).status_code == 200
    assert client.get("/ledger/verify", params={"tenant_id": "airbus-evtol"}).status_code == 200

    otlp_resp = client.get("/telemetry/otlp")
    assert otlp_resp.status_code == 200
    otlp_payload = otlp_resp.json()["result"]
    assert len(otlp_payload["resourceSpans"][0]["scopeSpans"][0]["spans"]) >= 2

    prom_resp = client.get("/metrics/prometheus")
    assert prom_resp.status_code == 200
    assert "aeroregu_pipeline_stage_duration_seconds" in prom_resp.text

    # Validate Grafana dashboard & Prometheus Alertmanager manifests on disk
    grafana_path = REPO_ROOT / "infra" / "observability" / "grafana-dashboard.json"
    alerts_path = REPO_ROOT / "infra" / "observability" / "prometheus-alerts.yaml"
    assert grafana_path.is_file()
    assert alerts_path.is_file()
    grafana_doc = json.loads(grafana_path.read_text(encoding="utf-8"))
    alerts_doc = yaml.safe_load(alerts_path.read_text(encoding="utf-8"))
    assert len(grafana_doc.get("panels", [])) >= 4
    assert len(alerts_doc.get("groups", [])) >= 1
