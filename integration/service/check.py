"""Run explicit service inputs against a fresh migrated candidate database."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("api", type=Path)
api = parser.parse_args().api.resolve()
source = Path(__file__).with_name("explicit_test.go").resolve()
with tempfile.TemporaryDirectory() as tmp:
    overlay = Path(tmp) / "overlay.json"
    overlay.write_text(json.dumps({"Replace": {
        str(api / "internal/service/qa_explicit_test.go"): str(source),
    }}))
    subprocess.run(["go", "test", "-mod=readonly", "-overlay", str(overlay),
                    "-count=1", "-run", "^TestExplicitOperator$", "-v", "./internal/service"],
                   cwd=api, check=True)
