import sys
from pathlib import Path

from idos.site.builder import write_site


def main() -> int:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    stale = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    write_site(base, stale_days=stale)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
