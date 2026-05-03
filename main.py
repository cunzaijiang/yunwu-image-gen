import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading, json, sys, base64, io, time, requests
from pathlib import Path
from PIL import Image, ImageTk

CONFIG_FILE = 'config.json'
MODEL_OPTIONS = ['gpt-image-2', 'gpt-image-1', 'gpt-image-1.5']
MODEL_PRESETS = ['gpt-image-2', 'gpt-image-1', 'gpt-image-1.5', 'dall-e-3', 'dall-e-2']
SIZE_OPTIONS = ['1024x1024', '1024x1536', '1536x1024', '2048x2048', '2048x3072', '3072x2048', '4096x4096', '512x512', '256x256']
QUALITY_OPTIONS = ['auto', 'high', 'medium', 'low']
MAX_REF_IMAGES = 6
DEFAULT_BASE_URL = 'https://yunwu.ai'
DEFAULT_GEN_PATH = '/v1/images/generations'
DEFAULT_EDIT_PATH = '/v1/images/edits'
DEFAULT_TIMEOUT = 200
C={'bg':'#1a1a2e','card':'#16213e','input':'#0d1b2e','border':'#2e3a52',
   'btn':'#e94560','btn_h':'#c73652','btn2':'#2e3a52','btn2_h':'#3e4a62',
   'fg':'#eaeaea','fg_dim':'#8090a8','success':'#4ecca3','error':'#ff4d6d','warning':'#ffd460'}

def get_app_dir():
    if getattr(sys,'frozen',False): return Path(sys.executable).parent
    return Path(__file__).parent
def load_config():
    p=get_app_dir()/CONFIG_FILE
    if p.exists():
        try: return json.loads(p.read_text(encoding='utf-8'))
        except: pass
    return {'api_key':'','base_url':DEFAULT_BASE_URL,'model':MODEL_PRESETS[0],'size':SIZE_OPTIONS[0],'quality':QUALITY_OPTIONS[0],'n':1,
            'chat_url':'https://yunwu.ai/v1/chat/completions','chat_model':'gpt-4o-mini','chat_key':''}
def save_config(cfg):
    p=get_app_dir()/CONFIG_FILE
    p.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
def _repair_json(s):
    """Try to fix truncated JSON by auto-closing open structures."""
    import json as _j
    try: _j.loads(s); return s
    except Exception: pass
    s = s.rstrip()
    # Remove trailing incomplete token until last safe char
    while s and s[-1] not in ('}', ']', '"', 'e', 'l', '0','1','2','3','4','5','6','7','8','9'):
        s = s[:-1]
    # Track open brackets
    depth = []
    in_str = False
    esc = False
    for c in s:
        if esc: esc = False; continue
        if c == '\\' and in_str: esc = True; continue
        if c == '"' and not esc: in_str = not in_str; continue
        if not in_str:
            if c == '{': depth.append('}')
            elif c == '[': depth.append(']')
            elif c in ('}', ']') and depth: depth.pop()
    if in_str: s += '"'
    s += ''.join(reversed(depth))
    return s

def b64_to_pil(b64):
    img=Image.open(io.BytesIO(base64.b64decode(b64)))
    img.load()  # force decode, prevent BytesIO GC issue
    return img
def make_thumb(img,size=(160,160)):
    th=img.copy(); th.thumbnail(size,Image.LANCZOS); return ImageTk.PhotoImage(th)
def auto_fn(idx,ext='png'):
    return f'image_{time.strftime("%Y%m%d_%H%M%S")}_{idx+1:02d}.{ext}'

class HoverBtn(tk.Button):
    def __init__(self,master,bg_n=None,bg_h=None,**kw):
        bg_n=bg_n or C['btn']; bg_h=bg_h or C['btn_h']
        super().__init__(master,bg=bg_n,activebackground=bg_h,fg=C['fg'],
            relief='flat',cursor='hand2',font=('Segoe UI',9,'bold'),bd=0,padx=12,pady=6,**kw)
        self._n=bg_n; self._h=bg_h
        self.bind('<Enter>',lambda e:self.config(bg=self._h))
        self.bind('<Leave>',lambda e:self.config(bg=self._n))

class ScrollableFrame(tk.Frame):
    def __init__(self,master,**kw):
        outer=tk.Frame(master,bg=C['bg'])
        outer.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(outer,bg=C['bg'],highlightthickness=0)
        vsb=ttk.Scrollbar(outer,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right',fill='y')
        self.canvas.pack(side='left',fill='both',expand=True)
        super().__init__(self.canvas,bg=C['bg'],**kw)
        self._win=self.canvas.create_window((0,0),window=self,anchor='nw')
        self.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfig(self._win,width=e.width))
        self.canvas.bind_all('<MouseWheel>',lambda e:self.canvas.yview_scroll(int(-1*(e.delta/120)),'units'))

class ImageViewer(tk.Toplevel):
    def __init__(self,master,pil_img):
        super().__init__(master)
        self.configure(bg=C['bg'])
        self.title('图片预览')
        self.resizable(True,True)
        sw=self.winfo_screenwidth(); sh=self.winfo_screenheight()
        w=min(pil_img.width+40,sw-100); h=min(pil_img.height+80,sh-100)
        self.geometry(f'{w}x{h}')
        self._orig=pil_img
        bf=tk.Frame(self,bg=C['bg']); bf.pack(fill='x',pady=4)
        HoverBtn(bf,text='保存图片',command=self._save).pack(side='left',padx=8)
        info_txt=f'{pil_img.width}x{pil_img.height} px'
        tk.Label(bf,text=info_txt,bg=C['bg'],fg=C['fg_dim'],font=('Segoe UI',8)).pack(side='right',padx=8)
        self._cv=tk.Canvas(self,bg='#111',highlightthickness=0)
        self._cv.pack(fill='both',expand=True,padx=8,pady=4)
        self.bind('<Configure>',lambda e:self.after(50,self._redraw))
        self.after(100,self._redraw)
    def _redraw(self):
        cw=self._cv.winfo_width() or 800; ch=self._cv.winfo_height() or 600
        img=self._orig.copy(); img.thumbnail((cw,ch),Image.LANCZOS)
        self._tk=ImageTk.PhotoImage(img)
        self._cv.delete('all')
        self._cv.create_image(cw//2,ch//2,image=self._tk,anchor='center')
    def _save(self):
        path=filedialog.asksaveasfilename(defaultextension='.png',
            filetypes=[('PNG','*.png'),('JPEG','*.jpg'),('All','*.*')])
        if path:
            self._orig.save(path)
            messagebox.showinfo('成功',f'已保存: {path}')

def get_api_urls(base_url):
    base=base_url.rstrip('/')
    return base+DEFAULT_GEN_PATH, base+DEFAULT_EDIT_PATH

def _parse_imgs(items):
    result=[]
    for d in items:
        if 'b64_json' in d and d['b64_json']: result.append(b64_to_pil(d['b64_json']))
        elif 'url' in d and d['url']:
            import urllib.request
            with urllib.request.urlopen(d['url'],timeout=30) as resp:
                _img=Image.open(io.BytesIO(resp.read())); _img.load(); result.append(_img)
    return result

def _extract_items(resp_json):
    # Support both {data:[...]} and direct list or other formats
    if isinstance(resp_json, dict):
        if 'data' in resp_json: return resp_json['data']
        if 'images' in resp_json: return resp_json['images']
        if 'output' in resp_json: return resp_json['output']
        # Single image dict
        if 'b64_json' in resp_json or 'url' in resp_json: return [resp_json]
    if isinstance(resp_json, list): return resp_json
    raise ValueError(f'无法解析 API 返回格式: {str(resp_json)[:200]}')

def api_generate(api_key,gen_url,model,prompt,n,size,quality,timeout):
    headers={'Authorization':f'Bearer {api_key}','Content-Type':'application/json'}
    body={'model':model,'prompt':prompt,'n':n,'size':size,'quality':quality}
    r=requests.post(gen_url,headers=headers,json=body,timeout=timeout)
    r.raise_for_status()
    resp=r.json()
    items=_extract_items(resp)
    result=_parse_imgs(items)
    if not result: raise ValueError(f'返回数据中未找到图片, 原始响应: {str(resp)[:300]}')
    return result

def api_edit(api_key,edit_url,model,prompt,n,size,image_paths,timeout):
    headers={'Authorization':f'Bearer {api_key}'}
    files=[]; opened=[]
    try:
        for path in image_paths:
            fh=open(path,'rb'); opened.append(fh)
            files.append(('image[]',(Path(path).name,fh,'image/png')))
        data={'model':model,'prompt':prompt,'n':str(n),'size':size}
        r=requests.post(edit_url,headers=headers,data=data,files=files,timeout=timeout)
        r.raise_for_status()
        resp=r.json()
        items=_extract_items(resp)
        result=_parse_imgs(items)
        if not result: raise ValueError(f'返回数据中未找到图片, 原始响应: {str(resp)[:300]}')
        return result
    finally:
        for fh in opened: fh.close()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('空的图像生成工具')
        self.geometry('1100x780')
        self.minsize(900,600)
        self.configure(bg=C['bg'])
        self.protocol('WM_DELETE_WINDOW',self._on_close)
        self._cfg=load_config()
        self._ref_images=[]   # list of (path_str, PIL.Image)
        self._result_images=[]  # list of PIL.Image
        self._thumb_refs=[]   # keep PhotoImage alive
        self._res_refs=[]
        self._build_ui()
        self._apply_config()
        self._set_mode('text')

    def _on_close(self):
        self._save_cfg()
        self.destroy()

    def _apply_config(self):
        self._var_key.set(self._cfg.get('api_key',''))
        self._var_base_url.set(self._cfg.get('base_url',DEFAULT_BASE_URL))
        if hasattr(self,'_var_gen_path'): self._var_gen_path.set(self._cfg.get('gen_path',DEFAULT_GEN_PATH))
        if hasattr(self,'_var_edit_path'): self._var_edit_path.set(self._cfg.get('edit_path',DEFAULT_EDIT_PATH))
        if hasattr(self,'_var_timeout'): self._var_timeout.set(self._cfg.get('timeout',DEFAULT_TIMEOUT))
        self._var_model.set(self._cfg.get('model',MODEL_PRESETS[0]) or MODEL_PRESETS[0])
        self._var_size.set(self._cfg.get('size',SIZE_OPTIONS[0]) or SIZE_OPTIONS[0])
        self._var_quality.set(self._cfg.get('quality',QUALITY_OPTIONS[0]) or QUALITY_OPTIONS[0])
        self._var_n.set(self._cfg.get('n',1))
        if hasattr(self,'_var_chat_url'): self._var_chat_url.set(self._cfg.get('chat_url','https://yunwu.ai/v1/chat/completions'))
        if hasattr(self,'_var_chat_model'): self._var_chat_model.set(self._cfg.get('chat_model','gpt-4o-mini'))
        if hasattr(self,'_var_chat_key'): self._var_chat_key.set(self._cfg.get('chat_key',''))

    def _save_cfg(self):
        self._cfg.update({'api_key':self._var_key.get().strip(),
            'base_url':self._var_base_url.get().strip() or DEFAULT_BASE_URL,
            'gen_path':(self._var_gen_path.get().strip() if hasattr(self,'_var_gen_path') else DEFAULT_GEN_PATH) or DEFAULT_GEN_PATH,
            'edit_path':(self._var_edit_path.get().strip() if hasattr(self,'_var_edit_path') else DEFAULT_EDIT_PATH) or DEFAULT_EDIT_PATH,
            'timeout':(self._var_timeout.get() if hasattr(self,'_var_timeout') else DEFAULT_TIMEOUT),
            'model':self._var_model.get() or MODEL_PRESETS[0],
            'size':self._var_size.get() or SIZE_OPTIONS[0],
            'quality':self._var_quality.get() or QUALITY_OPTIONS[0],
            'n':self._var_n.get(),
            'chat_url':(self._var_chat_url.get().strip() if hasattr(self,'_var_chat_url') else 'https://yunwu.ai/v1/chat/completions'),
            'chat_model':(self._var_chat_model.get().strip() if hasattr(self,'_var_chat_model') else 'gpt-4o-mini'),
            'chat_key':(self._var_chat_key.get().strip() if hasattr(self,'_var_chat_key') else '')})
        save_config(self._cfg)
        self._status('配置已保存',C['success'])

    def _build_ui(self):
        self._style_ttk()
        tb=tk.Frame(self,bg=C['card'],pady=10)
        tb.pack(fill='x')
        tk.Label(tb,text='✨  空的图像生成工具',
            bg=C['card'],fg=C['btn'],font=('Segoe UI',14,'bold')).pack(side='left',padx=16)
        tk.Label(tb,text='v1.0.0',bg=C['card'],fg=C['fg_dim'],font=('Segoe UI',8)).pack(side='left')
        kf=tk.Frame(self,bg=C['bg'],pady=6)
        kf.pack(fill='x',padx=16)
        tk.Label(kf,text='API Key:',bg=C['bg'],fg=C['fg'],font=('Segoe UI',9,'bold'),width=8).pack(side='left')
        self._var_key=tk.StringVar()
        self._key_entry=tk.Entry(kf,textvariable=self._var_key,show='*',
            bg=C['input'],fg=C['fg'],insertbackground=C['fg'],relief='flat',font=('Segoe UI',9),bd=4)
        self._key_entry.pack(side='left',fill='x',expand=True,padx=(4,8))
        HoverBtn(kf,text='保存配置',bg_n=C['btn2'],bg_h=C['btn2_h'],command=self._save_cfg).pack(side='left')
        HoverBtn(kf,text='显示/隐藏',bg_n=C['btn2'],bg_h=C['btn2_h'],
            command=lambda:self._key_entry.config(show='' if self._key_entry.cget('show')=='*' else '*')).pack(side='left',padx=4)
        # Base URL row
        uf=tk.Frame(self,bg=C['bg'],pady=2)
        uf.pack(fill='x',padx=16)
        tk.Label(uf,text='Base URL:',bg=C['bg'],fg=C['fg'],font=('Segoe UI',9,'bold'),width=8).pack(side='left')
        self._var_base_url=tk.StringVar(value=DEFAULT_BASE_URL)
        tk.Entry(uf,textvariable=self._var_base_url,
            bg=C['input'],fg=C['fg'],insertbackground=C['fg'],relief='flat',font=('Segoe UI',9),bd=4
        ).pack(side='left',fill='x',expand=True,padx=(4,8))
        tk.Label(uf,text='（默认云雾，可换成任意 NewAPI/OneAPI 地址）',
            bg=C['bg'],fg=C['fg_dim'],font=('Segoe UI',8)).pack(side='left')
        gp_v=tk.Frame(self,bg=C['bg'],pady=2)
        gp_v.pack(fill='x',padx=16)
        tk.Label(gp_v,text='生图路径:',bg=C['bg'],fg=C['fg'],font=('Segoe UI',9,'bold'),width=8).pack(side='left')
        self._var_gen_path=tk.StringVar(value=DEFAULT_GEN_PATH)
        tk.Entry(gp_v,textvariable=self._var_gen_path,bg=C['input'],fg=C['fg'],insertbackground=C['fg'],relief='flat',font=('Segoe UI',9),bd=4).pack(side='left',fill='x',expand=True,padx=(4,8))
        ep_v=tk.Frame(self,bg=C['bg'],pady=2)
        ep_v.pack(fill='x',padx=16)
        tk.Label(ep_v,text='编辑路径:',bg=C['bg'],fg=C['fg'],font=('Segoe UI',9,'bold'),width=8).pack(side='left')
        self._var_edit_path=tk.StringVar(value=DEFAULT_EDIT_PATH)
        tk.Entry(ep_v,textvariable=self._var_edit_path,bg=C['input'],fg=C['fg'],insertbackground=C['fg'],relief='flat',font=('Segoe UI',9),bd=4).pack(side='left',fill='x',expand=True,padx=(4,8))
        tp_v=tk.Frame(self,bg=C['bg'],pady=2)
        tp_v.pack(fill='x',padx=16)
        tk.Label(tp_v,text='超时(秒):',bg=C['bg'],fg=C['fg'],font=('Segoe UI',9,'bold'),width=8).pack(side='left')
        self._var_timeout=tk.IntVar(value=DEFAULT_TIMEOUT)
        tk.Spinbox(tp_v,textvariable=self._var_timeout,from_=30,to=600,width=6,bg=C['input'],fg=C['fg'],buttonbackground=C['btn2'],relief='flat',font=('Segoe UI',9)).pack(side='left',padx=(4,8))
        tk.Frame(self,bg=C['border'],height=1).pack(fill='x',padx=16,pady=2)
        main=tk.Frame(self,bg=C['bg'])
        main.pack(fill='both',expand=True,padx=6,pady=4)
        self._build_left(main)
        self._build_right(main)
        sb=tk.Frame(self,bg=C['card'],pady=3)
        sb.pack(fill='x',side='bottom')
        self._status_var=tk.StringVar(value='就绪...')
        self._status_lbl=tk.Label(sb,textvariable=self._status_var,bg=C['card'],fg=C['fg_dim'],font=('Segoe UI',8),anchor='w')
        self._status_lbl.pack(side='left',padx=12)
    def _style_ttk(self):
        s=ttk.Style(self)
        s.theme_use('clam')
        s.configure('TCombobox',fieldbackground=C['input'],
            background=C['input'],foreground=C['fg'],selectbackground=C['btn'])
        s.configure('TScrollbar',background=C['btn2'],troughcolor=C['bg'])

    def _status(self,msg,color=None):
        self._status_var.set(msg)
        if color: self._status_lbl.config(fg=color)
        else: self._status_lbl.config(fg=C['fg_dim'])

    def _build_left(self,parent):
        left=tk.Frame(parent,bg=C['card'],width=380)
        left.pack(side='left',fill='y',padx=(0,6),pady=0)
        left.pack_propagate(False)
        # Mode buttons
        mf=tk.Frame(left,bg=C['card'])
        mf.pack(fill='x',padx=12,pady=(10,4))
        tk.Label(mf,text='生图模式',bg=C['card'],fg=C['fg'],font=('Segoe UI',9,'bold')).pack(anchor='w')
        br=tk.Frame(mf,bg=C['card'])
        br.pack(fill='x',pady=4)
        self._btn_text=HoverBtn(br,text='文字生图',command=lambda:self._set_mode('text'))
        self._btn_text.pack(side='left',padx=(0,4))
        self._btn_img=HoverBtn(br,text='参考图生图',bg_n=C['btn2'],bg_h=C['btn2_h'],
            command=lambda:self._set_mode('image'))
        self._btn_img.pack(side='left',padx=(0,4))
        self._btn_suite=HoverBtn(br,text='主图套装',bg_n=C['btn2'],bg_h=C['btn2_h'],
            command=lambda:self._set_mode('suite'))
        self._btn_suite.pack(side='left')
        # Ref images panel
        self._ref_lf=tk.LabelFrame(left,text='参考图片 (0/6)',
            bg=C['card'],fg=C['fg_dim'],font=('Segoe UI',8),relief='flat',bd=1,
            highlightbackground=C['border'],highlightthickness=1)
        self._ref_lf.pack(fill='x',padx=12,pady=4)
        hint=tk.Label(self._ref_lf,text='拖入图片添加参考图（最多6张）',
            bg=C['card'],fg=C['fg_dim'],font=('Segoe UI',8),cursor='hand2')
        hint.pack(pady=4)
        hint.bind('<Button-1>',lambda e:self._add_ref_images())
        self._ref_grid=tk.Frame(self._ref_lf,bg=C['card'])
        self._ref_grid.pack(fill='x',padx=4,pady=2)
        HoverBtn(self._ref_lf,text='+ 添加图片',bg_n=C['btn2'],bg_h=C['btn2_h'],
            command=self._add_ref_images).pack(pady=4)
        self._setup_dnd(self._ref_lf)
        # Config options
        cf=tk.Frame(left,bg=C['card'])
        cf.pack(fill='x',padx=12,pady=4)
        cf.columnconfigure(1,weight=1)
        self._var_model=tk.StringVar(value=MODEL_PRESETS[0])
        self._var_size=tk.StringVar(value=SIZE_OPTIONS[0])
        self._var_quality=tk.StringVar(value=QUALITY_OPTIONS[0])
        self._var_n=tk.IntVar(value=1)
        rows=[('模型 (可自定义):',self._var_model,MODEL_PRESETS),
               ('尺寸 Size:',self._var_size,SIZE_OPTIONS),
               ('质量 Quality:',self._var_quality,QUALITY_OPTIONS)]
        for i,(lbl,var,vals) in enumerate(rows):
            tk.Label(cf,text=lbl,bg=C['card'],fg=C['fg'],font=('Segoe UI',9),anchor='w').grid(row=i,column=0,sticky='w',pady=3,padx=(0,4))
            cb_st='normal' if i<=1 else 'readonly'
            cb=ttk.Combobox(cf,textvariable=var,values=vals,state=cb_st,font=('Segoe UI',9))
            cb.grid(row=i,column=1,sticky='ew',pady=3)
        tk.Label(cf,text='数量 N:',bg=C['card'],fg=C['fg'],font=('Segoe UI',9),anchor='w').grid(row=3,column=0,sticky='w',pady=3,padx=(0,4))
        tk.Spinbox(cf,textvariable=self._var_n,from_=1,to=10,width=6,
            bg=C['input'],fg=C['fg'],buttonbackground=C['btn2'],relief='flat',font=('Segoe UI',9)).grid(row=3,column=1,sticky='w',pady=3)
        # Prompt area
        self._prompt_lf=tk.Frame(left,bg=C['card'])
        self._prompt_lf.pack(fill='both',expand=True,padx=12,pady=(0,6))
        tk.Label(self._prompt_lf,text='Prompt 描述:',bg=C['card'],fg=C['fg'],
            font=('Segoe UI',9,'bold')).pack(anchor='w',pady=(8,2))
        self._prompt=tk.Text(self._prompt_lf,height=7,wrap='word',bg=C['input'],fg=C['fg'],
            insertbackground=C['fg'],relief='flat',font=('Segoe UI',9),bd=4,padx=4,pady=4)
        self._prompt.pack(fill='both',expand=True)
        # Suite frame (hidden by default)
        # Suite frame with scrollbar
        self._suite_frame=tk.Frame(left,bg=C['card'])
        # scrollable inner container
        _suite_canvas=tk.Canvas(self._suite_frame,bg=C['card'],highlightthickness=0)
        _suite_vsb=ttk.Scrollbar(self._suite_frame,orient='vertical',command=_suite_canvas.yview)
        _suite_canvas.configure(yscrollcommand=_suite_vsb.set)
        _suite_vsb.pack(side='right',fill='y')
        _suite_canvas.pack(side='left',fill='both',expand=True)
        self._suite_inner=tk.Frame(_suite_canvas,bg=C['card'])
        _suite_win=_suite_canvas.create_window((0,0),window=self._suite_inner,anchor='nw')
        self._suite_inner.bind('<Configure>',lambda e:_suite_canvas.configure(scrollregion=_suite_canvas.bbox('all')))
        _suite_canvas.bind('<Configure>',lambda e:_suite_canvas.itemconfig(_suite_win,width=e.width))
        _suite_canvas.bind('<MouseWheel>',lambda e:_suite_canvas.yview_scroll(int(-1*(e.delta/120)),'units'))
        self._build_suite_panel(self._suite_inner)
        # Generate button
        self._gen_lf=tk.Frame(left,bg=C['card'])
        self._gen_lf.pack(fill='x',padx=12,pady=(0,10))
        self._gen_btn=HoverBtn(self._gen_lf,text='✨  开始生成',command=self._start_gen)
        self._gen_btn.pack(fill='x',ipady=4)
        HoverBtn(self._gen_lf,text='批量保存所有图片',
            bg_n=C['btn2'],bg_h=C['btn2_h'],command=self._save_all).pack(fill='x',pady=(4,0),ipady=2)
    def _build_right(self,parent):
        right=tk.Frame(parent,bg=C['bg'])
        right.pack(side='left',fill='both',expand=True)
        # Header
        rh=tk.Frame(right,bg=C['card'])
        rh.pack(fill='x',pady=(0,4))
        tk.Label(rh,text='生成结果',bg=C['card'],fg=C['fg'],
            font=('Segoe UI',11,'bold')).pack(side='left',padx=12,pady=6)
        self._count_lbl=tk.Label(rh,text='',bg=C['card'],fg=C['fg_dim'],font=('Segoe UI',8))
        self._count_lbl.pack(side='left')
        HoverBtn(rh,text='清空结果',bg_n=C['btn2'],bg_h=C['btn2_h'],
            command=self._clear_results).pack(side='right',padx=8,pady=4)
        # Loading overlay canvas (for spinner text)
        self._loading_var=tk.StringVar(value='')
        self._loading_lbl=tk.Label(right,textvariable=self._loading_var,
            bg=C['bg'],fg=C['warning'],font=('Segoe UI',12,'bold'))
        # Results scrollable frame
        rf=tk.Frame(right,bg=C['bg'])
        rf.pack(fill='both',expand=True)
        self._results_canvas=tk.Canvas(rf,bg=C['bg'],highlightthickness=0)
        vsb=ttk.Scrollbar(rf,orient='vertical',command=self._results_canvas.yview)
        self._results_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right',fill='y')
        self._results_canvas.pack(side='left',fill='both',expand=True)
        self._results_inner=tk.Frame(self._results_canvas,bg=C['bg'])
        self._results_win=self._results_canvas.create_window((0,0),window=self._results_inner,anchor='nw')
        self._results_inner.bind('<Configure>',lambda e:self._results_canvas.configure(
            scrollregion=self._results_canvas.bbox('all')))
        self._results_canvas.bind('<Configure>',lambda e:self._results_canvas.itemconfig(
            self._results_win,width=e.width))
        self._results_canvas.bind_all('<MouseWheel>',lambda e:self._results_canvas.yview_scroll(
            int(-1*(e.delta/120)),'units'))
    def _set_mode(self,mode):
        self._mode=mode
        # Reset all buttons
        for b in [self._btn_text,self._btn_img,self._btn_suite]:
            b.config(bg=C['btn2']); b._n=C['btn2']
        # Activate current
        btn_map={'text':self._btn_text,'image':self._btn_img,'suite':self._btn_suite}
        btn_map[mode].config(bg=C['btn']); btn_map[mode]._n=C['btn']
        # Show/hide panels
        self._ref_lf.pack_forget()
        self._suite_frame.pack_forget()
        self._prompt_lf.pack_forget()
        self._gen_lf.pack_forget()
        if mode=='image':
            self._ref_lf.pack(fill='x',padx=12,pady=4)
            self._prompt_lf.pack(fill='both',expand=True,padx=12,pady=(0,6))
            self._gen_lf.pack(fill='x',padx=12,pady=(0,10))
        elif mode=='suite':
            self._suite_frame.pack(fill='both',expand=True,padx=4,pady=4)
        else:  # text
            self._prompt_lf.pack(fill='both',expand=True,padx=12,pady=(0,6))
            self._gen_lf.pack(fill='x',padx=12,pady=(0,10))

    def _setup_dnd(self,widget):
        pass  # DnD disabled for exe compatibility

    def _on_drop(self,event):
        pass

    def _add_ref_images(self):
        paths=filedialog.askopenfilenames(
            title='选择参考图片',
            filetypes=[('图片','*.png *.jpg *.jpeg *.bmp *.webp'),('所有','*.*')])
        for p in paths:
            self._add_single_ref(p)

    def _add_single_ref(self,path):
        if len(self._ref_images)>=MAX_REF_IMAGES:
            messagebox.showwarning('提示','\u6700\u591a\u6dfb\u52a06\u5f20\u53c2\u8003\u56fe\u7247')
            return
        try:
            img=Image.open(path).convert('RGBA')
            self._ref_images.append((str(path),img))
            self._refresh_ref_thumbs()
        except Exception as e:
            messagebox.showerror('错误',f'\u65e0\u6cd5\u52a0\u8f7d\u56fe\u7247: {e}')

    def _refresh_ref_thumbs(self):
        for w in self._ref_grid.winfo_children(): w.destroy()
        self._thumb_refs.clear()
        n=len(self._ref_images)
        self._ref_lf.configure(text=f'参考图片 ({n}/6)')
        for i,(path,img) in enumerate(self._ref_images):
            cell=tk.Frame(self._ref_grid,bg=C['input'],bd=1,relief='flat')
            col=i%3; row=i//3
            cell.grid(row=row,column=col,padx=3,pady=3)
            th=make_thumb(img,(90,90))
            self._thumb_refs.append(th)
            tk.Label(cell,image=th,bg=C['input'],cursor='hand2').pack()
            del_btn=tk.Label(cell,text='x',bg=C['error'],fg='white',
                font=('Segoe UI',7,'bold'),cursor='hand2',padx=3)
            del_btn.place(relx=1.0,rely=0.0,anchor='ne')
            del_btn.bind('<Button-1>',lambda e,idx=i:self._del_ref(idx))

    def _del_ref(self,idx):
        if 0<=idx<len(self._ref_images):
            self._ref_images.pop(idx)
            self._refresh_ref_thumbs()

    def _start_gen(self):
        api_key=self._var_key.get().strip()
        if not api_key:
            messagebox.showwarning('提示','请先填写 API Key')
            return
        prompt=self._prompt.get('1.0','end').strip()
        if not prompt:
            messagebox.showwarning('提示','请输入 Prompt')
            return
        if self._mode=='image' and not self._ref_images:
            messagebox.showwarning('提示','参考图生图模式请添加至少一张参考图')
            return
        self._gen_btn.config(state='disabled')
        self._set_loading(True)
        self._status('正在生成中...',C['warning'])
        t=threading.Thread(target=self._do_gen,daemon=True)
        t.start()

    def _do_gen(self):
        try:
            api_key=self._var_key.get().strip()
            base_url=self._var_base_url.get().strip() or DEFAULT_BASE_URL
            model=self._var_model.get()
            prompt=self._prompt.get('1.0','end').strip()
            n=self._var_n.get()
            size=self._var_size.get() or SIZE_OPTIONS[0]
            quality=self._var_quality.get() or QUALITY_OPTIONS[0]
            timeout=self._var_timeout.get() if hasattr(self,'_var_timeout') else DEFAULT_TIMEOUT
            base_url=self._var_base_url.get().strip() or DEFAULT_BASE_URL
            gen_path=self._var_gen_path.get().strip() if hasattr(self,'_var_gen_path') else DEFAULT_GEN_PATH
            edit_path=self._var_edit_path.get().strip() if hasattr(self,'_var_edit_path') else DEFAULT_EDIT_PATH
            gen_url=base_url.rstrip('/')+gen_path
            edit_url=base_url.rstrip('/')+edit_path
            if self._mode=='text':
                imgs=api_generate(api_key,gen_url,model,prompt,n,size,quality,timeout)
            else:
                paths=[p for p,_ in self._ref_images]
                imgs=api_edit(api_key,edit_url,model,prompt,n,size,paths,timeout)
            self.after(0,lambda:self._on_gen_done(imgs))
        except requests.HTTPError as e:
            msg=str(e)
            try:
                d=e.response.json()
                msg=d.get('error',{}).get('message',msg)
            except Exception: pass
            self.after(0,lambda:self._on_gen_err(f'API错误: {msg}'))
        except Exception as e:
            import traceback; detail=traceback.format_exc()[-300:]
            msg=str(e) if str(e) and str(e)!='None' else detail
            self.after(0,lambda m=msg:self._on_gen_err(f'错误: {m}'))

    def _on_gen_done(self,imgs):
        self._result_images.extend(imgs)
        self._gen_btn.config(state='normal')
        self._set_loading(False)
        self._status(f'生成完成，共 {len(self._result_images)} 张图片',C['success'])
        self._refresh_results()

    def _on_gen_err(self,msg):
        self._gen_btn.config(state='normal')
        self._set_loading(False)
        self._status(msg,C['error'])
        messagebox.showerror('生成失败',msg)

    def _set_loading(self,on):
        if on:
            self._loading_var.set('⏳  正在生成中，请稍候...')
            self._loading_lbl.place(relx=0.5,rely=0.4,anchor='center')
        else:
            self._loading_var.set('')
            self._loading_lbl.place_forget()

    def _clear_results(self):
        self._result_images.clear()
        self._res_refs.clear()
        for w in self._results_inner.winfo_children(): w.destroy()
        self._count_lbl.config(text='')
        self._status('已清空结果')

    def _refresh_results(self):
        for w in self._results_inner.winfo_children(): w.destroy()
        self._res_refs.clear()
        n=len(self._result_images)
        self._count_lbl.config(text=f'共 {n} 张图片')
        if not self._result_images:
            tk.Label(self._results_inner,text='生成的图片将显示在这里',
                bg=C['bg'],fg=C['fg_dim'],font=('Segoe UI',11)).pack(pady=60)
            return
        # Arrange in grid 2 columns
        cols=2
        for i,img in enumerate(self._result_images):
            row=i//cols; col=i%cols
            cell=tk.Frame(self._results_inner,bg=C['card'],bd=0)
            cell.grid(row=row,column=col,padx=8,pady=8,sticky='nw')
            th=make_thumb(img,(240,240))
            self._res_refs.append(th)
            lbl=tk.Label(cell,image=th,bg=C['card'],cursor='hand2',
                bd=2,relief='flat',highlightbackground=C['btn'],highlightthickness=0)
            lbl.pack(padx=4,pady=4)
            lbl.bind('<Button-1>',lambda e,im=img:ImageViewer(self,im))
            lbl.bind('<Enter>',lambda e,l=lbl:l.config(highlightthickness=2))
            lbl.bind('<Leave>',lambda e,l=lbl:l.config(highlightthickness=0))
            # Save button
            sf=tk.Frame(cell,bg=C['card'])
            sf.pack(fill='x',padx=4,pady=(0,4))
            HoverBtn(sf,text='保存',bg_n=C['btn2'],bg_h=C['btn2_h'],
                command=lambda idx=i:self._save_one(idx)).pack(side='left',padx=2)
            sz=img.size
            tk.Label(sf,text=f'{sz[0]}x{sz[1]}',bg=C['card'],fg=C['fg_dim'],font=('Segoe UI',7)).pack(side='right',padx=4)
    def _save_one(self,idx):
        if idx>=len(self._result_images): return
        img=self._result_images[idx]
        default=auto_fn(idx)
        path=filedialog.asksaveasfilename(
            initialfile=default,
            defaultextension='.png',
            filetypes=[('PNG','*.png'),('JPEG','*.jpg'),('WebP','*.webp'),('All','*.*')])
        if path:
            img.save(path)
            self._status(f'已保存: {path}',C['success'])

    def _save_all(self):
        if not self._result_images:
            messagebox.showinfo('提示','没有可保存的图片')
            return
        folder=filedialog.askdirectory(title='选择保存目录')
        if not folder: return
        from pathlib import Path
        saved=[]
        for i,img in enumerate(self._result_images):
            name=auto_fn(i)
            dest=Path(folder)/name
            img.save(str(dest))
            saved.append(str(dest))
        messagebox.showinfo('成功',f'已保存 {len(saved)} 张图片到:\n{folder}')
        self._status(f'已批量保存 {len(saved)} 张',C['success'])


    # -- 电商主图套装 ----

    def _build_suite_panel(self, parent):
        tk.Label(parent, text='电商主图套装', bg=C['card'], fg=C['btn'],
                 font=('Segoe UI', 11, 'bold')).pack(anchor='w', pady=(8, 4))
        self._var_chat_url = tk.StringVar(value='https://yunwu.ai/v1/chat/completions')
        self._var_chat_key = tk.StringVar(value='')
        self._var_chat_model = tk.StringVar(value='gpt-4o-mini')
        self._var_suite_size = tk.StringVar(value='1024x1536')
        self._var_suite_count = tk.IntVar(value=6)
        self._var_suite_step = tk.BooleanVar(value=False)
        self._suite_progress_var = tk.StringVar(value='')
        api_frame = tk.Frame(parent, bg=C['card'])
        api_frame.pack(fill='x', pady=(0, 6))
        api_frame.columnconfigure(1, weight=1)
        tk.Label(api_frame, text='Chat URL:', bg=C['card'], fg=C['fg'],
                 font=('Segoe UI', 9), anchor='w').grid(
                     row=0, column=0, sticky='w', pady=3, padx=(0, 4))
        tk.Entry(api_frame, textvariable=self._var_chat_url,
                 bg=C['input'], fg=C['fg'], insertbackground=C['fg'],
                 relief='flat', font=('Segoe UI', 9), bd=4
                 ).grid(row=0, column=1, sticky='ew', pady=3)
        tk.Label(api_frame, text='Chat模型:', bg=C['card'], fg=C['fg'],
                 font=('Segoe UI', 9), anchor='w').grid(
                     row=1, column=0, sticky='w', pady=3, padx=(0, 4))
        ttk.Combobox(api_frame, textvariable=self._var_chat_model,
                     values=['gpt-4o-mini','gpt-4o','gpt-4-turbo',
                             'claude-3-5-sonnet','deepseek-chat','qwen-max'],
                     font=('Segoe UI', 9), state='normal'
                     ).grid(row=1, column=1, sticky='ew', pady=3)
        tk.Label(api_frame, text='Chat Key:', bg=C['card'], fg=C['fg'],
                 font=('Segoe UI', 9), anchor='w').grid(
                     row=2, column=0, sticky='w', pady=3, padx=(0, 4))
        tk.Entry(api_frame, textvariable=self._var_chat_key, show='*',
                 bg=C['input'], fg=C['fg'], insertbackground=C['fg'],
                 relief='flat', font=('Segoe UI', 9), bd=4
                 ).grid(row=2, column=1, sticky='ew', pady=3)
        tk.Label(api_frame, text='(留空则复用主 Key)', bg=C['card'], fg=C['fg_dim'],
                 font=('Segoe UI', 8)).grid(row=3, column=1, sticky='w', pady=(0,4))
        HoverBtn(api_frame,text='💾 保存套装配置',bg_n=C['btn2'],bg_h=C['btn2_h'],
            command=self._save_cfg).grid(row=4,column=0,columnspan=2,sticky='w',pady=(2,6),padx=4)
        tk.Label(parent, text='产品描述:', bg=C['card'], fg=C['fg'],
                 font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(4, 2))
        self._suite_desc = tk.Text(parent, height=5, wrap='word',
                                   bg=C['input'], fg=C['fg_dim'],
                                   insertbackground=C['fg'], relief='flat',
                                   font=('Segoe UI', 9), bd=4, padx=4, pady=4)
        self._suite_desc.pack(fill='x', pady=(0, 4))
        _ph = '输入产品信息，如：植物种子套装，自然清新风格...'
        self._suite_desc.insert('1.0', _ph)
        def _fi(e, ph=_ph):
            if self._suite_desc.get('1.0', 'end-1c') == ph:
                self._suite_desc.delete('1.0', 'end')
                self._suite_desc.config(fg=C['fg'])
        def _fo(e, ph=_ph):
            if not self._suite_desc.get('1.0', 'end-1c').strip():
                self._suite_desc.insert('1.0', ph)
                self._suite_desc.config(fg=C['fg_dim'])
        self._suite_desc.bind('<FocusIn>', _fi)
        self._suite_desc.bind('<FocusOut>', _fo)
        sz_frame = tk.Frame(parent, bg=C['card'])
        sz_frame.pack(fill='x', pady=(0, 4))
        tk.Label(sz_frame, text='图片尺寸:', bg=C['card'], fg=C['fg'],
                 font=('Segoe UI', 9)).pack(side='left', padx=(0, 6))
        ttk.Combobox(sz_frame, textvariable=self._var_suite_size,
                     values=['1024x1536','1536x1024','1024x1024','2048x3072','3072x2048','2048x2048','4096x4096'],
                     font=('Segoe UI', 9), state='normal', width=14
                     ).pack(side='left')
        # Suite reference images
        self._suite_refs=[]  # list of (path, thumb)
        ref_lbl=tk.Label(parent,text='参考图（可选，可上传产品图让 AI 更准确）:',bg=C['card'],fg=C['fg'],
            font=('Segoe UI',9,'bold'))
        ref_lbl.pack(anchor='w',pady=(4,2))
        self._suite_ref_frame=tk.Frame(parent,bg=C['card'])
        self._suite_ref_frame.pack(fill='x',pady=(0,4))
        HoverBtn(parent,text='+ 添加参考图',bg_n=C['btn2'],bg_h=C['btn2_h'],
            command=self._add_suite_refs).pack(anchor='w',pady=(0,4))
        cnt_frame=tk.Frame(parent,bg=C['card'])
        cnt_frame.pack(fill='x',pady=(0,4))
        tk.Label(cnt_frame,text='生成张数:',bg=C['card'],fg=C['fg'],
            font=('Segoe UI',9),anchor='w').pack(side='left',padx=(0,6))
        tk.Spinbox(cnt_frame,textvariable=self._var_suite_count,from_=1,to=20,width=5,
            bg=C['input'],fg=C['fg'],buttonbackground=C['btn2'],relief='flat',
            font=('Segoe UI',9)).pack(side='left')
        tk.Label(cnt_frame,text='张（Chat 模型按此数量生成提示词）',bg=C['card'],fg=C['fg_dim'],
            font=('Segoe UI',8)).pack(side='left',padx=6)
        # Step mode toggle
        step_fr=tk.Frame(parent,bg=C['card'])
        step_fr.pack(fill='x',pady=(0,4))
        tk.Checkbutton(step_fr,text='📝 分步模式',
            variable=self._var_suite_step,bg=C['card'],fg=C['fg'],
            activebackground=C['card'],activeforeground=C['fg'],
            selectcolor=C['input'],font=('Segoe UI',9),
            command=self._on_suite_step_toggle).pack(side='left')
        tk.Label(step_fr,text='先获取提示词，检查后再生图',
            bg=C['card'],fg=C['fg_dim'],font=('Segoe UI',8)).pack(side='left',padx=6)
        # Main generate / get-prompts button
        self._suite_gen_btn = HoverBtn(parent, text='✨ 一键生成主图套装',
                                        command=self._start_suite_gen)
        self._suite_gen_btn.pack(fill='x', ipady=4, pady=(4, 2))
        self._suite_prog_lbl=tk.Label(parent,textvariable=self._suite_progress_var,
            bg=C['card'],fg=C['warning'],font=('Segoe UI',8),anchor='w')
        self._suite_prog_lbl.pack(fill='x',padx=4)
        self._suite_prompts_btn=HoverBtn(parent,text='📋 查看提示词',command=self._show_suite_prompts,
            bg_n=C['btn2'],bg_h=C['btn2_h'])
        self._suite_prompts_btn.pack(fill='x',ipady=2,pady=(0,2))
        self._suite_custom_prompt_btn=HoverBtn(parent,text='✏️ 自定义提示词',command=self._open_custom_prompt_dialog,
            bg_n=C['btn2'],bg_h=C['btn2_h'])
        self._suite_custom_prompt_btn.pack(fill='x',ipady=2,pady=(0,4))
        # Prompt edit area (shown in step mode after fetching)
        self._suite_edit_frame=tk.Frame(parent,bg=C['card'])
        tk.Label(self._suite_edit_frame,
            text='提示词列表（可直接编辑），确认后发送给生图模型',
            bg=C['card'],fg=C['fg_dim'],font=('Segoe UI',8)).pack(anchor='w',pady=(0,2))
        _eco=tk.Frame(self._suite_edit_frame,bg=C['card'])
        _eco.pack(fill='both',expand=True)
        self._suite_ec=tk.Canvas(_eco,bg=C['card'],highlightthickness=0,height=220)
        _ecvsb=ttk.Scrollbar(_eco,orient='vertical',command=self._suite_ec.yview)
        self._suite_ec.configure(yscrollcommand=_ecvsb.set)
        _ecvsb.pack(side='right',fill='y')
        self._suite_ec.pack(side='left',fill='both',expand=True)
        self._suite_edit_inner=tk.Frame(self._suite_ec,bg=C['card'])
        _ecw=self._suite_ec.create_window((0,0),window=self._suite_edit_inner,anchor='nw')
        self._suite_edit_inner.bind('<Configure>',
            lambda e:self._suite_ec.configure(scrollregion=self._suite_ec.bbox('all')))
        self._suite_ec.bind('<Configure>',
            lambda e:self._suite_ec.itemconfig(_ecw,width=e.width))
        self._suite_ec.bind('<MouseWheel>',
            lambda e:self._suite_ec.yview_scroll(int(-1*(e.delta/120)),'units'))
        # Confirm button (step mode only, hidden by default)
        self._suite_confirm_btn=HoverBtn(self._suite_edit_frame,
            text='✅ 确认提示词，开始生图',command=self._confirm_suite_gen)
        self._suite_confirm_btn.pack(fill='x',ipady=4,pady=(4,2))

    def _add_suite_refs(self):
        from tkinter import filedialog
        paths=filedialog.askopenfilenames(title='选择参考图片',
            filetypes=[('图片','*.png *.jpg *.jpeg *.webp'),('所有文件','*.*')])
        if not paths: return
        for p in paths:
            if len(self._suite_refs)>=6: break
            try:
                img=Image.open(p).convert('RGB')
                img.thumbnail((60,60))
                thumb=ImageTk.PhotoImage(img)
                self._suite_refs.append((p,thumb))
            except Exception: pass
        self._refresh_suite_refs()

    def _refresh_suite_refs(self):
        for w in self._suite_ref_frame.winfo_children(): w.destroy()
        for idx,(path,thumb) in enumerate(self._suite_refs):
            f=tk.Frame(self._suite_ref_frame,bg=C['card'])
            f.pack(side='left',padx=2)
            tk.Label(f,image=thumb,bg=C['card']).pack()
            tk.Button(f,text='x',fg='red',bg=C['card'],relief='flat',font=('Segoe UI',7),
                command=lambda i=idx:self._rm_suite_ref(i)).pack()

    def _rm_suite_ref(self,idx):
        if 0<=idx<len(self._suite_refs): del self._suite_refs[idx]
        self._refresh_suite_refs()


    def _on_suite_step_toggle(self):
        if self._var_suite_step.get():
            self._suite_gen_btn.config(text="📝 获取提示词")
        else:
            self._suite_gen_btn.config(text="✨ 一键生成主图套装")
            self._suite_edit_frame.pack_forget()

    def _start_suite_gen(self):
        if self._var_suite_step.get(): self._fetch_suite_prompts_only(); return
        api_key = self._var_key.get().strip()
        if not api_key:
            messagebox.showwarning('提示', '请先填写 API Key')
            return
        desc = self._suite_desc.get('1.0', 'end-1c').strip()
        _ph = '输入产品信息，如：植物种子套装，自然清新风格...'
        if not desc or desc == _ph:
            messagebox.showwarning('提示', '请输入产品描述')
            return
        self._suite_gen_btn.config(state='disabled')
        self._suite_progress_var.set('正在生成提示词...')
        threading.Thread(target=self._do_suite_gen, daemon=True).start()


    def _fetch_suite_prompts_only(self):
        api_key=self._var_key.get().strip()
        ck=getattr(self,"_var_chat_key",None)
        chat_key=(ck.get().strip() if ck else "") or api_key
        cu=getattr(self,"_var_chat_url",None)
        chat_url=cu.get().strip() if cu else ""
        cm=getattr(self,"_var_chat_model",None)
        chat_model=(cm.get().strip() if cm else "") or ""
        desc=self._suite_desc.get("1.0","end-1c").strip()
        suite_count=self._var_suite_count.get() if hasattr(self,"_var_suite_count") else 6
        tv=int(self._var_timeout.get()) if hasattr(self,"_var_timeout") else 200
        ph="输入产品信息，如：植物种子套装，自然清新风格..."
        from tkinter import messagebox as _mb
        if not api_key: _mb.showwarning("提示","请先填写 API Key"); return
        if not chat_url: _mb.showwarning("提示","请填写 Chat URL"); return
        if not desc or desc==ph: _mb.showwarning("提示","请输入产品描述"); return
        self._suite_gen_btn.config(state="disabled")
        self._suite_progress_var.set("正在获取提示词...请稍候")
        import threading
        threading.Thread(target=self._do_fetch_prompts,
            args=(api_key,chat_key,chat_url,chat_model,desc,suite_count,tv),daemon=True).start()


    def _do_fetch_prompts(self,api_key,chat_key,chat_url,chat_model,desc,suite_count,tv):
        import requests,concurrent.futures as _cf2
        upd=lambda m:self.after(0,lambda x=m:self._suite_progress_var.set(x))
        def fail(m): self.after(0,lambda x=m:self._on_fetch_err(x))
        refs=getattr(self,"_suite_refs",[])
        def _make_uc(text):
            if refs:
                import base64 as _b64
                uc=[{"type":"text","text":text}]
                for rp,_ in refs[:6]:
                    try:
                        with open(rp,"rb") as _f: _d=_b64.b64encode(_f.read()).decode()
                        _ext=rp.rsplit(".",1)[-1].lower()
                        _mt="image/png" if _ext=="png" else "image/jpeg"
                        uc.append({"type":"image_url","image_url":{"url":f"data:{_mt};base64,{_d}"}})
                    except Exception: pass
                return uc
            return text
        _DEFAULT_SP='你是专业电商视觉设计师。为下面产品生成第{idx}/{total}张主图提示词。只返回纯文本提示词，200字以内，风格独特。不要JSON。'
        _sp_tpl=getattr(self,'_custom_suite_prompt','').strip() or _DEFAULT_SP
        _done=[0]
        def _get_one(idx):
            _sp=_sp_tpl.replace('{idx}',str(idx+1)).replace('{total}',str(suite_count))
            _cb={"model":chat_model,"messages":[{"role":"system","content":_sp},{"role":"user","content":_make_uc(desc)}],"temperature":0.8}
            _r=requests.post(chat_url,headers={"Authorization":f"Bearer {chat_key}","Content-Type":"application/json"},json=_cb,timeout=tv)
            _r.raise_for_status()
            _p=_r.json()["choices"][0]["message"]["content"].strip()
            _done[0]+=1
            upd(f"提示词 {_done[0]}/{suite_count} 已就绪...")
            return _p
        prompts=[]
        try:
            with _cf2.ThreadPoolExecutor(max_workers=min(suite_count,5)) as _ex2:
                _futs={_ex2.submit(_get_one,i):i for i in range(suite_count)}
                try:
                    for _fut in _cf2.as_completed(_futs,timeout=tv+10):
                        try:
                            _p=_fut.result()
                            if _p: prompts.append(_p)
                        except Exception as _ce:
                            upd(f"第{_futs[_fut]+1}条失败: {_ce}")
                except Exception: pass
        except Exception as e: fail(f"获取提示词失败: {e}"); return
        if not prompts: fail("所有提示词请求均失败"); return
        self.after(0,lambda ps=list(prompts):self._on_prompts_fetched(ps))


    def _on_prompts_fetched(self,prompts):
        self._last_suite_prompts=prompts
        self._suite_gen_btn.config(state="normal")
        cnt=len(prompts)
        self._suite_progress_var.set(f"{cnt} 条提示词已就绪，请检查并确认生图")
        inner=self._suite_edit_inner
        for w in inner.winfo_children(): w.destroy()
        self._suite_prompt_vars=[]
        for idx,p in enumerate(prompts):
            fr=tk.Frame(inner,bg=C["card"])
            fr.pack(fill="x",padx=4,pady=(4,0))
            tk.Label(fr,text=f"[{idx+1}]",bg=C["card"],fg=C["fg_dim"],
                font=("Segoe UI",8),width=3).pack(side="left",anchor="n",pady=2)
            txv=tk.Text(fr,height=4,bg=C["input"],fg=C["fg"],
                insertbackground=C["fg"],font=("Segoe UI",9),wrap="word",relief="flat")
            txv.insert("end",p)
            txv.pack(side="left",fill="x",expand=True)
            self._suite_prompt_vars.append(txv)
        self._suite_edit_frame.pack(fill="both",expand=True,padx=4,pady=(0,4))

    def _on_fetch_err(self,msg):
        self._suite_gen_btn.config(state="normal")
        self._suite_progress_var.set(f"获取提示词失败: {msg[:80]}")

    def _confirm_suite_gen(self):
        pvars=getattr(self,"_suite_prompt_vars",[])
        if not pvars: return
        prompts=[v.get("1.0","end-1c").strip() for v in pvars]
        prompts=[p for p in prompts if p]
        if not prompts: return
        self._suite_confirm_btn.config(state="disabled")
        self._suite_gen_btn.config(state="disabled")
        self._suite_progress_var.set("开始生图...")
        import threading
        threading.Thread(target=self._do_suite_gen_with_prompts,args=(prompts,),daemon=True).start()

    def _do_suite_gen(self):
        import json as _j, re as _re, concurrent.futures as _cf
        upd=lambda m:self.after(0,lambda x=m:self._suite_progress_var.set(x))
        fail=lambda m:self.after(0,lambda x=m:self._on_suite_err(x))
        try:
            k1=self._var_key.get().strip()
            k2=self._var_chat_key.get().strip() if hasattr(self,'_var_chat_key') else ''
            api_key=k2 if k2 else k1  # used for Chat
            img_key=k1  # always use main key for image generation
            chat_url=self._var_chat_url.get().strip()
            chat_model=self._var_chat_model.get().strip() or 'gpt-4o-mini'
            tv=int(self._var_timeout.get()) if hasattr(self,'_var_timeout') else 120
            desc=self._suite_desc.get('1.0','end-1c').strip()
            sz=self._var_suite_size.get() or '1024x1536'
            suite_count=self._var_suite_count.get() if hasattr(self,'_var_suite_count') else 6
            q=self._var_quality.get() or QUALITY_OPTIONS[0]
            mdl=self._var_model.get().strip() or MODEL_PRESETS[0]
            bu=self._var_base_url.get().strip() or DEFAULT_BASE_URL
            gp=self._var_gen_path.get().strip() if hasattr(self,'_var_gen_path') else DEFAULT_GEN_PATH
            gen_url=bu.rstrip('/')+gp
            if not desc: fail('请先填写产品描述'); return
            if not api_key: fail('请先填写 API Key'); return
            if not chat_url: fail('请填写 Chat URL'); return
            # Build base user content (with optional ref images)
            refs=getattr(self,'_suite_refs',[])
            def _make_uc(text):
                if refs:
                    import base64 as _b64
                    uc=[{'type':'text','text':text}]
                    for rp,_ in refs[:6]:
                        try:
                            with open(rp,'rb') as _f: _d=_b64.b64encode(_f.read()).decode()
                            _ext=rp.rsplit('.',1)[-1].lower()
                            _mt='image/png' if _ext=='png' else 'image/jpeg'
                            uc.append({'type':'image_url','image_url':{'url':f'data:{_mt};base64,{_d}'}})
                        except Exception: pass
                    return uc
                return text
            # One request per prompt to avoid JSON truncation
            upd(f'并行请求 {suite_count} 条提示词...')
            _chat_done=[0]
            _DEFAULT_SP2='你是专业电商视觉设计师。为下面产品生成第{idx}/{total}张主图提示词。只返回纯文本提示词，200字以内，风格独特。不要JSON。'
            _sp_tpl2=getattr(self,'_custom_suite_prompt','').strip() or _DEFAULT_SP2
            def _get_one_prompt(idx):
                _sp=_sp_tpl2.replace('{idx}',str(idx+1)).replace('{total}',str(suite_count))
                _cb={'model':chat_model,
                    'messages':[{'role':'system','content':_sp},{'role':'user','content':_make_uc(desc)}],
                    'temperature':0.8}
                _r=requests.post(chat_url,
                    headers={'Authorization':f'Bearer {api_key}','Content-Type':'application/json'},
                    json=_cb,timeout=tv)
                _r.raise_for_status()
                _p=_r.json()['choices'][0]['message']['content'].strip()
                _chat_done[0]+=1
                upd(f'提示词 {_chat_done[0]}/{suite_count} 已就绪...')
                return _p
            prompts=[]
            import concurrent.futures as _cf2
            with _cf2.ThreadPoolExecutor(max_workers=min(suite_count,5)) as _ex2:
                _futs={_ex2.submit(_get_one_prompt,i):i for i in range(suite_count)}
                try:
                    for _fut in _cf2.as_completed(_futs, timeout=tv+10):
                        try:
                            _p=_fut.result()
                            if _p: prompts.append(_p)
                        except Exception as _ce:
                            upd(f'第{_futs[_fut]+1}条提示词失败: {_ce}')
                except Exception: pass  # TimeoutError or other
            if not prompts: fail('所有提示词生成失败，请检查 Chat API 配置'); return

            total=len(prompts)
            upd(f'获得{total}条提示词...')
            _done=[0]
            def _gen_one(ip):
                idx,pr=ip
                _r2=requests.post(gen_url,
                    headers={'Authorization':f'Bearer {img_key}','Content-Type':'application/json'},
                    json={'model':mdl,'prompt':pr,'n':1,'size':sz,'quality':q},timeout=tv)
                _r2.raise_for_status()
                _imgs=_parse_imgs(_extract_items(_r2.json()))
                _done[0]+=1
                upd(f'已完成{_done[0]}/{total}张...')
                return (idx,_imgs)
            imgs_map={}
            with _cf.ThreadPoolExecutor(max_workers=min(total,5)) as ex:
                futs={ex.submit(_gen_one,(i,p)):i for i,p in enumerate(prompts)}
                try:
                    for fut in _cf.as_completed(futs, timeout=tv+10):
                        try: ix,res=fut.result(); imgs_map[ix]=res
                        except Exception as _ge:
                            imgs_map[futs[fut]]=[]
                            _gi=futs[fut]
                            upd(f'第{_gi+1}张生图失败: {_ge}')
                except Exception: upd(f"部分图片超时，已完成 {_done[0]}/{total} 张")
            self._last_suite_prompts=list(prompts)
            imgs=[x for i in sorted(imgs_map) for x in imgs_map[i]]
            self.after(0,lambda:self._on_suite_done(imgs))
        except Exception as e:
            import traceback
            self.after(0,lambda m=(str(e) or traceback.format_exc()[-200:]):self._on_suite_err(m))


    _DEFAULT_SUITE_SP='你是专业电商视觉设计师。为下面产品生成第{idx}/{total}张主图提示词。只返回纯文本提示词，200字以内，风格独特。不要JSON。'

    def _open_custom_prompt_dialog(self):
        win=tk.Toplevel(self)
        win.title('自定义 Chat 提示词')
        win.configure(bg=C['bg'])
        win.geometry('620x360')
        win.resizable(True,True)
        tk.Label(win,text='可用占位符：{idx}=当前第几张，{total}=总张数',
            bg=C['bg'],fg=C['fg_dim'],font=('Segoe UI',8)).pack(anchor='w',padx=12,pady=(10,2))
        fr=tk.Frame(win,bg=C['bg']); fr.pack(fill='both',expand=True,padx=12,pady=(0,6))
        sb=ttk.Scrollbar(fr); sb.pack(side='right',fill='y')
        txt=tk.Text(fr,bg=C['input'],fg=C['fg'],insertbackground=C['fg'],
            font=('Segoe UI',9),wrap='word',relief='flat',yscrollcommand=sb.set)
        txt.pack(side='left',fill='both',expand=True)
        sb.config(command=txt.yview)
        cur=getattr(self,'_custom_suite_prompt','').strip() or self._DEFAULT_SUITE_SP
        txt.insert('end',cur)
        btn_fr=tk.Frame(win,bg=C['bg']); btn_fr.pack(fill='x',padx=12,pady=(0,10))
        def _save():
            val=txt.get('1.0','end-1c').strip()
            self._custom_suite_prompt=val if val and val!=self._DEFAULT_SUITE_SP else ''
            win.destroy()
        def _reset():
            txt.delete('1.0','end')
            txt.insert('end',self._DEFAULT_SUITE_SP)
        HoverBtn(btn_fr,text='✅ 保存',command=_save).pack(side='left',ipady=2,padx=(0,6))
        HoverBtn(btn_fr,text='↩️ 恢复默认',command=_reset,bg_n=C['btn2'],bg_h=C['btn2_h']).pack(side='left',ipady=2)
        win.grab_set()

    def _show_suite_prompts(self):
        prompts=getattr(self,"_last_suite_prompts",[])
        win=tk.Toplevel(self)
        win.title('提示词列表')
        win.configure(bg=C['bg'])
        win.geometry("640x480")
        tk.Label(win,text=f'Chat 模型生成的提示词（共 {len(prompts)} 条）',
            bg=C['bg'],fg=C['fg'],font=('Segoe UI',10,'bold')).pack(pady=(12,6))
        fr=tk.Frame(win,bg=C['bg']); fr.pack(fill='both',expand=True,padx=12,pady=(0,12))
        sb=ttk.Scrollbar(fr); sb.pack(side='right',fill='y')
        txt=tk.Text(fr,bg=C['input'],fg=C['fg'],insertbackground=C['fg'],
            font=('Segoe UI',9),wrap='word',relief='flat',yscrollcommand=sb.set)
        txt.pack(side='left',fill='both',expand=True)
        sb.config(command=txt.yview)
        if not prompts:
            txt.insert('end','尚未生成提示词，请先运行一键生成主图套装。')
        else:
            for idx,p in enumerate(prompts,1):
                txt.insert('end','[第'+str(idx)+'张]\n'+p+'\n\n')

        txt.config(state='disabled')

    def _on_suite_done(self, imgs):
        self._result_images.extend(imgs)
        if not imgs:
            from tkinter import messagebox
            messagebox.showerror('生成失败', '所有图片生成均失败。请检查图像模型、API Key 和路径配置是否正确。')
        self._suite_gen_btn.config(state='normal')
        self._suite_progress_var.set(f'套装生成完成，共 {len(imgs)} 张图片 ✔')
        self._status(f'主图套装生成完成，共 {len(imgs)} 张', C['success'])
        self._refresh_results()

    def _on_suite_err(self, msg):
        self._suite_gen_btn.config(state='normal')
        self._suite_progress_var.set(f'错误: {msg[:60]}')
        self._status(msg, C['error'])
        messagebox.showerror('套装生成失败', msg)



    def _do_suite_gen_with_prompts(self,prompts):
        import requests,concurrent.futures as _cf
        upd=lambda m:self.after(0,lambda x=m:self._suite_progress_var.set(x))
        api_key=self._var_key.get().strip()
        mdl=self._var_model.get().strip()
        _vs=getattr(self,"_var_suite_size",None)
        sz=_vs.get() if _vs else "1024x1536"
        q=self._var_quality.get() or "standard"
        bu=self._var_base_url.get().strip()
        gp=self._var_gen_path.get().strip() if hasattr(self,"_var_gen_path") else "/v1/images/generations"
        gen_url=bu.rstrip('/')+gp
        tv=int(self._var_timeout.get()) if hasattr(self,"_var_timeout") else 200
        total=len(prompts)
        _done=[0]
        def _gen(ip):
            idx,pr=ip
            _r=requests.post(gen_url,headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"},json={"model":mdl,"prompt":pr,"n":1,"size":sz,"quality":q},timeout=tv)
            _r.raise_for_status()
            _imgs=_parse_imgs(_extract_items(_r.json()))
            _done[0]+=1; upd(f"\u5df2\u5b8c\u6210{_done[0]}/{total}\u5f20...")
            return (idx,_imgs)
        imgs_map={}
        self._last_suite_prompts=list(prompts)
        with _cf.ThreadPoolExecutor(max_workers=min(total,5)) as ex:
            futs={ex.submit(_gen,(i,p)):i for i,p in enumerate(prompts)}
            try:
                for fut in _cf.as_completed(futs,timeout=tv+10):
                    try: ix,res=fut.result(); imgs_map[ix]=res
                    except Exception as ge: imgs_map[futs[fut]]=[]; upd(f"\u7b2c{futs[fut]+1}\u5f20\u5931\u8d25: {ge}")
            except Exception: pass
        imgs=[x for i in sorted(imgs_map) for x in imgs_map[i]]
        self.after(0,lambda:self._on_suite_done_step(imgs))

    def _on_suite_done_step(self,imgs):
        self._result_images.extend(imgs)
        self._suite_confirm_btn.config(state='normal')
        self._suite_gen_btn.config(state='normal')
        self._suite_progress_var.set(f"\u5206\u6b65\u6a21\u5f0f\u5b8c\u6210\uff0c\u5171 {len(imgs)} \u5f20\u56fe\u7247 \u2714")
        self._refresh_results()

if __name__=='__main__':
    app=App()
    app.mainloop()
