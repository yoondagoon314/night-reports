"""GUI entry point and read-only diagnostic commands."""
import argparse
import json
from pathlib import Path
import sys
from .storage import FileLock, data_directory, write_json


def main():
    parser = argparse.ArgumentParser(description="MAISON Night Reports — check PDFs and create Outlook drafts")
    parser.add_argument("--data-dir", type=Path, default=data_directory())
    parser.add_argument("--check", type=Path, help="Read-only folder check; no Outlook access")
    parser.add_argument("--audit", help="Closed day YYYY-MM-DD")
    parser.add_argument("--business", help="New business day YYYY-MM-DD")
    parser.add_argument("--compatibility", action="store_true")
    parser.add_argument("--self-test", type=Path, help="Packaged startup check; no Outlook connection")
    args = parser.parse_args()
    if args.self_test:
        try:
            import tkinter as tk
            from pypdf import PdfReader
            if sys.platform == "win32":
                import pythoncom
                import win32com.client
            probe = tk.Tk()
            probe.withdraw()
            probe.update()
            probe.destroy()
            write_json(args.self_test, {"result": "PASS", "platform": sys.platform,
                       "frozen": bool(getattr(sys, "frozen", False)), "outlook_opened": False})
            return 0
        except Exception as exc:
            write_json(args.self_test, {"result": "FAIL", "error_type": type(exc).__name__})
            return 1
    if args.check:
        from datetime import date
        from .engine import scan
        if not args.audit or not args.business:
            parser.error("--check needs --audit and --business")
        try:
            check = scan(args.check, date.fromisoformat(args.audit), date.fromisoformat(args.business))
            print(json.dumps(check.record(), indent=2))
            return 0 if check.ready else 2
        except (ValueError, OSError) as exc:
            print(f"Check failed ({type(exc).__name__}). Verify folder access and dates.", file=sys.stderr)
            return 1
    if args.compatibility:
        from .outlook import OutlookAdapter, OutlookError
        try:
            result = OutlookAdapter().compatibility()
            write_json(args.data_dir / "compatibility.json", result)
            print(json.dumps(result, indent=2))
            return 0
        except OutlookError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    import tkinter as tk
    from tkinter import messagebox
    from .gui import Window
    root = tk.Tk()
    root.withdraw()
    try:
        with FileLock(args.data_dir / "app.lock"):
            Window(root, args.data_dir)
            root.deiconify()
            root.mainloop()
    except (ValueError, OSError) as exc:
        messagebox.showerror("Night Reports", str(exc), parent=root)
        root.destroy()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
