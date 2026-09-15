"""Windows notification icon; UI actions are passed to the Tk thread."""
import threading
import sys

class Tray:
    def __init__(self, actions):
        self.actions = actions
        self.hwnd = None
        self.ready = threading.Event()
        self.error = None
    def start(self):
        if sys.platform != 'win32':
            raise ValueError('The notification-area icon is available on Windows.')
        threading.Thread(target=self.run, daemon=True).start()
        if not self.ready.wait(3) or self.error:
            raise ValueError('Could not create the notification icon; window remains open.')
    def run(self):
        try:
            import win32api, win32con, win32gui
            self.gui = win32gui
            self.con = win32con
            message = win32con.WM_USER + 20
            def handler(hwnd, msg, wparam, lparam):
                if msg == message:
                    if lparam == win32con.WM_LBUTTONDBLCLK:
                        self.actions.put('open')
                    elif lparam == win32con.WM_RBUTTONUP:
                        menu = win32gui.CreatePopupMenu()
                        for id_, text in ((1,'Open Night Reports'),(2,'Pause / resume automation'),(3,'Exit')):
                            win32gui.AppendMenu(menu,win32con.MF_STRING,id_,text)
                        win32gui.SetForegroundWindow(hwnd)
                        choice = win32gui.TrackPopupMenu(menu,win32con.TPM_RETURNCMD|win32con.TPM_RIGHTBUTTON,*win32gui.GetCursorPos(),0,hwnd,None)
                        win32gui.DestroyMenu(menu)
                        if choice: self.actions.put({1:'open',2:'pause',3:'exit'}[choice])
                elif msg == win32con.WM_CLOSE:
                    win32gui.DestroyWindow(hwnd)
                elif msg == win32con.WM_DESTROY:
                    win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE,(hwnd,0))
                    win32gui.PostQuitMessage(0)
                return 0
            wc=win32gui.WNDCLASS(); wc.hInstance=win32api.GetModuleHandle(None)
            wc.lpszClassName='MaisonReportsTray'; wc.lpfnWndProc=handler
            atom=win32gui.RegisterClass(wc)
            self.hwnd=win32gui.CreateWindow(atom,'Maison Night Reports',0,0,0,0,0,0,0,wc.hInstance,None)
            icon=win32gui.LoadIcon(0,win32con.IDI_APPLICATION)
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD,(self.hwnd,0,win32gui.NIF_ICON|win32gui.NIF_MESSAGE|win32gui.NIF_TIP,message,icon,'Maison Night Reports'))
            self.ready.set(); win32gui.PumpMessages()
        except Exception as exc:
            self.error=type(exc).__name__; self.ready.set()
    def stop(self):
        if self.hwnd: self.gui.PostMessage(self.hwnd,self.con.WM_CLOSE,0,0)
