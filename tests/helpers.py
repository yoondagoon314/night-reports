from datetime import date
from pathlib import Path
from reportlab.pdfgen.canvas import Canvas
from night_reports.engine import scan
from night_reports.manifest import manifest

TITLES = {
    'arrivals': 'ARR01102 Arrivals by Name',
    'packages': 'RES01124 Package forecast - Detailed',
    'birthdays': 'PRO01110 Birthday Guests',
    'events': 'Event List Detailed',
    'groups': 'Rooms Forecast - Book',
    'yesterday': 'RES01145 Reservations - made Yesterday',
    'revenue': 'Revenue by Transaction Codes Net',
    'manager': 'NA01 - Manager Report Net *DEF*',
    'noshow': 'NA40 - No Shows *DEF*',
    'complimentary': 'NA50 - Guest in House Comp/House',
    'forecast': 'FOR01121 Past and Future Forecast',
}
AUDIT, BUSINESS = date(2026, 9, 10), date(2026, 9, 11)


def pdf(path, text, second=None):
    c = Canvas(str(path), invariant=1)
    for page in [text] + ([second] if second else []):
        t = c.beginText(40, 800)
        t.setFont('Helvetica', 10)
        for line in page.splitlines():
            t.textLine(line)
        c.drawText(t)
        c.showPage()
    c.save()
    return path


def report_text(slot, business=BUSINESS, *, missing_date=False, issue=True):
    lines = [business.strftime('%d.%m.%y') if issue else 'MAISON SYNTHETIC TEST', TITLES[slot.rule.key]]
    if not missing_date and slot.start and slot.rule.key != 'yesterday':
        lines.append(f'From Date {slot.start:%d.%m.%y} To Date {slot.end:%d.%m.%y}')
    if slot.rule.key == 'packages':
        lines.append('Pkg. Forecast Group BKF')
    if slot.rule.key == 'forecast':
        lines.extend(['Room Type All', 'Deduct Y Non-Deduct N Pseudo Rooms N',
                      'Include House Use in Occ.% and ADR Y Include Day Use in Occ.% and ADR N',
                      'Include No Show in Occ.% and ADR N Exclude OOO from Occ.% Y',
                      'Room Revenue Net Distributed Y'])
    lines.append('No records found. SYNTHETIC TEST ONLY')
    return '\n'.join(lines)


def pack(folder, audit=AUDIT, business=BUSINESS):
    folder.mkdir(parents=True, exist_ok=True)
    for index, slot in enumerate(manifest(audit, business)):
        pdf(folder / f'export-{index:02}.pdf', report_text(slot, business))
    return folder


def ready(folder, audit=AUDIT, business=BUSINESS):
    check = scan(folder, audit, business)
    for row in list(check.rows):
        if row.status == 'REVIEW':
            check.mark_opened(row.document.path)
            check.confirm_date(row.slot.key, 'TEST', 'Synthetic reference period and filters checked; no guest data.')
    assert check.ready, [(r.slot.key, r.status) for r in check.rows]
    return check
