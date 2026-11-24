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
helper = Path(__file__).resolve().parents[1] / "integration/guards/router_test.go"
with TemporaryDirectory() as tmp:
    overlay = Path(tmp) / "overlay.json"
    replacements = {
        str(target): str(source),
        str(target.with_name("qa_guard_router_test.go")): str(helper),
    }
    overlay.write_text(json.dumps({"Replace": replacements}))
    subprocess.run(["go", "test", "-overlay", str(overlay), "-mod=readonly", "-count=1",
                    "-v", "-run", "^TestMaintenanceGuardsDIWU68$", "./internal/controller"],
                   cwd=args.api, check=True)
