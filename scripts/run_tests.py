"""One test entry for Windows builds and development, with a portable report."""
from datetime import datetime, timezone
from pathlib import Path
import platform
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
root = Path(__file__).resolve().parents[1]
output = Path(sys.argv[1]) if len(sys.argv) > 1 else root / 'test-results.txt'
output.parent.mkdir(parents=True, exist_ok=True)
with output.open('w', encoding='utf-8') as stream:
    stream.write(f'Tested at: {datetime.now(timezone.utc).isoformat()}\n')
    stream.write(f'Host: {platform.platform()}\nPython: {sys.version.split()[0]}\n')
    stream.write('Synthetic PDFs and fake Outlook objects; no real emails.\n\n')
    suite = unittest.defaultTestLoader.discover(str(root / 'tests'), top_level_dir=str(root))
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
print(output.read_text(encoding='utf-8'))
raise SystemExit(0 if result.wasSuccessful() else 1)
