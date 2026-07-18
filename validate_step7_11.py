"""Steps 7-11: Watchlist, Opp, Lifecycle, Dashboard, Events"""
import subprocess, sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "idos-core"))

BASE = Path(__file__).parent
os.chdir(str(BASE))

IDOS_CMD = [sys.executable, "-m", "idos.cli.main"]

def run(args):
    cmd = IDOS_CMD + args
    print(f"\n$ python -m idos.cli.main {' '.join(args)}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = r.stdout.strip()[:300]
    print(f"  OK: {out}" if out else f"  ERR: {r.stderr.strip()[:300]}")
    return r

# Step 7: Watchlist
print("="*60, "\nSTEP 7: Watchlist")
run(["watchlist"])

# Step 8: Create opportunity
print("="*60, "\nSTEP 8: Create opportunity")
run(["opp-create", "GOOGL"])

# Step 9: Lifecycle transitions
print("="*60, "\nSTEP 9: Lifecycle")
r = run(["opp-list"])
if r.returncode == 0:
    for line in r.stdout.strip().split("\n"):
        if "OPP-" in line and "GOOGL" in line:
            opp_id = line.split()[0]
            print(f"  Found: {opp_id}")
            for status in ["SCREENED", "WATCHLIST", "UNDER_RESEARCH"]:
                run(["opp-transition", opp_id, status])
            break

# Step 10: Dashboard
print("="*60, "\nSTEP 10: Dashboard")
run(["dashboard"])

# Step 11: Event log
print("="*60, "\nSTEP 11: Event log")
run(["event-log"])

print("\n" + "="*60)
print("STEPS 7-11 COMPLETE")
