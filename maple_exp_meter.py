"""Visible-screen-only MapleStory EXP meter. No hooks, memory reads or input injection."""
import csv
import ctypes
from ctypes import wintypes
from datetime import datetime
import io
import json
import locale
import os
from pathlib import Path
import queue
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter import font as tkfont
from PIL import Image, ImageTk
import numpy as np
from meter_core import Session, parse_exp, verify
from i18n import translate

VERSION = '1.9.1'

BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
STORE = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'MapleExpMeter'
STORE.mkdir(parents=True, exist_ok=True)
LOGS = STORE / 'logs'
LOGS.mkdir(exist_ok=True)
CONFIG = STORE / 'config.json'
CAPS = {int(k): int(v) for k,v in json.loads((BASE/'exp_caps.json').read_text(encoding='utf-8')).items()}
DEFAULT = dict(exp_roi=[.525,.951,.635,.975], level_roi=[.224,.960,.246,.983], level=30,
               interval=3.0, auto_level=True, foreground=True, topmost=True,
               language='ko' if (locale.getlocale()[0] or '').lower().startswith('ko') else 'en')


def load_config():
    try:
        settings={**DEFAULT, **json.loads(CONFIG.read_text(encoding='utf-8'))}
        if settings.get('performance_version',0)<1:
            settings['interval']=max(3,float(settings.get('interval',3)))
        settings['performance_version']=1
        if settings.get('exp_roi')==[.552,.955,.622,.971]:
            settings['exp_roi']=list(DEFAULT['exp_roi'])
        return settings
    except Exception:
        return dict(DEFAULT)


def duration(seconds):
    if seconds is None:
        return '—'
    seconds = max(0, int(seconds))
    return f'{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}'


class Windows:
    def __init__(self):
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.u.GetForegroundWindow.restype = wintypes.HWND
        self.u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.u.IsIconic.argtypes = [wintypes.HWND]
        self.u.IsWindow.argtypes = [wintypes.HWND]
        self.u.IsWindowVisible.argtypes = [wintypes.HWND]

    def title(self, hwnd):
        text = ctypes.create_unicode_buffer(self.u.GetWindowTextLengthW(hwnd)+1)
        self.u.GetWindowTextW(hwnd,text,len(text))
        return text.value

    def windows(self):
        rows=[]
        @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        def visit(hwnd,_):
            title=self.title(hwnd)
            if self.u.IsWindowVisible(hwnd) and 'maplestory' in title.lower():
                rows.append((hwnd,title))
            return True
        self.u.EnumWindows(visit,0)
        return rows

    def rect(self, hwnd):
        if not self.u.IsWindow(hwnd) or self.u.IsIconic(hwnd):
            raise ValueError('MapleStory 창이 닫혔거나 최소화되어 있습니다.')
        r=wintypes.RECT()
        if not self.u.GetWindowRect(hwnd,ctypes.byref(r)):
            raise ValueError('게임 창 위치를 확인하지 못했습니다.')
        if r.right-r.left<200 or r.bottom-r.top<200:
            raise ValueError('게임 창 크기를 확인하세요.')
        return r.left,r.top,r.right,r.bottom


def screen_box(rect, roi):
    x,y,r,b=rect
    w,h=r-x,b-y
    return (int(x+roi[0]*w),int(y+roi[1]*h),int(x+roi[2]*w),int(y+roi[3]*h))


class SmallScreenCapture:
    """Copy only the requested desktop rectangle, reusing a small DIB buffer."""
    class Header(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('width',wintypes.LONG),('height',wintypes.LONG),
                  ('planes',wintypes.WORD),('bitcount',wintypes.WORD),('compression',wintypes.DWORD),
                  ('image_size',wintypes.DWORD),('xppm',wintypes.LONG),('yppm',wintypes.LONG),
                  ('used',wintypes.DWORD),('important',wintypes.DWORD)]

    def __init__(self):
        self.u=ctypes.WinDLL('user32',use_last_error=True)
        self.g=ctypes.WinDLL('gdi32',use_last_error=True)
        self.u.GetDC.argtypes=[wintypes.HWND];self.u.GetDC.restype=wintypes.HDC
        self.u.ReleaseDC.argtypes=[wintypes.HWND,wintypes.HDC]
        self.g.CreateCompatibleDC.argtypes=[wintypes.HDC];self.g.CreateCompatibleDC.restype=wintypes.HDC
        self.g.CreateDIBSection.argtypes=[wintypes.HDC,ctypes.c_void_p,wintypes.UINT,ctypes.POINTER(ctypes.c_void_p),wintypes.HANDLE,wintypes.DWORD]
        self.g.CreateDIBSection.restype=wintypes.HANDLE
        self.g.SelectObject.argtypes=[wintypes.HDC,wintypes.HANDLE];self.g.SelectObject.restype=wintypes.HANDLE
        self.g.DeleteObject.argtypes=[wintypes.HANDLE]
        self.g.DeleteDC.argtypes=[wintypes.HDC]
        self.g.BitBlt.argtypes=[wintypes.HDC,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.HDC,ctypes.c_int,ctypes.c_int,wintypes.DWORD]
        self.desktop=self.u.GetDC(None)
        self.memory=self.g.CreateCompatibleDC(self.desktop)
        self.bitmap=None;self.original=None;self.bits=ctypes.c_void_p();self.size=None
        if not self.desktop or not self.memory:
            self.close();raise OSError('화면 캡처 장치를 열지 못했습니다.')

    def grab(self,box):
        x,y,right,bottom=box;w,h=right-x,bottom-y
        if w<=0 or h<=0 or w*h>20_000_000:raise ValueError('인식 영역 크기를 확인하세요.')
        if self.size!=(w,h):
            if self.bitmap:
                self.g.SelectObject(self.memory,self.original);self.g.DeleteObject(self.bitmap);self.bitmap=None
            header=self.Header(ctypes.sizeof(self.Header),w,-h,1,32,0,w*h*4,0,0,0,0)
            self.bitmap=self.g.CreateDIBSection(self.desktop,ctypes.byref(header),0,ctypes.byref(self.bits),None,0)
            if not self.bitmap:raise OSError('캡처 버퍼를 생성하지 못했습니다.')
            self.original=self.g.SelectObject(self.memory,self.bitmap);self.size=(w,h)
        if not self.g.BitBlt(self.memory,0,0,w,h,self.desktop,x,y,0x00CC0020):
            raise OSError('게임의 화면 영역을 복사하지 못했습니다.')
        self.g.GdiFlush()
        return Image.frombytes('RGB',(w,h),ctypes.string_at(self.bits,w*h*4),'raw','BGRX')

    def close(self):
        if getattr(self,'bitmap',None):
            self.g.SelectObject(self.memory,self.original);self.g.DeleteObject(self.bitmap);self.bitmap=None
        if getattr(self,'memory',None):self.g.DeleteDC(self.memory);self.memory=None
        if getattr(self,'desktop',None):self.u.ReleaseDC(None,self.desktop);self.desktop=None


class Reader:
    def __init__(self):
        import cv2
        cv2.setNumThreads(1)
        from rapidocr_onnxruntime import RapidOCR
        self.engine=RapidOCR(intra_op_num_threads=1,inter_op_num_threads=1)

    def text(self,image):
        image=image.convert('RGB')
        scale=max(2,min(5,96/max(1,image.height)))
        image=image.resize((max(8,int(image.width*scale)),max(8,int(image.height*scale))),Image.Resampling.BICUBIC)
        pixels=np.array(image)
        # White HUD text becomes black on white; colored EXP brackets are discarded.
        mask=pixels.min(axis=2)>155
        binary=np.repeat(np.where(mask[:,:,None],0,255).astype(np.uint8),3,axis=2)
        result,_=self.engine(binary,use_det=False,use_cls=False)
        if not result:
            raise ValueError('OCR이 숫자를 찾지 못했습니다.')
        return ' '.join(str(r[0]) for r in result), min(float(r[1]) for r in result)

    def read(self,exp_image,level_image,fallback_level,auto=True):
        raw,confidence=self.text(exp_image)
        if confidence<.78:
            raise ValueError('EXP 숫자가 선명하게 읽히지 않습니다. 인식 영역을 확인하세요.')
        exp,pct=parse_exp(raw)
        level=fallback_level
        level_raw='수동'
        if auto:
            if level_image is None:
                raise CaptureReadError('level','자동 레벨 영역이 필요합니다.')
            try:level_raw,lc=self.text(level_image)
            except ValueError as error:
                raise CaptureReadError('level','레벨 숫자가 읽히지 않습니다. 레벨 영역을 다시 지정하세요.') from error
            digits=re.findall(r'\d{1,3}',level_raw)
            if lc<.75 or len(digits)!=1:
                raise CaptureReadError('level','레벨 숫자가 읽히지 않습니다. 레벨 영역을 다시 지정하세요.')
            level=int(digits[0])
            if not 1<=level<=99:
                raise CaptureReadError('level','레벨 숫자가 읽히지 않습니다. 레벨 영역을 다시 지정하세요.')
        verify(level,exp,pct,CAPS)
        return dict(level=level,exp=exp,pct=pct,raw=raw,confidence=confidence,level_raw=level_raw)


class CaptureReadError(ValueError):
    def __init__(self,area,message):
        super().__init__(message)
        self.area=area


class App:
    def __init__(self,root):
        self.root=root
        self.first_run=not CONFIG.exists()
        self.config=load_config()
        self.language=self.config.get('language','ko')
        if self.language not in ('ko','en'):self.language=DEFAULT['language']
        self.status_source='OCR 엔진을 준비하고 있습니다…'
        self.localized_widgets=[]
        self.win=Windows()
        self.session=Session(CAPS)
        self.results=queue.Queue()
        self.running=False
        self.shutdown=False
        self.test_requested=False
        self.generation=0
        self.settings={}
        self.last_image=None
        self.last_image_tk=None
        self.last_level_image=None
        self.last_level_image_tk=None
        self.rejected=0
        self.logpath=None
        self.latest=None
        self.root.title(f'Maple EXP Meter v{VERSION}')
        self.root.geometry('360x440+40+60')
        self.root.minsize(320,360)
        self.root.configure(bg='#101827')
        self.style=ttk.Style()
        self.style.theme_use('clam')
        self.ui_scale=1.0
        self.monitor_key=None
        self.font_specs={'body':('맑은 고딕',13,'normal'),'tiny':('맑은 고딕',11,'normal'),'title':('맑은 고딕',15,'bold'),'clock':('Consolas',20,'bold'),'metric':('맑은 고딕',20,'bold'),'percent':('맑은 고딕',28,'bold')}
        self.fonts={k:tkfont.Font(root=self.root,family=f,size=-size,weight=weight) for k,(f,size,weight) in self.font_specs.items()}
        self.style.configure('.',font=self.fonts['body'])
        self.style.configure('TFrame',background='#101827')
        self.style.configure('TLabel',background='#101827',foreground='#e6edf7')
        self.style.configure('TCheckbutton',background='#101827',foreground='#d7e2f2')
        self.style.map('TCheckbutton',background=[('active','#202e45')])
        self.build()
        self.apply_language()
        self.refresh_windows()
        self.refresh_settings()
        self.root.after(100,self.poll)
        self.root.after(500,self.refresh_display)
        self.root.after(100,self.watch_display)
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        if self.first_run:self.root.after(300,self.open_settings)
        threading.Thread(target=self.worker,daemon=True).start()

    def build(self):
        self.outer=ttk.Frame(self.root,padding=10);self.outer.pack(fill='both',expand=True)
        header=ttk.Frame(self.outer);header.pack(fill='x',pady=(0,7))
        ttk.Label(header,text='MAPLE EXP',font=self.fonts['title']).pack(side='left')
        clock=ttk.Frame(header);clock.pack(side='right')
        ttk.Label(clock,text='세션 경과',foreground='#97abc6',font=self.fonts['tiny']).pack(anchor='e')
        self.session_clock=tk.StringVar(value='00:00:00')
        ttk.Label(clock,textvariable=self.session_clock,foreground='#8ff1d7',font=self.fonts['clock']).pack(anchor='e')
        viewport=ttk.Frame(self.outer);viewport.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(viewport,bg='#101827',highlightthickness=0,borderwidth=0)
        scrollbar=ttk.Scrollbar(viewport,orient='vertical',command=self.canvas.yview);scrollbar.pack(side='right',fill='y')
        self.canvas.pack(side='left',fill='both',expand=True);self.canvas.configure(yscrollcommand=scrollbar.set)
        main=ttk.Frame(self.canvas);self.content=main
        self.content_window=self.canvas.create_window(0,0,window=main,anchor='nw')
        self.wrap_labels=[]
        main.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',self.resize_content)
        self.root.bind('<MouseWheel>',self.scroll_content,add='+')
        self.settings_window=tk.Toplevel(self.root)
        self.settings_window.title('Maple EXP · 상세설정')
        self.settings_window.geometry('460x460')
        self.settings_window.configure(bg='#101827')
        self.settings_window.transient(self.root)
        self.settings_window.protocol('WM_DELETE_WINDOW',self.settings_window.withdraw)
        self.settings_window.withdraw()
        settings=ttk.Frame(self.settings_window,padding=10);settings.pack(fill='both',expand=True)
        row=ttk.Frame(settings);row.pack(fill='x',pady=(0,6))
        ttk.Label(row,text='Language / 언어').pack(side='left')
        self.language_var=tk.StringVar(value='English' if self.language=='en' else '한국어')
        self.language_combo=ttk.Combobox(row,textvariable=self.language_var,values=['한국어','English'],state='readonly',width=12)
        self.language_combo.pack(side='left',padx=8)
        self.language_combo.bind('<<ComboboxSelected>>',self.change_language)
        ttk.Label(settings,text='처음 사용하거나 게임 해상도를 바꾸면 EXP·레벨 영역을 직접 지정하고 인식 시험을 하세요.',
                  wraplength=410,foreground='#f3cd83',font=self.fonts['tiny']).pack(fill='x',pady=(0,6))
        row=ttk.Frame(settings);row.pack(fill='x')
        ttk.Label(row,text='게임 창').pack(side='left')
        self.window_var=tk.StringVar();self.windows_combo=ttk.Combobox(row,textvariable=self.window_var,state='readonly',width=12);self.windows_combo.pack(side='left',padx=5,fill='x',expand=True)
        self.windows_combo.bind('<<ComboboxSelected>>',lambda _:self.refresh_settings())
        ttk.Button(row,text='새로고침',command=self.refresh_windows).pack(side='left')
        row=ttk.Frame(settings);row.pack(fill='x',pady=6);row.columnconfigure((0,1),weight=1,uniform='roi')
        actions=[('EXP 영역 지정',lambda:self.select_roi('exp_roi')),('레벨 영역 지정',lambda:self.select_roi('level_roi')),('기본 위치 복원',self.restore_roi),('인식 시험',self.request_test)]
        for i,(text,command) in enumerate(actions):ttk.Button(row,text=text,command=command).grid(row=i//2,column=i%2,sticky='ew',padx=2,pady=2)
        row=ttk.Frame(settings);row.pack(fill='x')
        self.auto=tk.BooleanVar(value=self.config['auto_level']);ttk.Checkbutton(row,text='레벨 자동',variable=self.auto,command=self.refresh_settings).pack(side='left')
        ttk.Label(row,text='수동 레벨').pack(side='left',padx=(8,3))
        self.level_var=tk.StringVar(value=str(self.config['level']));ttk.Spinbox(row,from_=1,to=99,width=4,textvariable=self.level_var,command=self.refresh_settings).pack(side='left')
        row=ttk.Frame(settings);row.pack(fill='x',pady=4)
        ttk.Label(row,text='인식 간격(초)').pack(side='left')
        self.interval=tk.StringVar(value=str(self.config['interval']));ttk.Combobox(row,values=['1','2','3','5'],textvariable=self.interval,width=4,state='readonly').pack(side='left',padx=5)
        self.top=tk.BooleanVar(value=self.config['topmost']);ttk.Checkbutton(row,text='항상 위',variable=self.top,command=self.refresh_settings).pack(side='left',padx=8)
        self.interval.trace_add('write',lambda *_:self.refresh_settings());self.level_var.trace_add('write',lambda *_:self.refresh_settings())
        self.foreground=tk.BooleanVar(value=self.config['foreground']);ttk.Checkbutton(settings,text='게임에 포커스가 있을 때만 측정',variable=self.foreground,command=self.refresh_settings).pack(anchor='w')
        row=ttk.Frame(main);row.pack(fill='x',pady=6);row.columnconfigure((0,1),weight=1,uniform='actions')
        self.start_button=ttk.Button(row,text='▶ 측정 시작',command=self.toggle);self.start_button.grid(row=0,column=0,sticky='ew',padx=2,pady=2)
        ttk.Button(row,text='측정 초기화',command=self.reset).grid(row=0,column=1,sticky='ew',padx=2,pady=2)
        ttk.Button(row,text='상세설정',command=self.open_settings).grid(row=0,column=2,sticky='ew',padx=2,pady=2)
        row.columnconfigure(2,weight=1,uniform='actions')
        tools=ttk.Frame(settings);tools.pack(fill='x',pady=6)
        ttk.Button(tools,text='CSV 내보내기',command=self.export).pack(side='left',expand=True,fill='x')
        ttk.Button(tools,text='기록 폴더',command=lambda:os.startfile(LOGS)).pack(side='left',expand=True,fill='x')
        self.status=tk.StringVar(value='OCR 엔진을 준비하고 있습니다…')
        status_label=ttk.Label(main,textvariable=self.status,wraplength=460,foreground='#f3cd83');status_label.pack(anchor='w',pady=(1,5));self.wrap_labels.append(status_label)
        self.repair_anchor=status_label
        self.repair_row=ttk.Frame(main)
        self.repair_row.pack(fill='x',before=status_label)
        ttk.Button(self.repair_row,text='레벨 영역 다시 지정',command=lambda:self.select_roi('level_roi')).pack(fill='x')
        self.repair_row.pack_forget()
        self.preview=ttk.Label(settings,text='EXP 인식 영역 미리보기',background='#263249');self.preview.pack(anchor='w',pady=(0,6))
        ttk.Label(settings,text='레벨 인식 영역 미리보기',font=self.fonts['tiny']).pack(anchor='w')
        self.level_preview=ttk.Label(settings,text='인식 시험을 누르면 여기에 표시됩니다.',background='#263249');self.level_preview.pack(anchor='w',pady=(0,6))
        percent_card=tk.Frame(main,bg='#183f3c',padx=9,pady=6);percent_card.pack(fill='x',pady=(0,4))
        tk.Label(percent_card,text='세션 획득률',bg='#183f3c',fg='#c5e9e2',font=self.fonts['body']).pack(side='left')
        percent_values=tk.Frame(percent_card,bg='#183f3c');percent_values.pack(side='right')
        self.session_exp=tk.StringVar(value='+0 EXP')
        tk.Label(percent_values,textvariable=self.session_exp,bg='#183f3c',fg='#c5e9e2',font=self.fonts['tiny']).pack(anchor='e')
        self.session_percent=tk.StringVar(value='+0.00%')
        tk.Label(percent_values,textvariable=self.session_percent,bg='#183f3c',fg='#8ff1d7',font=self.fonts['percent']).pack(anchor='e')
        cards=ttk.Frame(main);cards.pack(fill='x');cards.columnconfigure((0,1),weight=1,uniform='metrics')
        self.big={}
        for i,(key,title) in enumerate([('avg_min','평균 분당 EXP'),('recent60','최근 60초 획득'),('avg_hour','시간당 환산 EXP'),('gained','누적 획득 EXP')]):
            card=tk.Frame(cards,bg='#1c2c44',padx=7,pady=5);card.grid(row=i//2,column=i%2,sticky='nsew',padx=2,pady=2)
            tk.Label(card,text=title,bg='#1c2c44',fg='#b6c8df',font=self.fonts['body']).pack(anchor='w')
            v=tk.StringVar(value='—');self.big[key]=v
            tk.Label(card,textvariable=v,bg='#1c2c44',fg='#7ddbcc',font=self.fonts['metric']).pack(anchor='w')
        self.detail=tk.Text(main,height=5,width=1,background='#131f31',foreground='#e4edf9',relief='flat',font=self.fonts['tiny'],padx=5,pady=4,wrap='word',state='disabled')
        self.detail.pack(fill='x',pady=3)
        footer=ttk.Label(settings,text='60초 미만 속도는 환산값입니다. 중단 구간은 제외합니다.\n게임의 EXP 영역을 가리지 마세요.',foreground='#95a9c4',wraplength=460,font=self.fonts['tiny']);footer.pack(anchor='w');self.wrap_labels.append(footer)
        self.collect_localized_widgets(self.root)

    def tr(self,text):
        return translate(text,self.language)

    def collect_localized_widgets(self,parent):
        for widget in parent.winfo_children():
            if isinstance(widget,(tk.Label,ttk.Label,ttk.Button,ttk.Checkbutton)) and widget is not self.start_button:
                if 'textvariable' in widget.keys() and str(widget.cget('textvariable')):
                    continue
                source=str(widget.cget('text'))
                if source:self.localized_widgets.append((widget,source))
            self.collect_localized_widgets(widget)

    def apply_language(self):
        for widget,source in self.localized_widgets:
            widget.configure(text=self.tr(source))
        self.settings_window.title('Maple EXP · '+self.tr('상세설정'))
        start_text='❚❚ 일시정지' if self.running else '▶ 측정 재개' if self.session.started else '▶ 측정 시작'
        self.start_button.configure(text=self.tr(start_text))
        self.status.set(self.tr(self.status_source))
        if self.last_image is not None:self.show_preview(self.last_image,force=True)
        if self.last_level_image is not None:self.show_level_preview(self.last_level_image,force=True)
        self.refresh_display(schedule=False)

    def change_language(self,event=None):
        self.language='en' if self.language_var.get()=='English' else 'ko'
        self.config['language']=self.language
        self.apply_language()
        if not self.choices:self.window_var.set(self.tr('MapleStory 창을 찾지 못했습니다'))
        self.refresh_settings()
        self.fit_settings()

    def set_status(self,text):
        self.status_source=text
        self.status.set(self.tr(text))

    def fit_settings(self):
        self.root.update_idletasks()
        try:
            _,_,dpi,work=self.display_info()
            scale=dpi/96
            width=min(round(460*scale),work[2]-work[0]-24)
            height=min(self.settings_window.winfo_reqheight()+16,work[3]-work[1]-60)
            self.settings_window.geometry(f'{width}x{height}')
        except (OSError,tk.TclError):pass

    def open_settings(self):
        self.settings_window.deiconify()
        self.fit_settings()
        self.settings_window.lift()
        self.settings_window.attributes('-topmost',self.top.get())

    def resize_content(self,event):
        self.canvas.itemconfigure(self.content_window,width=event.width)
        for label in self.wrap_labels:label.configure(wraplength=max(180,event.width-10))
        if self.last_image is not None:self.show_preview(self.last_image,force=True)

    def scroll_content(self,event):
        if isinstance(event.widget,tk.Text) or event.widget.winfo_class() in ('TCombobox','Listbox'):return
        self.canvas.yview_scroll(-int(event.delta/120),'units')

    def display_info(self):
        u=self.win.u
        u.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];u.GetAncestor.restype=wintypes.HWND
        hwnd=u.GetAncestor(self.root.winfo_id(),2) or self.root.winfo_id()
        u.MonitorFromWindow.argtypes=[wintypes.HWND,wintypes.DWORD];u.MonitorFromWindow.restype=wintypes.HANDLE
        monitor=u.MonitorFromWindow(hwnd,2)
        class Info(ctypes.Structure):
            _fields_=[('size',wintypes.DWORD),('monitor',wintypes.RECT),('work',wintypes.RECT),('flags',wintypes.DWORD)]
        info=Info();info.size=ctypes.sizeof(Info)
        u.GetMonitorInfoW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Info)]
        if not u.GetMonitorInfoW(monitor,ctypes.byref(info)):raise OSError('모니터 정보를 확인하지 못했습니다.')
        try:
            u.GetDpiForWindow.argtypes=[wintypes.HWND];u.GetDpiForWindow.restype=wintypes.UINT
            dpi=u.GetDpiForWindow(hwnd) or 96
        except AttributeError:dpi=96
        r=info.work
        return hwnd,monitor,dpi,(r.left,r.top,r.right,r.bottom)

    def apply_display(self,dpi,work,hwnd=None):
        scale=max(.75,min(3.0,dpi/96));self.ui_scale=scale
        self.root.tk.call('tk','scaling',dpi/72)
        for key,(family,size,weight) in self.font_specs.items():self.fonts[key].configure(size=-max(8,round(size*scale)))
        self.style.configure('TButton',padding=(round(5*scale),round(3*scale)))
        self.outer.configure(padding=round(6*scale))
        left,top,right,bottom=work
        width=min(round(360*scale),right-left-round(24*scale))
        height=min(round(440*scale),bottom-top-round(42*scale))
        self.root.minsize(min(round(320*scale),width),min(round(320*scale),height))
        self.root.geometry(f'{width}x{height}')
        if hwnd:
            x=max(left+8,min(self.root.winfo_x(),right-width-8));y=max(top+8,min(self.root.winfo_y(),bottom-height-8))
            u=self.win.u;u.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
            u.SetWindowPos(hwnd,None,x,y,0,0,0x0015)
        if self.last_image is not None:self.show_preview(self.last_image,force=True)

    def watch_display(self):
        try:
            hwnd,monitor,dpi,work=self.display_info();key=(monitor,dpi,work)
            if key!=self.monitor_key:
                self.monitor_key=key;self.apply_display(dpi,work,hwnd)
        except (OSError,tk.TclError):pass
        if not self.shutdown:self.root.after(500,self.watch_display)

    def refresh_windows(self):
        self.choices=self.win.windows()
        labels=[f'{title}  [0x{hwnd:X}]' for hwnd,title in self.choices]
        old=self.window_var.get();self.windows_combo['values']=labels
        self.window_var.set(old if old in labels else labels[0] if labels else self.tr('MapleStory 창을 찾지 못했습니다'))
        self.refresh_settings()

    def refresh_settings(self):
        if not hasattr(self,'top'):return
        try:level=max(1,min(99,int(self.level_var.get())));interval=max(1,float(self.interval.get()))
        except ValueError:return
        i=self.windows_combo.current();hwnd=self.choices[i][0] if 0<=i<len(self.choices) else None
        self.settings=dict(hwnd=hwnd,level=level,interval=interval,auto=self.auto.get(),foreground=self.foreground.get(),exp_roi=list(self.config['exp_roi']),level_roi=list(self.config['level_roi']))
        self.root.attributes('-topmost',self.top.get())
        self.config.update(level=level,interval=interval,auto_level=self.auto.get(),foreground=self.foreground.get(),topmost=self.top.get())
        CONFIG.write_text(json.dumps(self.config,ensure_ascii=False,indent=2),encoding='utf-8')

    def worker(self):
        try:
            reader=Reader();capture=SmallScreenCapture();previous_key=None;previous_read=None
            ready='처음 사용하거나 게임 해상도를 바꾸면 EXP·레벨 영역을 직접 지정하고 인식 시험을 하세요.' if self.first_run else '준비 완료 · 저부하 캡처 / 게임 창 선택 후 인식 시험 또는 측정 시작을 누르세요.'
            self.results.put(('status',ready,None))
        except Exception as e:self.results.put(('fatal',str(e),None));return
        while not self.shutdown:
            if not self.running and not self.test_requested:time.sleep(.15);continue
            settings=dict(self.settings);generation=self.generation;testing=self.test_requested;self.test_requested=False
            exp_image=None;level_image=None
            try:
                hwnd=settings.get('hwnd')
                if not hwnd:raise ValueError('MapleStory 창을 찾지 못했습니다. 게임을 켠 뒤 창 새로고침을 누르세요.')
                rect=self.win.rect(hwnd)
                if settings['foreground'] and not testing and self.win.u.GetForegroundWindow()!=hwnd:
                    self.results.put(('gap','대기 · MapleStory 창을 클릭하면 자동으로 측정합니다.',generation));time.sleep(.5);continue
                exp_box=screen_box(rect,settings['exp_roi'])
                level_box=screen_box(rect,settings['level_roi']) if settings['auto'] else exp_box
                combined=(min(exp_box[0],level_box[0]),min(exp_box[1],level_box[1]),max(exp_box[2],level_box[2]),max(exp_box[3],level_box[3]))
                frame=capture.grab(combined)
                def crop(box):return frame.crop((box[0]-combined[0],box[1]-combined[1],box[2]-combined[0],box[3]-combined[1]))
                exp_image=crop(exp_box)
                level_image=crop(level_box) if settings['auto'] else None
                frame_key=(settings['hwnd'],settings['level'],settings['auto'],exp_image.size,exp_image.tobytes(),level_image.tobytes() if level_image else None)
                if not testing and previous_key==frame_key and previous_read:
                    data=dict(previous_read)
                else:
                    data=reader.read(exp_image,level_image,settings['level'],settings['auto'])
                    previous_read=dict(data);previous_key=frame_key
                data.update(now=time.monotonic(),wall=datetime.now().astimezone().isoformat(timespec='seconds'),testing=testing,image=exp_image,level_image=level_image)
                self.results.put(('read',data,generation))
            except Exception as e:self.results.put(('error',dict(message=str(e),image=exp_image,level_image=level_image,area=getattr(e,'area',None)),generation))
            until=time.monotonic()+settings.get('interval',2)
            while time.monotonic()<until and not self.shutdown:
                if self.test_requested:break
                time.sleep(.1)
        capture.close()

    def poll(self):
        try:
            while True:
                kind,payload,generation=self.results.get_nowait()
                if generation is not None and generation!=self.generation:continue
                if kind=='fatal':self.set_status('OCR 엔진 오류: '+payload)
                elif kind=='status':self.set_status(payload)
                elif kind=='gap':self.session.gap();self.set_status(payload)
                elif kind=='error':
                    self.rejected+=1;self.set_status(payload['message'])
                    if payload.get('area')=='level' and self.auto.get():
                        self.repair_row.pack(fill='x',before=self.repair_anchor)
                    else:self.repair_row.pack_forget()
                    if payload.get('image') is not None:self.show_preview(payload['image'])
                    if payload.get('level_image') is not None:self.show_level_preview(payload['level_image'])
                elif kind=='read':
                    self.repair_row.pack_forget()
                    self.latest=payload
                    self.show_preview(payload['image'])
                    if payload.get('level_image') is not None:self.show_level_preview(payload['level_image'])
                    if payload['testing']:
                        self.set_status(f"인식 시험 OK · Lv.{payload['level']} / EXP {payload['exp']:,} [{payload['pct']:.2f}%]")
                    elif self.running:
                        try:
                            msg=self.session.accept(payload['level'],payload['exp'],payload['pct'],payload['now'],payload['wall'])
                            self.set_status(msg);self.record(payload)
                        except ValueError as e:self.rejected+=1;self.set_status(str(e))
        except queue.Empty:pass
        if not self.shutdown:self.root.after(100,self.poll)

    def show_preview(self,image,force=False):
        if not force and self.last_image is not None and image.size==self.last_image.size and image.tobytes()==self.last_image.tobytes():return
        self.last_image=image
        available=max(180,self.canvas.winfo_width()-10)
        scale=min(2,available/max(1,image.width),round(65*self.ui_scale)/max(1,image.height))
        self.last_image_tk=ImageTk.PhotoImage(image.resize((max(1,int(image.width*scale)),max(1,int(image.height*scale)))))
        self.preview.configure(image=self.last_image_tk,text='')

    def show_level_preview(self,image,force=False):
        if not force and self.last_level_image is not None and image.size==self.last_level_image.size and image.tobytes()==self.last_level_image.tobytes():return
        self.last_level_image=image
        scale=min(3,round(45*self.ui_scale)/max(1,image.height),200*self.ui_scale/max(1,image.width))
        self.last_level_image_tk=ImageTk.PhotoImage(image.resize((max(1,int(image.width*scale)),max(1,int(image.height*scale)))))
        self.level_preview.configure(image=self.last_level_image_tk,text='')

    def toggle(self):
        self.refresh_settings();self.generation+=1
        self.running=not self.running
        self.session.gap()
        self.start_button.configure(text=self.tr('❚❚ 일시정지' if self.running else '▶ 측정 재개'))
        self.set_status('측정 시작 대기 · MapleStory 창을 클릭하세요.' if self.running else '일시정지 · 중단 중 EXP는 합산하지 않습니다.')

    def reset(self):
        self.generation+=1;self.session.reset();self.logpath=None;self.rejected=0
        self.repair_row.pack_forget()
        self.set_status('초기화 완료 · 다음 정상 인식값부터 새 측정을 시작합니다.')
        self.refresh_display(schedule=False)

    def request_test(self):
        self.refresh_settings();self.test_requested=True
        self.set_status('EXP/레벨 인식 시험 중…')

    def restore_roi(self):
        self.config['exp_roi']=list(DEFAULT['exp_roi']);self.config['level_roi']=list(DEFAULT['level_roi']);self.refresh_settings()
        self.session.gap();self.set_status('첨부 스크린샷 기준 기본 위치로 복원했습니다.')

    def select_roi(self,key):
        self.refresh_settings();hwnd=self.settings.get('hwnd')
        if not hwnd:messagebox.showinfo(self.tr('영역 지정'),self.tr('먼저 MapleStory 창을 선택하세요.'));return
        try:rect=self.win.rect(hwnd)
        except Exception as e:messagebox.showerror(self.tr('영역 지정'),self.tr(str(e)));return
        self.session.gap();was_running=self.running;self.running=False;self.generation+=1
        self.settings_window.withdraw()
        self.root.withdraw()
        overlay=tk.Toplevel(self.root);overlay.overrideredirect(True);overlay.attributes('-topmost',True);overlay.attributes('-alpha',.32)
        u=self.win.u;x=u.GetSystemMetrics(76);y=u.GetSystemMetrics(77);w=u.GetSystemMetrics(78);h=u.GetSystemMetrics(79)
        overlay.geometry(f'{w}x{h}{x:+d}{y:+d}')
        canvas=tk.Canvas(overlay,bg='black',highlightthickness=0,cursor='crosshair');canvas.pack(fill='both',expand=True)
        text='왼쪽 EXP 글자부터 [퍼센트%] 끝까지 여유 있게 드래그하세요. 게이지 제외. ESC 취소.' if key=='exp_roi' else '현재 레벨 숫자만 드래그하세요. LV 글자는 제외. ESC 취소.'
        canvas.create_text(w//2,50,text=self.tr(text),fill='white',font=('맑은 고딕',19,'bold'))
        selected={}
        def finish(event=None,cancel=False):
            saved=False
            if not cancel and 'start' in selected and event:
                ax,ay=selected['start'];bx,by=event.x_root,event.y_root
                left,right=sorted([ax,bx]);top,bottom=sorted([ay,by]);rx,ry,rr,rb=rect
                if right-left>=10 and bottom-top>=8 and left>=rx and top>=ry and right<=rr and bottom<=rb:
                    self.config[key]=[(left-rx)/(rr-rx),(top-ry)/(rb-ry),(right-rx)/(rr-rx),(bottom-ry)/(rb-ry)]
                    saved=True
            overlay.destroy();self.root.deiconify();self.running=was_running;self.refresh_settings()
            if saved:
                self.repair_row.pack_forget();self.request_test()
            else:self.set_status('영역 지정이 취소되었거나 영역이 잘못되었습니다. 기존 설정을 유지합니다.')
        def down(e):selected['start']=(e.x_root,e.y_root);selected['box']=canvas.create_rectangle(e.x,e.y,e.x,e.y,outline='#69f5c5',width=3)
        def motion(e):
            if 'start' in selected:
                ax,ay=selected['start'];canvas.coords(selected['box'],ax-x,ay-y,e.x,e.y)
        canvas.bind('<ButtonPress-1>',down);canvas.bind('<B1-Motion>',motion);canvas.bind('<ButtonRelease-1>',finish)
        overlay.bind('<Escape>',lambda e:finish(cancel=True));overlay.focus_force()

    def record(self,read):
        if self.logpath is None:self.logpath=LOGS/f'exp_{datetime.now():%Y%m%d_%H%M%S}_{time.time_ns()%1000000:06d}.csv'
        m=self.session.metrics()
        row=dict(time=read['wall'],start_time=self.session.started,start_level=self.session.start_level,start_exp=self.session.start_exp,
                 level=read['level'],exp=read['exp'],percent=read['pct'],
                 active_seconds=round(m['active'],2),gained=m['gained'],avg_exp_min=round(m['avg_min'],2),
                 avg_exp_hour=round(m['avg_hour'],2),recent60_gain=m['recent60'],session_gain_percent=round(m['gained_percent'],6))
        try:
            exists=self.logpath.exists()
            with self.logpath.open('a',newline='',encoding='utf-8-sig') as f:
                writer=csv.DictWriter(f,fieldnames=row.keys())
                if not exists:writer.writeheader()
                writer.writerow(row)
        except OSError as e:self.set_status('기록 저장 실패: '+str(e))

    def refresh_display(self,schedule=True):
        m=self.session.metrics();s=self.session
        percent_text=f"+{m['gained_percent']:,.2f}%"
        if self.session_percent.get()!=percent_text:self.session_percent.set(percent_text)
        exp_text=f"+{m['gained']:,} EXP"
        if self.session_exp.get()!=exp_text:self.session_exp.set(exp_text)
        for key,var in self.big.items():
            text=f'{m[key]:,.0f}' if s.started else '—'
            if var.get()!=text:var.set(text)
        now=datetime.now().astimezone()
        wall_elapsed=(now-datetime.fromisoformat(s.started)).total_seconds() if s.started else 0
        clock_text=duration(wall_elapsed)
        if self.session_clock.get()!=clock_text:self.session_clock.set(clock_text)
        cap=CAPS.get(s.level,0)
        f=lambda n:f'{n:,}' if n is not None else '—'
        start_clock=datetime.fromisoformat(s.started).strftime('%H:%M:%S') if s.started else '—'
        details=[f"시작 {start_clock} · 유효 측정 {duration(s.active)}",
                 f"시작 Lv.{s.start_level or '—'} · EXP {f(s.start_exp)}",
                 f"현재 Lv.{s.level or '—'} · {f(s.exp)} / {f(cap)} ({s.percent:.2f}%)" if s.started else '현재 EXP —',
                 f"레벨업까지 {f(cap-s.exp) if s.started else '—'} EXP",
                 f"예상 {duration(m['eta'])} · 레벨업 {s.levelups}회"]
        if self.language=='en':
            details=[f"Started {start_clock} · Active {duration(s.active)}",
                     f"Start Lv.{s.start_level or '—'} · EXP {f(s.start_exp)}",
                     f"Now Lv.{s.level or '—'} · {f(s.exp)} / {f(cap)} ({s.percent:.2f}%)" if s.started else 'Current EXP —',
                     f"To next level: {f(cap-s.exp) if s.started else '—'} EXP",
                     f"ETA {duration(m['eta'])} · Level-ups {s.levelups}"]
        detail_text='\n'.join(details)
        if self.detail.get('1.0','end-1c')!=detail_text:
            self.detail.configure(state='normal');self.detail.delete('1.0','end');self.detail.insert('1.0',detail_text);self.detail.configure(state='disabled')
        if schedule and not self.shutdown:self.root.after(500,self.refresh_display)

    def export(self):
        if not self.logpath or not self.logpath.exists():messagebox.showinfo(self.tr('내보내기'),self.tr('먼저 측정을 시작하세요.'));return
        path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[(self.tr('CSV 기록'),'*.csv')],initialfile=self.logpath.name)
        if path:
            try:Path(path).write_bytes(self.logpath.read_bytes())
            except OSError as e:messagebox.showerror(self.tr('저장 실패'),str(e))

    def close(self):
        self.shutdown=True;self.refresh_settings();self.root.destroy()


def screenshot_test(path):
    image=Image.open(path).convert('RGB');w,h=image.size
    exp=image.crop(screen_box((0,0,w,h),DEFAULT['exp_roi']))
    level=image.crop(screen_box((0,0,w,h),DEFAULT['level_roi']))
    result=Reader().read(exp,level,30,True)
    result.pop('image',None)
    print(json.dumps(result,ensure_ascii=False))
    return result


def main():
    if sys.platform=='win32':
        try:
            kernel=ctypes.WinDLL('kernel32')
            kernel.GetCurrentProcess.restype=wintypes.HANDLE
            kernel.SetPriorityClass.argtypes=[wintypes.HANDLE,wintypes.DWORD]
            kernel.SetPriorityClass(kernel.GetCurrentProcess(),0x00004000)  # BELOW_NORMAL_PRIORITY_CLASS
        except Exception:pass
        try:ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            try:ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:pass
    if '--test-image' in sys.argv:
        result=screenshot_test(sys.argv[sys.argv.index('--test-image')+1])
        if '--test-output' in sys.argv:
            Path(sys.argv[sys.argv.index('--test-output')+1]).write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
        return
    root=tk.Tk();App(root);root.mainloop()


if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        error=traceback.format_exc()
        (STORE/'error.log').write_text(error,encoding='utf-8')
        if '--test-image' in sys.argv:raise
        language=load_config().get('language',DEFAULT['language'])
        messagebox.showerror(translate('Maple EXP Meter 오류',language),error+translate('\n오류 기록: ',language)+str(STORE/'error.log'))
