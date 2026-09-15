"""Source-first report workflow with expandable activity and notification icon."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from queue import Queue, Empty
from dataclasses import replace
import json
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from .automation import DailyAutomation
from .dates import DateField, read_day
from .engine import scan
from .outlook import OutlookAdapter, OutlookError
from .service import PackService
from .storage import Settings, write_json
from .tray import Tray


def open_path(path):
    if sys.platform=='win32': os.startfile(str(path))
    else: subprocess.Popen(['open' if sys.platform=='darwin' else 'xdg-open',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

class Window:
    def __init__(self,root,data_root):
        self.root,self.data_root=root,data_root
        self.settings=Settings.load(data_root)
        self.service=PackService(data_root,OutlookAdapter())
        self.automation=DailyAutomation(data_root,self.service)
        self.pool=ThreadPoolExecutor(max_workers=1); self.queue=Queue(); self.events=Queue(); self.tray_actions=Queue()
        self.tray=None; self.busy=False; self.check=None; self.stamp=None; self.source_rows=[]; self.opened=set()
        self.paused=False
        self.folder=tk.StringVar(value=self.settings.last_folder)
        self.audit=tk.StringVar(value=str(date.today()-timedelta(days=1)))
        self.business=tk.StringVar(value=str(date.today()))
        self.confirmed=tk.BooleanVar(value=True)
        self.status=tk.StringVar(value='Ready to discover today’s OPERA exports')
        self.detail=tk.StringVar(); self.stage=tk.StringVar(value='Waiting for reports')
        self.progress_value=tk.DoubleVar(value=0)
        root.title('MAISON · Night Reports'); root.geometry('1200x760'); root.minsize(850,570)
        style=ttk.Style(root); style.theme_use('clam')
        style.configure('.',font=('Segoe UI',10),background='#f4f7fb',foreground='#20334c')
        style.configure('TButton',padding=(12,7),background='#e8edf5',borderwidth=0)
        style.configure('Treeview',rowheight=29,background='white',fieldbackground='white',borderwidth=0)
        style.configure('Treeview.Heading',font=('Segoe UI',10,'bold'),padding=8,background='#e8edf5')
        style.map('Treeview',background=[('selected','#dcecf7')],foreground=[('selected','#15324e')])
        self.frame=ttk.Frame(root,padding=18); self.frame.pack(fill='both',expand=True)
        header=ttk.Frame(self.frame); header.pack(fill='x')
        ttk.Label(header,text='Night Reports',font=('Segoe UI',24,'bold')).pack(side='left')
        for text,command in [('Settings',self.edit_settings),('Background',self.background),('Exit',self.exit_app)]:
            ttk.Button(header,text=text,command=command).pack(side='right',padx=4)
        dates=ttk.Frame(self.frame); dates.pack(fill='x',pady=12)
        ttk.Label(dates,text='Closed audit day').pack(side='left'); DateField(dates,self.audit).pack(side='left',padx=(6,18))
        ttk.Label(dates,text='OPERA business day').pack(side='left'); DateField(dates,self.business).pack(side='left',padx=6)
        self.collect_button=ttk.Button(dates,text='Collect now',command=self.start_check); self.collect_button.pack(side='right')
        self.flow=tk.Canvas(self.frame,height=66,bg='#f4f7fb',highlightthickness=0)
        self.flow.pack(fill='x'); self.flow.bind('<Configure>',lambda e:self.draw_progress())
        ttk.Label(self.frame,textvariable=self.stage).pack(anchor='w',pady=(0,5))
        self.log_button=ttk.Button(self.frame,text='▸ Activity log',command=self.toggle_log); self.log_button.pack(anchor='w')
        self.log_frame=ttk.Frame(self.frame)
        self.log_text=tk.Text(self.log_frame,height=5,wrap='word',font=('Segoe UI',9),bg='#edf2f8',relief='flat',state='disabled')
        self.log_text.pack(side='left',fill='both',expand=True)
        log_scroll=ttk.Scrollbar(self.log_frame,command=self.log_text.yview); log_scroll.pack(side='right',fill='y'); self.log_text.configure(yscrollcommand=log_scroll.set)
        self.tabs=ttk.Notebook(self.frame); self.tabs.pack(fill='both',expand=True,pady=(8,0))
        self.source_page=ttk.Frame(self.tabs); self.prepared_page=ttk.Frame(self.tabs)
        self.tabs.add(self.source_page,text='1  Source reports'); self.tabs.add(self.prepared_page,text='2  Prepared reports')
        self.source_table=self.make_table(self.source_page,[('report','Report',205),('original','Original document',200),('source','Source path',290),('retrieved','Retrieved at',155),('created','Original file created',155),('modified','Original modified',155),('issue','PDF issue date',110),('name','Final filename',220),('converted','Copied / renamed',115),('status','Result',100)])
        self.table=self.make_table(self.prepared_page,[('report','Report',210),('file','Final filename',240),('period','Reporting period',230),('status','Verification',110)])
        self.source_table.bind('<Double-1>',lambda e:self.report_menu(True)); self.table.bind('<Double-1>',lambda e:self.report_menu(False))
        self.table.bind('<<TreeviewSelect>>',self.selection_changed)
        # Legacy callable controls retained for keyboard/test integrations, not cluttering the main view.
        self.open_button=ttk.Button(self.frame,command=self.open_selected); self.confirm_button=ttk.Button(self.frame,command=self.confirm_period)
        self.assign_button=ttk.Button(self.frame); self.another_button=ttk.Button(self.frame)
        self.draft_button=ttk.Button(self.frame,text='Create draft only',command=self.draft)
        self.inputs=[self.collect_button]
        self.status.trace_add('write',lambda *_:self.add_log(self.status.get()))
        for var in (self.folder,self.audit,self.business): var.trace_add('write',self.invalidate)
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.after(100,self.poll); root.after(2000,self.watch); root.after(1000,self.schedule)
        self.update_buttons(); self.draw_progress()

    def make_table(self,parent,columns):
        parent.rowconfigure(0,weight=1); parent.columnconfigure(0,weight=1)
        table=ttk.Treeview(parent,columns=[c[0] for c in columns],show='headings',selectmode='browse')
        for key,title,width in columns: table.heading(key,text=title); table.column(key,width=width,minwidth=80,stretch=False)
        table.grid(row=0,column=0,sticky='nsew')
        y=ttk.Scrollbar(parent,command=table.yview); y.grid(row=0,column=1,sticky='ns')
        x=ttk.Scrollbar(parent,orient='horizontal',command=table.xview); x.grid(row=1,column=0,sticky='ew')
        table.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        for tag,color in [('PASS','#087f6c'),('CONFIRMED','#087f6c'),('WRONG','#b93845'),('MISSING','#9c6818'),('REVIEW','#9c6818'),('DUPLICATE','#b93845')]: table.tag_configure(tag,foreground=color)
        return table

    def draw_progress(self):
        canvas=self.flow; canvas.delete('all'); width=max(canvas.winfo_width(),800); value=self.progress_value.get()
        for i,label in enumerate(('Collect','Copy & rename','Verify','Draft','Send')):
            x=24+i*(width-48)/5; active=value>=(10,50,65,75,95)[i]
            canvas.create_oval(x,8,x+24,32,fill='#0b9b8a' if active else '#dae3ee',outline='')
            canvas.create_text(x+12,20,text='✓' if active else str(i+1),fill='white' if active else '#536780',font=('Segoe UI',9,'bold'))
            canvas.create_text(x+32,20,text=label,anchor='w',fill='#20334c',font=('Segoe UI',10))
        canvas.create_line(24,51,width-24,51,fill='#dce5ef',width=5,capstyle='round')
        if value: canvas.create_line(24,51,24+(width-48)*value/100,51,fill='#0b9b8a',width=5,capstyle='round')

    def toggle_log(self):
        if self.log_frame.winfo_manager(): self.log_frame.pack_forget(); self.log_button.configure(text='▸ Activity log')
        else: self.log_frame.pack(fill='x',before=self.tabs,pady=4); self.log_button.configure(text='▾ Activity log')
    def add_log(self,text):
        if not text or getattr(self,'last_log',None)==text:return
        self.last_log=text
        self.log_text.configure(state='normal'); self.log_text.insert('end',f'{datetime.now():%H:%M:%S}  {text}\n'); self.log_text.see('end'); self.log_text.configure(state='disabled')
        self.automation.log(text,datetime.now())
    def error(self,exc):
        text=str(exc) if isinstance(exc,(ValueError,OutlookError)) else f'Operation failed ({type(exc).__name__}). Check source access and Outlook.'
        self.status.set(text); self.stage.set(text[:150])
    def invalidate(self,*args,**kwargs):
        self.check=None; self.stamp=None
        if hasattr(self,'table'):self.table.delete(*self.table.get_children()); self.update_buttons()
    def work(self,action,done):
        if self.busy:return
        self.busy=True; self.collect_button.state(['disabled']); self.update_buttons()
        def run():
            try:self.queue.put((done,action(),None))
            except Exception as exc:self.queue.put((done,None,exc))
        self.pool.submit(run)
    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='sources':
                    self.source_rows=value; self.source_table.delete(*self.source_table.get_children())
                    for r in value:self.source_table.insert('','end',iid=r['key'],values=[r.get(c,'—') for c in self.source_table['columns']],tags=(r['status'],))
                elif kind=='prepared':
                    self.check=value; self.stamp=self.folder_stamp(); self.render(); self.tabs.select(self.prepared_page)
                elif kind=='progress':
                    n,text=value; self.progress_value.set(n); self.stage.set(text); self.add_log(text); self.draw_progress()
        except Empty:pass
        try:
            while True:
                action=self.tray_actions.get_nowait()
                if action=='open':self.root.deiconify(); self.root.lift()
                elif action=='pause':self.paused=not self.paused; self.status.set('Automation paused' if self.paused else 'Automation resumed')
                elif action=='exit':self.exit_app()
        except Empty:pass
        try:
            done,result,exc=self.queue.get_nowait(); self.busy=False; self.collect_button.state(['!disabled'])
            if exc:self.error(exc)
            else:
                try:done(result)
                except Exception as err:self.error(err)
            self.update_buttons()
        except Empty:pass
        self.root.after(100,self.poll)
    def schedule(self):
        if not self.busy and not self.paused:
            settings=replace(self.settings)
            if not self.source_rows:
                self.start_check()
            elif settings.automation_enabled:
                # Automatic dates roll over daily, independently of historical inspection dates.
                self.work(lambda:self.automation.tick(settings,progress=lambda n,t:self.events.put(('progress',(n,t))),event=lambda k,v:self.events.put((k,v))),lambda text:self.status.set(text))
            elif not self.source_rows:self.start_check()
        self.root.after(60000,self.schedule)
    def start_check(self):
        if self.busy:return
        try:audit,business=read_day(self.audit.get()),read_day(self.business.get())
        except ValueError as exc:self.error(exc);return
        self.tabs.select(self.source_page)
        settings=replace(self.settings)
        self.work(lambda:self.automation.discover(settings,audit=audit,business=business,event=lambda k,v:self.events.put((k,v))),lambda result:self.status.set(result[3]))
    def render(self):
        self.table.delete(*self.table.get_children())
        if not self.check:return
        for r in self.check.rows:self.table.insert('','end',iid=r.slot.key,values=(r.slot.label,'; '.join(d.path.name for d in r.candidates),r.document.period.display if r.document else '—',r.status),tags=(r.status,))
        self.update_buttons()
    def selected(self):
        if not self.check or not self.table.selection():return None,None
        row=next((r for r in self.check.rows if r.slot.key==self.table.selection()[0]),None)
        return row,row.document if row else None
    def selection_changed(self,*args):self.update_buttons()
    def update_buttons(self):
        row,doc=self.selected(); available=not self.busy and self.check is not None
        for button,enabled in [(self.open_button,available and doc is not None),(self.confirm_button,available and row is not None and row.status=='REVIEW'),(self.assign_button,False),(self.draft_button,available and self.check.ready),(self.another_button,False)]:button.state(['!disabled' if enabled else 'disabled'])
    def open_selected(self):
        row,doc=self.selected()
        if doc:
            open_path(doc.path); self.check.mark_opened(doc.path)
    def confirm_period(self):
        row,doc=self.selected()
        if not row or not doc:return
        initials=simpledialog.askstring('Confirm report','Your initials:',parent=self.root)
        if initials:
            try:self.check.confirm_date(row.slot.key,initials,'Period and filters inspected');self.render()
            except Exception as exc:self.error(exc)
    def report_menu(self,source):
        table=self.source_table if source else self.table
        if not table.selection() or self.busy:return
        key=table.selection()[0]
        info=next((r for r in self.source_rows if r['key']==key),None)
        row,doc=self.selected() if not source else (None,None)
        path=Path(info['source']) if source and info and info.get('sha256') else (doc.path if doc else None)
        dialog=tk.Toplevel(self.root);dialog.title('Report actions');dialog.transient(self.root)
        frame=ttk.Frame(dialog,padding=16);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text=info['report'] if info else key,font=('Segoe UI',12,'bold')).pack(anchor='w')
        ttk.Label(frame,text=info['reason'] if source and info else (row.message if row else ''),wraplength=450).pack(pady=8)
        def view():
            if path:open_path(path);self.opened.add(str(path))
        def confirm():
            if not path or str(path) not in self.opened:self.error(ValueError('View the PDF before confirming.'));return
            initials=simpledialog.askstring('Confirm report','Your initials:',parent=dialog)
            if not initials:return
            try:
                if source:self.automation.collector.confirm(read_day(self.business.get()),info,initials);dialog.destroy();self.start_check()
                else:self.check.mark_opened(path);self.check.confirm_date(key,initials,'Period and filters inspected');self.render();dialog.destroy()
            except Exception as exc:self.error(exc)
        def attach():
            value=filedialog.askopenfilename(parent=dialog,filetypes=[('PDF report','*.pdf')])
            if value:
                self.automation.collector.replacement(read_day(self.business.get()),key,Path(value));dialog.destroy();self.start_check()
        for text,command in [('View PDF',view),('Confirm correct report',confirm),('Attach another report',attach),('Close',dialog.destroy)]:ttk.Button(frame,text=text,command=command).pack(fill='x',pady=3)
    def draft(self,another=False):
        if self.busy or not self.check or not self.check.ready:return
        self.work(lambda:self.service.prepare(self.check,self.settings),lambda text:self.status.set(text))
    def compatibility(self):
        def done(result):
            write_json(self.data_root/'compatibility.json',result);self.status.set(result['result']);messagebox.showinfo('Outlook connection',result['result'],parent=self.root)
        self.work(self.service.adapter.compatibility,done)
    def browse(self):
        value=filedialog.askdirectory(parent=self.root,title='Choose Night Reports destination')
        if value:self.folder.set(value)
    def history(self):self.data_root.mkdir(parents=True,exist_ok=True);open_path(self.data_root)
    def edit_settings(self):
        if self.busy:return
        dialog=tk.Toplevel(self.root);dialog.title('Night Reports settings');dialog.geometry('690x650');dialog.transient(self.root)
        notebook=ttk.Notebook(dialog);notebook.pack(fill='both',expand=True,padx=14,pady=14)
        sources=ttk.Frame(notebook,padding=16);email=ttk.Frame(notebook,padding=16)
        notebook.add(sources,text='Sources & schedule');notebook.add(email,text='Email & Outlook')
        values={}
        def field(parent,label,key,value):
            ttk.Label(parent,text=label).pack(anchor='w',pady=(10,3));var=tk.StringVar(value=value);ttk.Entry(parent,textvariable=var).pack(fill='x');values[key]=var
        field(sources,'OPERA source folder (contains audit subfolders)','scheduler_folder',self.settings.scheduler_folder)
        field(sources,'Night Reports destination','last_folder',self.folder.get())
        def choose():
            value=filedialog.askdirectory(parent=dialog)
            if value:values['last_folder'].set(value)
        ttk.Button(sources,text='Choose report folder…',command=choose).pack(anchor='w',pady=4)
        enabled=tk.BooleanVar(value=self.settings.automation_enabled)
        ttk.Checkbutton(sources,text='Automatically collect, verify and send',variable=enabled).pack(anchor='w',pady=10)
        for key,label in [('collect_time','Start collection'),('send_time','Send no earlier than'),('stop_time','Stop incomplete run')]:field(sources,label,key,getattr(self.settings,key))
        ttk.Label(sources,text='Checks every minute. Source files must be generated today.\nClosing hides to the notification area; Exit stops the app.',wraplength=600).pack(anchor='w',pady=12)
        ttk.Button(sources,text='Run history / logs',command=self.history).pack(anchor='w')
        ttk.Label(email,text='Recipients · one address per line').pack(anchor='w')
        addresses=tk.Text(email,height=5);addresses.pack(fill='x');addresses.insert('1.0','\n'.join(self.settings.recipients))
        field(email,'Sending account address (blank = Outlook default)','sender',self.settings.sender)
        field(email,'Subject','subject',self.settings.subject)
        ttk.Label(email,text='Body and signature').pack(anchor='w',pady=(10,3));body=tk.Text(email,height=6);body.pack(fill='x');body.insert('1.0',self.settings.body)
        ttk.Button(email,text='Check Outlook connection',command=self.compatibility).pack(anchor='w',pady=8)
        def save():
            try:
                settings=replace(self.settings,**{key:var.get().strip() for key,var in values.items()},automation_enabled=enabled.get(),recipients=[a.strip() for a in addresses.get('1.0','end').splitlines() if a.strip()],body=body.get('1.0','end-1c'))
                settings.save(self.data_root);self.settings=settings;self.folder.set(settings.last_folder);dialog.destroy();self.status.set('Settings saved. Next collection check within one minute.')
            except Exception as exc:self.error(exc)
        ttk.Button(dialog,text='Save settings',command=save).pack(anchor='e',padx=14,pady=(0,14))
    def folder_stamp(self):
        if not self.check:return None
        return tuple((str(d.path),d.path.stat().st_size,d.path.stat().st_mtime_ns) for d in self.check.documents)
    def watch(self):
        if self.check and not self.busy:
            try:
                if self.folder_stamp()!=self.stamp:self.invalidate();self.status.set('Prepared files changed; verification is required again.')
            except OSError:self.invalidate()
        self.root.after(2000,self.watch)
    def background(self):
        try:
            if self.tray is None:self.tray=Tray(self.tray_actions);self.tray.start()
            self.root.withdraw()
        except Exception as exc:self.tray=None;self.error(exc)
    def close(self):self.background()
    def exit_app(self):
        if self.busy:self.status.set('Finish the active operation before exiting.');return
        if self.tray:self.tray.stop()
        self.pool.shutdown(wait=False);self.root.destroy()

def main():
    from .__main__ import main as entry
    entry()
