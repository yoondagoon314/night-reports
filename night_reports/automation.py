"""One visible daily workflow, bounded polling and durable duplicate prevention."""
from datetime import datetime, timedelta, time
from pathlib import Path
from hashlib import sha256
import json

from .collection import Collector, EOD, PREFIXES
from .outlook import DraftRef
from .storage import FileLock, write_json

# Backwards-compatible standalone collection diagnostic.
def collect(root, source, now, progress):
    collector = Collector(root)
    rows, chosen, reviews, problems = collector.inspect(source, now)
    progress(40, 'Renaming collected reports')
    return collector.prepare(root/'collected'/str(now.date()), now.date()-timedelta(days=1), now.date(), chosen, reviews)

class DailyAutomation:
    def __init__(self, root, service):
        self.root, self.service = root, service
        self.collector = Collector(root)
        self.last_check = None

    def log(self, text, now):
        path = self.root/'logs'/f'{now.date()}.json'
        entries = json.loads(path.read_text()) if path.exists() else []
        if not entries or entries[-1]['message'] != text:
            entries.append({'at': now.isoformat(timespec='seconds'), 'message': text})
            write_json(path, entries[-500:])

    def discover(self, settings, now=None, audit=None, business=None, event=lambda *args:None):
        now = now or datetime.now()
        rows, chosen, reviews, problems = self.collector.inspect(Path(settings.scheduler_folder), now, audit, business)
        event('sources', rows)
        count = len(chosen)
        text = f'{count}/23 current reports collected.'
        if problems: text += ' ' + '; '.join(problems[:3])
        self.log(text, now)
        return rows, chosen, reviews, text

    def tick(self, settings, now=None, progress=lambda *args:None, event=lambda *args:None):
        live_clock = now is None
        now = now or datetime.now()
        def report(n, text):
            progress(n, text); self.log(text, now)
            return text
        if not settings.automation_enabled:
            return report(0, 'Automatic sending is off')
        settings.validate()
        if now.time() < time.fromisoformat(settings.collect_time):
            return report(0, f'Waiting for {settings.collect_time}')
        with FileLock(self.root/'automation.lock'):
            path = self.root/'daily'/f'{now.date()}.json'
            record = json.loads(path.read_text()) if path.exists() else {}
            if record.get('run_folder') and self.last_check is None:
                from .engine import Check, inspect_pdf
                directory = Path(record['run_folder'])
                if not directory.resolve().is_relative_to((self.root/'runs').resolve()):
                    raise ValueError('Invalid saved run location.')
                saved = json.loads((directory/'run.json').read_text())
                files = self.service._checked_saved_files(directory, saved)
                self.last_check = Check(directory, now.date()-timedelta(days=1), now.date(), tuple(inspect_pdf(p) for p in files), managed_only=True)
                event('prepared', self.last_check)
            if record.get('state') in ('submitted', 'sent'):
                state = 'Submitted to Outlook; delivery status not yet confirmed.'
                if hasattr(self.service.adapter, 'submission_status'):
                    state = self.service.adapter.submission_status(record['run_id'])
                return report(100, state)
            if now.time() >= time.fromisoformat(settings.stop_time):
                return report(0, '09:00 collection window closed. No automatic email will be sent today.')
            if record.get('state') in ('preparing', 'sending', 'uncertain'):
                raise ValueError('An earlier Outlook attempt needs review in Run history and Outlook. A second email will not be sent automatically.')
            if not record:
                rows, chosen, reviews, text = self.discover(settings, now, event=event)
                report(10 + 35*len(chosen)/23, text)
                if len(chosen) != 23:
                    return text + ' Retrying in one minute.'
                if not settings.last_folder.strip():
                    raise ValueError('Choose the Night Reports destination in Settings.')
                report(50, 'Copying and renaming the complete pack into the Night Reports folder')
                check = self.collector.prepare(Path(settings.last_folder), now.date()-timedelta(days=1), now.date(), chosen, reviews)
                self.last_check = check
                event('sources', self.collector.last_rows)
                event('prepared', check)
                self.service.save_check(check)
                report(65, '23 destination filenames, contents and periods verified')
                record = {'state':'preparing', 'run_folder':str(self.service.run_folder(check)), 'day':str(now.date())}
                write_json(path, record)
                report(75, 'Preparing Outlook draft and verifying all attachments')
                try:
                    self.service.prepare(check, settings, display=False)
                    run = self.service.existing(check)
                    record.update(state='ready', run_id=run['run_id'])
                    write_json(path, record)
                except Exception:
                    record['state']='uncertain'; write_json(path, record)
                    raise
            if now.time() < time.fromisoformat(settings.send_time):
                return report(85, f'Draft verified. Waiting until {settings.send_time} to send.')
            if live_clock:
                current = datetime.now()
                if current.date() != now.date() or current.time() >= time.fromisoformat(settings.stop_time):
                    return report(85, 'Sending window closed during preparation. Draft remains unsent.')
            directory = Path(record['run_folder'])
            if not directory.resolve().is_relative_to((self.root/'runs').resolve()):
                raise ValueError('Invalid saved run location.')
            run = json.loads((directory/'run.json').read_text())
            expected = sha256(json.dumps([settings.recipients,settings.subject,settings.body,settings.sender]).encode()).hexdigest()
            if run['state'] != 'ready' or run['email']['sha256'] != expected:
                raise ValueError('Email settings changed after draft preparation. Inspect the draft before continuing.')
            files = self.service._checked_saved_files(directory, run)
            report(95, 'Checking recipients and submitting the verified email to Outlook')
            record['state']='sending'; write_json(path, record)
            try:
                self.service.adapter.send(DraftRef(**run['draft']),files,run['run_id'],settings)
            except Exception:
                record['state']='uncertain'; write_json(path,record)
                raise
            record.update(state='submitted',submitted_at=now.isoformat(),run_id=run['run_id'])
            write_json(path,record)
            run['state']='submitted'; write_json(directory/'run.json',run)
            return report(100,'Submitted to Outlook. Checking Outbox / Sent Items on the next refresh.')
