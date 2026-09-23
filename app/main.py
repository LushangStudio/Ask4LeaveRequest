"""Local demonstration. Identity is seeded; never expose this demo to the public."""
import hashlib
import io
import json
import logging
import os
import secrets
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import (JSON, DateTime, ForeignKey, LargeBinary, String, Text, UniqueConstraint,
                        create_engine, select, update, event)
from sqlalchemy.dialects.mysql import MEDIUMBLOB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
Path('var').mkdir(exist_ok=True)
URL = os.getenv('DATABASE_URL', 'sqlite:///./var/leave.db')
engine = create_engine(URL, pool_pre_ping=True, connect_args={'check_same_thread': False} if URL.startswith('sqlite') else {})
if URL.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def sqlite_foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=10000')
class Base(DeclarativeBase): pass
class Person(Base):
    __tablename__ = 'people'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(20))
    counselor: Mapped[str | None] = mapped_column(String(40), nullable=True)
    profile: Mapped[dict] = mapped_column(JSON)
class Login(Base):
    __tablename__ = 'demo_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    person_id: Mapped[str] = mapped_column(ForeignKey('people.id'))
    expires: Mapped[datetime] = mapped_column(DateTime)
class Request(Base):
    __tablename__ = 'leave_requests'
    __table_args__ = (UniqueConstraint('student_id', 'idempotency_key'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey('people.id'))
    counselor_id: Mapped[str] = mapped_column(ForeignKey('people.id'))
    idempotency_key: Mapped[str] = mapped_column(String(80))
    payload_hash: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    starts: Mapped[str] = mapped_column(String(10))
    ends: Mapped[str] = mapped_column(String(10))
    layout: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default='pending')
    file_status: Mapped[str] = mapped_column(String(16), default='not_started')
    generation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created: Mapped[str] = mapped_column(String(40))
class Item(Base):
    __tablename__ = 'leave_items'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey('leave_requests.id'), index=True)
    position: Mapped[int]
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    day: Mapped[str] = mapped_column(String(10))
    time: Mapped[str] = mapped_column(String(120))
class Decision(Base):
    __tablename__ = 'approval_records'
    request_id: Mapped[str] = mapped_column(ForeignKey('leave_requests.id'), primary_key=True)
    approver_id: Mapped[str] = mapped_column(ForeignKey('people.id'))
    approver_name: Mapped[str] = mapped_column(String(80))
    outcome: Mapped[str] = mapped_column(String(16))
    opinion: Mapped[str] = mapped_column(Text)
    at: Mapped[str] = mapped_column(String(40))
class Document(Base):
    __tablename__ = 'generated_documents'
    __table_args__ = (UniqueConstraint('request_id', 'position'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey('leave_requests.id'), index=True)
    position: Mapped[int]
    name: Mapped[str] = mapped_column(String(100))
    content: Mapped[bytes] = mapped_column(LargeBinary().with_variant(MEDIUMBLOB(), 'mysql'))
    digest: Mapped[str] = mapped_column(String(64))

DEMO_PEOPLE = [
 ('student-a','演示学生甲','student','counselor-a',{'college':'管理学院','major':'工商管理','grade':'2026','student_number':'DEMO001'}),
 ('student-b','演示学生乙','student','counselor-b',{'college':'管理学院','major':'管理科学','grade':'2026','student_number':'DEMO002'}),
 ('counselor-a','演示辅导员甲','counselor',None,{}),
 ('counselor-b','演示辅导员乙','counselor',None,{})]
@asynccontextmanager
async def lifespan(app):
    if os.getenv('APP_MODE','disabled') != 'demo':
        raise RuntimeError('Formal ehall identity adapter is not configured. Set APP_MODE=demo for loopback-only demo.')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for pid,name,role,counselor,profile in DEMO_PEOPLE:
            if not db.get(Person,pid): db.add(Person(id=pid,name=name,role=role,counselor=counselor,profile=profile))
        # A stopped process may leave a job in progress. Mark it retryable on demo restart.
        db.execute(update(Request).where(Request.file_status=='generating').values(file_status='failed', generation_error='生成被中断，请重试'))
        db.commit()
    yield
app = FastAPI(title='Ask4LeaveRequest',lifespan=lifespan)
def db_session():
    with Session(engine) as db: yield db
def current_user(leave_session: str | None = Cookie(default=None), db:Session=Depends(db_session)):
    login=db.get(Login,hashlib.sha256((leave_session or '').encode()).hexdigest())
    if not login or login.expires < datetime.now(timezone.utc).replace(tzinfo=None): raise HTTPException(401,'请先选择演示身份')
    return db.get(Person, login.person_id)
def authorized(db, rid, user):
    row=db.get(Request,rid)
    if not row or not (row.student_id==user.id or user.role=='counselor' and row.counselor_id==user.id):
        raise HTTPException(404,'申请不存在或无权查看')
    return row
class LoginInput(BaseModel):
    person_id: str
@app.post('/api/demo/login')
def login(body:LoginInput,response:Response,db:Session=Depends(db_session)):
    if not db.get(Person,body.person_id): raise HTTPException(400,'无效演示身份')
    from datetime import timedelta
    token=secrets.token_urlsafe(32)
    db.add(Login(token_hash=hashlib.sha256(token.encode()).hexdigest(), person_id=body.person_id,expires=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(hours=8)))
    db.commit()
    response.set_cookie('leave_session',token,httponly=True,samesite='strict',max_age=28800,path='/')
    return {'ok':True}
@app.post('/api/logout')
def logout(response:Response, leave_session:str|None=Cookie(default=None),db:Session=Depends(db_session)):
    row=db.get(Login,hashlib.sha256((leave_session or '').encode()).hexdigest())
    if row: db.delete(row); db.commit()
    response.delete_cookie('leave_session',path='/')
    return {'ok':True}
@app.get('/api/me')
def me(user:Person=Depends(current_user)):
    return {'id':user.id,'name':user.name,'role':user.role,'profile':user.profile}
@app.get('/api/health')
def health(): return {'status':'ok','mode':'demo'}
class ItemInput(BaseModel):
    kind: Literal['course','activity','other']
    title: str = Field(min_length=1,max_length=200)
    day: date
    time: str = Field(min_length=1,max_length=120)
    @model_validator(mode='after')
    def nonblank(self):
        self.title=self.title.strip(); self.time=self.time.strip()
        if not self.title or not self.time: raise ValueError('事项名称和时间不能为空')
        return self
class ApplicationInput(BaseModel):
    reason: str = Field(min_length=1,max_length=4000)
    starts: date
    ends: date
    layout: Literal['combined','separate']='combined'
    items: list[ItemInput] = Field(min_length=1,max_length=30)
    idempotency_key: str = Field(min_length=8,max_length=80)
    @model_validator(mode='after')
    def valid_dates(self):
        self.reason=self.reason.strip()
        if not self.reason: raise ValueError('请填写请假原因')
        if self.ends < self.starts: raise ValueError('结束日期不能早于开始日期')
        if any(not self.starts<=i.day<=self.ends for i in self.items): raise ValueError('事项日期须在请假起止日期内')
        return self

def serialize(db,row):
    approval=db.get(Decision,row.id)
    return {'id':row.id,'student':row.snapshot,'reason':row.reason,'starts':row.starts,'ends':row.ends,'layout':row.layout,'status':row.status,'file_status':row.file_status,'generation_error':row.generation_error,'created':row.created,
      'items':[{'kind':i.kind,'title':i.title,'day':i.day,'time':i.time} for i in db.scalars(select(Item).where(Item.request_id==row.id).order_by(Item.position))],
      'approval':{'approver':approval.approver_name,'outcome':approval.outcome,'opinion':approval.opinion,'at':approval.at} if approval else None,
      'documents':[{'id':d.id,'name':d.name,'sha256':d.digest} for d in db.scalars(select(Document).where(Document.request_id==row.id).order_by(Document.position))]}
@app.post('/api/requests',status_code=201)
def submit(body:ApplicationInput, db:Session=Depends(db_session),user:Person=Depends(current_user)):
    if user.role!='student': raise HTTPException(403,'仅学生可提交申请')
    if not user.counselor: raise HTTPException(409,'尚未分配辅导员')
    payload=body.model_dump(mode='json'); payload.pop('idempotency_key')
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    old=db.scalar(select(Request).where(Request.student_id==user.id,Request.idempotency_key==body.idempotency_key))
    if old:
        if old.payload_hash!=digest: raise HTTPException(409,'重复提交标识已用于不同内容')
        return serialize(db,old)
    row=Request(id=str(uuid.uuid4()),student_id=user.id,counselor_id=user.counselor,idempotency_key=body.idempotency_key,payload_hash=digest,snapshot={'name':user.name,**user.profile},reason=body.reason,starts=str(body.starts),ends=str(body.ends),layout=body.layout,created=datetime.now(timezone.utc).isoformat())
    try:
        db.add(row); db.flush()
        for pos,item in enumerate(body.items):
            db.add(Item(id=str(uuid.uuid4()),request_id=row.id,position=pos,kind=item.kind,title=item.title,day=str(item.day),time=item.time))
        db.commit()
    except IntegrityError:
        db.rollback()
        old=db.scalar(select(Request).where(Request.student_id==user.id,Request.idempotency_key==body.idempotency_key))
        if not old or old.payload_hash!=digest: raise HTTPException(409,'提交冲突，请刷新')
        return serialize(db,old)
    return serialize(db,row)
@app.get('/api/requests')
def listing(db:Session=Depends(db_session),user:Person=Depends(current_user)):
    query=select(Request).where(Request.student_id==user.id if user.role=='student' else Request.counselor_id==user.id).order_by(Request.created.desc())
    return [serialize(db,row) for row in db.scalars(query)]
@app.get('/api/requests/{rid}')
def detail(rid:str,db:Session=Depends(db_session),user:Person=Depends(current_user)):
    return serialize(db,authorized(db,rid,user))

font_lock=threading.Lock()
def font_name():
    with font_lock:
        if 'LeaveChinese' in pdfmetrics.getRegisteredFontNames(): return 'LeaveChinese'
        candidates=[os.getenv('PDF_FONT_PATH',''),'/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc','/System/Library/Fonts/STHeiti Light.ttc']
        for path in candidates:
            if path and Path(path).is_file():
                pdfmetrics.registerFont(TTFont('LeaveChinese',path)); return 'LeaveChinese'
        raise RuntimeError('未找到可嵌入的中文字体，请配置 PDF_FONT_PATH')
def render_pdf(row,decision,items):
    font=font_name(); output=io.BytesIO()
    style=ParagraphStyle('body',fontName=font,fontSize=11,leading=18,wordWrap='CJK',spaceAfter=9)
    title=ParagraphStyle('title',parent=style,fontSize=23,leading=30,spaceAfter=18)
    p=lambda text: Paragraph(escape(str(text)).replace('\n','<br/>'),style)
    story=[Paragraph('请假条',title),p('本地演示 · 非正式凭证'),p('姓名：'+row.snapshot['name']+'　学号：'+row.snapshot['student_number']),p('学院：'+row.snapshot['college']+'　专业：'+row.snapshot['major']+'　年级：'+row.snapshot['grade']),p('请假期间：'+row.starts+' 至 '+row.ends),p('请假原因：'+row.reason),Spacer(1,4*mm)]
    names={'course':'课程','activity':'活动','other':'其他'}
    table=[[p('类型'),p('请假事项'),p('日期 / 时间')]]
    for item in items: table.append([p(names[item.kind]),p(item.title),p(item.day+'\n'+item.time)])
    t=Table(table,colWidths=[20*mm,83*mm,65*mm],repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e7edf6')),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#cbd5e1')),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
    story.extend([t,Spacer(1,8*mm),p('审批人：'+decision.approver_name),p('审批时间：'+datetime.fromisoformat(decision.at).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M（北京时间）')),p('审批意见：'+(decision.opinion or '同意')),p('申请记录：'+row.id)])
    SimpleDocTemplate(output,pagesize=(210*mm,297*mm),leftMargin=21*mm,rightMargin=21*mm,topMargin=20*mm,bottomMargin=20*mm,title='请假条（演示）').build(story)
    return output.getvalue()
def generate(rid):
    with Session(engine) as db:
        claimed=db.execute(update(Request).where(Request.id==rid,Request.status=='approved',Request.file_status.in_(['not_started','failed'])).values(file_status='generating',generation_error=None)).rowcount
        db.commit()
        if not claimed: return
        try:
            row=db.get(Request,rid); decision=db.get(Decision,rid)
            items=list(db.scalars(select(Item).where(Item.request_id==rid).order_by(Item.position)))
            groups=[items] if row.layout=='combined' else [[i] for i in items]
            for pos,group in enumerate(groups):
                data=render_pdf(row,decision,group)
                db.add(Document(id=str(uuid.uuid4()),request_id=rid,position=pos,name=f'leave-{pos+1}.pdf',content=data,digest=hashlib.sha256(data).hexdigest()))
            row.file_status='ready'; db.commit()
        except Exception:
            db.rollback()
            db.execute(update(Request).where(Request.id==rid).values(file_status='failed',generation_error='审批已通过，文件生成失败。请检查中文字体与服务日志后重试。'))
            db.commit()
            logging.getLogger(__name__).exception('PDF generation failed for request %s',rid)
class DecisionInput(BaseModel):
    outcome:Literal['approved','rejected']
    opinion:str=Field(default='',max_length=2000)
    @model_validator(mode='after')
    def rejection_reason(self):
        self.opinion=self.opinion.strip()
        if self.outcome=='rejected' and not self.opinion: raise ValueError('驳回时须填写原因')
        return self
@app.post('/api/requests/{rid}/decision')
def decide(rid:str,body:DecisionInput,db:Session=Depends(db_session),user:Person=Depends(current_user)):
    row=authorized(db,rid,user)
    if user.role!='counselor': raise HTTPException(403,'仅负责该学生的辅导员可审批')
    if row.status!='pending':
        old=db.get(Decision,rid)
        if old.outcome==body.outcome and old.opinion==body.opinion: return serialize(db,row)
        raise HTTPException(409,'该申请已经审批，不能更改')
    changed=db.execute(update(Request).where(Request.id==rid,Request.status=='pending').values(status=body.outcome)).rowcount
    if not changed: db.rollback(); raise HTTPException(409,'申请已由另一个请求处理，请刷新')
    db.add(Decision(request_id=rid,approver_id=user.id,approver_name=user.name,outcome=body.outcome,opinion=body.opinion,at=datetime.now(timezone.utc).isoformat()))
    db.commit()
    if body.outcome=='approved': generate(rid)
    db.expire_all()
    return serialize(db,db.get(Request,rid))
@app.post('/api/requests/{rid}/retry')
def retry(rid:str,db:Session=Depends(db_session),user:Person=Depends(current_user)):
    row=authorized(db,rid,user)
    if row.status!='approved': raise HTTPException(409,'只有已通过的申请可生成文件')
    generate(rid); db.expire_all()
    return serialize(db,db.get(Request,rid))
@app.get('/api/documents/{did}')
def download(did:str,db:Session=Depends(db_session),user:Person=Depends(current_user)):
    doc=db.get(Document,did)
    if not doc: raise HTTPException(404,'文件不存在')
    row=authorized(db,doc.request_id,user)
    if row.status!='approved' or row.file_status!='ready': raise HTTPException(409,'文件尚未就绪')
    return Response(doc.content,media_type='application/pdf',headers={'Content-Disposition':f'inline; filename="{doc.name}"','Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
@app.middleware('http')
async def no_cache(request,call_next):
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    return response
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
@app.get('/')
def index(): return FileResponse(ROOT/'static/index.html')
