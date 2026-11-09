from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evidence_kernel.ledger import verify_chain_document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evidence_kernel")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("path")
    args = parser.parse_args(argv)
    document = json.loads(Path(args.path).read_text(encoding="utf-8"))
    ok = verify_chain_document(document)
    print("ok" if ok else "fail")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
