"""Small operator window. Background workers exist only while this app is open."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from queue import Queue, Empty
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from .automation import DailyAutomation
from .engine import scan
from .manifest import manifest
from .outlook import OutlookAdapter
from .service import PackService
from .storage import Settings, write_json


def read_day(value):
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        from .engine import parse_report_date
        return parse_report_date(value.strip())


def open_path(path):
    if sys.platform == "win32":
        os.startfile(str(path))
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Window:
    def __init__(self, root, data_root):
        self.root, self.data_root = root, data_root
        self.settings = Settings.load(data_root)
        self.service = PackService(data_root, OutlookAdapter())
        self.automation = DailyAutomation(data_root, self.service)
        self.progress_queue = Queue()
        self.check = None
        self.busy = False
        self.stamp = None
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.queue = Queue()
        root.title("MAISON · Night Reports")
        root.geometry("1160x790")
        root.minsize(960, 680)
        style = ttk.Style(root)
        style.theme_use("clam")
        root.configure(background="#f1f5f9")
        style.configure(".", font=("Segoe UI", 10), background="#f1f5f9", foreground="#183047")
        style.configure("TButton", padding=(14, 8), background="#e2e8f0")
        style.configure("Treeview", rowheight=32, background="#ffffff", fieldbackground="#ffffff", borderwidth=0)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), padding=10)
        style.configure("Horizontal.TProgressbar", background="#0d9488", troughcolor="#dbe7ed")
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"))
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Night Reports", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Collect → rename → verify → draft → send · 23 reports, one daily pack").pack(anchor="w", pady=(0, 14))
        top = ttk.Frame(frame)
        top.pack(fill="x")
        self.folder = tk.StringVar(value=self.settings.last_folder)
        self.audit = tk.StringVar(value=(date.today() - timedelta(days=1)).isoformat())
        self.business = tk.StringVar(value=date.today().isoformat())
        self.confirmed = tk.BooleanVar(value=False)
        self.inputs = []
        def entry(var, row, col, width):
            w = ttk.Entry(top, textvariable=var, width=width)
            w.grid(row=row, column=col, sticky="ew", padx=(0, 8), pady=4)
            self.inputs.append(w)
            return w
        ttk.Label(top, text="Manual report check · source folder in Settings").grid(row=1, column=0, sticky="w")
        ttk.Label(top, text="Closed audit day").grid(row=0, column=2, sticky="w")
        entry(self.audit, 1, 2, 14)
        ttk.Label(top, text="New OPERA business day").grid(row=0, column=3, sticky="w")
        entry(self.business, 1, 3, 18)
        top.columnconfigure(0, weight=1)
        self.suggest = ttk.Button(top, text="Suggest next day", command=self.suggest_day)
        self.suggest.grid(row=2, column=3, sticky="w")
        self.inputs.append(self.suggest)
        confirmed = ttk.Checkbutton(top, text="I confirm both dates (YYYY-MM-DD or DD.MM.YYYY)", variable=self.confirmed)
        confirmed.grid(row=2, column=0, columnspan=3, sticky="w", pady=6)
        self.inputs.append(confirmed)
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill="x", pady=8)
        for text, cmd in [("Check Reports", self.start_check), ("Settings", self.edit_settings),
                          ("Run history", self.history), ("Run in background", self.background), ("Exit", self.exit_app)]:
            b = ttk.Button(toolbar, text=text, command=cmd)
            b.pack(side="left", padx=(0, 8))
            self.inputs.append(b)
        self.progress_value = tk.DoubleVar(value=0)
        self.stage = tk.StringVar(value="Daily automation · configure in Settings")
        ttk.Label(frame, textvariable=self.stage).pack(anchor="w", pady=(6, 4))
        ttk.Progressbar(frame, variable=self.progress_value, maximum=100).pack(fill="x", pady=(0, 14))
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table_frame, columns=("report", "file", "period", "status"), show="headings", selectmode="browse")
        for key, title, width in [("report", "Expected report / extra file", 220), ("file", "Detected filename", 255),
                                  ("period", "Detected reporting period", 275), ("status", "Result", 100)]:
            self.table.heading(key, text=title)
            self.table.column(key, width=width, minwidth=80)
        self.table.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        scroll.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scroll.set)
        self.table.tag_configure("PASS", foreground="#246543")
        self.table.tag_configure("CONFIRMED", foreground="#246543")
        self.table.tag_configure("WRONG", foreground="#a22b2b")
        self.table.tag_configure("MISSING", foreground="#a22b2b")
        self.table.bind("<<TreeviewSelect>>", self.selection_changed)
        self.detail = tk.StringVar(value="Choose the exported report folder and confirm both OPERA dates.")
        ttk.Label(frame, textvariable=self.detail, wraplength=1080).pack(fill="x", pady=10)
        review = ttk.Frame(frame)
        review.pack(fill="x")
        self.open_button = ttk.Button(review, text="Open PDF", command=self.open_selected)
        self.open_button.pack(side="left")
        self.confirm_button = ttk.Button(review, text="Confirm reporting period…", command=self.confirm_period)
        self.confirm_button.pack(side="left", padx=8)
        self.assign_button = ttk.Button(review, text="Assign forecast month…", command=self.assign_month)
        self.assign_button.pack(side="left")
        self.draft_button = ttk.Button(review, text="Create Outlook Draft", command=self.draft)
        self.draft_button.pack(side="right")
        self.another_button = ttk.Button(review, text="Create another…", command=lambda: self.draft(True))
        self.another_button.pack(side="right", padx=8)
        self.status = tk.StringVar(value="Automatic collection 07:05 · send after 07:10 · keep this PC awake and Outlook available.")
        ttk.Label(frame, textvariable=self.status, wraplength=1080).pack(anchor="w", pady=(12, 0))
        for var in (self.folder, self.audit, self.business):
            var.trace_add("write", self.invalidate)
        self.confirmed.trace_add("write", lambda *_: self.invalidate(reset_dates=False))
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)
        root.after(2000, self.watch)
        root.after(1000, self.schedule)
        self.update_buttons()

    def error(self, exc):
        # Display only controlled application messages; external exceptions can
        # contain PDF operands or Outlook details, so show their type instead.
        from .outlook import OutlookError
        text = str(exc) if isinstance(exc, (ValueError, OutlookError)) else f"Operation failed ({type(exc).__name__}). Check file access and try again."
        messagebox.showerror("Night Reports", text, parent=self.root)
        self.status.set(text)

    def invalidate(self, *_, reset_dates=True):
        self.check = None
        self.stamp = None
        if reset_dates and self.confirmed.get():
            self.confirmed.set(False)
        self.table.delete(*self.table.get_children())
        self.detail.set("Folder, dates or settings changed. Confirm the dates and check reports again.")
        self.status.set("Not checked")
        self.update_buttons()

    def browse(self):
        path = filedialog.askdirectory(parent=self.root, title="Choose exported Night Reports folder", initialdir=self.folder.get() or None)
        if path:
            self.folder.set(path)

    def suggest_day(self):
        try:
            self.business.set((read_day(self.audit.get()) + timedelta(days=1)).isoformat())
        except ValueError:
            self.error(ValueError("Enter a valid closed audit date first."))

    def work(self, action, done):
        if self.busy:
            return
        self.busy = True
        for w in self.inputs:
            w.state(["disabled"])
        self.update_buttons()
        self.status.set("Working… You can minimize this window.")
        def run():
            try:
                self.queue.put((done, action(), None))
            except Exception as exc:
                self.queue.put((done, None, exc))
        self.pool.submit(run)

    def schedule(self):
        if self.settings.automation_enabled and not self.busy:
            settings = self.settings
            def action():
                try:
                    return self.automation.tick(settings, progress=lambda n, text: self.progress_queue.put((n, text)))
                except Exception as exc:
                    from .outlook import OutlookError
                    text = str(exc) if isinstance(exc, (ValueError, OutlookError)) else f"Automation stopped ({type(exc).__name__}). Check sources and Outlook."
                    self.progress_queue.put((0, text))
                    return text
            self.work(action, lambda text: self.status.set(text))
        self.root.after(30000, self.schedule)

    def background(self):
        self.root.iconify()

    def poll(self):
        try:
            while True:
                value, text = self.progress_queue.get_nowait()
                self.progress_value.set(value)
                self.stage.set(text)
        except Empty:
            pass
        try:
            done, result, exc = self.queue.get_nowait()
            self.busy = False
            for w in self.inputs:
                w.state(["!disabled"])
            if exc:
                self.error(exc)
            else:
                try:
                    done(result)
                except Exception as callback_error:
                    self.error(callback_error)
            self.update_buttons()
        except Empty:
            pass
        self.root.after(100, self.poll)

    def start_check(self):
        try:
            if not self.confirmed.get():
                raise ValueError("Confirm the closed audit day and new OPERA business day first.")
            audit, business = read_day(self.audit.get()), read_day(self.business.get())
            manifest(audit, business)
            folder = Path(self.folder.get())
            if not self.folder.get().strip():
                raise ValueError("Choose a report folder first.")
            self.settings.last_folder = str(folder)
            self.settings.save(self.data_root)
            self.check = None
            self.table.delete(*self.table.get_children())
            def action():
                check = scan(folder, audit, business)
                self.service.save_check(check)
                return check
            def done(check):
                self.check = check
                self.stamp = self.folder_stamp()
                self.render()
            self.work(action, done)
        except Exception as exc:
            self.error(exc)

    def render(self):
        selected = self.table.selection()
        self.table.delete(*self.table.get_children())
        if not self.check:
            return
        for row in self.check.rows:
            self.table.insert("", "end", iid=row.slot.key, values=(row.slot.label,
                "; ".join(d.path.name for d in row.candidates), row.document.period.display if row.document else "—", row.status), tags=(row.status,))
        for i, (doc, reason, block) in enumerate(self.check.extras):
            self.table.insert("", "end", iid=f"extra:{i}", values=("Extra / unresolved PDF", doc.path.name, doc.period.display,
                "BLOCKED" if block else "EXCLUDED"))
        if selected and self.table.exists(selected[0]):
            self.table.selection_set(selected[0])
        passed = sum(r.status in ("PASS", "CONFIRMED") for r in self.check.rows)
        self.status.set(f"{passed}/23 reports ready. " + ("Ready to create an Outlook draft." if self.check.ready else "Resolve missing, invalid and review items."))
        self.update_buttons()

    def selected(self):
        if not self.check or not self.table.selection():
            return None, None
        key = self.table.selection()[0]
        if key.startswith("extra:"):
            return None, self.check.extras[int(key.split(":")[1])][0]
        row = next(r for r in self.check.rows if r.slot.key == key)
        return row, row.document

    def selection_changed(self, *_):
        row, doc = self.selected()
        if row:
            self.detail.set(f"Expected: {row.slot.expected}. {row.message}")
        elif doc:
            self.detail.set(next(reason for d, reason, _ in self.check.extras if d == doc))
        self.update_buttons()

    def update_buttons(self):
        row, doc = self.selected()
        available = not self.busy and self.check is not None
        for button, enable in [(self.open_button, available and doc is not None),
            (self.confirm_button, available and row is not None and row.status == "REVIEW"),
            (self.assign_button, available and doc is not None and doc.kind == "forecast" and not doc.period.start and not doc.period.ambiguous),
            (self.draft_button, available and self.check.ready),
            (self.another_button, available and self.check.ready)]:
            button.state(["!disabled" if enable else "disabled"])

    def open_selected(self):
        try:
            _, doc = self.selected()
            if doc:
                self.check.assert_unchanged()
                open_path(doc.path)
                self.check.mark_opened(doc.path)
        except Exception as exc:
            self.error(exc)

    def confirm_period(self):
        row, doc = self.selected()
        if not row or not doc:
            return
        if doc.digest not in self.check.opened:
            self.error(ValueError("Use Open PDF and inspect the reporting period first."))
            return
        reviewer = simpledialog.askstring("Staff confirmation", "Your initials / staff identifier:", parent=self.root)
        if not reviewer:
            return
        note = simpledialog.askstring("Reporting period", f"Expected: {row.slot.expected}\nRecord the actual period and filters checked; no guest details:", parent=self.root)
        if note is None:
            return
        try:
            self.check.confirm_date(row.slot.key, reviewer, note)
            self.service.save_check(self.check)
            self.render()
        except Exception as exc:
            self.error(exc)

    def assign_month(self):
        _, doc = self.selected()
        if not doc:
            return
        month = simpledialog.askstring("Forecast month", "After opening the PDF, enter its month as YYYY-MM.\nYou must then separately confirm its reporting period.", parent=self.root)
        if month:
            try:
                self.check.assert_unchanged()
                self.check.assign_forecast(doc.path, "forecast-" + month.strip())
                self.service.save_check(self.check)
                self.render()
            except Exception as exc:
                self.error(exc)

    def draft(self, another=False):
        if self.busy or not self.check or not self.check.ready:
            return
        if another and not messagebox.askyesno("Create another draft?", "Inspect Outlook first for an existing or incomplete draft.\n\nCreate a separate additional draft for this pack?", parent=self.root):
            return
        check, settings = self.check, self.settings
        self.work(lambda: self.service.prepare(check, settings, another=another), lambda text: self.status.set(text))

    def compatibility(self):
        def done(result):
            write_json(self.data_root / "compatibility.json", result)
            messagebox.showinfo("Workstation compatibility", "\n".join(str(v) for v in result.values()), parent=self.root)
            self.status.set("Compatibility check recorded. Complete the attachment pilot on this PC.")
        self.work(self.service.adapter.compatibility, done)

    def history(self):
        self.data_root.mkdir(parents=True, exist_ok=True)
        open_path(self.data_root)

    def edit_settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Night Reports settings")
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Sources & daily automation", style="Title.TLabel").pack(anchor="w")
        ttk.Button(frame, text="Choose report folder…", command=self.browse).pack(anchor="w")
        ttk.Label(frame, textvariable=self.folder, wraplength=600).pack(anchor="w")
        ttk.Button(frame, text="Check Outlook compatibility", command=self.compatibility).pack(anchor="w", pady=5)
        enabled = tk.BooleanVar(value=self.settings.automation_enabled)
        ttk.Checkbutton(frame, text="Automatically collect, verify and send daily", variable=enabled).pack(anchor="w")
        ttk.Label(frame, text="OPERA scheduler folder (audit subfolders are found here too)").pack(anchor="w")
        source = ttk.Entry(frame, width=65)
        source.pack(fill="x")
        source.insert(0, self.settings.scheduler_folder)
        times = ttk.Frame(frame)
        times.pack(fill="x", pady=5)
        ttk.Label(times, text="Collect at").pack(side="left")
        collect_time = ttk.Entry(times, width=8)
        collect_time.insert(0, self.settings.collect_time)
        collect_time.pack(side="left", padx=8)
        ttk.Label(times, text="Send after").pack(side="left")
        send_time = ttk.Entry(times, width=8)
        send_time.insert(0, self.settings.send_time)
        send_time.pack(side="left", padx=8)
        ttk.Label(frame, text="Uses this PC's local date/time. Closed audit day = yesterday. Closing minimizes; Exit stops automation.", wraplength=600).pack(anchor="w", pady=5)
        ttk.Label(frame, text="To recipients — one email address per line").pack(anchor="w")
        addresses = tk.Text(frame, width=65, height=6)
        addresses.pack(fill="x", pady=5)
        addresses.insert("1.0", "\n".join(self.settings.recipients))
        ttk.Label(frame, text="Subject").pack(anchor="w")
        subject = ttk.Entry(frame, width=65)
        subject.pack(fill="x", pady=5)
        subject.insert(0, self.settings.subject)
        ttk.Label(frame, text="Body (plain text, including signature)").pack(anchor="w")
        body = tk.Text(frame, width=65, height=7)
        body.pack(fill="x", pady=5)
        body.insert("1.0", self.settings.body)
        def save():
            try:
                settings = Settings([s.strip() for s in addresses.get("1.0", "end").splitlines() if s.strip()],
                                    subject.get(), body.get("1.0", "end-1c"), self.folder.get(),
                                    enabled.get(), source.get().strip(), collect_time.get().strip(), send_time.get().strip())
                settings.save(self.data_root)
                self.settings = settings
                self.invalidate()
                dialog.destroy()
            except Exception as exc:
                self.error(exc)
        ttk.Button(frame, text="Save settings", command=save).pack(anchor="e", pady=8)

    def folder_stamp(self):
        if not self.check:
            return None
        return tuple(sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in self.check.folder.iterdir() if p.suffix.lower() == ".pdf"))

    def watch(self):
        if self.check and not self.busy:
            try:
                if self.folder_stamp() != self.stamp:
                    self.invalidate()
                    self.status.set("Report files changed. Confirm dates and Check Reports again.")
            except OSError:
                self.invalidate()
                self.status.set("Report folder is no longer accessible. Check Reports again.")
        self.root.after(2000, self.watch)

    def close(self):
        self.background()

    def exit_app(self):
        if self.busy:
            messagebox.showinfo("Night Reports", "Wait for the current check or draft attempt to finish before closing.", parent=self.root)
            return
        self.pool.shutdown(wait=False)
        self.root.destroy()


def main():
    from .__main__ import main as entry
    entry()
