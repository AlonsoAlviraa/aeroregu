from __future__ import annotations

import sys

from evidence_domain.generate import write_data_files


def main() -> int:
    write_data_files()
    return 0


if __name__ == "__main__":
    sys.exit(main())
