"""Generate a synthetic check-only pack. Never use it as management output."""
import argparse
from datetime import date
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.helpers import pack

p = argparse.ArgumentParser()
p.add_argument('folder', type=Path)
p.add_argument('--audit', type=date.fromisoformat, default=date(2026, 9, 10))
p.add_argument('--business', type=date.fromisoformat, default=date(2026, 9, 11))
a = p.parse_args()
if a.folder.exists():
    p.error('Choose a new folder; this script never overwrites existing files.')
pack(a.folder, a.audit, a.business)
print('Synthetic check-only pack created. Do not email it to management.')
