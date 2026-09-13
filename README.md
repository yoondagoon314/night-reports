# Night Reports — private Windows build

Manually opened PDF checker and classic Outlook draft preparer. No OPERA access, scheduling or automatic sending.

## Download a build

Open **Actions → Build Windows application → Run workflow**. After success, download **NightReports-Windows-x64**. Extract the artifact and then its application ZIP. Keep the executable and `_internal` folder together.

The workflow runs tests on Windows, builds with PyInstaller and smoke-tests the packaged executable without opening Outlook. It runs only on manual request, has a 20-minute timeout, and retains build downloads for seven days. No guest PDFs, original recipient list, local run records, or report-derived metadata are in this repository.

## First use

Open `MaisonNightReports.exe`. The cloud build starts with **no recipients** and a generic Front Office signature. Configure approved recipients/body locally through Settings before creating a draft. PDF checking works without mail configuration. See [the staff guide](docs/STAFF-GUIDE.md).

This is a pilot application. Real classic Outlook compatibility, the complete 23-report reference pack and the three-pack reception pilot still require local verification. Event List and group-report date rules require recorded manual review. The app checks selected header dates/filters; it does not reconcile report totals.

## Development

Python 3.12 x64 is used for Windows builds. From a source checkout:

```text
python -m pip install -e . -r requirements-test.txt
python scripts/run_tests.py
python -m night_reports
```

Set `MAISON_GUI_TESTS=1` to include native window smoke tests. All fixtures are synthetic and Outlook tests use fake objects. Run `scripts/build_windows.ps1` on Windows to build manually. Reception does not need Python installed.

The app stores settings, checks and prepared packs under `%LOCALAPPDATA%\MaisonNightReports`. Originals remain unchanged. Keep one operational history to prevent duplicate drafts. Prepared packs are retained; retention must be agreed locally.

References: [GitHub Windows runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners), [PyInstaller](https://www.pyinstaller.org/en/stable/), [Outlook attachments](https://learn.microsoft.com/en-us/office/vba/api/outlook.attachment).
