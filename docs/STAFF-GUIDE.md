# Daily Night Reports

Open Settings and set the OPERA source share and the separate Night Reports destination. Enter the approved recipients and optional Outlook sending-account address. Enable automatic collection and sending.

The app checks once per minute from 07:00 until 09:00. It uses the PC's local day as the new business day and yesterday as the closed audit day. The date fields are for inspecting a different day; automatic processing uses today's dates. The PC must remain awake and signed in, with classic Outlook available.

The Source reports tab shows original filenames, source paths, discovery time, original file timestamps, PDF issue dates, intended names and conversion status. Missing reports remain visible as collection continues. Scheduler reports come from the root share; Manager Net, No Shows and Complimentary come from the matching audit subfolder. The app never changes OPERA originals.

Scheduler titles include Package forecast RS, Event List Detailed RS, FIN01127 Revenue by transaction code all, and Past and Future Forecast RS MONTH with offsets +01 through +12. MONTH is the current month. Both the offset and PDF reporting period must agree. The PDF issue date must be current for scheduler forecasts, including the group rooms forecast.

After all 23 qualify, the app stages, copies and renames them into the chosen destination. Previous managed copies are moved into .previous before replacement; unrelated files remain untouched and are not attached. It then switches to Prepared reports. The app creates and verifies the Outlook draft and sends no earlier than 07:10. At 09:00 an incomplete or unsent run stops for the day.

The progress steps show collection, copying, verification, draft and send. Expand Activity log for details. Run history in Settings opens local records, including daily logs and original-file provenance. No guest PDF text is written to logs.

Double-click a report for View PDF, Confirm correct report, Attach another report, or Close. Confirmation is only available for uncertain information after viewing the PDF. A known wrong date or stale report requires replacement. A replacement is checked before use. Changes after a draft has been prepared stop automatic sending and require Outlook review.

Closing the window hides the app in Windows' notification area. Double-click its icon to restore it, or right-click for Open, Pause/resume or Exit. Windows controls whether the icon appears in the overflow area. Exit stops processing. This version does not launch itself at Windows sign-in.

The Outlook connection check creates no email and sends nothing. Submission and delivery are separate: the activity log reports whether the message is found in Outbox or Sent Items. Sent Items is not proof that every recipient received the message. If a send attempt is uncertain, the app will not send another automatically; inspect Outlook and the daily run record first.
