from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

from evidence_kernel.attestation import verify_attestation_dsse
from evidence_kernel.canonical import canonicalize
from evidence_kernel.ledger import GENESIS, verify_chain_document
from evidence_kernel.merkle import inclusion_proof, merkle_root, verify_inclusion_proof


def verify_zip_bundle(
    zip_path: Path,
    *,
    public_key_pem: bytes | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Offline verification of an exported dossier ZIP (chain + Merkle root + DSSE Ed25519)."""
    report: dict[str, Any] = {
        "bundle": str(zip_path),
        "chain_ok": False,
        "merkle_ok": False,
        "dsse_present": False,
        "dsse_signature_ok": False,
        "dsse_digest_ok": False,
        "event_count": 0,
        "merkle_root": None,
        "error": None,
    }
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            names = set(archive.namelist())
            if "chain.json" not in names:
                report["error"] = "missing_chain_json"
                return False, report
            chain = json.loads(archive.read("chain.json").decode("utf-8"))
            chain_ok = verify_chain_document(chain)
            report["chain_ok"] = chain_ok
            report["event_count"] = len(chain)
            if not chain_ok:
                report["error"] = "invalid_ledger_chain"
                return False, report

            hashes = [str(ev["event_hash"]) for ev in chain]
            actual_merkle = merkle_root(hashes)
            actual_head = str(chain[-1]["event_hash"]) if chain else GENESIS
            report["merkle_root"] = actual_merkle

            merkle_ok = True
            if "merkle_root.txt" in names:
                recorded_merkle = archive.read("merkle_root.txt").decode("utf-8").strip()
                merkle_ok = recorded_merkle == actual_merkle
            report["merkle_ok"] = merkle_ok
            if not merkle_ok:
                report["error"] = "merkle_root_mismatch"
                return False, report

            if (
                "attestation_bundle.json" not in names
                or "attestation_bundle.dsse.json" not in names
            ):
                report["error"] = "missing_dsse_attestation"
                return False, report

            pub_pem = public_key_pem
            if pub_pem is None:
                if "attestation_public_key.pem" not in names:
                    report["error"] = "missing_attestation_public_key"
                    return False, report
                pub_pem = archive.read("attestation_public_key.pem")

            report["dsse_present"] = True
            att_bundle = json.loads(archive.read("attestation_bundle.json").decode("utf-8"))
            dsse_env = json.loads(archive.read("attestation_bundle.dsse.json").decode("utf-8"))

            sig_ok, decoded = verify_attestation_dsse(dsse_env, pub_pem)
            report["dsse_signature_ok"] = sig_ok
            if not sig_ok or decoded is None:
                report["error"] = "invalid_dsse_signature"
                return False, report

            digest_ok = canonicalize(decoded) == canonicalize(att_bundle)
            subjects = decoded.get("subject") or []
            if subjects and isinstance(subjects[0], dict):
                subj_digest = subjects[0].get("digest") or {}
                digest_ok = digest_ok and (
                    subj_digest.get("merkle_root") == actual_merkle
                    and subj_digest.get("sha256") == actual_head
                )
            else:
                digest_ok = False
            report["dsse_digest_ok"] = digest_ok
            if not digest_ok:
                report["error"] = "dsse_digest_mismatch"
                return False, report
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        return False, report

    return True, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evidence_kernel")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("path")
    verify.add_argument("--public-key", default=None, help="Optional Ed25519 public key PEM path")
    verify.add_argument("--json", action="store_true", help="Print structured verification report")

    mroot = sub.add_parser("merkle-root")
    mroot.add_argument("path")

    prove = sub.add_parser("prove")
    prove.add_argument("path")
    prove.add_argument("event_hash")

    verify_proof = sub.add_parser("verify-proof")
    verify_proof.add_argument("path")

    args = parser.parse_args(argv)
    target = Path(args.path)
    if args.command == "verify":
        if target.suffix.lower() == ".zip" or zipfile.is_zipfile(target):
            pub_pem = Path(args.public_key).read_bytes() if args.public_key else None
            ok, report = verify_zip_bundle(target, public_key_pem=pub_pem)
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print("ok" if ok else "fail")
            return 0 if ok else 1
        document = json.loads(target.read_text(encoding="utf-8"))
        ok = verify_chain_document(document)
        if args.json:
            print(json.dumps({"bundle": str(target), "chain_ok": ok}, indent=2, sort_keys=True))
        else:
            print("ok" if ok else "fail")
        return 0 if ok else 1

    document = json.loads(target.read_text(encoding="utf-8"))
    if args.command == "merkle-root":
        hashes = [str(event["event_hash"]) for event in document]
        print(merkle_root(hashes))
        return 0
    if args.command == "prove":
        hashes = [str(event["event_hash"]) for event in document]
        try:
            proof = inclusion_proof(hashes, args.event_hash)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(proof, indent=2, sort_keys=True))
        return 0
    if args.command == "verify-proof":
        ok = verify_inclusion_proof(
            str(document.get("target_hash", "")),
            document.get("audit_path", []),
            str(document.get("merkle_root", "")),
        )
        print("ok" if ok else "fail")
        return 0 if ok else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
