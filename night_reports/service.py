"""Validated copy preparation and durable, duplicate-aware draft orchestration."""
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import json
from hashlib import sha256

from .engine import Check, file_digest, inspect_pdf, validate_period
from .outlook import DraftRef
from .storage import FileLock, Settings, write_json


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class PackService:
    def __init__(self, root: Path, adapter):
        self.root, self.adapter = root, adapter

    def save_check(self, check: Check):
        write_json(self.root / "checks" / f"{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.json",
                   {"checked_at": utcnow(), **check.record()})

    def run_folder(self, check: Check) -> Path:
        return self.root / "runs" / check.audit.isoformat() / check.fingerprint

    def existing(self, check: Check) -> dict | None:
        path = self.run_folder(check) / "run.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError("The saved run record is unreadable. Inspect Outlook and restore the record before retrying.") from exc
        return None

    def prepare(self, check: Check, settings: Settings, *, another: bool = False) -> str:
        """Creates once, or reopens by ID; deliberate replacement is explicit."""
        settings.validate()
        if not check.ready:
            raise ValueError("Resolve every blocking report and date review before creating a draft.")
        check.assert_unchanged()
        email_digest = sha256(json.dumps([settings.recipients, settings.subject, settings.body]).encode()).hexdigest()
        with FileLock(self.root / "draft.lock"):
            directory = self.run_folder(check)
            record = self.existing(check)
            if record and not another:
                if record.get("email", {}).get("sha256") != email_digest:
                    raise ValueError("Email settings changed since this draft attempt. Inspect Outlook, then use Create another if a replacement is needed.")
                if record.get("state") != "ready" or not record.get("draft"):
                    raise ValueError("A previous draft attempt is incomplete or uncertain. Inspect Outlook first. Use Create another only after review.")
                files = self._checked_saved_files(directory, record)
                self.adapter.reopen(DraftRef(**record["draft"]), files, record["run_id"])
                return "Existing draft opened. No new draft was created."
            if record:
                write_json(directory / f"previous-{uuid4().hex}.json", record)
            attempt = uuid4().hex
            copies = directory / attempt
            copies.mkdir(parents=True, exist_ok=False)
            record = {"run_id": attempt, "pack_id": check.fingerprint,
                      "started_at": utcnow(), "state": "preparing", "draft": None,
                      "check": check.record(), "files": [],
                      "email": {"recipient_count": len(settings.recipients), "subject": settings.subject, "sha256": email_digest}}
            write_json(directory / "run.json", record)
            try:
                files = self._copy_pack(check, copies)
                record["files"] = [{"path": str(p.relative_to(directory)), "sha256": file_digest(p)} for p in files]
                check.assert_unchanged()
                record["state"] = "creating"
                write_json(directory / "run.json", record)

                def saved(ref):
                    record["draft"] = asdict(ref)
                    write_json(directory / "run.json", record)

                self._checked_saved_files(directory, record)
                ref = self.adapter.create(files, settings, attempt, saved)
                self._checked_saved_files(directory, record)
                check.assert_unchanged()
                record["draft"] = asdict(ref)
                record["state"] = "ready"
                record["ready_at"] = utcnow()
                write_json(directory / "run.json", record)
            except Exception as exc:
                record["state"] = "uncertain" if record["state"] == "creating" else "failed"
                # Avoid storing COM/parser exception payloads containing user data.
                record["error_type"] = type(exc).__name__
                record["failed_at"] = utcnow()
                write_json(directory / "run.json", record)
                raise
            # If only displaying fails, the valid saved draft remains 'ready'.
            self.adapter.reopen(ref, files, attempt)
            return "Draft ready in Outlook — 23 PDFs attached. Review and send from Outlook."

    @staticmethod
    def _copy_pack(check: Check, directory: Path) -> list[Path]:
        files = []
        for row in check.rows:
            original = row.document
            target = directory / row.slot.filename
            # Exclusive file creation prevents silent replacement of another run.
            with original.path.open("rb") as source, target.open("xb") as dest:
                while block := source.read(1024 * 1024):
                    dest.write(block)
            doc = inspect_pdf(target)
            if doc.digest != original.digest or doc.error or doc.kind != row.slot.rule.key:
                raise ValueError("A report changed or a prepared copy failed validation. Check Reports again.")
            state, _ = validate_period(row.slot, doc, check.audit, check.business)
            if state == "WRONG" or (state == "REVIEW" and row.slot.key not in check.confirmations):
                raise ValueError("A prepared copy does not satisfy the reviewed reporting period.")
            files.append(target)
        if len(files) != 23:
            raise ValueError("Exactly 23 reports are required.")
        return files

    @staticmethod
    def _checked_saved_files(directory: Path, record: dict) -> list[Path]:
        files = []
        for entry in record.get("files", []):
            path = (directory / entry["path"]).resolve()
            if not path.is_relative_to(directory.resolve()) or not path.is_file() or file_digest(path) != entry["sha256"]:
                raise ValueError("Prepared files have changed or are missing. Inspect the existing Outlook draft before creating another.")
            files.append(path)
        if len(files) != 23:
            raise ValueError("The saved run does not contain 23 prepared PDFs.")
        return files
