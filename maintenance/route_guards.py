"""Mount QA test into a candidate Go module with Go's read-only overlay."""
import argparse
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("api", type=Path)
args = parser.parse_args()
target = args.api.resolve() / "internal/controller/diwu68_guard_test.go"
source = Path(__file__).with_name("route_guard_test.go").resolve()
with TemporaryDirectory() as tmp:
    overlay = Path(tmp) / "overlay.json"
    overlay.write_text(json.dumps({"Replace": {str(target): str(source)}}))
    subprocess.run(["go", "test", "-overlay", str(overlay), "-mod=readonly", "-count=1",
                    "-v", "-run", "^TestMaintenanceGuardsDIWU68$", "./internal/controller"],
                   cwd=args.api, check=True)
