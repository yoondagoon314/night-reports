from datetime import date
import calendar
import re
import tkinter as tk
from tkinter import ttk

def read_day(value):
    value=value.strip()
    try: return date.fromisoformat(value)
    except ValueError: pass
    match=re.fullmatch(r'(\d{1,2})[./-](\d{1,2})(?:[./-](\d{0,4}))?',value)
    if not match: raise ValueError('Enter a valid date, e.g. 19.05.2026.')
    day,month,year=match.groups()
    if not year or (len(year)==3 and str(date.today().year).startswith(year)):
        year=str(date.today().year)
    elif len(year)==2: year='20'+year
    elif len(year)!=4: raise ValueError('Complete the year using four digits.')
    return date(int(year),int(month),int(day))

class DateField(ttk.Frame):
    def __init__(self,parent,variable):
        super().__init__(parent); self.variable=variable
        self.entry=ttk.Entry(self,textvariable=variable,width=13)
        self.entry.pack(side='left')
        self.entry.bind('<FocusOut>',self.complete)
        self.entry.bind('<Button-1>',lambda e:self.after_idle(self.calendar))
        ttk.Button(self,text='▦',width=3,command=self.calendar).pack(side='left')
        self.popup=None
    def complete(self,*args):
        try:
            parsed=read_day(self.variable.get()).isoformat()
            if parsed!=self.variable.get(): self.variable.set(parsed)
        except ValueError: pass
    def calendar(self):
        if self.popup and self.popup.winfo_exists(): return
        try: current=read_day(self.variable.get())
        except ValueError: current=date.today()
        self.popup=tk.Toplevel(self); self.popup.title('Choose date'); self.popup.transient(self.winfo_toplevel())
        panel=ttk.Frame(self.popup,padding=10); panel.pack()
        def draw(year,month):
            for child in panel.winfo_children(): child.destroy()
            def move(delta):
                y,m=divmod(year*12+month-1+delta,12); draw(y,m+1)
            ttk.Button(panel,text='‹',width=3,command=lambda:move(-1)).grid(row=0,column=0)
            ttk.Label(panel,text=f'{calendar.month_name[month]} {year}').grid(row=0,column=1,columnspan=5)
            ttk.Button(panel,text='›',width=3,command=lambda:move(1)).grid(row=0,column=6)
            for col,label in enumerate(('M','T','W','T','F','S','S')): ttk.Label(panel,text=label).grid(row=1,column=col)
            def choose(day):
                self.variable.set(date(year,month,day).isoformat()); self.popup.destroy()
            for row,week in enumerate(calendar.monthcalendar(year,month),2):
                for col,day in enumerate(week):
                    if day: ttk.Button(panel,text=str(day),width=3,command=lambda d=day:choose(d)).grid(row=row,column=col)
        draw(current.year,current.month)
