"""Run the QA-owned test with the candidate Go module's internal packages and lockfile."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('api', type=Path, help='tested API worktree root')
args = parser.parse_args()
api = args.api.resolve()
source = Path(__file__).with_name('waitlist_test.go').resolve()
with tempfile.TemporaryDirectory() as tmp:
    overlay = Path(tmp) / 'overlay.json'
    target = api / 'internal/controller/diwu63_waitlist_qa_test.go'
    overlay.write_text(json.dumps({'Replace': {str(target): str(source)}}))
    subprocess.run(['go', 'test', '-mod=readonly', '-overlay', str(overlay), '-count=1',
                    '-v', './internal/controller', '-run', '^TestDIWU63WaitlistBoundary$'],
                   cwd=api, check=True)
