"""Classic Windows Outlook adapter. There is deliberately no sending method."""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import platform
import sys
import tempfile

from .engine import file_digest
from .storage import Settings


class OutlookError(RuntimeError):
    pass


@dataclass(frozen=True)
class DraftRef:
    entry_id: str
    store_id: str


@contextmanager
def outlook_application():
    if sys.platform != "win32":
        raise OutlookError("Outlook drafts require classic Outlook on Windows. PDF checking works here; test drafts on the hotel PC.")
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise OutlookError("The Windows Outlook component is missing. Use the complete Windows application bundle.") from exc
    pythoncom.CoInitialize()
    try:
        try:
            app = win32com.client.Dispatch("Outlook.Application")
        except Exception as exc:
            raise OutlookError("Classic Outlook is unavailable. Open Outlook, sign into the intended profile, then try again.") from exc
        yield app
    finally:
        pythoncom.CoUninitialize()


class OutlookAdapter:
    def compatibility(self) -> dict:
        with outlook_application() as app:
            try:
                app.Session.GetDefaultFolder(16)  # olFolderDrafts
                item = app.CreateItem(0)
                item.Close(1)  # olDiscard; unsaved compatibility probe, no recipients
                return {"windows": platform.platform(), "outlook_version": str(app.Version),
                        "result": "Classic Outlook can create an unsaved mail item. Full draft/attachment pilot still required."}
            except Exception as exc:
                raise OutlookError("Outlook opened, but the draft compatibility check failed. Verify the active mail profile.") from exc

    def create(self, files: list[Path], settings: Settings, run_id: str, on_saved) -> DraftRef:
        settings.validate()
        with outlook_application() as app:
            return self._create(app, files, settings, run_id, on_saved)

    def _create(self, app, files, settings, run_id, on_saved):
        mail = None
        complete = False
        try:
            mail = app.CreateItem(0)
            mail.BodyFormat = 1  # plain text, exact approved body, no extra signature
            mail.Subject = "[INCOMPLETE] Night Reports preparation"
            mail.UserProperties.Add("MaisonNightReportsRun", 1).Value = run_id
            mail.Save()
            ref = DraftRef(str(mail.EntryID), str(mail.Parent.StoreID))
            # Persist the ID before attachment/recipient changes, to recover after crashes.
            on_saved(ref)
            for path in files:
                mail.Attachments.Add(str(path.resolve()), 1)  # olByValue
            mail.Save()
            self._verify_attachments(mail, files)
            mail.Subject = settings.subject
            mail.Body = settings.body
            for address in settings.recipients:
                recipient = mail.Recipients.Add(address)
                recipient.Type = 1  # To
            if not mail.Recipients.ResolveAll():
                raise OutlookError("Outlook could not resolve every recipient. Check the addresses and profile.")
            mail.Save()
            if mail.Recipients.Count != len(settings.recipients):
                raise OutlookError("Outlook recipient count does not match the configured list.")
            self._verify_attachments(mail, files)
            complete = True
            # Delivery has not occurred. Display failures are recoverable by ID.
            return ref
        except Exception as exc:
            if mail is not None and not complete:
                try:
                    # Retain an identifiable failed draft but remove distribution.
                    for i in range(mail.Recipients.Count, 0, -1):
                        mail.Recipients.Remove(i)
                    mail.Subject = "[INCOMPLETE - DO NOT SEND] Night Reports"
                    mail.Save()
                except Exception:
                    pass
            if isinstance(exc, OutlookError):
                raise
            raise OutlookError("Outlook draft preparation failed. Inspect Outlook for an incomplete draft before explicitly creating another.") from exc

    @staticmethod
    def _verify_attachments(mail, files):
        if mail.Attachments.Count != len(files):
            raise OutlookError("Outlook attachment count does not match the validated pack.")
        with tempfile.TemporaryDirectory(prefix="maison-attachment-check-") as directory:
            for i, path in enumerate(files, 1):
                attachment = mail.Attachments.Item(i)
                if str(attachment.FileName) != path.name:
                    raise OutlookError("Outlook attachment names or order do not match the validated pack.")
                copy = Path(directory) / f"attachment-{i}.pdf"
                attachment.SaveAsFile(str(copy))
                if file_digest(copy) != file_digest(path):
                    raise OutlookError("An Outlook attachment differs from its validated PDF.")

    def reopen(self, ref: DraftRef, files: list[Path], run_id: str):
        with outlook_application() as app:
            try:
                mail = app.Session.GetItemFromID(ref.entry_id, ref.store_id)
                if bool(mail.Sent):
                    raise OutlookError("This message has already been sent. A second draft was not created.")
                prop = mail.UserProperties.Find("MaisonNightReportsRun")
                if prop is None or str(prop.Value) != run_id:
                    raise OutlookError("The saved message does not match this run. Check Outlook manually.")
                self._verify_attachments(mail, files)
                mail.Display(False)
            except OutlookError:
                raise
            except Exception as exc:
                raise OutlookError("The saved draft could not be reopened. It may have moved or been deleted. Check Outlook before explicitly creating another.") from exc
