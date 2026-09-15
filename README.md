# Maison Night Reports 0.2

Portable Windows application for source discovery, verified report copying and scheduled classic Outlook submission.

- Source and Prepared report lists with provenance and validation results.
- Minute-by-minute collection between 07:00 and 09:00; send no earlier than 07:10.
- Scheduler RS report titles and MONTH / +01…+12 forecasts matched against PDF dates.
- Staged destination replacement; unchanged source PDFs; hash-verified attachments.
- Persistent duplicate prevention and activity logs; Outlook Outbox / Sent Items status.
- Calendar inputs, notification-area icon, and report review/replacement actions.

Extract the whole Windows ZIP. Run MaisonNightReports.exe with its _internal folder beside it. Existing per-user settings are retained; the previous 07:05 default migrates to 07:00. Configure source, destination and recipients in Settings before enabling automation. No recipients or guest reports are bundled.

See docs/STAFF-GUIDE.md for operation. Live Outlook policy and the hotel's original PDF exports still require workstation verification; automated tests use synthetic reports and mocked mail delivery.

Build on Windows with scripts/build_windows.ps1. It runs the test suite, packages the app and runs the packaged self-test. On other platforms use `python -m unittest discover -s tests -t .` after installing requirements-test.txt and pypdf. Native UI tests require MAISON_GUI_TESTS=1.
