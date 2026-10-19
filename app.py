"""Chinese desktop controls and floating bilingual captions."""
from pathlib import Path
import json
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, colorchooser
from realtime_core import BASE, CaptionEngine, enumerate_devices, load_config, export_subtitles, install_network_guard
from glossary import merge_glossaries, read_glossary_files
from alpha_subtitles import AlphaSubtitles

class PinkBackground(tk.Canvas):
    """Resize the soft pink gradient without covering the controls above it."""
    def __init__(self, parent):
        super().__init__(parent, highlightthickness=0, bd=0, bg='#fff6fa')
        self.bind('<Configure>', self.draw_gradient)

    def draw_gradient(self, event):
        if event.widget is not self:
            return
        self.delete('gradient')
        start, end = (255, 246, 250), (246, 205, 222)
        steps = min(128, max(2, event.height))
        for i in range(steps):
            ratio = i / (steps - 1)
            color = '#{:02x}{:02x}{:02x}'.format(
                *(round(a + (b - a) * ratio) for a, b in zip(start, end)))
            self.create_rectangle(0, i * event.height / steps, event.width,
                                  (i + 1) * event.height / steps + 1,
                                  fill=color, outline='', tags='gradient')
        self.tag_lower('gradient')


def apply_pink_theme(root):
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background='#fff0f6', foreground='#633f50',
                    font=('Microsoft YaHei UI', 10))
    style.configure('TFrame', background='#fff0f6')
    style.configure('TLabel', background='#fff0f6')
    style.configure('TNotebook', background='#fff0f6', bordercolor='#e8bacd')
    style.configure('TNotebook.Tab', background='#f8dce8', padding=(12,6))
    style.map('TNotebook.Tab', background=[('selected','#fff0f6'),('active','#f5cddd')])
    style.configure('TLabelframe', background='#fff0f6', bordercolor='#e8bacd')
    style.configure('TLabelframe.Label', background='#fff0f6', foreground='#8b4f68')
    style.configure('TButton', background='#f8dce8', bordercolor='#dfaec2',
                    lightcolor='#fff6fa', darkcolor='#e9bfd0', padding=(10, 5))
    style.map('TButton', background=[('disabled', '#f5e8ee'), ('pressed', '#eebbd0'),
                                    ('active', '#f5cddd')],
              foreground=[('disabled', '#ad94a0')])
    for name in ('TEntry', 'TCombobox', 'TSpinbox'):
        style.configure(name, fieldbackground='#fffbfd', background='#f8dce8',
                        bordercolor='#e3bacb', lightcolor='#fff6fa',
                        darkcolor='#e3bacb', selectbackground='#eab4cb',
                        selectforeground='#563345', arrowcolor='#8b4f68')
        style.map(name, fieldbackground=[('readonly', '#fffbfd')],
                  foreground=[('readonly', '#633f50')])
    style.configure('TCheckbutton', background='#fff0f6', indicatorbackground='#fffbfd')
    style.map('TCheckbutton', background=[('active', '#fbe1ec')],
              indicatorbackground=[('selected', '#d787a8')])
    style.configure('Vertical.TScrollbar', background='#edbfd3',
                    troughcolor='#fff0f6', bordercolor='#e3bacb',
                    arrowcolor='#8b4f68')
    root.option_add('*TCombobox*Listbox.background', '#fffbfd')
    root.option_add('*TCombobox*Listbox.foreground', '#633f50')
    root.option_add('*TCombobox*Listbox.selectBackground', '#eab4cb')
    root.option_add('*TCombobox*Listbox.selectForeground', '#563345')


class App:
    def __init__(self,root):
        self.root=root
        root.title('ASMR 日语 → 中文 · 本地实时字幕')
        icon=BASE/'launcher'/'ASMR.ico'
        if icon.is_file():
            root.iconbitmap(default=str(icon))
        root.geometry('850x760')
        root.minsize(720,700)
        apply_pink_theme(root)
        self.background=PinkBackground(root)
        self.background.pack(fill='both',expand=True)
        content=self.background
        self.events=queue.Queue()
        self.engine=CaptionEngine(lambda kind,value:self.events.put((kind,value)))
        self.rows=[]
        self.listening=False
        self.closing=False
        try:
            self.config=load_config()
        except Exception:
            self.config=load_defaults()
        self.overlay=None
        self.overlay_renderer=None
        self.overlay_render_job=None
        self.zh=tk.StringVar(value='')
        self.ja=tk.StringVar(value='')
        self.caption_data=('尚未开始收音','', 'status')
        self.last_caption=('', '')
        self.font_size=tk.StringVar(value=str(self.config.get('font_size',23)))
        self.ja_font_size=tk.StringVar(value=str(self.config.get('ja_font_size',14)))
        self.topmost=tk.BooleanVar(value=bool(self.config.get('topmost',True)))
        self.only_translation=tk.BooleanVar(value=bool(self.config.get('overlay_only_translation',True)))
        self.show_status=tk.BooleanVar(value=bool(self.config.get('overlay_show_status',False)))
        self.streaming=tk.BooleanVar(value=bool(self.config.get('overlay_streaming',True)))
        self.transparent_bg=tk.BooleanVar(value=bool(self.config.get('overlay_transparent_bg',False)))
        self.zh_color=tk.StringVar(value=self.config.get('overlay_zh_color','#ffffff'))
        self.ja_color=tk.StringVar(value=self.config.get('overlay_ja_color','#bdcbd9'))
        self.font_weight=tk.StringVar(value='加粗' if self.config.get('overlay_font_weight')=='bold' else '常规')
        self.outline_width=tk.StringVar(value=str(self.config.get('overlay_outline_width',1)))
        self.shadow=tk.BooleanVar(value=bool(self.config.get('overlay_shadow',True)))
        backend_labels={'auto':'自动','cuda':'显卡 CUDA','vulkan':'显卡 Vulkan','cpu':'仅 CPU',
                        'hybrid':'CPU＋显卡（均衡）','hybrid_lowvram':'CPU＋显卡（省显存）'}
        self.translation_backend=tk.StringVar(value=backend_labels.get(self.config.get('translation_backend','auto'),'自动'))
        self.cpu_llm_threads=tk.StringVar(value=str(self.config.get('cpu_llm_threads',8)))
        self.status=tk.StringVar(value='正在准备本地模型，尚未接收声音…')
        ttk.Label(content,text='ASMR 本地字幕',font=('Microsoft YaHei UI',19,'bold')).pack(anchor='w',padx=18,pady=(12,3))
        ttk.Label(content,text='日语识别在 CPU 上运行，中文翻译使用显卡。音频只留在内存中。').pack(anchor='w',padx=18)
        top=ttk.Frame(content);top.pack(fill='x',padx=18,pady=10)
        ttk.Label(top,text='播放设备').pack(side='left')
        self.device=ttk.Combobox(top,state='readonly');self.device.pack(side='left',fill='x',expand=True,padx=8)
        ttk.Button(top,text='刷新',command=self.refresh).pack(side='left')
        buttons=ttk.Frame(content);buttons.pack(fill='x',padx=18)
        self.start_button=ttk.Button(buttons,text='开始接收播放声音',command=self.start,state='disabled');self.start_button.pack(side='left')
        self.stop_button=ttk.Button(buttons,text='停止',command=self.stop,state='disabled');self.stop_button.pack(side='left',padx=8)
        ttk.Button(buttons,text='显示悬浮字幕',command=self.show_overlay).pack(side='left')
        ttk.Button(buttons,text='新作品 / 清空',command=self.reset).pack(side='right')
        ttk.Label(content,textvariable=self.status,wraplength=800).pack(anchor='w',padx=18,pady=9)
        self.settings_tabs=ttk.Notebook(content);self.settings_tabs.pack(fill='x',padx=18)
        settings=ttk.Frame(self.settings_tabs)
        self.settings_tabs.add(settings,text='识别与词库')
        runtime=ttk.Frame(settings);runtime.pack(fill='x',padx=8,pady=5)
        ttk.Label(runtime,text='中文翻译设备').pack(side='left')
        ttk.Combobox(runtime,textvariable=self.translation_backend,
                     values=['自动','显卡 CUDA','CPU＋显卡（均衡）','CPU＋显卡（省显存）','仅 CPU','显卡 Vulkan'],
                     state='readonly',width=20).pack(side='left',padx=6)
        ttk.Label(runtime,text='CPU 翻译线程').pack(side='left',padx=(8,0))
        self.cpu_thread_control=ttk.Spinbox(runtime,from_=1,to=24,increment=1,textvariable=self.cpu_llm_threads,width=4)
        self.cpu_thread_control.pack(side='left',padx=6)
        def update_cpu_threads(*_):
            self.cpu_thread_control.configure(state='normal' if self.translation_backend.get() in
                ('仅 CPU','CPU＋显卡（均衡）','CPU＋显卡（省显存）') else 'disabled')
        self.translation_backend.trace_add('write',update_cpu_threads)
        update_cpu_threads()
        ttk.Label(runtime,text='保存后重开程序生效').pack(side='left',padx=6)
        line=ttk.Frame(settings);line.pack(fill='x',padx=8,pady=6)
        ttk.Label(line,text='识别灵敏度').pack(side='left')
        self.sensitivity=ttk.Combobox(line,values=['标准','耳语','强降误识别'],state='readonly',width=13)
        self.sensitivity.set(self.config['sensitivity']);self.sensitivity.pack(side='left',padx=6)
        ttk.Label(line,text='断句等待（秒）').pack(side='left')
        self.pause=tk.StringVar(value=str(self.config['pause']))
        ttk.Spinbox(line,from_=0.3,to=1.5,increment=0.1,textvariable=self.pause,width=6).pack(side='left',padx=5)
        self.context=tk.BooleanVar(value=self.config['context'])
        ttk.Checkbutton(line,text='参考前几句',variable=self.context).pack(side='left',padx=8)
        speed=ttk.Frame(settings);speed.pack(fill='x',padx=8,pady=(0,5))
        ttk.Label(speed,text='最长收音（秒）').pack(side='left')
        self.max_phrase=tk.StringVar(value=str(self.config['max_phrase']))
        ttk.Spinbox(speed,from_=2,to=8,increment=0.5,textvariable=self.max_phrase,width=6).pack(side='left',padx=5)
        self.fast_asr=tk.BooleanVar(value=self.config.get('fast_asr',True))
        ttk.Checkbutton(speed,text='快速识别',variable=self.fast_asr).pack(side='left',padx=8)
        ttk.Label(speed,text='收音越短越快；长段更有利于整句理解。').pack(side='left')
        row=ttk.Frame(settings);row.pack(fill='x',padx=8,pady=4)
        ttk.Label(row,text='作品背景').pack(side='left')
        self.scene=ttk.Entry(row);self.scene.insert(0,self.config['scene']);self.scene.pack(side='left',fill='x',expand=True,padx=6)
        ttk.Label(settings,text='称呼 / 术语：粘贴 JSON 或导入文件；支持 usage_note 语境说明，修改后请保存。').pack(anchor='w',padx=8)
        editor=ttk.Frame(settings);editor.pack(fill='x',padx=8,pady=5)
        self.glossary=tk.Text(editor,height=3,wrap='word',font=('Microsoft YaHei UI',10),
                              bg='#fffbfd',fg='#633f50',insertbackground='#a75b7d',
                              selectbackground='#eab4cb',selectforeground='#563345',
                              relief='flat',highlightthickness=1,highlightbackground='#e3bacb',
                              highlightcolor='#d787a8',padx=6,pady=4)
        glossary_scroll=ttk.Scrollbar(editor,command=self.glossary.yview)
        self.glossary.configure(yscrollcommand=glossary_scroll.set)
        self.glossary.insert('1.0',json.dumps(self.config['glossary'],ensure_ascii=False,indent=2))
        self.glossary.pack(side='left',fill='both',expand=True)
        glossary_scroll.pack(side='right',fill='y')
        tools=ttk.Frame(settings);tools.pack(fill='x',padx=8,pady=(0,6))
        ttk.Button(tools,text='导入词库文件…',command=self.import_glossary).pack(side='left')
        self.glossary_summary=tk.StringVar()
        ttk.Label(tools,textvariable=self.glossary_summary).pack(side='left',padx=10)
        ttk.Button(tools,text='保存作品设置',command=self.save).pack(side='right')
        self.glossary_update=None
        self.glossary.bind('<<Modified>>',self.glossary_changed)
        self.update_glossary_summary()
        self.overlay_settings=ttk.Frame(self.settings_tabs)
        self.settings_tabs.add(self.overlay_settings,text='悬浮字幕设置')
        display=self.overlay_settings
        ttk.Label(display,text='拖动字幕区域移动，拖动边缘调整大小；显示设置在这里调整。',
                  font=('Microsoft YaHei UI',11,'bold')).pack(anchor='w',padx=12,pady=(8,4))
        fonts=ttk.Frame(display);fonts.pack(fill='x',padx=12,pady=3)
        ttk.Label(fonts,text='中文字幕字号').pack(side='left')
        ttk.Spinbox(fonts,from_=12,to=48,increment=1,textvariable=self.font_size,width=5).pack(side='left',padx=(6,20))
        ttk.Label(fonts,text='日文字号').pack(side='left')
        self.ja_font_control=ttk.Spinbox(fonts,from_=10,to=32,increment=1,textvariable=self.ja_font_size,width=5)
        self.ja_font_control.pack(side='left',padx=6)
        ttk.Button(fonts,text='中文颜色…',command=lambda:self.choose_caption_color('zh')).pack(side='left',padx=(12,4))
        self.zh_color_sample=tk.Label(fonts,text='字',width=2,bg='#17212b',fg=self.zh_color.get())
        self.zh_color_sample.pack(side='left')
        ttk.Button(fonts,text='日文颜色…',command=lambda:self.choose_caption_color('ja')).pack(side='left',padx=(12,4))
        self.ja_color_sample=tk.Label(fonts,text='字',width=2,bg='#17212b',fg=self.ja_color.get())
        self.ja_color_sample.pack(side='left')
        effects=ttk.Frame(display);effects.pack(fill='x',padx=12,pady=3)
        ttk.Label(effects,text='字重').pack(side='left')
        ttk.Combobox(effects,textvariable=self.font_weight,values=['常规','加粗'],state='readonly',width=6).pack(side='left',padx=(6,16))
        ttk.Label(effects,text='描边粗细').pack(side='left')
        ttk.Combobox(effects,textvariable=self.outline_width,values=['0','1','2'],state='readonly',width=3).pack(side='left',padx=(6,16))
        ttk.Checkbutton(effects,text='柔和阴影',variable=self.shadow).pack(side='left')
        ttk.Button(effects,text='应用“柔和字幕”',command=self.apply_soft_preset).pack(side='right')
        visibility=ttk.Frame(display);visibility.pack(fill='x',padx=12,pady=3)
        ttk.Checkbutton(visibility,text='仅显示中文译文',variable=self.only_translation).pack(side='left')
        ttk.Checkbutton(visibility,text='悬浮窗置顶',variable=self.topmost).pack(side='left',padx=20)
        ttk.Checkbutton(visibility,text='背景透明（只显示文字）',variable=self.transparent_bg).pack(side='left')
        progress=ttk.Frame(display);progress.pack(fill='x',padx=12,pady=3)
        ttk.Checkbutton(progress,text='显示“正在本机翻译”等状态提示',variable=self.show_status).pack(side='left')
        ttk.Checkbutton(progress,text='逐步显示译文',variable=self.streaming).pack(side='left',padx=20)
        ttk.Label(display,text='关闭状态提示时保留上一句；关闭逐步显示时只显示完整译文。\n透明时按住文字拖动；调整大小可暂时关闭透明背景。',
                  wraplength=650).pack(anchor='w',padx=12,pady=(4,6))
        actions=ttk.Frame(display);actions.pack(fill='x',padx=12,pady=(0,10))
        ttk.Button(actions,text='预览显示效果',command=self.preview_overlay).pack(side='left')
        ttk.Button(actions,text='隐藏悬浮字幕',command=self.hide_overlay).pack(side='left',padx=8)
        ttk.Button(actions,text='保存显示设置',command=self.save_overlay_settings).pack(side='right')
        for variable in (self.font_size,self.ja_font_size,self.topmost,self.only_translation,self.show_status,self.streaming,
                         self.transparent_bg,self.zh_color,self.ja_color,self.font_weight,self.outline_width,self.shadow):
            variable.trace_add('write',lambda *_:self.apply_overlay_settings())
        preview=ttk.LabelFrame(content,text='本地翻译测试（不接收声音）');preview.pack(fill='x',padx=18,pady=8)
        self.test_text=ttk.Entry(preview);self.test_text.insert(0,'今日はゆっくり休んでください。');self.test_text.pack(side='left',fill='x',expand=True,padx=8,pady=6)
        self.test_button=ttk.Button(preview,text='翻译这句',command=self.manual,state='disabled');self.test_button.pack(side='right',padx=8)
        history=ttk.Frame(content);history.pack(fill='both',expand=True,padx=18,pady=(3,8))
        self.history=tk.Text(history,height=2,state='disabled',wrap='word',font=('Microsoft YaHei UI',11),
                             bg='#fff8fc',fg='#633f50',selectbackground='#eab4cb',
                             selectforeground='#563345',relief='flat',highlightthickness=1,
                             highlightbackground='#e3bacb',padx=10,pady=8)
        scroll=ttk.Scrollbar(history,command=self.history.yview);self.history.configure(yscrollcommand=scroll.set)
        self.history.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        foot=ttk.Frame(content);foot.pack(fill='x',padx=18,pady=(0,12))
        ttk.Label(foot,text='字幕保存在内存；仅点击导出时写入文件。').pack(side='left')
        ttk.Button(foot,text='导出双语 SRT',command=self.export).pack(side='right')
        self.refresh()
        self.show_overlay()
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.after(100,self.poll)
        self.engine.prepare()
    def refresh(self):
        if self.listening:
            messagebox.showinfo('设备','请先停止，再刷新播放设备。');return
        try:
            self.devices,default=enumerate_devices()
            names=[d['name'] for d in self.devices]
            self.device.configure(values=names)
            preferred=self.device.get() or self.config.get('device_name') or default
            self.device.set(preferred if preferred in names else (names[0] if names else ''))
        except Exception as exc:
            self.status.set('未找到播放回环设备：'+str(exc))
    def read_glossary(self):
        return merge_glossaries([],json.loads(self.glossary.get('1.0','end').strip() or '[]'))
    def glossary_changed(self,event=None):
        if not self.glossary.edit_modified():return
        self.glossary.edit_modified(False)
        if self.glossary_update is not None:self.root.after_cancel(self.glossary_update)
        self.glossary_update=self.root.after(250,self.update_glossary_summary)
    def update_glossary_summary(self):
        self.glossary_update=None
        try:
            terms=self.read_glossary()
            notes=sum(bool(term.get('usage_note')) for term in terms)
            self.glossary_summary.set(f'{len(terms)} 条 · 含语境说明 {notes} 条')
        except (ValueError,TypeError):
            self.glossary_summary.set('JSON 待修正')
    def import_glossary(self):
        paths=filedialog.askopenfilenames(title='导入词库（可同时选择核心词库和多义词库）',
            initialdir=str(BASE),filetypes=[('JSON 词库','*.json')])
        if not paths:return
        try:
            merged=merge_glossaries(self.read_glossary(),read_glossary_files(paths))
            self.glossary.delete('1.0','end')
            self.glossary.insert('1.0',json.dumps(merged,ensure_ascii=False,indent=2))
            self.update_glossary_summary()
            self.status.set(f'已合并 {len(paths)} 个词库文件，共 {len(merged)} 条；请点击“保存作品设置”长期保存。')
        except (ValueError,TypeError) as exc:
            messagebox.showerror('词库导入失败',str(exc))
    def options(self):
        glossary=self.read_glossary()
        pause=float(self.pause.get())
        if not 0.3<=pause<=1.5:
            raise ValueError('断句等待应为 0.3 到 1.5 秒')
        max_phrase=float(self.max_phrase.get())
        if not 2<=max_phrase<=8:
            raise ValueError('最长收音应为 2 到 8 秒')
        backends={'自动':'auto','显卡 CUDA':'cuda','显卡 Vulkan':'vulkan','仅 CPU':'cpu',
                  'CPU＋显卡（均衡）':'hybrid','CPU＋显卡（省显存）':'hybrid_lowvram'}
        if self.translation_backend.get() not in backends:raise ValueError('请选择中文翻译设备')
        threads=int(self.cpu_llm_threads.get())
        if not 1<=threads<=64:raise ValueError('CPU 翻译线程应为 1 到 64')
        return {**self.config,'device_name':self.device.get(),'sensitivity':self.sensitivity.get(),
                'pause':pause,'max_phrase':max_phrase,'fast_asr':self.fast_asr.get(),
                'scene':self.scene.get()[:250],'glossary':glossary,'context':self.context.get(),
                'translation_backend':backends[self.translation_backend.get()],'cpu_llm_threads':threads,
                **self.overlay_options()}
    def overlay_options(self):
        try:
            size=int(self.font_size.get());ja_size=int(self.ja_font_size.get())
        except ValueError as exc:
            raise ValueError('字幕字号必须为整数') from exc
        if not 12<=size<=48:raise ValueError('中文字幕字号应为 12 到 48')
        if not 10<=ja_size<=32:raise ValueError('日文字号应为 10 到 32')
        if self.font_weight.get() not in ('常规','加粗'):raise ValueError('请选择常规或加粗字重')
        try:outline=int(self.outline_width.get())
        except ValueError as exc:raise ValueError('描边粗细必须为 0、1 或 2') from exc
        if outline not in (0,1,2):raise ValueError('描边粗细必须为 0、1 或 2')
        colors={}
        for key,variable,label in (('overlay_zh_color',self.zh_color,'中文'),('overlay_ja_color',self.ja_color,'日文')):
            try:
                rgb=self.root.winfo_rgb(variable.get())
            except tk.TclError as exc:
                raise ValueError(f'{label}字体颜色无效，请重新选择') from exc
            colors[key]='#' + ''.join(f'{value//257:02x}' for value in rgb)
        return {'font_size':size,'ja_font_size':ja_size,'topmost':self.topmost.get(),
                'overlay_only_translation':self.only_translation.get(),
                'overlay_show_status':self.show_status.get(),'overlay_streaming':self.streaming.get(),
                'overlay_transparent_bg':self.transparent_bg.get(),**colors,
                'overlay_font_weight':'bold' if self.font_weight.get()=='加粗' else 'normal',
                'overlay_outline_width':outline,'overlay_shadow':self.shadow.get()}
    def apply_soft_preset(self):
        self.font_size.set('22');self.ja_font_size.set('14')
        self.zh_color.set('#f5f3ed');self.ja_color.set('#dedcd6')
        self.font_weight.set('常规');self.outline_width.set('1');self.shadow.set(True)
        self.transparent_bg.set(True)
        self.status.set('已应用柔和字幕：常规字重、柔白文字、细描边和轻阴影。点击“保存显示设置”可记住。')
    def choose_caption_color(self,language):
        variable=self.zh_color if language=='zh' else self.ja_color
        title='选择中文字幕颜色' if language=='zh' else '选择日文字幕颜色'
        _,chosen=colorchooser.askcolor(color=variable.get(),parent=self.root,title=title)
        if chosen:variable.set(chosen)
    def write_config(self,config):
        target=BASE/'作品设置.json'
        temp=target.with_suffix('.json.tmp')
        temp.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
        temp.replace(target)
    def save_overlay_settings(self):
        try:
            display=self.overlay_options()
            self.write_config({**load_config(),**display})
            self.config.update(display)
            self.status.set('字幕显示设置已保存，下次打开继续沿用。')
        except Exception as exc:
            messagebox.showerror('显示设置无效',str(exc))
    def save(self):
        try:
            config=self.options()
            self.write_config(config)
            self.config=config
            self.update_glossary_summary()
            self.status.set('设置已保存。翻译设备 / CPU 线程需重开程序生效；其他识别设置停止后再开始生效。')
        except Exception as exc:
            messagebox.showerror('设置无效',str(exc))
    def start(self):
        try:
            selected=next((d for d in self.devices if d['name']==self.device.get()),None)
            if selected is None:
                raise ValueError('请选择实际播放声音的耳机或扬声器')
            self.engine.start(selected,self.options())
            self.listening=True
            self.start_button.configure(state='disabled')
            self.stop_button.configure(state='normal')
            self.test_button.configure(state='disabled')
            self.status.set('正在打开播放回环设备…')
            self.set_caption('等待台词…','',kind='status')
        except Exception as exc:
            messagebox.showerror('无法开始',str(exc))
    def stop(self):
        self.listening=False
        try:
            self.engine.stop()
            self.status.set('已停止，播放音频流已关闭。')
        except Exception as exc:
            self.status.set(str(exc))
        self.start_button.configure(state='normal' if self.engine.ready else 'disabled')
        self.stop_button.configure(state='disabled')
        self.test_button.configure(state='normal' if self.engine.ready else 'disabled')
        self.set_caption('已停止','',kind='status')
    def reset(self):
        self.stop()
        self.engine.reset()
        self.rows.clear()
        self.last_caption=('', '')
        self.set_caption('尚未开始收音','',kind='status')
        self.history.configure(state='normal');self.history.delete('1.0','end');self.history.configure(state='disabled')
        self.status.set('已清空上一作品字幕与翻译上下文。')
    def manual(self):
        try:
            source=self.test_text.get().strip()
            if not source:raise ValueError('请输入日文原句')
            self.engine.translate_manual(source,self.options())
            self.test_button.configure(state='disabled')
            self.status.set('正在本机翻译测试句…')
        except Exception as exc:
            messagebox.showerror('翻译测试',str(exc))
    def show_overlay(self):
        if self.overlay is not None and self.overlay.winfo_exists():
            self.overlay.deiconify();self.overlay.lift();return
        self.overlay=tk.Toplevel(self.root)
        self.overlay.title('ASMR 悬浮字幕')
        self.overlay.overrideredirect(True)
        width=min(920,max(400,self.root.winfo_screenwidth()-80))
        height=160 if self.only_translation.get() else 210
        x=max(0,(self.root.winfo_screenwidth()-width)//2)
        y=max(0,self.root.winfo_screenheight()-height-80)
        self.overlay.geometry(f'{width}x{height}+{x}+{y}')
        self.overlay.configure(bg='#17212b')
        self.overlay.protocol('WM_DELETE_WINDOW',self.overlay.withdraw)
        self.overlay_renderer=AlphaSubtitles()
        def resize(event):
            if self.closing or event.widget is not self.overlay:
                return
            previous=self.overlay_renderer.last_frame
            if (event.width,event.height)!=(previous.get('width'),previous.get('height')):
                self.request_overlay_render()
        def destroyed(event):
            if event.widget is not self.overlay:return
            if self.overlay_render_job is not None:
                try:self.root.after_cancel(self.overlay_render_job)
                except tk.TclError:pass
                self.overlay_render_job=None
            if self.overlay_renderer:self.overlay_renderer.close()
        self.overlay.bind('<Configure>',resize)
        self.overlay.bind('<Map>',lambda event:self.request_overlay_render() if event.widget is self.overlay else None)
        self.overlay.bind('<Destroy>',destroyed)
        self.bind_overlay_drag()
        self.apply_overlay_settings()
    def bind_overlay_drag(self):
        self.overlay_drag=None
        def edges(event):
            x=event.x_root-self.overlay.winfo_rootx()
            y=event.y_root-self.overlay.winfo_rooty()
            horizontal='w' if x<8 else ('e' if x>=self.overlay.winfo_width()-8 else '')
            vertical='n' if y<8 else ('s' if y>=self.overlay.winfo_height()-8 else '')
            return vertical+horizontal
        def pointer(event):
            if self.overlay_drag is not None:return
            edge=edges(event)
            cursor={'nw':'top_left_corner','ne':'top_right_corner',
                    'sw':'bottom_left_corner','se':'bottom_right_corner',
                    'w':'sb_h_double_arrow','e':'sb_h_double_arrow',
                    'n':'sb_v_double_arrow','s':'sb_v_double_arrow'}.get(edge,'fleur')
            self.overlay.configure(cursor=cursor)
        def press(event):
            self.overlay_drag=(event.x_root,event.y_root,self.overlay.winfo_x(),self.overlay.winfo_y(),
                               self.overlay.winfo_width(),self.overlay.winfo_height(),edges(event))
            return 'break'
        def drag(event):
            if self.overlay_drag is None:return
            start_x,start_y,x,y,width,height,edge=self.overlay_drag
            dx=event.x_root-start_x;dy=event.y_root-start_y
            minimum_width,minimum_height=self.overlay.minsize()
            if not edge:
                x+=dx;y+=dy
            else:
                if 'w' in edge:
                    size=max(minimum_width,width-dx);x+=width-size;width=size
                elif 'e' in edge:width=max(minimum_width,width+dx)
                if 'n' in edge:
                    size=max(minimum_height,height-dy);y+=height-size;height=size
                elif 's' in edge:height=max(minimum_height,height+dy)
            # A monitor left/above the primary has negative desktop coordinates.
            # Tk's '+-240' means x=-240; '-240' would anchor to the right edge.
            self.overlay.geometry(f'{width}x{height}+{x}+{y}')
            return 'break'
        def release(event):
            self.overlay_drag=None
        self.overlay.bind('<Motion>',pointer)
        self.overlay.bind('<ButtonPress-1>',press)
        self.overlay.bind('<B1-Motion>',drag)
        self.overlay.bind('<ButtonRelease-1>',release)
    def hide_overlay(self):
        if self.overlay is not None and self.overlay.winfo_exists():
            self.overlay.withdraw()
    def preview_overlay(self):
        self.show_overlay()
        self.set_caption('今天请好好休息。','今日はゆっくり休んでください。',kind='preview')
    def apply_overlay_settings(self):
        try:display=self.overlay_options()
        except (ValueError,tk.TclError):return  # Permit editing an empty/incomplete spinbox.
        self.ja_font_control.configure(state='disabled' if display['overlay_only_translation'] else 'normal')
        self.zh_color_sample.configure(fg=display['overlay_zh_color'])
        self.ja_color_sample.configure(fg=display['overlay_ja_color'])
        if self.overlay is not None and self.overlay.winfo_exists():
            self.overlay.attributes('-topmost',display['topmost'])
            self.overlay.minsize(400,90 if display['overlay_only_translation'] else 130)
        self.render_caption()
    def set_caption(self,zh,ja,kind='caption'):
        self.caption_data=(zh,ja,kind)
        if kind=='caption':self.last_caption=(zh,ja)
        self.render_caption()
    def render_caption(self):
        zh,ja,kind=self.caption_data
        if kind=='partial' and not self.streaming.get():
            zh='正在本机翻译…';kind='pending'
        if kind in ('status','pending','error') and not self.show_status.get():
            zh,ja=self.last_caption
        elif kind=='partial' and self.show_status.get():
            zh+='  …'
        if self.only_translation.get():ja=''
        self.zh.set(zh);self.ja.set(ja)
        self.request_overlay_render()
    def request_overlay_render(self):
        if self.closing or self.overlay_renderer is None:return
        if self.overlay_render_job is None:
            self.overlay_render_job=self.root.after_idle(self.draw_overlay)
    def draw_overlay(self):
        self.overlay_render_job=None
        if self.closing or self.overlay is None or not self.overlay.winfo_exists():return
        if not self.overlay.winfo_ismapped():return
        try:
            self.overlay_renderer.render(self.overlay,self.zh.get(),self.ja.get(),self.overlay_options())
        except (ValueError,tk.TclError):pass  # Allow incomplete spinbox edits.
        except Exception as exc:self.status.set('字幕显示失败：'+str(exc))
    def poll(self):
        if self.closing:return
        for _ in range(100):
            try:kind,value=self.events.get_nowait()
            except queue.Empty:break
            if kind=='ready':
                self.start_button.configure(state='normal');self.test_button.configure(state='normal')
                device_label='仅 CPU' if value=='CPU' else f'{value} 加速'
                self.status.set(f'本地模型已就绪（{device_label}）。当前停止，点击开始后才接收声音。')
            elif kind=='prepare_error':
                self.status.set('模型未就绪：'+value)
                messagebox.showerror('准备失败',value+'\n模型下载期间请等待完成，再重新打开程序。')
            elif kind=='status':
                if self.listening or '加载' in value or '预热' in value or str(self.test_button.cget('state'))=='disabled':self.status.set(value)
            elif kind=='capture_open':self.status.set('正在接收所选播放设备的声音。')
            elif kind=='capture_error':
                self.stop();self.status.set('收音已停止：'+value)
            elif kind=='original':
                if value['epoch']==self.engine.epoch:self.set_caption('正在本机翻译…',value['ja'],kind='pending')
            elif kind=='partial':
                if value['epoch']==self.engine.epoch:self.set_caption(value['zh'],value['ja'],kind='partial')
            elif kind=='caption':
                if value['epoch']!=self.engine.epoch:continue
                self.rows.append(value)
                # Retain a bounded transcript in RAM. Export before a very long session.
                if len(self.rows)>3000:self.rows=self.rows[-3000:]
                zh=value['zh'] if value['ok'] else '【翻译失败，保留日文】'
                self.set_caption(zh,value['ja'],kind='caption' if value['ok'] else 'error')
                tag='测试' if value['manual'] else f"{value['start']:.1f}s"
                self.history.configure(state='normal');self.history.insert('end',f"[{tag}] {value['ja']}\n{zh}\n\n")
                lines=int(self.history.index('end-1c').split('.')[0])
                if lines>10000:self.history.delete('1.0',f'{lines-10000+1}.0')
                self.history.see('end');self.history.configure(state='disabled')
                if not value['ok']:self.status.set(value['error'])
                elif self.listening:self.status.set(f"正在接收声音 · 识别 {value['asr_seconds']:.1f}s / 首字 {value.get('first_text_seconds',0):.1f}s / 完整翻译 {value.get('translate_seconds',0):.1f}s · 等待 {self.engine.work.qsize()+self.engine.translation_work.qsize()} 段")
                else:self.status.set(f"本地翻译完成，用时 {value.get('translate_seconds',0):.1f} 秒。当前未收音。")
                if not self.listening:self.test_button.configure(state='normal')
            elif kind=='inference_error':
                self.status.set('识别失败：'+value)
                if not self.listening:self.test_button.configure(state='normal')
        self.root.after(100,self.poll)
    def export(self):
        if not any(not x.get('manual') for x in self.rows):
            messagebox.showinfo('导出','还没有播放音频字幕。测试输入不计入 SRT。');return
        path=filedialog.asksaveasfilename(title='保存双语字幕',initialdir=str(BASE),initialfile='双语字幕.srt',defaultextension='.srt',filetypes=[('SRT 字幕','*.srt')])
        if path:
            try:export_subtitles(list(self.rows),path);self.status.set('已导出双语字幕。')
            except Exception as exc:messagebox.showerror('导出失败',str(exc))
    def close(self):
        if self.closing:return
        self.closing=True
        self.status.set('正在关闭音频设备和本地模型…')
        def close():
            try:self.engine.close()
            finally:self.events.put(('exit',None))
        threading.Thread(target=close,daemon=True).start()
        def finish():
            try:
                while True:
                    kind,_=self.events.get_nowait()
                    if kind=='exit':self.root.destroy();return
            except queue.Empty:pass
            self.root.after(100,finish)
        finish()

def load_defaults():
    from realtime_core import DEFAULTS
    return dict(DEFAULTS)

if __name__=='__main__':
    install_network_guard()
    root=tk.Tk()
    App(root)
    root.mainloop()
