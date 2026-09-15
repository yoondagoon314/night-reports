"""Incremental source discovery, provenance and verified destination replacement."""
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
import json
import os
import shutil

from .engine import inspect_pdf, scan, validate_period, file_digest
from .manifest import manifest
from .storage import write_json, FileLock

EOD = {'manager', 'noshow', 'complimentary'}
PREFIXES = ('res_detail', 'pkgforecast', 'pr_birthday', 'rep_event_list_detailed',
            'rep_rooms_f', 'resreserveyesterday', 'findeptcodes', 'history_forecast',
            'manrepht', 'noshow', 'gihcomp')

class Collector:
    def __init__(self, root):
        self.root = root
        self.cache = {}
        self.discovered = {}
        self.documents = {}
        self.last_rows = []

    def inspect(self, source, now, audit=None, business=None):
        business = business or now.date()
        audit = audit or business - timedelta(days=1)
        slots = manifest(audit, business)
        matches = {s.key: [] for s in slots}
        problems = []
        day_root = self.root / 'collection' / business.isoformat()
        override_path = day_root / 'overrides.json'
        overrides = json.loads(override_path.read_text()) if override_path.exists() else {}
        reviews_path = day_root / 'reviews.json'
        reviews = json.loads(reviews_path.read_text()) if reviews_path.exists() else {}
        folders = [(source, False), (source/'audit'/audit.strftime('%d%m%y'), True)]
        paths = []
        for folder, eod in folders:
            if not folder.is_dir():
                problems.append(f'Source unavailable: {folder}')
                continue
            # One metadata listing; no historical PDF parsing on the large share.
            with os.scandir(folder) as entries:
                for entry in entries:
                    if not entry.name.lower().endswith('.pdf') or not entry.name.lower().startswith(PREFIXES):
                        continue
                    try:
                        stat = entry.stat()
                        if datetime.fromtimestamp(stat.st_mtime).date() != now.date():
                            continue
                        paths.append((Path(entry.path), eod, None, stat))
                    except OSError:
                        problems.append(f'File unavailable: {entry.name}')
        for key, value in overrides.items():
            try:
                path = Path(value)
                paths.append((path, key in EOD, key, path.stat()))
            except OSError:
                problems.append(f'Replacement unavailable: {key}')
        for path, eod, override, stat in paths:
            if now.timestamp() - stat.st_mtime < 30:
                problems.append(f'Waiting for export to finish: {path.name}')
                continue
            signature = (str(path), stat.st_size, stat.st_mtime_ns)
            if signature not in self.cache:
                self.cache[signature] = inspect_pdf(path)
            doc = self.cache[signature]
            if (doc.kind in EOD) != eod and not override:
                continue
            found = self.discovered.setdefault(signature, now.isoformat(timespec='seconds'))
            self.documents[str(path)] = doc
            for slot in slots:
                if override and slot.key != override:
                    continue
                if not override and slot.key in overrides:
                    continue
                if not override and doc.kind != slot.rule.key:
                    continue
                if doc.kind == 'forecast' and not override and doc.period.start:
                    if (slot.start.year, slot.start.month) != (doc.period.start.year, doc.period.start.month):
                        continue
                status, reason = validate_period(slot, doc, audit, business)
                if doc.error or doc.kind != slot.rule.key:
                    status, reason = 'WRONG', doc.error or 'Replacement is a different report type.'
                if not eod:
                    if doc.period.issue and doc.period.issue != business:
                        status, reason = 'WRONG', 'Report issue date is not the selected business day.'
                    elif not doc.period.issue and status == 'PASS':
                        status, reason = 'REVIEW', 'Issue date is unreadable; inspect the source PDF.'
                if status == 'REVIEW' and reviews.get(slot.key, {}).get('sha256') == doc.digest:
                    status = 'CONFIRMED'
                creation = getattr(stat, 'st_birthtime', None)
                if creation is None and os.name == 'nt':
                    creation = stat.st_ctime
                info = dict(key=slot.key, report=slot.label, original=path.name, source=str(path),
                            retrieved=found, created=datetime.fromtimestamp(creation).isoformat(timespec='seconds') if creation else 'Unavailable',
                            modified=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds'),
                            issue=str(doc.period.issue or 'Unreadable'), name=slot.filename, converted='No',
                            status=status, reason=reason, sha256=doc.digest)
                matches[slot.key].append((doc, info))
        rows, chosen = [], {}
        for slot in slots:
            candidates = matches[slot.key]
            good = {d.digest: (d, i) for d, i in candidates if i['status'] in ('PASS', 'CONFIRMED')}
            if len(good) == 1:
                doc, info = next(iter(good.values())); chosen[slot.key] = doc
                rows.append(info)
            elif len(good) > 1:
                info = dict(next(iter(good.values()))[1]); info.update(status='DUPLICATE', reason='Conflicting current exports; choose a replacement explicitly.')
                rows.append(info)
            elif candidates:
                rows.append(candidates[-1][1])
            else:
                rows.append(dict(key=slot.key, report=slot.label, original='—', source=str(folders[slot.key in EOD][0]), retrieved='—', created='—', modified='—', issue='—', name=slot.filename, converted='No', status='MISSING', reason='Waiting for a current matching export.'))
        self.last_rows = rows
        write_json(day_root/'sources.json', {'at': now.isoformat(), 'rows': rows, 'problems': problems})
        return rows, chosen, reviews, problems

    def replacement(self, business, key, path):
        record = self.root/'collection'/business.isoformat()/'overrides.json'
        values = json.loads(record.read_text()) if record.exists() else {}
        values[key] = str(path)
        write_json(record, values)

    def confirm(self, business, row, initials):
        if row['status'] != 'REVIEW':
            raise ValueError('Known wrong or stale reports must be replaced, not confirmed.')
        if file_digest(Path(row['source'])) != row['sha256']:
            raise ValueError('Source changed; collect again before confirming.')
        record = self.root/'collection'/business.isoformat()/'reviews.json'
        values = json.loads(record.read_text()) if record.exists() else {}
        values[row['key']] = {'sha256': row['sha256'], 'reviewer': initials, 'note': 'Source PDF issue date, period and filters inspected.'}
        write_json(record, values)

    def prepare(self, destination, audit, business, chosen, reviews):
        if len(chosen) != 23:
            raise ValueError('All 23 reports must be collected before copying.')
        destination = destination.expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        # Never allow source files or their parent share to become the output pack.
        if any(d.path.resolve().parent == destination for d in chosen.values()):
            raise ValueError('The Night Reports destination must differ from the OPERA source folders.')
        stage = destination / '.staging' / uuid4().hex
        stage.mkdir(parents=True)
        slots = manifest(audit, business)
        for slot in slots:
            doc = chosen[slot.key]
            shutil.copyfile(doc.path, stage/slot.filename)
            if file_digest(stage/slot.filename) != doc.digest or file_digest(doc.path) != doc.digest:
                raise ValueError('Source changed while copying. Collection will retry.')
        checked = scan(stage, audit, business)
        checked.confirmations.update(reviews); checked.evaluate()
        if not checked.ready:
            raise ValueError('Copied PDFs failed final verification.')
        with FileLock(destination/'.pack.lock'):
            index = destination/'.night-reports.json'
            previous = json.loads(index.read_text()) if index.exists() else {}
            names = set(previous.get('filenames', [])) | {s.filename for s in slots}
            backup = destination/'.previous'/uuid4().hex
            backup.mkdir(parents=True)
            moved, installed = [], []
            try:
                for name in names:
                    if Path(name).name != name:
                        raise ValueError('Invalid saved pack filename.')
                    old = destination/name
                    if old.exists():
                        os.replace(old, backup/name); moved.append(name)
                for slot in slots:
                    os.replace(stage/slot.filename, destination/slot.filename); installed.append(slot.filename)
                # Check only managed PDFs; unrelated PDFs remain outside the email pack.
                from .engine import Check
                final = Check(destination, audit, business, tuple(inspect_pdf(destination/s.filename) for s in slots))
                final.managed_only = True
                final.confirmations.update(reviews); final.evaluate()
                if not final.ready or any(r.document.path.name != r.slot.filename for r in final.rows):
                    raise ValueError('Destination verification failed.')
                write_json(index, {'business': str(business), 'filenames': installed})
            except Exception:
                for name in installed:
                    (destination/name).unlink(missing_ok=True)
                for name in moved:
                    os.replace(backup/name, destination/name)
                raise
        for row in self.last_rows:
            row['converted'] = 'Yes'
        write_json(self.root/'collection'/business.isoformat()/'sources.json', {'rows': self.last_rows})
        return final
