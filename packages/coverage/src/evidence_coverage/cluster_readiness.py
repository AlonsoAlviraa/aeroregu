"""Multi-Worker Cache Coordination & PostgreSQL/MinIO/Helm Infrastructure Verification."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import yaml


class SharedWorkerCacheCoordinator:
    """SQLite-WAL cross-process cache version coordinator for multi-worker API replicas."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_epochs (
                    tenant_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    epoch INTEGER NOT NULL DEFAULT 1,
                    head_hash TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (tenant_id, namespace)
                )
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path), timeout=10.0)

    def bump_version(
        self, tenant_id: str, namespace: str = "ledger_head", *, head_hash: str = ""
    ) -> int:
        now = time.time()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT epoch FROM cache_epochs WHERE tenant_id = ? AND namespace = ?",
                (tenant_id, namespace),
            )
            row = cur.fetchone()
            next_epoch = int(row[0]) + 1 if row else 1
            conn.execute(
                """
                INSERT INTO cache_epochs (tenant_id, namespace, epoch, head_hash, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, namespace)
                DO UPDATE SET epoch = excluded.epoch,
                              head_hash = CASE
                                  WHEN excluded.head_hash != '' THEN excluded.head_hash
                                  ELSE cache_epochs.head_hash
                              END,
                              updated_at = excluded.updated_at
                """,
                (tenant_id, namespace, next_epoch, head_hash, now),
            )
            conn.commit()
            return next_epoch

    def get_version(self, tenant_id: str, namespace: str = "ledger_head") -> dict[str, Any]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT epoch, head_hash, updated_at FROM cache_epochs "
                "WHERE tenant_id = ? AND namespace = ?",
                (tenant_id, namespace),
            )
            row = cur.fetchone()
        if not row:
            return {"tenant_id": tenant_id, "namespace": namespace, "epoch": 0, "head_hash": ""}
        return {
            "tenant_id": tenant_id,
            "namespace": namespace,
            "epoch": int(row[0]),
            "head_hash": str(row[1]),
            "updated_at": float(row[2]),
        }

    def is_stale(self, tenant_id: str, observed_epoch: int, namespace: str = "ledger_head") -> bool:
        return int(self.get_version(tenant_id, namespace)["epoch"]) != int(observed_epoch)


def verify_postgres_rls_and_worm_ddl(sql_path: Path) -> dict[str, Any]:
    """Validate PostgreSQL RLS tenant isolation and WORM append-only triggers in init SQL."""
    p = Path(sql_path)
    if not p.is_file():
        return {"verified": False, "reason": "missing_init_sql", "path": str(p)}
    text = p.read_text(encoding="utf-8")
    upper = text.upper()
    checks = {
        "has_table_ledger_events": "CREATE TABLE" in upper and "LEDGER_EVENTS" in upper,
        "has_enable_rls": "ENABLE ROW LEVEL SECURITY" in upper,
        "has_force_rls": "FORCE ROW LEVEL SECURITY" in upper,
        "has_tenant_policy": "CREATE POLICY" in upper and "APP.CURRENT_TENANT" in upper,
        "has_worm_trigger": "BEFORE UPDATE OR DELETE ON LEDGER_EVENTS" in upper,
    }
    return {
        "verified": all(checks.values()),
        "checks": checks,
        "sql_path": str(p),
    }


def verify_cluster_infra_manifests(repo_root: Path) -> dict[str, Any]:
    """Verify Compose, Helm HA templates (Deployment/Service/HPA/PDB), and airgap OCI bundle."""
    root = Path(repo_root)
    compose_p = root / "infra" / "compose.yaml"
    values_p = root / "infra" / "helm" / "aeroregu" / "values.yaml"
    tpl_dir = root / "infra" / "helm" / "aeroregu" / "templates"
    airgap_p = root / "infra" / "airgap" / "oci-bundle-manifest.json"
    sql_p = root / "infra" / "postgres" / "init-rls-worm.sql"

    compose_data = yaml.safe_load(compose_p.read_text(encoding="utf-8"))
    values_data = yaml.safe_load(values_p.read_text(encoding="utf-8"))
    airgap_data = json.loads(airgap_p.read_text(encoding="utf-8"))
    sql_res = verify_postgres_rls_and_worm_ddl(sql_p)

    services = compose_data.get("services") or {}
    pinned_images_ok = all(
        not str(img.get("tag", "")).endswith("latest")
        and str(img.get("digest", "")).startswith("sha256:")
        for img in (airgap_data.get("images") or [])
    )
    tpl_files = {
        name: (tpl_dir / name).is_file()
        for name in ("deployment.yaml", "service.yaml", "hpa.yaml", "pdb.yaml")
    }
    dep_txt = (tpl_dir / "deployment.yaml").read_text(encoding="utf-8")

    checks = {
        "compose_has_api": "api" in services,
        "compose_has_postgres": "postgres" in services,
        "compose_has_minio": "minio" in services,
        "compose_has_redis": "redis" in services,
        "helm_ha_replicas": int(values_data.get("replicaCount", 0)) >= 2,
        "helm_airgap_no_egress": (values_data.get("airgap") or {}).get(
            "allowOutboundInternetEgress"
        )
        is False,
        "helm_worm_enabled": (values_data.get("storage") or {}).get("wormObjectLockEnabled")
        is True,
        "helm_non_root": (values_data.get("security") or {}).get("runAsNonRoot") is True,
        "helm_ro_rootfs": (values_data.get("security") or {}).get("readOnlyRootFilesystem") is True,
        "helm_templates_complete": all(tpl_files.values()),
        "helm_network_policy_egress_locked": "aeroregu-zero-internet-egress" in dep_txt,
        "airgap_manifest_pinned_digests": pinned_images_ok
        and bool(airgap_data.get("airgap_verified"))
        and airgap_data.get("outbound_network_required") is False,
        "postgres_rls_worm_verified": bool(sql_res["verified"]),
    }
    return {
        "verified": all(checks.values()),
        "checks": checks,
        "postgres_ddl": sql_res,
        "helm_templates": tpl_files,
        "airgap_image_count": len(airgap_data.get("images") or []),
    }
