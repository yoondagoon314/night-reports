"""Read-only PDF inspection. No guest text is retained in results or logs."""
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import calendar
import json
import logging
import re

from pypdf import PdfReader
from .manifest import RULE_VERSION, Slot, identify, manifest

# pypdf diagnostics can contain PDF operands. Never write them to application logs.
logging.getLogger("pypdf").addHandler(logging.NullHandler())
logging.getLogger("pypdf").propagate = False

MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_PAGES = 500
DATE = r"\d{1,2}[./-]\d{1,2}[./-](?:\d{4}|\d{2})(?!\d)"


def parse_report_date(value: str) -> date:
    d, m, y = map(int, re.split(r"[./-]", value))
    return date(y + 2000 if y < 100 else y, m, d)


@dataclass(frozen=True)
class Period:
    start: date | None = None
    end: date | None = None
    issue: date | None = None
    ambiguous: bool = False

    @property
    def display(self) -> str:
        if self.ambiguous:
            return "Conflicting or invalid period fields"
        if self.start and not self.end:
            return f"From {self.start:%d.%m.%Y}; end unreadable"
        if self.end and not self.start:
            return f"To {self.end:%d.%m.%Y}; start unreadable"
        if self.start:
            return (f"{self.start:%d.%m.%Y}" if self.start == self.end else
                    f"{self.start:%d.%m.%Y} – {self.end:%d.%m.%Y}")
        if self.issue:
            return f"Header date {self.issue:%d.%m.%Y}; period not explicit"
        return "Date not readable"


def extract_period(first: str, pages: tuple[str, ...], kind: str | None) -> Period:
    # Only labelled report parameter fields are periods; guest arrival/departure
    # dates in body tables must never be interpreted as the report period.
    starts, ends = set(), set()
    invalid = False
    def add_date(value, values):
        nonlocal invalid
        try:
            values.add(parse_report_date(value))
        except ValueError:
            invalid = True

    for page in pages:
        if kind == "birthdays":
            for label, values in (("From", starts), ("To", ends)):
                for value in re.findall(rf"\b{label}\s+Stay\s+Date\s*[:=]?\s*({DATE})", page, re.I):
                    add_date(value, values)
        elif kind == "events":
            for a, b in re.findall(rf"\bDate\s*:\s*({DATE})\s+To\s+({DATE})", page, re.I):
                add_date(a, starts)
                add_date(b, ends)
        elif kind == "groups":
            # The page header describes one month/status. The footer describes
            # the complete report, which can span several months and pages.
            for label, values in (("Start", starts), ("End", ends)):
                for month, year in re.findall(rf"\bPeriod\s+{label}\s*:\s*([A-Za-z]+)\s*(\d{{4}})", page, re.I):
                    try:
                        number = list(calendar.month_name).index(month.capitalize())
                        day = 1 if label == "Start" else calendar.monthrange(int(year), number)[1]
                        values.add(date(int(year), number, day))
                    except (ValueError, IndexError):
                        invalid = True

        for label, values in (("From", starts), ("To", ends)):
            for value in re.findall(rf"\b{label}\s+Date\s*[:=]?\s*({DATE})", page, re.I):
                try:
                    values.add(parse_report_date(value))
                except ValueError:
                    invalid = True
        if kind in ("manager", "revenue"):
            for a in re.findall(rf"Calendar\s*/\s*Month\s+to\s+Date\s*(?:\(\s*Date\s*)?[:=]?\s*({DATE})", page, re.I):
                try:
                    day = parse_report_date(a)
                    starts.add(day)
                    ends.add(day)
                except ValueError:
                    invalid = True
    issue = None
    # The issue date is printed at the start in supplied PDFs. It is not a
    # substitute for a labelled period except for the relative Yesterday report.
    m = re.match(rf"\s*({DATE})", first)
    if not m:
        # OPERA may extract its property/title before the top-right date/time.
        m = re.search(rf"(?<![\d./-])({DATE})\s+\d{{1,2}}:\d{{2}}\b", first[:800])
    if m:
        try:
            issue = parse_report_date(m.group(1))
        except ValueError:
            invalid = True
    if len(starts) > 1 or len(ends) > 1 or invalid:
        return Period(issue=issue, ambiguous=True)
    a, b = next(iter(starts), None), next(iter(ends), None)
    return Period(a, b, issue, bool(a and b and b < a))


@dataclass(frozen=True)
class Document:
    path: Path
    digest: str
    size: int
    kind: str | None
    period: Period
    pages: int = 0
    error: str = ""
    filter_issue: str = ""
    filter_review: str = ""


def check_filters(text: str, kind: str | None) -> tuple[str, str]:
    """Only known header parameters; missing parameters require operator review."""
    # Repeated column headings in the body (e.g. Room Revenue followed by a
    # number) are not parameter values. The supplied forms end their parameter
    # header at these internal report identifiers.
    text = re.split(r"\b(?:history_forecast|pkgforecast)\b", text, maxsplit=1, flags=re.I)[0]
    contracts = []
    if kind == "packages":
        contracts = [(r"Pkg\.\s*Forecast\s+Group\s+(\S+)", "BKF", "breakfast package group")]
    elif kind == "forecast":
        contracts = [
            (r"(?<![-\w])Deduct\s+([YN])\b", "Y", "deduct reservations"),
            (r"Non-Deduct\s+([YN])\b", "N", "non-deduct reservations"),
            (r"Pseudo\s+Rooms\s+([YN])\b", "N", "pseudo rooms"),
            (r"Include\s+House\s+Use\s+in\s+Occ\.%\s+and\s+ADR\s+([YN])\b", "Y", "house use"),
            (r"Include\s+Day\s+Use\s+in\s+Occ\.%\s+and\s+ADR\s+([YN])\b", "N", "day use"),
            (r"Include\s+No\s+Show\s+in\s+Occ\.%\s+and\s+ADR\s+([YN])\b", "N", "no shows"),
            (r"Exclude\s+OOO\s+from\s+Occ\.%\s+([YN])\b", "Y", "out of order rooms"),
            (r"Room\s+Revenue\s+(\w+)", "NET", "net room revenue"),
            (r"Distributed\s+([YN])\b", "Y", "distributed revenue"),
            (r"Room\s+Type\s+(\S+)", "ALL", "all room types"),
        ]
    missing = []
    for pattern, expected, label in contracts:
        # The first occurrence is the parameter field; later body headings must
        # not masquerade as conflicting parameters when the footer ID is absent.
        match = re.search(pattern, text, re.I)
        values = [match.group(1)] if match else []
        if any(value.upper() != expected for value in values):
            return f"Wrong {label} filter; expected {expected} in the reference pack.", ""
        if not values:
            missing.append(label)
    return "", ("Verify unreadable report filters: " + ", ".join(missing) + "." if missing else "")


def pdf_paths(folder: Path) -> list[Path]:
    if not folder.is_dir():
        raise ValueError("Select an existing Night Reports folder.")
    return sorted((p for p in folder.iterdir() if p.suffix.lower() == ".pdf"),
                  key=lambda p: p.name.casefold())


def file_digest(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inspect_pdf(path: Path) -> Document:
    path = path.resolve()
    digest, size = "", 0
    try:
        if path.stat().st_size > MAX_PDF_BYTES:
            return Document(path, "", path.stat().st_size, None, Period(), error="PDF exceeds the 50 MB pilot limit.")
        data = path.read_bytes()
        digest, size = sha256(data).hexdigest(), len(data)
        if not data.startswith(b"%PDF-") or not data.rstrip().endswith(b"%%EOF"):
            raise ValueError("PDF header or end marker missing")
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            return Document(path, digest, size, None, Period(), error="Encrypted PDF: export an unencrypted report.")
        count = len(reader.pages)
        if not 1 <= count <= MAX_PAGES:
            raise ValueError("Invalid page count")
        pages = []
        kinds = set()
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)
            # Known report titles near the top of each page; reject combined packs.
            kinds.update(identify(text[:1600]))
        if len(kinds) > 1:
            return Document(path, digest, size, None, Period(), count,
                            "Multiple report types in one PDF; export individual reports.")
        kind = next(iter(kinds), None)
        period = extract_period(pages[0], tuple(pages), kind)
        filter_issue, filter_review = check_filters(pages[0][:2400], kind)
        return Document(path, digest, size, kind, period, count,
                        filter_issue=filter_issue, filter_review=filter_review)
    except Exception as exc:
        # Raw parser exceptions are intentionally not logged (they can carry data).
        return Document(path, digest, size, None, Period(),
                        error=f"Cannot fully read this PDF ({type(exc).__name__}). Export it again.")


@dataclass
class Row:
    slot: Slot
    candidates: tuple[Document, ...]
    status: str
    message: str

    @property
    def document(self) -> Document | None:
        return self.candidates[0] if len(self.candidates) == 1 else None


@dataclass
class Check:
    folder: Path
    audit: date
    business: date
    documents: tuple[Document, ...]
    assignments: dict[str, str] = field(default_factory=dict)
    confirmations: dict[str, dict] = field(default_factory=dict)
    opened: set[str] = field(default_factory=set)
    rows: list[Row] = field(default_factory=list)
    extras: list[tuple[Document, str, bool]] = field(default_factory=list)

    def __post_init__(self):
        self.evaluate()

    @property
    def ready(self) -> bool:
        return (len(self.rows) == 23 and all(r.status in ("PASS", "CONFIRMED") for r in self.rows)
                and not any(blocks for _, _, blocks in self.extras))

    @property
    def snapshot(self) -> dict[str, str]:
        return {str(d.path): d.digest for d in self.documents}

    def assert_unchanged(self):
        current = {str(p.resolve()): file_digest(p) for p in pdf_paths(self.folder)}
        if current != self.snapshot:
            raise ValueError("Files changed after checking. Check Reports again before proceeding.")

    def mark_opened(self, path: Path):
        d = next(d for d in self.documents if d.path == path.resolve())
        if file_digest(d.path) != d.digest:
            raise ValueError("The PDF changed. Check Reports again.")
        self.opened.add(d.digest)

    def assign_forecast(self, path: Path, slot_key: str):
        doc = next(d for d in self.documents if d.path == path.resolve())
        if doc.kind != "forecast" or doc.error or doc.period.start or doc.period.ambiguous:
            raise ValueError("Only a forecast with no readable period can be assigned manually.")
        if doc.digest not in self.opened:
            raise ValueError("Open the PDF before selecting its forecast month.")
        slots = {s.key for s in manifest(self.audit, self.business) if s.rule.key == "forecast"}
        if slot_key not in slots:
            raise ValueError("Select one of the thirteen expected forecast months.")
        self.assignments[str(doc.path)] = slot_key
        self.confirmations.clear()
        self.evaluate()

    def confirm_date(self, key: str, reviewer: str, note: str):
        self.assert_unchanged()
        row = next(r for r in self.rows if r.slot.key == key)
        doc = row.document
        if row.status != "REVIEW" or doc is None:
            raise ValueError("Only an unreadable or undocumented period can be confirmed. Known wrong dates cannot be overridden.")
        if doc.digest not in self.opened:
            raise ValueError("Open the PDF and inspect the period before confirming it.")
        if not reviewer.strip() or not note.strip():
            raise ValueError("Enter staff initials and the period/filters you checked. Do not enter guest details.")
        self.confirmations[key] = {"sha256": doc.digest, "reviewer": reviewer.strip(),
                                   "note": note.strip(), "at": datetime.now(timezone.utc).isoformat(),
                                   "expected": row.slot.expected}
        self.evaluate()

    def evaluate(self):
        slots = manifest(self.audit, self.business)
        grouped: dict[str, list[Document]] = {s.key: [] for s in slots}
        self.extras = []
        for d in self.documents:
            if d.error:
                self.extras.append((d, d.error, True))
                continue
            if d.kind is None:
                self.extras.append((d, "Unrecognized PDF; not attached. Check that this is an unrelated extra.", False))
                continue
            key = d.kind
            if d.kind == "forecast":
                if d.period.start:
                    key = f"forecast-{d.period.start.year}-{d.period.start.month:02}"
                else:
                    key = self.assignments.get(str(d.path), "")
            if key in grouped:
                grouped[key].append(d)
            else:
                message = ("Forecast outside the thirteen-month horizon; not attached."
                           if d.period.start else "Forecast month unreadable. Open PDF, assign its month, then confirm the period.")
                self.extras.append((d, message, not bool(d.period.start)))
        self.rows = []
        for slot in slots:
            candidates = tuple(grouped[slot.key])
            if not candidates:
                self.rows.append(Row(slot, (), "MISSING", f"{slot.label} missing."))
                continue
            if len(candidates) > 1:
                self.rows.append(Row(slot, candidates, "DUPLICATE", "More than one PDF matches. Move unused copies outside the input folder, then recheck."))
                continue
            doc = candidates[0]
            status, message = validate_period(slot, doc, self.audit, self.business)
            confirmation = self.confirmations.get(slot.key)
            if status == "REVIEW" and confirmation and confirmation["sha256"] == doc.digest:
                status, message = "CONFIRMED", f"Period checked by {confirmation['reviewer']}."
            self.rows.append(Row(slot, candidates, status, message))

    def record(self) -> dict:
        return {"rule_version": RULE_VERSION, "audit_day": self.audit.isoformat(),
                "business_day": self.business.isoformat(), "ready": self.ready,
                "reports": [{"key": r.slot.key, "filename": r.document.path.name if r.document else None,
                             "candidates": [d.path.name for d in r.candidates], "message": r.message,
                             "output_filename": r.slot.filename, "status": r.status,
                             "sha256": r.document.digest if r.document else None,
                             "expected_period": r.slot.expected,
                             "detected_period": r.document.period.display if r.document else None,
                             "confirmation": self.confirmations.get(r.slot.key)} for r in self.rows],
                "extras": [{"filename": d.path.name, "reason": reason, "blocking": block}
                           for d, reason, block in self.extras]}

    @property
    def fingerprint(self) -> str:
        if not self.ready:
            raise ValueError("The pack is not ready.")
        identity = [RULE_VERSION, self.audit.isoformat(), self.business.isoformat(),
                    [(r.slot.key, r.document.digest) for r in self.rows]]
        return sha256(json.dumps(identity).encode()).hexdigest()


def validate_period(slot: Slot, doc: Document, audit: date, business: date) -> tuple[str, str]:
    p = doc.period
    if doc.filter_issue:
        return "WRONG", doc.filter_issue
    if p.ambiguous:
        return "WRONG", "Conflicting or invalid report periods. Export this report again."
    if slot.rule.key == "forecast" and p.issue and p.issue != business:
        return "WRONG", f"Stale forecast: header date is {p.issue:%d.%m.%Y}; expected {business:%d.%m.%Y}."
    if slot.rule.date_basis == "review":
        return "REVIEW", "Exact hotel date/filter contract is pending. Open the PDF and record the period and filters you verified."
    if p.start or p.end:
        if (p.start and p.start != slot.start) or (p.end and p.end != slot.end):
            return "WRONG", f"Wrong reporting period: expected {slot.expected}, found {p.display}."
        if not p.start or not p.end:
            return "REVIEW", f"Only part of the reporting period is readable. Verify {slot.expected}."
        if slot.rule.key == "forecast" and not p.issue:
            return "REVIEW", "Month matches, but the forecast issue date is unreadable. Verify it was generated for this pack."
        if doc.filter_review:
            return "REVIEW", doc.filter_review
        return "PASS", "Report identity and period match."
    if slot.rule.key == "complimentary" and p.issue:
        if p.issue != audit:
            return "WRONG", f"EOD report date is {p.issue:%d.%m.%Y}; expected {audit:%d.%m.%Y}."
        return "PASS", "EOD complimentary report date matches the closed audit day."
    if slot.rule.key == "yesterday" and p.issue:
        if p.issue != business:
            return "WRONG", f"Yesterday report header is {p.issue:%d.%m.%Y}; expected {business:%d.%m.%Y}."
        if (business - audit).days == 1:
            return "PASS", "Yesterday report issued on the new business day; covers the closed day."
    return "REVIEW", f"Reporting period cannot be verified automatically. Expected {slot.expected}."


def scan(folder: Path, audit: date, business: date) -> Check:
    manifest(audit, business)
    folder = folder.expanduser().resolve()
    docs = tuple(inspect_pdf(p) for p in pdf_paths(folder))
    result = Check(folder, audit, business, docs)
    # Corrupt/unreadable documents already block progression; avoid masking their
    # useful report-specific errors with a snapshot exception.
    if not any(d.error for d in docs):
        result.assert_unchanged()
    return result
