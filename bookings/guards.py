"""Run guard cases in a candidate's actual API module without editing its sources."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

if len(sys.argv) != 2:
    sys.exit("usage: python3 bookings/guards.py /path/to/api-candidate")
api = Path(sys.argv[1]).resolve()
source = Path(__file__).resolve().parent / "routes/validation_test.go"
helper = Path(__file__).resolve().parents[1] / "integration/guards/router_test.go"
with TemporaryDirectory() as directory:
    overlay = Path(directory) / "overlay.json"
    target = api / "internal/controller/diwu70_test.go"
    replacements = {
        str(target): str(source),
        str(target.with_name("qa_guard_router_test.go")): str(helper),
    }
    overlay.write_text(json.dumps({"Replace": replacements}))
    subprocess.run(["go", "test", "-mod=readonly", "-overlay", str(overlay), "-count=1",
                    "-v", "-run", "^TestDIWU70Guards$", "./internal/controller"], cwd=api, check=True)
