"""Daily collection and Outlook submission with durable once-per-day state."""
from datetime import datetime, timedelta, time
from pathlib import Path
from uuid import uuid4
from hashlib import sha256
import json
import shutil

from .engine import inspect_pdf, scan, validate_period, file_digest
from .manifest import manifest
from .outlook import DraftRef
from .storage import FileLock, write_json

EOD = {'manager', 'noshow', 'complimentary'}
PREFIXES = ('res_detail', 'pkgforecast', 'pr_birthday', 'rep_event_list_detailed',
            'rep_rooms_f', 'resreserveyesterday', 'findeptcodes', 'history_forecast',
            'manrepht', 'noshow', 'gihcomp')


def collect(root, source, now, progress):
    business, audit = now.date(), now.date() - timedelta(days=1)
    slots = manifest(audit, business)
    matches = {s.key: [] for s in slots}
    for folder, eod in [(source, False), (source / 'audit' / audit.strftime('%d%m%y'), True)]:
        if not folder.is_dir():
            raise ValueError(f'Report source unavailable: {folder}')
        for path in folder.iterdir():
            if path.suffix.lower() != '.pdf' or not path.name.lower().startswith(PREFIXES):
                continue
            stat = path.stat()
            # Scheduler root holds historical runs. Only today's settled exports qualify.
            if not eod and datetime.fromtimestamp(stat.st_mtime).date() != business:
                continue
            if now.timestamp() - stat.st_mtime < 30:
                raise ValueError('Reports are still being written. Retrying shortly.')
            doc = inspect_pdf(path)
            if doc.error:
                raise ValueError(f'Cannot read report: {path.name}')
            if (doc.kind in EOD) != eod:
                continue
            for slot in slots:
                if doc.kind == slot.rule.key and validate_period(slot, doc, audit, business)[0] == 'PASS':
                    matches[slot.key].append(doc)
    selected = []
    for slot in slots:
        docs = {d.digest: d for d in matches[slot.key]}
        if len(docs) != 1:
            raise ValueError(f'{slot.label}: {"missing or incorrect period" if not docs else "conflicting exports"}. Waiting for a valid pack.')
        selected.append((slot, next(iter(docs.values()))))
    progress(40, 'Renaming 23 verified reports')
    destination = root / 'collected' / business.isoformat() / uuid4().hex
    destination.mkdir(parents=True)
    for slot, doc in selected:
        target = destination / slot.filename
        shutil.copyfile(doc.path, target)
        if file_digest(target) != doc.digest or file_digest(doc.path) != doc.digest:
            raise ValueError('A source changed while copying. Retrying collection.')
    progress(60, 'Checking names, dates and contents of all 23 copies')
    check = scan(destination, audit, business)
    if not check.ready or any(r.document.path.name != r.slot.filename for r in check.rows):
        raise ValueError('Renamed report verification failed. Nothing will be sent.')
    return check


class DailyAutomation:
    def __init__(self, root, service):
        self.root, self.service = root, service

    def tick(self, settings, now=None, progress=lambda value, text: None):
        now = now or datetime.now()
        if not settings.automation_enabled:
            return 'Automatic sending is off'
        settings.validate()
        if now.time() < time.fromisoformat(settings.collect_time):
            progress(0, f'Waiting for {settings.collect_time}')
            return f'Next collection today at {settings.collect_time}'
        with FileLock(self.root / 'automation.lock'):
            path = self.root / 'daily' / f'{now.date()}.json'
            record = json.loads(path.read_text()) if path.exists() else {}
            if record.get('state') == 'submitted':
                progress(100, 'Submitted to Outlook · completed today')
                return 'Submitted to Outlook. Check Sent Items for delivery status.'
            if record.get('state') in ('preparing', 'sending', 'uncertain'):
                raise ValueError('An earlier Outlook attempt needs review. Automatic retry is blocked to prevent duplicate email.')
            if not record:
                progress(15, 'Searching scheduler and closed audit folders')
                check = collect(self.root, Path(settings.scheduler_folder), now, progress)
                self.service.save_check(check)
                record = {'state': 'preparing', 'run_folder': str(self.service.run_folder(check)), 'day': str(now.date())}
                write_json(path, record)
                progress(75, 'Creating and verifying the Outlook draft')
                try:
                    self.service.prepare(check, settings, display=False)
                    record['state'] = 'ready'
                    write_json(path, record)
                except Exception:
                    record['state'] = 'uncertain'
                    write_json(path, record)
                    raise
            if now.time() < time.fromisoformat(settings.send_time):
                progress(85, f'Draft verified · waiting for {settings.send_time}')
                return f'Draft ready. Automatic send at {settings.send_time}.'
            directory = Path(record['run_folder'])
            if not directory.resolve().is_relative_to((self.root / 'runs').resolve()):
                raise ValueError('Invalid saved run location.')
            run = json.loads((directory / 'run.json').read_text())
            expected = sha256(json.dumps([settings.recipients, settings.subject, settings.body]).encode()).hexdigest()
            if run['state'] != 'ready' or run['email']['sha256'] != expected:
                raise ValueError('Draft or email settings changed. Review before sending.')
            files = self.service._checked_saved_files(directory, run)
            progress(95, 'Verifying Outlook attachments and submitting email')
            record['state'] = 'sending'
            write_json(path, record)
            try:
                self.service.adapter.send(DraftRef(**run['draft']), files, run['run_id'], settings)
            except Exception:
                record['state'] = 'uncertain'
                write_json(path, record)
                raise
            record.update(state='submitted', submitted_at=now.isoformat())
            write_json(path, record)
            run['state'] = 'submitted'
            write_json(directory / 'run.json', run)
            progress(100, 'Submitted to Outlook · completed today')
            return 'Submitted to Outlook. Check Sent Items for delivery status.'
