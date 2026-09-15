"""Hotel report identities and period contracts, independent of filenames."""
from dataclasses import dataclass
from datetime import date, timedelta
import calendar
import re

RULE_VERSION = "maison-2026-09-15-v2"
MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")


@dataclass(frozen=True)
class Rule:
    key: str
    label: str
    filename: str
    pattern: str
    date_basis: str
    evidence: str


RULES = (
    Rule("arrivals", "Arrivals", "Arrivals.pdf", r"\bARR01102\s+Arrivals\s+by\s+Name\b", "business", "Master/branch identity; full sample pending"),
    Rule("packages", "Breakfast package forecast", "Package forecast.pdf", r"\bRES01124\s+Package\s+forecast\s*-\s*Detailed\b", "business", "Direct PDF sample"),
    Rule("birthdays", "Birthday guests", "Birthday Guests.pdf", r"\bPRO01110\s+Birthday\s+Guests\b", "business", "Master/branch identity; full sample pending"),
    Rule("events", "Event List", "Event List.pdf", r"\bEvent\s+List\s+Detailed\b", "week", "Hotel screenshot: business day through business day +7"),
    Rule("groups", "Group rooms forecast", "group rep.pdf", r"\bRooms\s+Forecast\s*-\s*Book\b", "group_months", "Hotel screenshot: business month through month +3 inclusive"),
    Rule("yesterday", "Reservations made yesterday", "Reservations - made Yesterday.pdf", r"\bRES01145\s+Reservations\s*-\s*made\s+Yesterday\b", "yesterday", "Direct sample: issue date is new business day"),
    Rule("revenue", "Revenue by transaction codes", "Revenue by Transaction Codes.pdf", r"\bRevenue\s+by\s+Transaction\s+Codes\s+Net\b", "audit", "Direct PDF sample"),
    Rule("manager", "Manager Flash", "Manager flash.pdf", r"\bNA01\s*-\s*Manager\s+Report\s+Net\b", "audit", "Direct PDF sample"),
    Rule("noshow", "No shows", "NOSHOW.pdf", r"\bNA40\s*-\s*No\s+Shows\b", "audit", "Direct zero-result PDF sample"),
    Rule("complimentary", "In-house complimentary", "Guests in House complimentary.pdf", r"\bNA50\s*-\s*Guest\s+in\s+House\s+Comp\s*/\s*House\b", "audit", "Master/branch identity; full sample pending"),
    Rule("forecast", "Past and Future Forecast", "", r"\bFOR01121\s+Past\s+and\s+Future\s+Forecast\b", "month", "September direct PDF sample"),
)
BY_KEY = {r.key: r for r in RULES}


@dataclass(frozen=True)
class Slot:
    key: str
    rule: Rule
    label: str
    filename: str
    start: date | None
    end: date | None

    @property
    def expected(self) -> str:
        if self.start is None:
            return "Staff must verify the report period and filters"
        a = self.start.strftime("%d.%m.%Y")
        return a if self.end == self.start else f"{a} – {self.end:%d.%m.%Y}"


def manifest(audit: date, business: date) -> tuple[Slot, ...]:
    if business <= audit:
        raise ValueError("The new OPERA business day must be after the closed audit day.")
    slots = []
    for rule in RULES[:-1]:
        target = None if rule.date_basis == "review" else (
            business if rule.date_basis == "business" else audit)
        end = target
        if rule.date_basis == "week":
            target, end = business, business + timedelta(days=7)
        elif rule.date_basis == "group_months":
            target = business.replace(day=1)
            year, month0 = divmod(business.year * 12 + business.month - 1 + 3, 12)
            end = date(year, month0 + 1, calendar.monthrange(year, month0 + 1)[1])
        slots.append(Slot(rule.key, rule, rule.label, rule.filename, target, end))
    for offset in range(13):
        absolute = business.year * 12 + business.month - 1 + offset
        year, month0 = divmod(absolute, 12)
        month = month0 + 1
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        suffix = "" if year == business.year else f" {year}"
        filename = f"HF {MONTHS[month0]}{suffix} EUR.pdf"
        slots.append(Slot(f"forecast-{year}-{month:02}", BY_KEY["forecast"],
                          f"Forecast · {MONTHS[month0]} {year}", filename, start, end))
    return tuple(slots)


def identify(text: str) -> tuple[str, ...]:
    normalized = re.sub(r"\s+", " ", text)
    return tuple(r.key for r in RULES if re.search(r.pattern, normalized, re.I))
