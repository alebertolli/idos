"""Steps 2-5: Init, Company, CLI"""
import subprocess, sys, json, os
from pathlib import Path

BASE = Path(__file__).parent
os.chdir(str(BASE))

IDOS_CMD = [sys.executable, "-m", "idos.cli.main"]

def run(args):
    cmd = IDOS_CMD + args
    print(f"\n$ python -m idos.cli.main {' '.join(args)}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ERROR: {r.stderr.strip() or r.stdout.strip()}")
        return False
    print(f"  OK: {r.stdout.strip()[:300]}")
    return True

# Step 2: Init
print("="*60, "\nSTEP 2: Init")
run(["init"])

# Step 3: Universe config
print("="*60, "\nSTEP 3: Universe")
u_path = Path("idos-config/universe/watchlist.md")
if u_path.exists():
    content = u_path.read_text(encoding="utf-8")
    if "GOOGL" in content:
        print("  OK: GOOGL found in watchlist.md")
    else:
        u_path.write_text(content + "\n| GOOGL | Alphabet | Technology | $2T | Moat digital | ALTA |\n", encoding="utf-8")
        print("  OK: Added GOOGL to watchlist.md")
else:
    print("  WARN: watchlist.md not found")

# Step 4: Company add
print("="*60, "\nSTEP 4: Company add")
run(["company-add", "GOOGL", "--name", "Alphabet Inc.", "--sector", "Technology"])

# Step 5: Company show
print("="*60, "\nSTEP 5: Company show")
run(["company-show", "GOOGL"])

print("\n" + "="*60)
print("STEPS 2-5 COMPLETE")
