"""Collect installed dependency license notices for the portable distribution."""
from importlib.metadata import distributions
from pathlib import Path
import sys

sections = ['Third-party dependency notices\n', 'Python runtime license: https://docs.python.org/3/license.html\n']
for dist in sorted(distributions(), key=lambda d: d.metadata.get('Name', '')):
    sections.append('\n' + '=' * 72 + '\n' + dist.metadata['Name'] + ' ' + dist.version + '\n')
    found = False
    for file in dist.files or []:
        if any(part.lower().startswith(('license', 'copying', 'notice')) for part in file.parts):
            path = Path(dist.locate_file(file))
            if path.is_file():
                sections.append(path.read_text(encoding='utf-8', errors='replace'))
                found = True
    if not found:
        sections.append(str(dist.metadata.get('License-Expression') or dist.metadata.get('License') or 'Refer to package source for license.'))
Path(sys.argv[1]).write_text('\n'.join(sections), encoding='utf-8')
