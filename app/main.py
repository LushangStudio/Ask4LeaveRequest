"""Operator-configured leave workflow. Demo identity remains loopback-only."""
import hashlib
import io
import json
import logging
import os
import secrets
import threading
import uuid
import base64
import binascii
import warnings
import hmac
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, Request as HTTPRequest
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import (JSON, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, func,
                        create_engine, select, update, event)
from sqlalchemy.dialects.mysql import MEDIUMBLOB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.platypus import Image as PDFImage, KeepTogether
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
from app.directory import read_directories, DirectoryConfig
from app.student_import import preview_import
from app.leave_dates import leave_end_limit
from app.test_login import TestQueryRedaction, load_test_login
from app.uis import UISSettings, UISOAuthClient, OAuthProviderError

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv('LEAVE_DATA_DIR', str(ROOT/'var'))).resolve()
URL = os.getenv('DATABASE_URL', f'sqlite:///{DATA_DIR/"leave.db"}')
if URL.startswith('sqlite'): DATA_DIR.mkdir(parents=True,exist_ok=True)
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

class TestLoginSession(Base):
    __tablename__ = 'test_login_sessions'
    token_hash: Mapped[str] = mapped_column(ForeignKey('demo_sessions.token_hash',ondelete='CASCADE'), primary_key=True)
    secret_digest: Mapped[str] = mapped_column(String(64))

class UISLoginSession(Base):
    __tablename__ = 'uis_login_sessions'
    token_hash: Mapped[str] = mapped_column(ForeignKey('demo_sessions.token_hash',ondelete='CASCADE'), primary_key=True)
    user_type: Mapped[str] = mapped_column(String(80))

class OAuthState(Base):
    __tablename__ = 'oauth_states'
    state_hash: Mapped[str] = mapped_column(String(64),primary_key=True)
    expires: Mapped[datetime] = mapped_column(DateTime,index=True)
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
class Withdrawal(Base):
    __tablename__ = 'request_withdrawals'
    request_id: Mapped[str] = mapped_column(ForeignKey('leave_requests.id'), primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('people.id'))
    actor_name: Mapped[str] = mapped_column(String(80))
    actor_role: Mapped[str] = mapped_column(String(20))
    prior_status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    at: Mapped[str] = mapped_column(String(40))
class DirectoryAudit(Base):
    __tablename__ = 'directory_audits'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('people.id'))
    actor_name: Mapped[str] = mapped_column(String(80))
    before_digest: Mapped[str] = mapped_column(String(64))
    after_digest: Mapped[str] = mapped_column(String(64))
    counts: Mapped[dict] = mapped_column(JSON)
    at: Mapped[str] = mapped_column(String(40))
class DirectoryState(Base):
    __tablename__ = 'class_directory'
    id: Mapped[int] = mapped_column(Integer,primary_key=True)
    directory: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    updated: Mapped[str] = mapped_column(String(40))

def directory_digest(directory):
    return hashlib.sha256(json.dumps(directory,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
class Document(Base):
    __tablename__ = 'generated_documents'
    __table_args__ = (UniqueConstraint('request_id', 'position'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey('leave_requests.id'), index=True)
    position: Mapped[int]
    name: Mapped[str] = mapped_column(String(100))
    content: Mapped[bytes] = mapped_column(LargeBinary().with_variant(MEDIUMBLOB(), 'mysql'))
    digest: Mapped[str] = mapped_column(String(64))

class DirectoryMember(Base):
    __tablename__ = 'directory_members'
    person_id: Mapped[str] = mapped_column(ForeignKey('people.id'), primary_key=True)

class RequestCounselor(Base):
    __tablename__ = 'request_counselors'
    request_id: Mapped[str] = mapped_column(ForeignKey('leave_requests.id'), primary_key=True)
    counselor_id: Mapped[str] = mapped_column(ForeignKey('people.id'), primary_key=True, index=True)

class Signature(Base):
    __tablename__ = 'counselor_signatures'
    counselor_id: Mapped[str] = mapped_column(ForeignKey('people.id'), primary_key=True)
    version: Mapped[str] = mapped_column(String(36))
    content: Mapped[bytes] = mapped_column(LargeBinary().with_variant(MEDIUMBLOB(), 'mysql'))
    digest: Mapped[str] = mapped_column(String(64))
    updated: Mapped[str] = mapped_column(String(40))

class ApprovalSignature(Base):
    __tablename__ = 'approval_signatures'
    request_id: Mapped[str] = mapped_column(ForeignKey('approval_records.request_id'), primary_key=True)
    signature_version: Mapped[str] = mapped_column(String(36))
    content: Mapped[bytes] = mapped_column(LargeBinary().with_variant(MEDIUMBLOB(), 'mysql'))
    digest: Mapped[str] = mapped_column(String(64))
    watermark: Mapped[str] = mapped_column(String(160))

class ApprovalPreview(Base):
    __tablename__ = 'approval_previews'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey('leave_requests.id'), index=True)
    counselor_id: Mapped[str] = mapped_column(ForeignKey('people.id'))
    signature_version: Mapped[str] = mapped_column(String(36))
    signature_content: Mapped[bytes] = mapped_column(LargeBinary().with_variant(MEDIUMBLOB(), 'mysql'))
    watermark: Mapped[str] = mapped_column(String(160))
    opinion: Mapped[str] = mapped_column(Text)
    at: Mapped[str] = mapped_column(String(40))
    expires: Mapped[datetime] = mapped_column(DateTime, index=True)

def sync_directory(db, roster, commit=True):
    classes = {c.class_id:c for c in roster.classes}
    student_ids={s.user_id for s in roster.students}
    counselor_ids={c.user_id for c in roster.counselors}
    people = [(c.user_id, c.name, 'counselor', None, {}) for c in roster.counselors if c.user_id not in student_ids]
    people += [(s.user_id, s.name, 'both' if s.user_id in counselor_ids else 'student', classes[s.class_id].counselor_ids[0],
                {'college': s.college, 'major': s.major, 'grade': s.grade, 'student_number': s.user_id,
                 'class_id':s.class_id,'class_name':classes[s.class_id].name,
                 'counselor_ids':classes[s.class_id].counselor_ids}) for s in roster.students]
    active = {p[0] for p in people}
    admins=app.state.admin_ids
    active |= admins
    for pid in admins-student_ids-counselor_ids:
        existing=db.get(Person,pid)
        people.append((pid,existing.name if existing else pid,'admin',None,{}))
    for pid, name, role, counselor, profile in people:
        person = db.get(Person, pid)
        if person and person.role != role and not {'both','admin'} & {person.role,role}:
            raise RuntimeError('Cannot change an existing directory identity role')
        if person:
            person.name, person.role, person.counselor, person.profile = name, role, counselor, profile
        else:
            db.add(Person(id=pid, name=name, role=role, counselor=counselor, profile=profile))
        db.flush()
        if not db.get(DirectoryMember, pid): db.add(DirectoryMember(person_id=pid))
    for member in db.scalars(select(DirectoryMember)):
        if member.person_id not in active: db.delete(member)
    # Historical people and request/approval snapshots remain intact; removed identities lose access.
    if commit:db.commit()

@asynccontextmanager
async def lifespan(app):
    mode = os.getenv('APP_MODE','disabled')
    if mode not in {'demo','test','production'}:
        raise RuntimeError('Set APP_MODE to demo, test or production')
    uis=UISSettings.from_env()
    if mode=='production':
        if not uis.configured:raise RuntimeError('UIS/ehall authentication is not configured')
        if any(urlsplit(url).scheme!='https' or not urlsplit(url).hostname for url in [uis.authorization_url,uis.token_url,uis.user_info_url,uis.logout_url,uis.redirect_uri,uis.frontend_url]):
            raise RuntimeError('Production UIS endpoints and frontend must use HTTPS')
    test_config=load_test_login(os.getenv('TEST_LOGIN_CONFIG_PATH'))
    admins={s.strip() for s in os.getenv('ADMIN_USER_IDS','').split(',') if s.strip()}
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',s) for s in admins):raise RuntimeError('Invalid ADMIN_USER_IDS configuration')
    app.state.admin_ids=admins
    cookie_path=os.getenv('SESSION_COOKIE_PATH','/')
    if not cookie_path.startswith('/') or not cookie_path.endswith('/') or cookie_path.startswith('//') or any(c in cookie_path for c in '?\\#\r\n'):
        raise RuntimeError('Invalid session cookie / application base path')
    app.state.test_login_config=test_config
    app.state.uis_settings=uis
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        state=db.get(DirectoryState,1)
        if state is None:
            # JSON fixtures only bootstrap a new local demo/test database. Production never reads roster files.
            if mode=='production':roster=DirectoryConfig(version=1,counselors=[],classes=[],students=[])
            else:
                default_roster=ROOT/'config'/('relationships.test.json' if mode=='test' else 'relationships.example.json')
                try:roster=read_directories(os.getenv('RELATIONSHIPS_PATH',str(default_roster)),os.getenv('TEST_RELATIONSHIPS_PATH'))
                except Exception:raise RuntimeError('Invalid local fixture directory configuration') from None
            data=roster.model_dump()
            state=DirectoryState(id=1,directory=data,digest=directory_digest(data),updated=datetime.now(timezone.utc).isoformat());db.add(state)
        else:roster=DirectoryConfig.model_validate(state.directory)
        if mode=='test' and (any(not p.user_id.startswith('test-') for p in roster.counselors+roster.students) or any(not c.class_id.startswith('test-') for c in roster.classes)):
            raise RuntimeError('Test mode accepts only test- identities and test- classes')
        sync_directory(db, roster)
        # Additive migration for legacy requests; do not rewrite historical approvals.
        for row in db.scalars(select(Request).where(~select(RequestCounselor).where(RequestCounselor.request_id==Request.id).exists())):
            db.add(RequestCounselor(request_id=row.id,counselor_id=row.counselor_id))
        db.query(ApprovalPreview).filter(ApprovalPreview.expires < datetime.now(timezone.utc).replace(tzinfo=None)).delete()
        db.query(OAuthState).filter(OAuthState.expires < datetime.now(timezone.utc).replace(tzinfo=None)).delete()
        # A stopped process may leave a job in progress. Mark it retryable on demo restart.
        db.execute(update(Request).where(Request.file_status=='generating').values(file_status='failed', generation_error='生成被中断，请重试'))
        db.commit()
    yield
app = FastAPI(title='Ask4LeaveRequest',lifespan=lifespan)
def db_session():
    with Session(engine) as db: yield db
def current_user(leave_session: str | None = Cookie(default=None), db:Session=Depends(db_session)):
    login=db.get(Login,hashlib.sha256((leave_session or '').encode()).hexdigest())
    if not login or login.expires < datetime.now(timezone.utc).replace(tzinfo=None): raise HTTPException(401,'请先登录')
    if not db.get(DirectoryMember, login.person_id): raise HTTPException(403,'该身份已停用，请联系管理员')
    tagged=db.get(TestLoginSession,login.token_hash)
    if tagged or os.getenv('APP_MODE')=='test':
        config=app.state.test_login_config
        if not tagged or not config.enabled or not login.person_id.startswith('test-') or not hmac.compare_digest(tagged.secret_digest,config.secret_digest()):
            raise HTTPException(401,'测试登录已关闭或已失效，请重新登录')
    elif os.getenv('APP_MODE')=='production' and not db.get(UISLoginSession,login.token_hash):
        raise HTTPException(401,'请使用复旦UIS重新登录')
    return db.get(Person, login.person_id)

def cookie_secure():
    return os.getenv('APP_MODE')=='production' or os.getenv('SESSION_COOKIE_SECURE','false').lower()=='true'

def remove_login(db,token):
    digest=hashlib.sha256((token or '').encode()).hexdigest()
    old=db.get(Login,digest)
    if old:
        for model in [TestLoginSession,UISLoginSession]:
            tag=db.get(model,digest)
            if tag:db.delete(tag)
        db.flush();db.delete(old)

def establish_login(db, person_id, response, old_token=None, test_digest=None,uis_type=None):
    remove_login(db,old_token)
    token=secrets.token_urlsafe(32)
    digest=hashlib.sha256(token.encode()).hexdigest()
    ttl=app.state.uis_settings.session_ttl
    db.add(Login(token_hash=digest,person_id=person_id,expires=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(seconds=ttl)))
    db.flush()
    if test_digest:db.add(TestLoginSession(token_hash=digest,secret_digest=test_digest))
    if uis_type is not None:db.add(UISLoginSession(token_hash=digest,user_type=uis_type[:80]))
    db.commit()
    response.set_cookie('leave_session',token,httponly=True,samesite='strict',max_age=ttl,
                        secure=cookie_secure(),path=os.getenv('SESSION_COOKIE_PATH','/'))
def authorized(db, rid, user):
    row=db.get(Request,rid)
    if not row or not (has_role(user,'student') and row.student_id==user.id or has_role(user,'counselor') and db.get(RequestCounselor,(rid,user.id))):
        raise HTTPException(404,'申请不存在或无权查看')
    return row
def has_role(user,role):return user.role in {role,'both'}
def user_roles(user):return [r for r in ['student','counselor'] if has_role(user,r)]
def is_admin(user):return user.id in app.state.admin_ids
def require_admin(user):
    if not is_admin(user):raise HTTPException(403,'仅管理员可管理班级')
class LoginInput(BaseModel):
    person_id: str
@app.post('/api/demo/login')
def login(body:LoginInput,response:Response,leave_session:str|None=Cookie(default=None),db:Session=Depends(db_session)):
    if os.getenv('APP_MODE') != 'demo': raise HTTPException(404,'演示登录未启用')
    if not db.get(DirectoryMember,body.person_id): raise HTTPException(400,'无效演示身份')
    establish_login(db,body.person_id,response,leave_session)
    return {'ok':True}
@app.post('/api/logout')
def logout(response:Response, leave_session:str|None=Cookie(default=None),db:Session=Depends(db_session)):
    remove_login(db,leave_session);db.commit()
    response.delete_cookie('leave_session',path=os.getenv('SESSION_COOKIE_PATH','/'),
                           secure=cookie_secure(),httponly=True,samesite='strict')
    return {'ok':True}
@app.get('/api/me')
def me(user:Person=Depends(current_user),leave_session:str|None=Cookie(default=None),db:Session=Depends(db_session)):
    digest=hashlib.sha256((leave_session or '').encode()).hexdigest()
    uis=db.get(UISLoginSession,digest)
    return {'id':user.id,'name':user.name,'role':user.role,'roles':user_roles(user),'is_admin':is_admin(user),'profile':user.profile,
            'auth_provider':'uis' if uis else 'test' if db.get(TestLoginSession,digest) else 'demo',
            'user_type':uis.user_type if uis else None}
@app.get('/api/health')
def health(): return {'status':'ok','mode':os.getenv('APP_MODE','disabled')}

@app.get('/api/runtime')
def runtime():
    return {'mode':os.getenv('APP_MODE','disabled'),'demo_login':os.getenv('APP_MODE')=='demo',
            'uis_login':os.getenv('APP_MODE')=='production' and app.state.uis_settings.configured,
            'app_list_url':os.getenv('APP_LIST_URL','/'),'max_end_date':leave_end_limit().isoformat()}

def get_uis_oauth_client():return UISOAuthClient(app.state.uis_settings)

def require_uis():
    if os.getenv('APP_MODE')!='production' or not app.state.uis_settings.configured:
        raise HTTPException(503,'UIS登录未配置')
    return app.state.uis_settings

def uis_state_cookie_path():
    # Callback can be outside the application's session-cookie path.
    path=os.getenv('UIS_STATE_COOKIE_PATH',os.getenv('SESSION_COOKIE_PATH','/'))
    if not path.startswith('/') or not path.endswith('/') or path.startswith('//') or any(c in path for c in '?\\#\r\n'):
        raise RuntimeError('Invalid UIS state cookie path')
    return path

@app.get('/api/auth/login')
def uis_login(leave_oauth_state:str|None=Cookie(default=None),db:Session=Depends(db_session),client=Depends(get_uis_oauth_client)):
    settings=require_uis()
    if leave_oauth_state:
        old=db.get(OAuthState,hashlib.sha256(leave_oauth_state.encode()).hexdigest())
        if old:db.delete(old)
    # Namespace only routes the shared callback; the full nonce is still validated below.
    nonce='ask4leave.'+secrets.token_urlsafe(32)
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    db.query(OAuthState).filter(OAuthState.expires < now).delete()
    db.add(OAuthState(state_hash=hashlib.sha256(nonce.encode()).hexdigest(),expires=now+timedelta(seconds=settings.state_ttl)));db.commit()
    response=RedirectResponse(client.build_authorization_url(nonce),status_code=302)
    response.set_cookie('leave_oauth_state',nonce,httponly=True,samesite='lax',secure=cookie_secure(),
                        max_age=settings.state_ttl,path=uis_state_cookie_path())
    return response

@app.get('/api/auth/callback')
async def uis_callback(code:str,state:str|None=None,leave_oauth_state:str|None=Cookie(default=None),
                       leave_session:str|None=Cookie(default=None),db:Session=Depends(db_session),client=Depends(get_uis_oauth_client)):
    settings=require_uis()
    if not state or not leave_oauth_state or not hmac.compare_digest(state.encode(),leave_oauth_state.encode()):
        raise HTTPException(400,'UIS登录状态无效或已过期')
    digest=hashlib.sha256(state.encode()).hexdigest()
    claimed=db.query(OAuthState).filter(OAuthState.state_hash==digest,OAuthState.expires>=datetime.now(timezone.utc).replace(tzinfo=None)).delete()
    db.commit()
    if claimed!=1:raise HTTPException(400,'UIS登录状态无效或已过期')
    try:
        token=await client.exchange_code(code)
        user=await client.fetch_user_info(token.access_token)
    except OAuthProviderError:raise HTTPException(502,'UIS身份认证失败') from None
    # No undergraduate/type allowlist: the operator roster alone determines application roles.
    person=db.get(Person,user.user_id)
    if not person or not db.get(DirectoryMember,user.user_id):raise HTTPException(403,'尚未配置班级或辅导员关系，请联系管理员')
    if person.role=='admin':person.name=user.user_name[:80];db.commit()
    response=RedirectResponse(settings.frontend_url,status_code=303)
    establish_login(db,user.user_id,response,leave_session,uis_type=user.user_type)
    response.delete_cookie('leave_oauth_state',path=uis_state_cookie_path(),secure=cookie_secure(),httponly=True,samesite='lax')
    return response

@app.post('/api/auth/logout')
def uis_logout(leave_session:str|None=Cookie(default=None),db:Session=Depends(db_session),user:Person=Depends(current_user)):
    settings=require_uis()
    if not db.get(UISLoginSession,hashlib.sha256((leave_session or '').encode()).hexdigest()):
        raise HTTPException(403,'当前不是UIS登录')
    remove_login(db,leave_session);db.commit()
    import httpx
    url=str(httpx.URL(settings.logout_url).copy_merge_params({'redirectToLogin':'true','redirectToUrl':settings.frontend_url}))
    response=RedirectResponse(url,status_code=303)
    response.delete_cookie('leave_session',path=os.getenv('SESSION_COOKIE_PATH','/'),secure=cookie_secure(),httponly=True,samesite='strict')
    return response

@app.get('/api/auth/sso-logout',status_code=204)
def uis_sso_logout(leave_session:str|None=Cookie(default=None),db:Session=Depends(db_session)):
    remove_login(db,leave_session);db.commit()
    response=Response(status_code=204)
    response.delete_cookie('leave_session',path=os.getenv('SESSION_COOKIE_PATH','/'),secure=cookie_secure(),httponly=True,samesite='strict')
    return response

@app.get('/api/demo/identities')
def demo_identities(db:Session=Depends(db_session)):
    if os.getenv('APP_MODE') != 'demo': raise HTTPException(404)
    return [{'id':p.id,'name':p.name,'role':p.role} for p in db.scalars(select(Person).join(DirectoryMember))]

def require_counselor(user):
    if not has_role(user,'counselor'): raise HTTPException(403,'仅辅导员可管理签名和预览审批')

class SignatureInput(BaseModel):
    image: str = Field(max_length=4_200_000)

def normalize_signature(encoded):
    try:
        raw = base64.b64decode(encoded, validate=True)
        if not raw or len(raw) > 3 * 1024 * 1024: raise ValueError()
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {'PNG','JPEG','WEBP'} or getattr(image,'n_frames',1) != 1: raise ValueError()
                if image.width < 16 or image.height < 16 or image.width * image.height > 12_000_000: raise ValueError()
                image.load()
                clean = image.convert('RGBA')
                clean.thumbnail((1200,600),Image.Resampling.LANCZOS)
                white = Image.new('RGBA',clean.size,'white'); white.alpha_composite(clean)
                output = io.BytesIO(); white.convert('RGB').save(output,format='PNG')
                return output.getvalue()
    except (ValueError, binascii.Error, OSError, UnidentifiedImageError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise HTTPException(422,'签名必须是有效的 PNG、JPEG 或 WebP 静态图片，最大 3 MiB、1200 万像素，裁切尺寸至少 16×16') from None

@app.post('/api/signature')
def upload_signature(body:SignatureInput,db:Session=Depends(db_session),user:Person=Depends(current_user)):
    require_counselor(user)
    data = normalize_signature(body.image)
    record = db.scalar(select(Signature).where(Signature.counselor_id==user.id).with_for_update())
    if not record: record=Signature(counselor_id=user.id); db.add(record)
    record.version, record.content, record.digest, record.updated = str(uuid.uuid4()),data,hashlib.sha256(data).hexdigest(),datetime.now(timezone.utc).isoformat()
    db.commit()
    return {'version':record.version,'updated':record.updated}

@app.get('/api/signature')
def signature_info(db:Session=Depends(db_session),user:Person=Depends(current_user)):
    require_counselor(user)
    record=db.get(Signature,user.id)
    return {'configured':bool(record),'version':record.version if record else None,'updated':record.updated if record else None}

@app.get('/api/signature/image')
def signature_image(db:Session=Depends(db_session),user:Person=Depends(current_user)):
    require_counselor(user)
    record=db.get(Signature,user.id)
    if not record: raise HTTPException(404,'尚未上传签名')
    return Response(record.content,media_type='image/png')
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
        limit=leave_end_limit()
        if self.ends>limit:raise ValueError(f'请假结束日期不得超过当前日期后三个月（最晚 {limit}）')
        if any(not self.starts<=i.day<=self.ends for i in self.items): raise ValueError('事项日期须在请假起止日期内')
        return self

def serialize(db,row):
    approval=db.get(Decision,row.id)
    withdrawal=db.get(Withdrawal,row.id)
    return {'id':row.id,'student':row.snapshot,'reason':row.reason,'starts':row.starts,'ends':row.ends,'layout':row.layout,'status':row.status,'file_status':row.file_status,'generation_error':row.generation_error,'created':row.created,
      'items':[{'kind':i.kind,'title':i.title,'day':i.day,'time':i.time} for i in db.scalars(select(Item).where(Item.request_id==row.id).order_by(Item.position))],
      'approval':{'approver':approval.approver_name,'outcome':approval.outcome,'opinion':approval.opinion,'at':approval.at} if approval else None,
      'withdrawal':{'actor':withdrawal.actor_name,'role':withdrawal.actor_role,'reason':withdrawal.reason,'at':withdrawal.at} if withdrawal else None,
      'documents':[{'id':d.id,'name':d.name,'sha256':d.digest} for d in db.scalars(select(Document).where(Document.request_id==row.id).order_by(Document.position))] if row.status=='approved' else []}
@app.post('/api/requests',status_code=201)
def submit(body:ApplicationInput, db:Session=Depends(db_session),user:Person=Depends(current_user)):
    if not has_role(user,'student'): raise HTTPException(403,'仅学生可提交申请')
    counselors = user.profile.get('counselor_ids',[])
    if not counselors or not all(db.get(DirectoryMember,c) for c in counselors): raise HTTPException(409,'尚未分配有效班级辅导员，请联系管理员')
    payload=body.model_dump(mode='json'); payload.pop('idempotency_key')
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    old=db.scalar(select(Request).where(Request.student_id==user.id,Request.idempotency_key==body.idempotency_key))
    if old:
        if old.payload_hash!=digest: raise HTTPException(409,'重复提交标识已用于不同内容')
        return serialize(db,old)
    row=Request(id=str(uuid.uuid4()),student_id=user.id,counselor_id=user.counselor,idempotency_key=body.idempotency_key,payload_hash=digest,snapshot={'name':user.name,**user.profile},reason=body.reason,starts=str(body.starts),ends=str(body.ends),layout=body.layout,created=datetime.now(timezone.utc).isoformat())
    try:
        db.add(row); db.flush()
        for counselor_id in counselors:
            db.add(RequestCounselor(request_id=row.id,counselor_id=counselor_id))
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
def listing(view:Literal['student','counselor']|None=None,db:Session=Depends(db_session),user:Person=Depends(current_user)):
    if not user_roles(user) and view is None:return []
    role=view or ('student' if has_role(user,'student') else 'counselor')
    if not has_role(user,role):raise HTTPException(403,'无此工作台身份')
    scope = Request.student_id==user.id if role=='student' else select(RequestCounselor).where(RequestCounselor.request_id==Request.id,RequestCounselor.counselor_id==user.id).exists()
    query=select(Request).where(scope).order_by(Request.created.desc())
    return [serialize(db,row) for row in db.scalars(query)]
@app.get('/api/requests/{rid}')
def detail(rid:str,db:Session=Depends(db_session),user:Person=Depends(current_user)):
    return serialize(db,authorized(db,rid,user))

@app.get('/api/admin/directory')
def admin_directory(db:Session=Depends(db_session),user:Person=Depends(current_user)):
    require_admin(user)
    state=db.get(DirectoryState,1)
    if not state:raise HTTPException(503,'班级数据库尚未初始化')
    return {'directory':state.directory,'revision':state.digest}

class DirectoryUpdate(BaseModel):
    directory:DirectoryConfig
    revision:str=Field(pattern=r'^[a-f0-9]{64}$')

@app.post('/api/admin/directory')
def save_admin_directory(body:DirectoryUpdate,db:Session=Depends(db_session),user:Person=Depends(current_user)):
    require_admin(user)
    data=body.directory.model_dump();digest=directory_digest(data)
    try:
        changed=db.execute(update(DirectoryState).where(DirectoryState.id==1,DirectoryState.digest==body.revision).values(directory=data,digest=digest,updated=datetime.now(timezone.utc).isoformat())).rowcount
        if not changed:db.rollback();raise HTTPException(409,'名单已被其他管理员修改，请刷新后重新编辑')
        try:sync_directory(db,body.directory,commit=False)
        except RuntimeError:
            db.rollback();raise HTTPException(409,'已有单一身份不能直接互换；可先配置学生兼辅导员身份') from None
        db.add(DirectoryAudit(id=str(uuid.uuid4()),actor_id=user.id,actor_name=user.name,before_digest=body.revision,after_digest=digest,
                              counts={'classes':len(data['classes']),'counselors':len(data['counselors']),'students':len(data['students'])},at=datetime.now(timezone.utc).isoformat()))
        db.commit()
        return {'directory':data,'revision':digest}
    except HTTPException:raise
    except Exception:
        db.rollback();logging.getLogger(__name__).exception('Admin directory save failed')
        raise HTTPException(503,'名单保存失败，已回滚，请稍后重试') from None

class StudentImportInput(BaseModel):
    text:str=Field(min_length=1,max_length=2_000_000)
    revision:str=Field(pattern=r'^[a-f0-9]{64}$')

def prepare_student_import(body,db,user):
    require_admin(user)
    state=db.get(DirectoryState,1)
    if not state or state.digest!=body.revision:raise HTTPException(409,'名单已变化，请刷新后重新导入')
    return preview_import(body.text,DirectoryConfig.model_validate(state.directory))

@app.post('/api/admin/students/import/preview')
def student_import_preview(body:StudentImportInput,db:Session=Depends(db_session),user:Person=Depends(current_user)):
    result,_=prepare_student_import(body,db,user)
    return result

@app.post('/api/admin/students/import')
def import_students(body:StudentImportInput,db:Session=Depends(db_session),user:Person=Depends(current_user)):
    result,directory=prepare_student_import(body,db,user)
    if result['errors']:raise HTTPException(422,'批量导入有错误，请先修正全部错误行')
    saved=save_admin_directory(DirectoryUpdate(directory=directory,revision=body.revision),db,user)
    return {**saved,'created':result['created'],'updated':result['updated']}

font_lock=threading.Lock()
def font_path():
    candidates=[os.getenv('PDF_FONT_PATH',''),'/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc','/System/Library/Fonts/STHeiti Light.ttc']
    for path in candidates:
        if path and Path(path).is_file(): return path
    raise RuntimeError('未找到可嵌入的中文字体，请配置 PDF_FONT_PATH')

def font_name():
    with font_lock:
        if 'LeaveChinese' in pdfmetrics.getRegisteredFontNames(): return 'LeaveChinese'
        pdfmetrics.registerFont(TTFont('LeaveChinese',font_path())); return 'LeaveChinese'

def document_font(kind):
    name = 'LeaveDocumentBody' if kind == 'body' else 'LeaveDocumentHeading'
    override = os.getenv('PDF_BODY_FONT_PATH' if kind == 'body' else 'PDF_TITLE_FONT_PATH', '')
    candidates = ([override, '/usr/share/fonts/truetype/arphic/uming.ttc', '/System/Library/Fonts/Supplemental/Songti.ttc']
                  if kind == 'body' else [override, '/System/Library/Fonts/STHeiti Medium.ttc'])
    with font_lock:
        if name in pdfmetrics.getRegisteredFontNames(): return name
        path = next((path for path in candidates if path and Path(path).is_file()), font_path())
        # Apple's Songti collection starts with Black; index 6 is SC Regular.
        subfont = 6 if kind == 'body' and path == '/System/Library/Fonts/Supplemental/Songti.ttc' else 0
        pdfmetrics.registerFont(TTFont(name, path, subfontIndex=subfont))
    return name

def chinese_date(value):
    day = date.fromisoformat(value)
    return f'{day.year} 年 {day.month} 月 {day.day} 日'

def signature_watermark(row):
    days = (date.fromisoformat(row.ends)-date.fromisoformat(row.starts)).days+1
    return f"{row.snapshot['name']}-{row.starts}-{days}天"

def watermarked_signature(content,label):
    # Burn the restriction into image pixels; the PDF contains no unmarked source image.
    source=Image.open(io.BytesIO(content)).convert('RGBA')
    scale=min(1000/source.width,360/source.height)
    source=source.resize((round(source.width*scale),round(source.height*scale)),Image.Resampling.LANCZOS)
    canvas=Image.new('RGBA',(1100,420),'white')
    canvas.alpha_composite(source,((1100-source.width)//2,(420-source.height)//2))
    mask=Image.new('L',canvas.size,0); draw=ImageDraw.Draw(mask)
    font=ImageFont.truetype(font_path(),32)
    lines=[]; current=''
    for char in label:
        if draw.textlength(current+char,font=font)>1030:
            lines.append(current);current=''
        current+=char
    lines.append(current)
    for y in range(35,390,max(85,len(lines)*38+12)):
        for line_index,line in enumerate(lines):
            width=draw.textlength(line,font=font)
            draw.text(((1100-width)/2,y+line_index*38),line,font=font,fill=255)
    # Halftone text uses 3x3 black dots on a 4px grid, over a sparse black dot field.
    # All added pixels are opaque black; the pattern continues through the handwriting.
    # Global binary thresholding retains both handwriting and watermark dots.
    canvas=canvas.convert('RGB')
    target=canvas.load(); glyphs=mask.load()
    for y in range(canvas.height):
        for x in range(canvas.width):
            if (x%4<3 and y%4<3 and glyphs[x,y]>=96) or (x%4==0 and y%4==0):
                target[x,y]=(0,0,0)
    output=io.BytesIO();canvas.save(output,format='PNG');return output.getvalue()

def render_pdf(row,decision,items,signature=None,draft=False):
    body_font=document_font('body'); heading_font=document_font('heading'); output=io.BytesIO()
    body=ParagraphStyle('document-body',fontName=body_font,fontSize=14,leading=27,
                        firstLineIndent=28,alignment=TA_JUSTIFY,wordWrap='CJK',spaceAfter=12*mm)
    title=ParagraphStyle('document-title',fontName=heading_font,fontSize=27,leading=36,
                         alignment=TA_CENTER,spaceAfter=27*mm)
    closing=ParagraphStyle('document-closing',parent=body,spaceAfter=5*mm)
    cell=ParagraphStyle('document-cell',fontName=body_font,fontSize=10.5,leading=16,wordWrap='CJK')
    centered=ParagraphStyle('document-cell-center',parent=cell,alignment=TA_CENTER)
    signing=ParagraphStyle('document-signing',parent=body,fontSize=13,leading=22,
                           firstLineIndent=0,alignment=TA_RIGHT,spaceAfter=2*mm)
    def p(text,style=body):
        # Normalize typographic time-range dashes unsupported by some embedded CJK fonts.
        printable=str(text).translate(str.maketrans({'–':'-','—':'-','‑':'-','−':'-','－':'-'}))
        return Paragraph(escape(printable).replace('\n','<br/>'),style)
    student=row.snapshot
    class_text=f"；班级：{student['class_name']}" if student.get('class_name') else ''
    identity=(f"兹证明，复旦大学{student['college']}{student['major']}专业{student['grade']}级学生"
              f"{student['name']}（学号：{student['student_number']}{class_text}）。")
    days=(date.fromisoformat(row.ends)-date.fromisoformat(row.starts)).days+1
    period=chinese_date(row.starts) if row.starts==row.ends else f'{chinese_date(row.starts)}至{chinese_date(row.ends)}'
    reason=row.reason.strip().rstrip('。.!！?？;；')
    narrative=f"该生请假事由为{reason}。经辅导员审核，{'拟同意' if draft else '同意'}其于{period}请假，共 {days} 天。"
    names={'course':'课程','activity':'活动','other':'事项'}
    # A split document describes only its own item; only merged multiple items need a table.
    if len(items)==1:
        item=items[0]
        narrative+=f'本请假条适用于{chinese_date(item.day)}（{item.time}）的“{item.title}”{names[item.kind]}。'
    if decision.opinion and decision.opinion.strip() not in {'同意','同意。'}:
        narrative+=f'辅导员审批意见为：“{decision.opinion.strip().rstrip("。")}”。'
    story=[Paragraph('请 假 条',title),p(identity),p(narrative)]
    if len(items)>1:
        story.append(p('请假以下事项：',closing))
        rows=[[p('序号',centered),p('类型',centered),p('请假事项',centered),p('日期',centered),p('节次 / 时间',centered)]]
        for index,item in enumerate(items,1):
            rows.append([p(index,centered),p(names[item.kind],centered),p(item.title,cell),p(item.day,centered),p(item.time,cell)])
        table=Table(rows,colWidths=[12*mm,18*mm,66*mm,31*mm,29*mm],repeatRows=1,hAlign='CENTER')
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#f4f4f4')),
                                  ('GRID',(0,0),(-1,-1),.5,colors.HexColor('#555555')),
                                  ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                                  ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
                                  ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
        story.append(table)
    else:
        story.append(p('特此证明。',closing))
    image=(PDFImage(io.BytesIO(signature),width=62*mm,height=23.67*mm) if signature else p('历史审批未留存签名',cell))
    signature_row=Table([[p('辅导员签字：',signing),image]],colWidths=[41*mm,62*mm],hAlign='RIGHT')
    signature_row.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                                      ('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
    signed_at=datetime.fromisoformat(decision.at).astimezone(ZoneInfo('Asia/Shanghai'))
    story.append(KeepTogether([Spacer(1,23*mm),signature_row,p(decision.approver_name,signing),
                               Spacer(1,4*mm),p(f'{signed_at.year} 年 {signed_at.month} 月 {signed_at.day} 日',signing)]))

    def footer(canvas,doc):
        canvas.saveState();canvas.setFont(body_font,8);canvas.setFillColor(colors.HexColor('#777777'))
        label='审批前预览 · 尚未通过' if draft else ('本地演示 · 非正式凭证' if os.getenv('APP_MODE')!='production' or row.student_id.startswith('test-') else '')
        canvas.drawString(27*mm,15*mm,label)
        canvas.drawRightString(183*mm,15*mm,f'第 {doc.page} 页')
        canvas.setFont(body_font,7)
        canvas.drawString(27*mm,10*mm,'申请编号：'+row.id)
        canvas.restoreState()
    SimpleDocTemplate(output,pagesize=(210*mm,297*mm),leftMargin=25*mm,rightMargin=25*mm,
                      topMargin=24*mm,bottomMargin=26*mm,title='请假条',author=decision.approver_name).build(story,onFirstPage=footer,onLaterPages=footer)
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
            generated=[]
            for pos,group in enumerate(groups):
                signature=db.get(ApprovalSignature,rid)
                data=render_pdf(row,decision,group,signature.content if signature else None)
                generated.append(Document(id=str(uuid.uuid4()),request_id=rid,position=pos,name=f'{uuid.uuid4().hex}.pdf',content=data,digest=hashlib.sha256(data).hexdigest()))
            # Revocation can win while rendering; publish only if approval is still current.
            published=db.execute(update(Request).where(Request.id==rid,Request.status=='approved',Request.file_status=='generating').values(file_status='ready')).rowcount
            if not published:db.rollback();return
            db.add_all(generated);db.commit()
        except Exception:
            db.rollback()
            db.execute(update(Request).where(Request.id==rid,Request.status=='approved',Request.file_status=='generating').values(file_status='failed',generation_error='审批已通过，文件生成失败。请检查中文字体与服务日志后重试。'))
            db.commit()
            logging.getLogger(__name__).exception('PDF generation failed for request %s',rid)
class DecisionInput(BaseModel):
    outcome:Literal['approved','rejected']
    opinion:str=Field(default='',max_length=2000)
    preview_id:str|None=Field(default=None,max_length=36)
    @model_validator(mode='after')
    def rejection_reason(self):
        self.opinion=self.opinion.strip()
        if self.outcome=='rejected' and not self.opinion: raise ValueError('驳回时须填写原因')
        return self
@app.post('/api/requests/{rid}/decision')
def decide(rid:str,body:DecisionInput,db:Session=Depends(db_session),user:Person=Depends(current_user)):
    row=authorized(db,rid,user)
    if not has_role(user,'counselor') or not db.get(RequestCounselor,(rid,user.id)): raise HTTPException(403,'仅负责该申请的辅导员可审批')
    if row.status!='pending':
        old=db.get(Decision,rid)
        if row.status in {'approved','rejected'} and old and old.approver_id==user.id and old.outcome==body.outcome and old.opinion==body.opinion: return serialize(db,row)
        raise HTTPException(409,'该申请已处理或撤回，不能审批')
    preview=None
    if body.outcome=='approved':
        signature=db.scalar(select(Signature).where(Signature.counselor_id==user.id).with_for_update())
        if not signature: raise HTTPException(409,'请先上传并保存个人签名')
        preview=db.get(ApprovalPreview,body.preview_id) if body.preview_id else None
        if (not preview or preview.request_id!=rid or preview.counselor_id!=user.id
            or preview.expires < datetime.now(timezone.utc).replace(tzinfo=None)
            or preview.signature_version!=signature.version or preview.opinion!=body.opinion):
            raise HTTPException(409,'请重新预览请假条，确认当前签名和审批意见后再通过')
    changed=db.execute(update(Request).where(Request.id==rid,Request.status=='pending').values(status=body.outcome)).rowcount
    if not changed: db.rollback(); raise HTTPException(409,'申请已由另一个请求处理，请刷新')
    db.add(Decision(request_id=rid,approver_id=user.id,approver_name=user.name,outcome=body.outcome,opinion=body.opinion,at=datetime.now(timezone.utc).isoformat()))
    db.flush()
    if preview:
        db.add(ApprovalSignature(request_id=rid,signature_version=preview.signature_version,content=preview.signature_content,
                                 digest=hashlib.sha256(preview.signature_content).hexdigest(),watermark=preview.watermark))
    db.commit()
    if body.outcome=='approved': generate(rid)
    db.expire_all()
    return serialize(db,db.get(Request,rid))

class WithdrawalInput(BaseModel):
    reason:str=Field(default='',max_length=2000)
    role:Literal['student','counselor']|None=None

@app.post('/api/requests/{rid}/withdraw')
def withdraw(rid:str,body:WithdrawalInput,db:Session=Depends(db_session),user:Person=Depends(current_user)):
    row=authorized(db,rid,user)
    role=body.role or ('student' if has_role(user,'student') and (row.status in {'pending','withdrawn'} or not has_role(user,'counselor')) else 'counselor')
    if not has_role(user,role) or (role=='student' and row.student_id!=user.id) or (role=='counselor' and not db.get(RequestCounselor,(rid,user.id))):
        raise HTTPException(403,'无权以该身份撤回')
    prior='pending' if role=='student' else 'approved'
    target='withdrawn' if role=='student' else 'revoked'
    reason=body.reason.strip()
    if row.status!=prior:
        old=db.get(Withdrawal,rid)
        if row.status==target and old and old.actor_id==user.id and old.reason==reason:return serialize(db,row)
        raise HTTPException(409,'学生只能撤回待审批申请，辅导员只能撤回已通过请假条')
    changed=db.execute(update(Request).where(Request.id==rid,Request.status==prior).values(status=target,file_status='cancelled',generation_error=None)).rowcount
    if not changed:db.rollback();raise HTTPException(409,'申请状态已变化，请刷新')
    db.add(Withdrawal(request_id=rid,actor_id=user.id,actor_name=user.name,actor_role=role,
                      prior_status=prior,reason=reason,at=datetime.now(timezone.utc).isoformat()))
    db.commit();db.expire_all()
    return serialize(db,db.get(Request,rid))

class PreviewInput(BaseModel):
    opinion:str=Field(default='',max_length=2000)

def preview_filename(pid,position):
    return hashlib.sha256(f'{pid}:{position}'.encode()).hexdigest()[:32]+'.pdf'

@app.post('/api/requests/{rid}/preview')
def create_preview(rid:str,body:PreviewInput,db:Session=Depends(db_session),user:Person=Depends(current_user)):
    require_counselor(user);authorized(db,rid,user)
    if not db.get(RequestCounselor,(rid,user.id)):raise HTTPException(403,'仅负责该申请的辅导员可预览')
    row=db.scalar(select(Request).where(Request.id==rid).with_for_update().execution_options(populate_existing=True))
    if row.status!='pending': raise HTTPException(409,'该申请已经审批')
    signature=db.get(Signature,user.id)
    if not signature: raise HTTPException(409,'请先上传并保存个人签名，再预览请假条')
    watermark=signature_watermark(row)
    data=watermarked_signature(signature.content,watermark)
    now=datetime.now(timezone.utc)
    preview=ApprovalPreview(id=str(uuid.uuid4()),request_id=rid,counselor_id=user.id,signature_version=signature.version,
                            signature_content=data,watermark=watermark,opinion=body.opinion.strip(),at=now.isoformat(),
                            expires=(now+timedelta(minutes=15)).replace(tzinfo=None))
    # Only retain the latest pending preview for this reviewer/request.
    db.query(ApprovalPreview).filter(ApprovalPreview.request_id==rid,ApprovalPreview.counselor_id==user.id).delete()
    db.query(ApprovalPreview).filter(ApprovalPreview.expires < now.replace(tzinfo=None)).delete()
    db.add(preview);db.commit()
    count=1 if row.layout=='combined' else db.scalar(select(func.count()).select_from(Item).where(Item.request_id==rid))
    return {'id':preview.id,'count':count,'filenames':[preview_filename(preview.id,i) for i in range(count)],'watermark':watermark,'expires_at':preview.expires.replace(tzinfo=timezone.utc).isoformat()}

@app.get('/api/previews/{pid}/{position}')
def preview_pdf(pid:str,position:int,db:Session=Depends(db_session),user:Person=Depends(current_user)):
    require_counselor(user)
    preview=db.get(ApprovalPreview,pid)
    if not preview or preview.counselor_id!=user.id: raise HTTPException(404,'预览不存在或无权查看')
    if preview.expires < datetime.now(timezone.utc).replace(tzinfo=None): raise HTTPException(409,'预览已过期，请重新预览')
    row=authorized(db,preview.request_id,user)
    signature=db.get(Signature,user.id)
    if row.status!='pending' or not signature or signature.version!=preview.signature_version: raise HTTPException(409,'申请或签名已更新，请重新预览')
    items=list(db.scalars(select(Item).where(Item.request_id==row.id).order_by(Item.position)))
    groups=[items] if row.layout=='combined' else [[item] for item in items]
    if position<0 or position>=len(groups):raise HTTPException(404,'预览页不存在')
    decision=Decision(approver_name=user.name,opinion=preview.opinion,at=preview.at)
    data=render_pdf(row,decision,groups[position],preview.signature_content,draft=True)
    return Response(data,media_type='application/pdf',headers={'Content-Disposition':f'inline; filename="{preview_filename(pid,position)}"'})
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
    if row.status in {'withdrawn','revoked'}:raise HTTPException(410,'请假条已撤回，文件已失效')
    if row.status!='approved' or row.file_status!='ready': raise HTTPException(409,'文件尚未就绪')
    return Response(doc.content,media_type='application/pdf',headers={'Content-Disposition':f'inline; filename="{doc.name}"','Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
@app.middleware('http')
async def no_cache(request,call_next):
    # Browser mutations must come from this origin; local script/test calls have no Origin.
    origin=request.headers.get('origin')
    expected=os.getenv('PUBLIC_ORIGIN',str(request.base_url).rstrip('/'))
    if request.method in {'POST','PUT','PATCH','DELETE'} and (
        (origin is not None and origin != expected) or request.headers.get('sec-fetch-site')=='cross-site'
    ):
        response=Response(json.dumps({'detail':'请求来源不被允许'}),status_code=403,media_type='application/json')
    elif request.headers.get('content-length','').isdigit() and int(request.headers['content-length'])>4_300_000:
        response=Response(json.dumps({'detail':'请求内容过大'}),status_code=413,media_type='application/json')
    else:
        response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Frame-Options']='SAMEORIGIN'
    return response
app.add_middleware(TestQueryRedaction)
# Relative Vite asset URLs work both directly and behind the /leave/ proxy.
FRONTEND_DIST = ROOT/'dist'
app.mount('/assets', StaticFiles(directory=FRONTEND_DIST/'assets', check_dir=False), name='assets')
@app.get('/class-management/')
def management_page():
    if not (FRONTEND_DIST/'index.html').is_file():raise HTTPException(503,'前端尚未构建')
    # Shared bundled shell; protected APIs supply no roster data before admin authorization.
    html=(FRONTEND_DIST/'index.html').read_text().replace('<head>','<head><base href="../">',1)
    return Response(html,media_type='text/html')
@app.get('/')
def index(request:HTTPRequest,leave_session:str|None=Cookie(default=None),db:Session=Depends(db_session)):
    attempt=getattr(request.state,'test_login_query',None)
    if attempt is not None:
        config=app.state.test_login_config
        uid=attempt['uid']
        if (not config.enabled or not attempt['valid_shape'] or not uid.startswith('test-') or len(uid)<=5
            or not hmac.compare_digest(attempt['secret_digest'],config.secret_digest()) or not db.get(DirectoryMember,uid)):
            raise HTTPException(403,'测试登录不可用或凭据无效')
        response=RedirectResponse(os.getenv('SESSION_COOKIE_PATH','/'),status_code=303)
        establish_login(db,uid,response,leave_session,test_digest=config.secret_digest())
        return response
    if not (FRONTEND_DIST/'index.html').is_file():
        raise HTTPException(503, '前端尚未构建，请先运行 npm ci && npm run build')
    return FileResponse(FRONTEND_DIST/'index.html')
