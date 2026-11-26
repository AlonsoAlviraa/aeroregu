"""Modular FastAPI routers extracted from apps/api/src/evidence_api/app.py."""

from __future__ import annotations

from evidence_api.routers.cad_cae_plm import build_cad_cae_plm_router
from evidence_api.routers.enterprise_ops import build_enterprise_ops_router
from evidence_api.routers.quotations import build_quotations_router
from evidence_api.routers.security_audit import build_security_audit_router
from evidence_api.routers.sprint7_engineering import build_sprint7_engineering_router

__all__ = [
    "build_cad_cae_plm_router",
    "build_enterprise_ops_router",
    "build_quotations_router",
    "build_security_audit_router",
    "build_sprint7_engineering_router",
]
