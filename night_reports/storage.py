"""Per-user settings and local audit records, outside application binaries."""
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import os
import re
import sys
import tempfile

RECIPIENTS = ()  # Configure locally; no distribution list in cloud builds.


def data_directory() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "MaisonNightReports"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/MaisonNightReports"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "MaisonNightReports"


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@dataclass
class Settings:
    recipients: list[str] = field(default_factory=lambda: list(RECIPIENTS))
    subject: str = "RE: Night reports"
    body: str = "Please find attached the night reports.\n\nKind Regards,\n\nFront Office"
    last_folder: str = ""

    def validate(self, *, require_recipients=True):
        if not isinstance(self.recipients, list) or (require_recipients and not self.recipients) or any(not isinstance(a, str) or not re.fullmatch(r"[^\s@;,<>]+@[^\s@;,<>]+\.[^\s@;,<>]+", a) for a in self.recipients):
            raise ValueError("Enter one valid email address per line.")
        if len({a.casefold() for a in self.recipients}) != len(self.recipients):
            raise ValueError("Remove repeated email addresses. Different domains are distinct recipients.")
        if not isinstance(self.subject, str) or not isinstance(self.body, str) or not self.subject.strip() or not self.body.strip() or "\n" in self.subject or "\r" in self.subject:
            raise ValueError("Enter a subject on one line and a non-empty email body.")
        if not isinstance(self.last_folder, str):
            raise ValueError("The saved folder must be text.")

    def save(self, root: Path):
        self.validate(require_recipients=False)
        write_json(root / "settings.json", asdict(self))

    @classmethod
    def load(cls, root: Path):
        path = root / "settings.json"
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            result = cls(**data)
            result.validate(require_recipients=False)
            return result
        except (OSError, TypeError, ValueError) as exc:
            raise ValueError("Settings could not be read. Restore settings.json from a known-good copy; defaults were not silently substituted.") from exc


class FileLock(AbstractContextManager):
    """OS-backed lock: automatically released if the process crashes."""
    def __init__(self, path: Path):
        self.path, self.handle = path, None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise ValueError("Night Reports is already running or preparing this pack. Use the existing window.") from exc
        return self

    def __exit__(self, *args):
        if self.handle:
            self.handle.close()
            self.handle = None
