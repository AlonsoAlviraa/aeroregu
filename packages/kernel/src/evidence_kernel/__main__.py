from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evidence_kernel.ledger import verify_chain_document
from evidence_kernel.merkle import inclusion_proof, merkle_root, verify_inclusion_proof


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evidence_kernel")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("path")

    mroot = sub.add_parser("merkle-root")
    mroot.add_argument("path")

    prove = sub.add_parser("prove")
    prove.add_argument("path")
    prove.add_argument("event_hash")

    verify_proof = sub.add_parser("verify-proof")
    verify_proof.add_argument("path")

    args = parser.parse_args(argv)
    document = json.loads(Path(args.path).read_text(encoding="utf-8"))
    if args.command == "verify":
        ok = verify_chain_document(document)
        print("ok" if ok else "fail")
        return 0 if ok else 1
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
