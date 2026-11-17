from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import fitz
from PIL import Image, ImageTk

from . import APP_NAME
from .domain import Project, Symbol, description_for, normalize_size, number_symbols, parse_pages, validate
from .exporter import export_bundle, inspect_template, make_template
from .vision import Cancelled, DEFAULT_MODEL, VisionClient, extract

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT/'local_data'


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry('1560x960')
        self.minsize(1200,780)
        self.configure(bg='#edf2f6')
        self.project = Project()
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.selected_id = None
        self.page_number = 1
        self.zoom = 1.0
        self.image = None
        self.controller_choices = {}
        self.status = tk.StringVar(value='PFD를 직접 선택한 뒤 AI 판독을 실행하세요. 기존 회사 자료는 자동으로 불러오지 않습니다.')
        self.pdf_var, self.template_var = tk.StringVar(), tk.StringVar()
        self.pages_var = tk.StringVar(value='1-5')
        self.plant_var, self.unit_var = tk.StringVar(value='ACK'), tk.StringVar(value='UNIT')
        self.key_var = tk.StringVar(value=os.environ.get('OPENAI_API_KEY',''))
        self.model_var = tk.StringVar(value=DEFAULT_MODEL)
        self.detailed_var = tk.BooleanVar(value=True)
        self.filter_var = tk.StringVar()
        self.count_var = tk.StringVar(value='0 TAGS')
        self.editor = {}
        self._style()
        self._build()
        self.filter_var.trace_add('write', lambda *a:self.refresh_table())
        self.after(100,self.poll)
        self.protocol('WM_DELETE_WINDOW',self.close)
        # Never discover or restore company workbooks, drawings, or previous sessions.
        # The default template is generated from generic headers/styles, not a populated workbook.
        LOCAL.mkdir(parents=True,exist_ok=True)
        default_template=LOCAL/'ack_blank_template.xlsx'
        make_template(default_template)
        self.project.template=str(default_template)
        self.template_var.set(str(default_template))
        self.refresh_table()

    def _style(self):
        style=ttk.Style(self)
        style.theme_use('clam')
        style.configure('.',font=('맑은 고딕',10),background='#edf2f6',foreground='#183547')
        style.configure('TFrame',background='#edf2f6')
        style.configure('Card.TFrame',background='white')
        style.configure('Title.TLabel',font=('맑은 고딕',20,'bold'),foreground='#12374b')
        style.configure('Sub.TLabel',font=('맑은 고딕',10),foreground='#52697a')
        style.configure('TButton',padding=(12,8))
        style.configure('Accent.TButton',background='#126f77',foreground='white',font=('맑은 고딕',10,'bold'))
        style.map('Accent.TButton',background=[('active','#0a555c')])
        style.configure('Treeview',rowheight=28,background='white',fieldbackground='white')
        style.configure('Treeview.Heading',font=('맑은 고딕',10,'bold'),background='#dbe7ed')
        style.configure('TLabelframe',padding=10)
        style.configure('TLabelframe.Label',font=('맑은 고딕',11,'bold'))

    def _button(self,parent,text,command,accent=False):
        b=ttk.Button(parent,text=text,command=lambda:self.safe(command),style='Accent.TButton' if accent else 'TButton')
        b.pack(side='left',padx=(0,6))
        return b

    def _build(self):
        header=ttk.Frame(self,padding=(22,15))
        header.pack(fill='x')
        ttk.Label(header,text=APP_NAME,style='Title.TLabel').pack(side='left')
        ttk.Label(header,text='PFD → 검토 → Instrument Index',style='Sub.TLabel').pack(side='left',padx=18)
        ttk.Label(header,text=self.count_var.get(),textvariable=self.count_var,font=('맑은 고딕',14,'bold')).pack(side='right')
        actions=ttk.Frame(self,padding=(22,0,22,10));actions.pack(fill='x')
        self._button(actions,'가상 예제',self.demo)
        self._button(actions,'프로젝트 열기',self.load)
        self._button(actions,'프로젝트 저장',self.save)
        self._button(actions,'설명서',lambda:os.startfile(ROOT/'README.md'))
        top=ttk.Frame(self,padding=(22,0,22,12));top.pack(fill='x')
        left=ttk.LabelFrame(top,text='1  입력 · 범위');left.pack(side='left',fill='both',expand=True,padx=(0,12))
        self._path_row(left,'PFD PDF',self.pdf_var,self.choose_pdf,0)
        self._path_row(left,'엑셀 템플릿',self.template_var,self.choose_template,1)
        row=ttk.Frame(left);row.grid(row=2,column=0,columnspan=3,sticky='ew',pady=(7,0))
        for label,var,width in [('페이지',self.pages_var,12),('PLANT',self.plant_var,22),('UNIT',self.unit_var,14)]:
            ttk.Label(row,text=label).pack(side='left',padx=(0,5));ttk.Entry(row,textvariable=var,width=width).pack(side='left',padx=(0,13))
        left.columnconfigure(1,weight=1)
        right=ttk.LabelFrame(top,text='2  AI 판독');right.pack(side='left',fill='both')
        ttk.Label(right,text='API 키').grid(row=0,column=0,sticky='w')
        ttk.Entry(right,textvariable=self.key_var,show='●',width=29).grid(row=0,column=1,sticky='ew',padx=7)
        ttk.Label(right,text='모델').grid(row=1,column=0,sticky='w',pady=5)
        ttk.Entry(right,textvariable=self.model_var,width=29).grid(row=1,column=1,sticky='ew',padx=7)
        ttk.Checkbutton(right,text='정밀 판독: 전체 + 겹침 확대 4구역',variable=self.detailed_var).grid(row=2,column=0,columnspan=2,sticky='w')
        ai=ttk.Frame(right);ai.grid(row=3,column=0,columnspan=2,sticky='w',pady=5)
        self.analyze_button=self._button(ai,'AI 판독 · 이미지 전송',self.analyze,True)
        self._button(ai,'중지',lambda:self.cancel.set())
        ttk.Label(right,text='선택 페이지가 OpenAI API로 전송됩니다. 키는 저장하지 않습니다.',style='Sub.TLabel',wraplength=380).grid(row=4,column=0,columnspan=2,sticky='w')
        center=ttk.Panedwindow(self,orient='horizontal');center.pack(fill='both',expand=True,padx=22)
        table_frame=ttk.Frame(center);center.add(table_frame,weight=5)
        tools=ttk.Frame(table_frame);tools.pack(fill='x',pady=(0,8))
        ttk.Label(tools,text='3  태그 검토',font=('맑은 고딕',12,'bold')).pack(side='left',padx=(0,16))
        ttk.Entry(tools,textvariable=self.filter_var,width=21).pack(side='left')
        self._button(tools,'번호 다시 부여',self.renumber)
        columns=('tag','page','kind','description','size','status')
        self.tree=ttk.Treeview(table_frame,columns=columns,show='headings',selectmode='browse')
        for name,title,width in [('tag','TAG',115),('page','PID',45),('kind','기호',65),('description','J · 기능',185),('size','L · 구경',95),('status','검토',90)]:
            self.tree.heading(name,text=title);self.tree.column(name,width=width,minwidth=35,stretch=name=='description')
        scroll=ttk.Scrollbar(table_frame,orient='vertical',command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True)
        self.tree.tag_configure('warning',foreground='#a35c0a')
        self.tree.tag_configure('error',foreground='#b42a37')
        self.tree.tag_configure('excluded',foreground='#9babb4')
        self.tree.bind('<<TreeviewSelect>>',self.select_row)
        detail=ttk.Frame(center);center.add(detail,weight=5)
        nav=ttk.Frame(detail);nav.pack(fill='x',padx=(12,0),pady=(0,8))
        self._button(nav,'◀',lambda:self.change_page(-1));self._button(nav,'▶',lambda:self.change_page(1))
        self.page_label=ttk.Label(nav,text='PDF 미선택');self.page_label.pack(side='left',padx=10)
        self._button(nav,'확대 +',lambda:self.set_zoom(1.25));self._button(nav,'축소 −',lambda:self.set_zoom(.8))
        ttk.Label(nav,text='드래그: 이동 / 더블클릭: 수동 기호 추가',style='Sub.TLabel').pack(side='left')
        canvas_frame=ttk.Frame(detail);canvas_frame.pack(fill='both',expand=True,padx=(12,0))
        self.canvas=tk.Canvas(canvas_frame,bg='#dae3e9',highlightthickness=0)
        cx=ttk.Scrollbar(canvas_frame,orient='horizontal',command=self.canvas.xview)
        cy=ttk.Scrollbar(canvas_frame,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=cx.set,yscrollcommand=cy.set)
        cy.pack(side='right',fill='y');cx.pack(side='bottom',fill='x');self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<ButtonPress-1>',lambda e:self.canvas.scan_mark(e.x,e.y))
        self.canvas.bind('<B1-Motion>',lambda e:self.canvas.scan_dragto(e.x,e.y,gain=1))
        self.canvas.bind('<Double-Button-1>',self.add_manual)
        editor=ttk.LabelFrame(detail,text='선택 태그 · 직접 수정');editor.pack(fill='x',padx=(12,0),pady=(10,0))
        definitions=[('kind','기호'),('tag','태그'),('category','종류'),('size','구경 원문'),('size_unit','단위'),('description','J · 설명'),('controller','연결 계기'),('size_evidence','구경 근거'),('notes','메모')]
        for index,(key,label) in enumerate(definitions):
            r,c=divmod(index,3)
            cell=ttk.Frame(editor);cell.grid(row=r,column=c,sticky='ew',padx=4,pady=3)
            ttk.Label(cell,text=label).pack(anchor='w')
            var=tk.StringVar();self.editor[key]=var
            if key=='category':widget=ttk.Combobox(cell,textvariable=var,values=['instrument','valve'],state='readonly')
            elif key=='size_unit':widget=ttk.Combobox(cell,textvariable=var,values=['inch','mm','unknown','not_applicable'],state='readonly')
            elif key=='controller':
                widget=ttk.Combobox(cell,textvariable=var,state='readonly');self.controller_box=widget
            else:widget=ttk.Entry(cell,textvariable=var)
            widget.pack(fill='x')
        for i in range(3):editor.columnconfigure(i,weight=1)
        controls=ttk.Frame(editor);controls.grid(row=3,column=0,columnspan=3,sticky='ew',pady=5)
        self.locked_var=tk.BooleanVar();self.reviewed_var=tk.BooleanVar();self.excluded_var=tk.BooleanVar()
        for text,var in [('태그 고정',self.locked_var),('사람 검토 완료',self.reviewed_var),('출력 제외',self.excluded_var)]:
            ttk.Checkbutton(controls,text=text,variable=var).pack(side='left')
        self._button(controls,'변경 적용',self.apply_edit,True)
        bottom=ttk.Frame(self,padding=(22,12));bottom.pack(fill='x')
        self._button(bottom,'검증 결과',self.show_issues)
        self._button(bottom,'PDF + INDEX 출력',self.export,True)
        ttk.Label(bottom,textvariable=self.status,style='Sub.TLabel',wraplength=1000).pack(side='left',padx=10)

    def _path_row(self,parent,label,var,command,row):
        ttk.Label(parent,text=label,width=13).grid(row=row,column=0,sticky='w',pady=3)
        ttk.Entry(parent,textvariable=var,width=52).grid(row=row,column=1,sticky='ew',padx=5)
        ttk.Button(parent,text='선택',command=lambda:self.safe(command)).grid(row=row,column=2,padx=4)

    def safe(self,command):
        try:
            command()
        except Exception as exc:
            messagebox.showerror('확인 필요',str(exc),parent=self)

    def sync_settings(self):
        if not Path(self.pdf_var.get()).is_file():raise ValueError('PFD PDF를 선택하세요.')
        self.project.pdf=self.pdf_var.get();self.project.template=self.template_var.get()
        with fitz.open(self.project.pdf) as doc:
            self.project.selected_pages=parse_pages(self.pages_var.get(),len(doc))
        self.project.plant,self.project.unit=self.plant_var.get(),self.unit_var.get()

    def choose_pdf(self):
        self.assert_idle()
        path=filedialog.askopenfilename(filetypes=[('PDF','*.pdf')])
        if not path:return
        if path!=self.project.pdf:
            self.project.symbols=[];self.selected_id=None;self.project.extraction={}
            self.clear_editor()
        self.project.pdf=path;self.pdf_var.set(path)
        with fitz.open(path) as d:self.pages_var.set('1-'+str(min(5,len(d))))
        self.page_number=1;self.refresh_table();self.render_page()

    def choose_template(self):
        self.assert_idle()
        path=filedialog.askopenfilename(filetypes=[('Instrument Index','*.xlsx')])
        if not path:return
        data=inspect_template(path)
        self.template_var.set(path);self.project.template=path;self.project.rules=data['rules']
        if data['plant']:self.plant_var.set(data['plant'])
        if data['unit']:self.unit_var.set(data['unit'])
        self.status.set('선택한 템플릿의 양식과 일관된 J열 설명을 읽었습니다. 원본 템플릿은 덮어쓰지 않습니다.')
        self.refresh_table()

    def set_project(self,project):
        self.assert_idle()
        self.project=project;self.pdf_var.set(project.pdf);self.template_var.set(project.template)
        self.plant_var.set(project.plant);self.unit_var.set(project.unit)
        self.pages_var.set(','.join(map(str,project.selected_pages)))
        self.page_number=project.selected_pages[0] if project.selected_pages else 1
        self.selected_id=None;self.clear_editor();self.refresh_table();self.render_page()

    def clear_editor(self):
        for var in self.editor.values():var.set('')
        self.editor['controller'].set('연결 없음')
        self.locked_var.set(False);self.reviewed_var.set(False);self.excluded_var.set(False)

    def load(self):
        self.assert_idle()
        path=filedialog.askopenfilename(filetypes=[('PFD project','*.json')])
        if path:self.set_project(Project.load(path));self.status.set('프로젝트를 불러왔습니다.')

    def save(self):
        self.assert_idle();self.sync_settings()
        path=filedialog.asksaveasfilename(defaultextension='.json',initialdir=LOCAL,filetypes=[('PFD project','*.json')])
        if path:self.project.save(path);self.status.set('프로젝트를 저장했습니다.')

    def demo(self):
        self.assert_idle()
        from .sample import create_demo
        folder=LOCAL/'demo';folder.mkdir(parents=True,exist_ok=True)
        self.set_project(create_demo(folder))
        self.status.set('가상 예제: 이미 알려진 정답을 불러온 데모입니다. AI 자동 판독 성능 시연은 아닙니다.')

    def assert_idle(self):
        if self.busy:raise ValueError('판독 중입니다. 중지 후 완료될 때까지 기다려 주세요.')

    def analyze(self):
        self.assert_idle();self.sync_settings()
        if not Path(self.project.template).is_file():raise ValueError('엑셀 템플릿을 선택하세요.')
        learned=inspect_template(self.project.template)
        self.project.rules=learned['rules']
        client=VisionClient(self.key_var.get(),self.model_var.get())
        # Snapshot all settings on the UI thread; workers never access Tk variables.
        task=copy.deepcopy(self.project);task.symbols=[]
        detail=self.detailed_var.get();self.busy=True;self.cancel.clear()
        self.analyze_button.state(['disabled'])
        def worker():
            try:
                result=extract(task,client,LOCAL/'cache',detail,lambda text:self.events.put(('status',text)),self.cancel)
                self.events.put(('done',result))
            except Cancelled as exc:self.events.put(('cancelled',str(exc)))
            except Exception as exc:self.events.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        try:
            while True:
                event,value=self.events.get_nowait()
                if event=='status':self.status.set(value)
                else:
                    self.busy=False;self.analyze_button.state(['!disabled'])
                    if event=='done':
                        self.set_project(value)
                        value.save(LOCAL/'last_analysis.json')
                        self.status.set('AI 판독 완료. 태그·연결·구경 근거를 검토하고 출력하세요.')
                    elif event=='cancelled':self.status.set(value)
                    else:self.status.set('판독 실패: '+value);messagebox.showerror('판독 실패',value,parent=self)
        except queue.Empty:pass
        self.after(100,self.poll)

    def refresh_table(self):
        if not hasattr(self,'tree'):return
        self.tree.delete(*self.tree.get_children())
        issues=validate(self.project)
        errors={i['id'] for i in issues if i['level']=='error'}
        warnings={i['id'] for i in issues if i['level']=='warning'}
        query=self.filter_var.get().lower().strip()
        for item in self.project.symbols:
            desc=description_for(item,self.project.rules)
            try:size=normalize_size(item.size,item.size_unit)
            except ValueError:size='표기 오류'
            if query and query not in f'{item.tag} {item.kind} {desc} {size}'.lower():continue
            state='제외' if item.excluded else '오류' if item.id in errors else '확인 필요' if item.id in warnings else '완료'
            tag='excluded' if item.excluded else 'error' if item.id in errors else 'warning' if item.id in warnings else ''
            self.tree.insert('',tk.END,iid=item.id,values=(item.tag,item.page,item.kind,desc,size,state),tags=(tag,))
        active=sum(not x.excluded for x in self.project.symbols)
        self.count_var.set(f'{active} TAGS · {len(errors)} 오류 · {len(warnings)} 검토')
        self.controller_choices={'연결 없음':''}
        for item in self.project.symbols:
            if item.category=='instrument' and not item.excluded:
                self.controller_choices[f'{item.tag} · p{item.page}']=item.id
        self.controller_box['values']=list(self.controller_choices)

    def select_row(self,event=None):
        selected=self.tree.selection()
        if not selected:return
        self.selected_id=selected[0]
        item=next(x for x in self.project.symbols if x.id==self.selected_id)
        for key,var in self.editor.items():
            if key=='controller':
                var.set(next((label for label,id_ in self.controller_choices.items() if id_==item.controller_id),'연결 없음'))
            elif key=='description':var.set(description_for(item,self.project.rules))
            else:var.set(getattr(item,key))
        self.locked_var.set(item.tag_locked);self.reviewed_var.set(item.reviewed);self.excluded_var.set(item.excluded)
        self.page_number=item.page;self.render_page()

    def apply_edit(self):
        self.assert_idle()
        if not self.selected_id:raise ValueError('수정할 태그를 선택하세요.')
        item=next(x for x in self.project.symbols if x.id==self.selected_id)
        candidate=copy.deepcopy(item)
        for key,var in self.editor.items():
            if key=='controller':candidate.controller_id=self.controller_choices.get(var.get(),'')
            else:setattr(candidate,key,var.get().strip())
        candidate.kind=candidate.kind.upper();candidate.tag=candidate.tag.upper()
        normalize_size(candidate.size,candidate.size_unit)
        candidate.tag_locked=self.locked_var.get() or candidate.tag!=item.tag
        candidate.reviewed=self.reviewed_var.get();candidate.excluded=self.excluded_var.get()
        # Explicit J editing wins over a legacy row override.
        if candidate.description!=description_for(item,self.project.rules):candidate.overrides.pop('10',None)
        if candidate.kind!=item.kind:candidate.overrides.pop('9',None)
        index=self.project.symbols.index(item);self.project.symbols[index]=candidate
        self.refresh_table()
        if self.tree.exists(candidate.id):self.tree.selection_set(candidate.id)
        self.status.set('변경했습니다. 연결 계기/기호를 바꾼 경우 번호 다시 부여를 실행하세요.')

    def renumber(self):
        self.assert_idle();self.sync_settings()
        task=copy.deepcopy(self.project)
        number_symbols(task.symbols)
        self.project=task;self.refresh_table();self.render_page()
        self.status.set('페이지 간 연속 번호와 연결 밸브 번호를 갱신했습니다. 고정 태그는 유지했습니다.')

    def render_page(self):
        self.canvas.delete('all')
        if not self.project.pdf or not Path(self.project.pdf).is_file():return
        with fitz.open(self.project.pdf) as d:
            self.page_number=max(1,min(self.page_number,len(d)))
            page=d[self.page_number-1]
            pix=page.get_pixmap(matrix=fitz.Matrix(self.zoom,self.zoom),alpha=False)
            im=Image.frombytes('RGB',[pix.width,pix.height],pix.samples)
            self.image=ImageTk.PhotoImage(im)
            self.canvas.create_image(0,0,anchor='nw',image=self.image)
            self.canvas.configure(scrollregion=(0,0,pix.width,pix.height))
            self.page_label.configure(text=f'{self.page_number} / {len(d)} 페이지')
        for item in self.project.symbols:
            if item.page!=self.page_number or item.excluded:continue
            x,y=item.x*self.zoom,item.y*self.zoom
            selected=item.id==self.selected_id
            color='#e15428' if selected else '#087f87'
            self.canvas.create_oval(x-6,y-6,x+6,y+6,outline=color,width=3 if selected else 1)
            self.canvas.create_text(x+8,y+8,text=item.tag,anchor='nw',fill=color,font=('Arial',9,'bold'))
        selected=next((x for x in self.project.symbols if x.id==self.selected_id),None)
        if selected and selected.page==self.page_number:
            self.canvas.update_idletasks()
            w,h=self.image.width(),self.image.height()
            self.canvas.xview_moveto(max(0,(selected.x*self.zoom-self.canvas.winfo_width()/2)/w))
            self.canvas.yview_moveto(max(0,(selected.y*self.zoom-self.canvas.winfo_height()/2)/h))

    def change_page(self,delta):
        self.page_number+=delta;self.render_page()

    def set_zoom(self,factor):
        self.zoom=max(.4,min(3,self.zoom*factor));self.render_page()

    def add_manual(self,event):
        if self.busy:return
        try:
            self.sync_settings()
            if self.page_number not in self.project.selected_pages:
                raise ValueError('추가하려는 페이지를 입력 페이지 범위에 포함하세요.')
            x=self.canvas.canvasx(event.x)/self.zoom;y=self.canvas.canvasy(event.y)/self.zoom
            with fitz.open(self.project.pdf) as doc:
                if not doc[self.page_number-1].rect.contains(fitz.Point(x,y)):return
            item=Symbol(page=self.page_number,x=x,y=y,kind='UNKNOWN',confidence=1,
                        notes='수동 추가: 기호·종류·연결·구경을 지정하세요.')
            self.project.symbols.append(item);self.refresh_table();self.tree.selection_set(item.id);self.tree.see(item.id)
            self.status.set('수동 기호를 추가했습니다. 기호와 종류를 지정한 뒤 번호 다시 부여를 실행하세요.')
        except Exception as exc:messagebox.showerror('수동 추가',str(exc),parent=self)

    def show_issues(self):
        window=tk.Toplevel(self);window.title('검증 · 판독 근거');window.geometry('1050x650')
        text=tk.Text(window,wrap='word',font=('맑은 고딕',10));text.pack(fill='both',expand=True)
        issues=validate(self.project)
        text.insert('end',f'검증 항목 {len(issues)}개\n\n')
        for issue in issues:text.insert('end',f"[{issue['level']}] p{issue['page']} {issue['tag']}: {issue['message']}\n")
        for warning in self.project.extraction.get('warnings',[]):text.insert('end',warning+'\n')
        text.configure(state='disabled')

    def export(self):
        self.assert_idle();self.sync_settings()
        root=filedialog.askdirectory(title='출력 폴더 선택',initialdir=ROOT/'outputs')
        if not root:return
        folder=export_bundle(self.project,root)
        self.status.set('출력 완료: '+str(folder))
        os.startfile(folder)

    def close(self):
        if self.busy:
            self.cancel.set()
        self.key_var.set('')
        self.destroy()


def main():
    LOCAL.mkdir(parents=True,exist_ok=True)
    (ROOT/'outputs').mkdir(exist_ok=True)
    App().mainloop()


if __name__=='__main__':main()
