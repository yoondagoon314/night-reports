# Night Reports — first use and daily workflow

1. Extract the entire application folder. Keep `MaisonNightReports.exe` and `_internal` together. Open the executable or create a desktop shortcut using the included shortcut script.
2. In **Settings**, enter the approved recipient list and exact email body/signature locally. Cloud builds contain no hotel recipients. The default subject is `RE: Night reports`. You may check PDFs before configuring email.
3. Generate the reports normally. Choose their folder in the application. Only PDFs directly in that folder are scanned.
4. Confirm the closed audit day and new OPERA business day from OPERA; the initial dates are suggestions from the computer clock.
5. Select **Check Reports**. The pack requires 10 fixed reports and 13 full monthly forecasts starting with the new business month.
6. For a review item, use **Open PDF**, inspect its period/filters, then **Confirm reporting period** with staff initials and a short note. Do not enter guest details. Event List and group forecast always require review during this pilot.
7. For an unreadable forecast month, open its extra-file row, assign the month as YYYY-MM and separately confirm its period. Known wrong dates/filters cannot be overridden.
8. Resolve missing/corrupt PDFs by regenerating them. Move duplicate copies outside the input folder, then recheck. Readable unrelated extras are excluded; unreadable extras block.
9. Once 23/23 are ready and mail settings are configured, create the Outlook draft. The tool preserves originals, prepares renamed copies and verifies attachments. Review account, recipients, body and every attachment in classic Outlook before sending yourself.

**Check Outlook compatibility** tests an unsaved, recipient-free mail item and discards it. The cloud build cannot establish compatibility with your local profile. Start with copied real packs, compare a draft to the manual pack, then require three consecutive successful real packs before regular use.

A repeat draft request reopens the saved draft where possible. An incomplete or uncertain attempt requires inspecting Outlook first; **Create another** deliberately creates an additional draft and preserves the earlier run history. No automatic sending is implemented.

**Run history** opens the per-user data folder. Retain it during pilot; it contains full prepared PDFs plus metadata and confirmations. Closing the app after an operation finishes leaves no background job. The existing manual workflow remains available.
