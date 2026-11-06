"""Local-only operator dashboard over the existing CLI; no model tools or shell."""
from collections import deque
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import re
import secrets
import shlex
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid
import webbrowser

from .config import PACKAGE_ROOT, load_config, validate_config, round_allowance
from .context import _is_link, redact_text
from .engine import ensure_external
from .roles import SEED_ROLES, seed_agents
from .storage import atomic_write, now
from .profile_defaults import (PROFILE_FILES, EDITABLE, profile_config,
                               validate_overrides, save_defaults, reset_defaults,
                               profile_ids, profile_details, create_profile, delete_profile)

PROFILE_NAMES = {'research': 'Brainstorming', 'cheap': 'Brainstorming · levné modely',
                 'experimental': 'Plný běh · experimentální prototyp'}
RUN_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{1,100}\Z')
SAFE_EVENTS = {'agent_round_started','agent_round_finished','idea_recorded','research_task_assigned',
               'review_task_assigned','critique_recorded','note','research_report_recorded',
               'agent_note','sdk_tool_started','sdk_tool_finished',
               'prototype_review_recorded','prototype_review_probe_finished','operator_comment_applied',
               'operator_comment_received','run_stopped','research_report_only_prepared',
               'research_closure_prepared','http_request_finished','http_request_completed',
               'agent_round_failed','agent_round_interrupted','agent_prompt_preflight_blocked',
               'sdk_model_request_started','sdk_web_search_call','sdk_activity','file_read','file_searched',
               'http_document_read','document_redirect_hint','http_request_failed',
               'http_request_uncertain','carrier_screened','spawn_decision',
               'coding_command_finished','experiment_finished','export_materialized',
               'hypothesis_recorded','hypothesis_portfolio_retained','hypothesis_review_recorded','hypothesis_shortlist_selected','hypothesis_development_started','hypothesis_development_finished',
               'agent_request_capacity_deferred','agent_request_capacity_available','agent_request_preflight_blocked'}
ACTIVITY_LIMIT = 80


def _activity_url(value):
    """Display public locations without signed queries, fragments or userinfo."""
    if not isinstance(value,str):return ''
    try:
        url=urlsplit(value)
        if url.scheme not in {'http','https'} or not url.hostname:return ''
        hostname='['+url.hostname+']' if ':' in url.hostname else url.hostname
        port=':'+str(url.port) if url.port else ''
        return (url.scheme+'://'+hostname+port+url.path)[:800]
    except ValueError:return ''


def _activity_text(value, limit=900):
    if not isinstance(value,(str,int,float,bool)):return ''
    text=str(value)
    text=re.sub(r'https?://[^\s<>\"\']+',lambda match:_activity_url(match.group()),text)
    text=re.sub(r'(?im)\b(?:authorization|proxy-authorization|cookie|set-cookie|x-api-key)[\"\']?\s*[:=]\s*[^\r\n]+',
                '[HTTP HEADER OMITTED]',text)
    return redact_text(text)[:limit]


def _activity_object(value):
    if isinstance(value,dict):return value
    if isinstance(value,str):
        try:
            parsed=json.loads(value)
            return parsed if isinstance(parsed,dict) else {}
        except (ValueError,TypeError):pass
    return {}


def _argument_preview(arguments):
    """A fixed research-field allowlist, never headers, bodies or shell code."""
    arguments=_activity_object(arguments);parts=[]
    for key in ('idea_id','target_id','provider','url','service_url','path','query',
                'queries','terms','purpose','proposed_change','validation_plan','offset','limit'):
        value=arguments.get(key)
        if value is None:continue
        if key in {'url','service_url'}:value=_activity_url(value)
        elif isinstance(value,list):value='; '.join(_activity_text(v,180) for v in value[:5] if isinstance(v,str))
        value=_activity_text(value,400)
        if value:parts.append(key+': '+value)
    return '\n'.join(parts)[:1300]


def _result_preview(name, result):
    """Summarize observed public tool output, not an SDK conversation dump."""
    parsed=_activity_object(result)
    if not parsed:
        # read_file intentionally returns public/snapshot text rather than JSON.
        # Unknown tools and HTTP bodies never get a free-form output fallback.
        if name=='read_file' and isinstance(result,str):return _activity_text(result,800)
        return ''
    parts=[]
    for key in ('status','verdict','id','idea_id','target_id','request_id','reason','title','summary','mechanism','meaning','next_action',
                'path','response_path','offset','end','total_chars','matches','count'):
        value=_activity_text(parsed.get(key),320)
        if value:parts.append(key+': '+value)
    # A document tool extracts public text explicitly. Generic HTTP receipts
    # retain only status/size/path; raw body, cookies and headers are omitted.
    if name in {'read_document','search_file','check_baseline','check_prior_work'}:
        excerpt=_activity_text(parsed.get('text') or parsed.get('excerpt'),700)
        if excerpt:parts.append(excerpt)
        for key in ('matches','results','entries'):
            rows=parsed.get(key)
            if isinstance(rows,list):
                for row in rows[:3]:
                    if isinstance(row,dict):
                        sample=' | '.join(filter(None,(_activity_text(row.get(k),200) for k in ('id','path','line','title','excerpt','text'))))
                        if sample:parts.append(sample)
    response=parsed.get('response')
    if isinstance(response,dict):
        for key in ('status','response_bytes','path'):
            value=_activity_text(response.get(key),200)
            if value:parts.append('response.'+key+': '+value)
    return '\n'.join(parts)[:1600]


def _integer(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(name + ' musí být nezáporné celé číslo')
    return value


def _words(command):
    if not isinstance(command, str) or not command.strip() or len(command) > 16000 or '\n' in command or '\r' in command or '\0' in command:
        raise ValueError('Zadej jeden příkaz swarmu')
    # Windows quoting leaves backslashes in paths untouched. No shell executes
    # this string: the resulting argument list goes to Python with shell=False.
    words=shlex.split(command, posix=False)
    return [word[1:-1] if len(word)>=2 and word[0]==word[-1] and word[0] in "\"'" else word for word in words]


def writer_active(run_dir):
    """Probe the existing OS lock without writing or creating a lock file.

    A stale RUNNING checkpoint is not a live writer. If the lock file cannot be
    opened, leave recovery enabled; the actual CLI still enforces run_lock.
    """
    path=run_dir/'.runner.lock'
    if not path.is_file() or _is_link(path) or path.stat().st_size<1:return False
    try:stream=path.open('rb')
    except OSError:return False
    with stream:
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
            return False
        except OSError:return True


class GUIService:
    def __init__(self, project=None, runs_root=None, settings_path=None):
        self.project=Path(project or PACKAGE_ROOT.parents[1]).resolve()
        from .runtime_paths import runs_root as default_runs_root,files_root
        self.runs_root=Path(runs_root or default_runs_root(self.project)).resolve()
        self._paths(self.project,self.runs_root)
        self.token=secrets.token_urlsafe(32)
        self.settings_path=Path(settings_path) if settings_path else files_root(self.project)/'gui-settings.json'
        self._saved_key=''
        try:
            if not _is_link(self.settings_path) and self.settings_path.stat().st_size<16384:
                saved=json.loads(self.settings_path.read_text(encoding='utf-8'))
                key=saved.get('api_key','')
                if isinstance(key,str) and len(key)<=4096 and not any(c in key for c in '\r\n\0'):
                    self._saved_key=key.strip()
        except (OSError,ValueError,AttributeError):pass
        self._key=self._saved_key or os.environ.get('OPENAI_API_KEY','')
        self._secrets=[self._key] if self._key else []
        self._lock=threading.RLock()
        self._job=None
        self._process=None
        self._thread=None
        self._lines=deque(maxlen=3000)
        self._seq=0
        self._pending_pause=False
        self._state_cache=None

    def _paths(self, project, runs_root):
        if not project.is_dir() or _is_link(project) or _is_link(runs_root):
            raise ValueError('Zvol existující projekt a skutečnou složku běhů bez junction/symlink')
        ensure_external(project,runs_root)

    def clean(self, value):
        if isinstance(value,str):
            for secret in self._secrets:
                value=value.replace(secret,'[REDACTED]')
            return redact_text(value)
        if isinstance(value,list):return [self.clean(v) for v in value]
        if isinstance(value,dict):return {k:self.clean(v) for k,v in value.items()}
        return value

    def _append(self, text):
        with self._lock:
            self._seq+=1
            self._lines.append({'seq':self._seq,'text':self.clean(str(text))[:12000]})

    def settings(self, payload):
        if self.active():raise ValueError('Cesty a klíč změň až po skončení nebo pozastavení běhu')
        project=Path(payload.get('project') or self.project).resolve()
        runs_root=Path(payload.get('runs_root') or self.runs_root).resolve()
        self._paths(project,runs_root)
        key=payload.get('api_key')
        remember=payload.get('remember_api_key',bool(self._saved_key))
        forget=payload.get('forget_api_key',False)
        if type(remember) is not bool or type(forget) is not bool:raise ValueError('Neplatná volba zapamatování klíče')
        if key is not None:
            if not isinstance(key,str) or len(key)>4096 or any(c in key for c in '\r\n\0'):
                raise ValueError('Neplatný API klíč')
        next_key='' if forget else (key.strip() if key is not None else self._key)
        if forget or 'remember_api_key' in payload or key is not None:
            if _is_link(self.settings_path) or _is_link(self.settings_path.parent):raise ValueError('Propojený soubor nastavení je odmítnut')
            if remember and next_key and not forget:
                self.settings_path.parent.mkdir(parents=True,exist_ok=True)
                atomic_write(self.settings_path,json.dumps({'api_key':next_key},ensure_ascii=False))
                self._saved_key=next_key
            else:
                self.settings_path.unlink(missing_ok=True)
                self._saved_key=''
            self._key=next_key
            if self._key:self._secrets.append(self._key)
        self.project,self.runs_root=project,runs_root
        self._state_cache=None
        return {'ok':True,'api_key_present':bool(self._key),'api_key_saved':bool(self._saved_key),
                'message':'API klíč zapomenut.' if forget else 'Nastavení uloženo. Klíč se použije i příště.' if self._saved_key else 'Nastavení platí pro tuto relaci GUI.'}

    def run_path(self, run_id):
        if not isinstance(run_id,str) or not RUN_ID.fullmatch(run_id):raise ValueError('Neplatné ID běhu')
        path=self.runs_root/run_id
        if _is_link(path) or not path.is_dir() or path.resolve().parent!=self.runs_root:
            raise ValueError('Běh není v nastavené složce')
        for name in ('state.sqlite3','checkpoint.json'):
            if _is_link(path/name):raise ValueError('Propojené soubory běhu jsou odmítnuty')
        if not (path/'state.sqlite3').is_file():raise ValueError('Běh nemá SQLite checkpoint')
        return path

    def _db(self, run_id):
        path=self.run_path(run_id)/'state.sqlite3'
        return sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=1)

    def _state(self, run_id):
        path=self.run_path(run_id)
        def stamp(name):
            try:
                stat=(path/name).stat();return stat.st_mtime_ns,stat.st_size
            except FileNotFoundError:return None
        fingerprint=(run_id,stamp('state.sqlite3'),stamp('state.sqlite3-wal'),stamp('checkpoint.json'))
        if self._state_cache and self._state_cache[0]==fingerprint:return self._state_cache[1]
        with closing(self._db(run_id)) as db:
            row=db.execute('SELECT body FROM state WHERE id=1').fetchone()
        if not row or len(row[0])>64*1024*1024:raise ValueError('Checkpoint chybí nebo je příliš velký')
        state=json.loads(row[0]);self._state_cache=(fingerprint,state)
        return state

    def _summary(self, run_id):
        # SQLite parses the JSON in C; Python receives only tiny display values,
        # never sixty copies of historical model conversations on each poll.
        with closing(self._db(run_id)) as db:
            row=db.execute("""SELECT json_extract(body,'$.status'), json_extract(body,'$.updated_at'),
                json_extract(body,'$.config.task_style'), substr(json_extract(body,'$.objective'),1,600),
                json_extract(body,'$.steps'), json_extract(body,'$.usage.total_tokens'),
                json_extract(body,'$.usage_estimated_usd'),json_array_length(body,'$.agents'),
                json_array_length(body,'$.ideas'),json_array_length(body,'$.brainstorm_hypotheses') FROM state WHERE id=1""").fetchone()
        if not row:raise ValueError('Chybí stav běhu')
        return dict(zip(('status','updated_at','task_style','objective','steps','tokens','estimated_usd','agents','ideas','hypotheses'),row),id=run_id)

    def bootstrap(self):
        profiles=[]
        for key in profile_ids(self.project):
            profiles.append(self._profile(key))
        return {'project':str(self.project),'runs_root':str(self.runs_root),
                'api_key_present':bool(self._key),'api_key_saved':bool(self._saved_key),'profiles':profiles,
                'role_catalog':[{'phase':phase,'role':role,'mission':mission} for phase,role,mission in SEED_ROLES],
                'models':profiles[0]['config']['model_tiers']}

    def _profile(self, key):
        config,saved=profile_config(self.project,key)
        details=profile_details(self.project,key)
        from .engine import OBJECTIVE
        config['operator_objective']=config.get('operator_objective') or OBJECTIVE
        roles=seed_agents(config)
        for agent in roles:agent['round_limit']=round_allowance(config,agent)
        return {'id':key,'name':details['name'] or PROFILE_NAMES[details['base_profile']],
                'label':details['name'] or PROFILE_NAMES[details['base_profile']],
                'custom':details['custom'],'base_profile':details['base_profile'],
                'config':config,'objective':config['operator_objective'],
                'roles':roles,'agents':roles,'has_saved_defaults':saved}

    def defaults(self, payload, reset=False):
        key=payload.get('profile','research')
        profile_details(self.project,key)
        with self._lock:
            if reset:reset_defaults(self.project,key)
            else:
                kwargs={k:payload[k] for k in ('objective','name') if k in payload}
                save_defaults(self.project,key,payload.get('overrides',{}),**kwargs)
        return {'ok':True,'profile':self._profile(key),
                'message':'Původní profil obnoven. Dřívější běhy se nemění.' if reset else
                          'Výchozí nastavení profilu uloženo pro příští běhy v GUI i CLI.'}

    def create_profile(self,payload):
        kwargs={'objective':payload['objective']} if 'objective' in payload else {}
        with self._lock:
            key=create_profile(self.project,payload.get('profile','research'),payload.get('name'),payload.get('overrides',{}),**kwargs)
        return {'ok':True,'profile':self._profile(key)}

    def delete_profile(self,payload):
        with self._lock:base=delete_profile(self.project,payload.get('profile'))
        return {'ok':True,'base_profile':base}

    def active(self):
        return bool(self._job and self._job['active'])

    def job(self, cursor=0):
        cursor=_integer(cursor,'cursor')
        with self._lock:
            return {'job':dict(self._job) if self._job else None,
                    'lines':[line for line in self._lines if line['seq']>cursor], 'cursor':self._seq}

    def runs(self):
        rows=[]
        if self.runs_root.is_dir():
            paths=sorted((p for p in self.runs_root.iterdir() if RUN_ID.fullmatch(p.name) and p.is_dir() and not _is_link(p) and (p/'state.sqlite3').is_file()),
                         key=lambda p:p.stat().st_mtime,reverse=True)
            for path in paths[:60]:
                try:
                    rows.append(self._summary(path.name))
                except (ValueError,OSError,sqlite3.Error,json.JSONDecodeError):continue
        return {'runs':rows,'active_job':dict(self._job) if self._job else None}

    def _activity(self, run_id):
        # Filter *before* LIMIT: a hundred SDK history checkpoints must not
        # erase the last useful tool/document/note observations. JSON1 extracts
        # bounded scalar fields so model histories/HTTP bodies never leave SQL.
        fields={
            'time':('$.time',80),'kind':('$.kind',120),'agent_id':('$.agent_id',160),
            'name':('$.data.name',160),'arguments':('$.data.arguments',12000),
            'result':('$.data.result',24576),'text':('$.data.text',1800),
            'reason':('$.data.reason',1200),'title':('$.data.title',500),
            'conclusion':('$.data.conclusion',1200),'verdict':('$.data.verdict',100),
            'task_kind':('$.data.kind',100),'target_id':('$.data.target_id',160),
            'hypothesis_id':('$.data.hypothesis_id',160),'idea_id':('$.data.idea_id',160),'round':('$.data.round',20),
            'status':('$.data.status',120),'path':('$.data.path',1000),
            'url':('$.data.url',8000),'query':('$.data.query',600),
            'offset':('$.data.offset',20),'end':('$.data.end',20),
            'characters':('$.data.characters',20),'provider':('$.data.provider',300),
            'action':('$.data.action',6000),'response_status':('$.data.response.status',30),
            'response_bytes':('$.data.response.response_bytes',30),
        }
        selected='seq,'+','.join("substr(json_extract(body,'"+path+"'),1,"+str(size)+") AS "+name
                                  for name,(path,size) in fields.items())
        marks=','.join('?' for _ in SAFE_EVENTS);kinds=tuple(sorted(SAFE_EVENTS))
        where="json_extract(body,'$.kind') IN ("+marks+")"
        with closing(self._db(run_id)) as db:
            rows=db.execute('SELECT '+selected+' FROM events WHERE '+where+
                            ' ORDER BY seq DESC LIMIT ?',(*kinds,ACTIVITY_LIMIT)).fetchall()
            # Separate per-agent latest lookup preserves the last observation of
            # quieter/completed roles even after another role fills the stream.
            latest=db.execute('SELECT '+selected+' FROM events WHERE seq IN ('+
                'SELECT max(seq) FROM events WHERE '+where+
                " AND json_extract(body,'$.agent_id') IS NOT NULL GROUP BY json_extract(body,'$.agent_id'))"+
                ' ORDER BY seq DESC LIMIT 64',kinds).fetchall()
        def display(row):
            item=dict(zip(('seq',*fields),row));kind=item['kind'];detail=''
            if kind in {'sdk_tool_started','sdk_tool_finished'}:
                name=_activity_text(item['name'] or 'tool',120)
                started=kind=='sdk_tool_started'
                text=('Pracuje: ' if started else 'Dokončeno: ')+name
                detail=_argument_preview(item['arguments']) if started else _result_preview(name,item['result'])
            elif kind=='sdk_web_search_call':
                text='Hledání na webu'
                detail=_argument_preview(item['action']) or _activity_text(item['query'])
            elif kind=='sdk_model_request_started':text='Čeká na odpověď modelu'
            elif kind=='sdk_activity':text=item['text'] or 'Model připravuje odpověď'
            elif kind=='agent_round_started':text='Začíná kolo '+str(item['round'] or '')
            elif kind=='agent_round_finished':
                text='Kolo dokončeno: '+str(item['status'] or '')
                detail=_activity_text(item['reason'])
            elif kind in {'agent_round_failed','agent_prompt_preflight_blocked'}:
                text='Kolo zastaveno';detail=_activity_text(item['reason'])
            elif kind=='hypothesis_shortlist_selected':text='Vybrán shortlist k rozpracování'
            elif kind=='hypothesis_development_started':text='Rozpracovává námět';detail=_activity_text(item['hypothesis_id'])
            elif kind=='hypothesis_development_finished':text='Rozpracování: '+str(item['status'] or '');detail=_activity_text(item['hypothesis_id'])+' '+_activity_text(item['reason'])
            elif kind=='agent_round_interrupted':text='Kolo přerušeno; uložená práce zachována'
            elif kind=='agent_request_capacity_deferred':
                text='Úkol odložen: nevejde se do zbývajícího rozpočtu';detail=_activity_text(item['reason'])
            elif kind=='agent_request_capacity_available':text='Rozpočet opět umožňuje pokračovat v úkolu'
            elif kind=='agent_request_preflight_blocked':
                text='Příprava požadavku blokována';detail=_activity_text(item['reason'])
            elif kind=='file_read':
                text='Čte soubor: '+_activity_text(item['path'],450)
                detail='Pozice '+str(item['offset'] or 0)+'; '+str(item['characters'] or '?')+' znaků'
            elif kind=='file_searched':
                text='Hledá v souboru: '+_activity_text(item['path'],450)
                detail=_activity_text(item['query'])
            elif kind=='http_document_read':
                text='Čte dokumentaci: '+_activity_url(item['url'])
                detail='Znaky '+str(item['offset'] or 0)+'–'+str(item['end'] or '?')
            elif kind in {'http_request_finished','http_request_completed','http_request_failed','http_request_uncertain'}:
                action=_activity_object(item['action']);payload=action.get('payload',{})
                if not isinstance(payload,dict):payload={}
                text='HTTP '+_activity_text(payload.get('method',''),20)+' '+str(item['status'] or '')
                detail=_activity_url(payload.get('url'))
                if item['response_status']:detail+=' | HTTP '+str(item['response_status'])
                if item['response_bytes']:detail+=' | '+str(item['response_bytes'])+' bytů'
                if item['reason']:detail+='\n'+_activity_text(item['reason'],400)
            elif kind in {'research_task_assigned','review_task_assigned'}:
                text='Úkol: '+str(item['task_kind'] or '')+' '+str(item['target_id'] or '')
            elif kind=='carrier_screened':
                text='Prověřuje službu: '+_activity_text(item['provider'],300)
                detail=_activity_text(item['status'],160)
            else:
                text=next((item[key] for key in ('text','title','conclusion','verdict','reason','task_kind') if item.get(key)),kind)
                if item['idea_id']:detail=str(item['idea_id'])
            return self.clean({'seq':item['seq'],'time':item['time'],'kind':kind,
                               'agent_id':item['agent_id'],'text':_activity_text(text,1400),
                               'detail':_activity_text(detail,1600)})
        return [display(row) for row in reversed(rows)],[display(row) for row in latest]

    def _events(self, run_id):
        return self._activity(run_id)[0]

    def run(self, run_id):
        state=self._state(run_id)
        keys=('run_id','backend','status','stop_reason','config','objective','usage','steps','active_seconds','usage_estimated_usd','created_at','updated_at')
        result={k:state.get(k) for k in keys}
        result['config']={k:v for k,v in result['config'].items() if k not in {'http_credentials','external_resources'}}
        result['agents']=[]
        for agent in state.get('agents',[]):
            row={k:agent.get(k) for k in ('id','role','display_name','mission','work_kind','model_tier','model','status','rounds','summary','reason_for_stopping','parent_id','unexplored_leads','handoff_leads','blind_spots','usage')}
            row['round_limit']=round_allowance(state['config'],agent)
            assignment=agent.get('review_assignment') or agent.get('research_assignment') or {}
            row['current_task']={k:assignment.get(k) for k in ('kind','target_id','stage')}
            result['agents'].append(row)
        result['ideas']=[{k:i.get(k) for k in ('id','title','provider','status','summary','mechanism','payment','novelty','novelty_delta','next_action','blocker','critique','contributors','evidence')} for i in state.get('ideas',[])]
        hypotheses=state.get('brainstorm_hypotheses',[])
        if not hypotheses and state['config'].get('task_style')=='brainstorming':
            from .brainstorm_portfolio import from_audit
            with closing(self._db(run_id)) as db:hypotheses=from_audit(db)
        result['hypothesis_reviews']=state.get('hypothesis_reviews',[])
        result['hypothesis_development']=state.get('hypothesis_development',{})
        result['hypotheses']=[{k:h.get(k) for k in ('id','title','mechanism','provider','unknowns','source_urls','status',
            'contributors','screen_status','created_at','last_updated','source_event_seq','meaning','idea_id','development_status')}
            for h in hypotheses[:120]]
        result['approvals']=[{k:a.get(k) for k in ('id','status','kind','description','target','idea_id','created_at','decision','note')} | {
            'description':a.get('description') or a.get('action',{}).get('description'),
            'target':a.get('target') or a.get('action',{}).get('target')}
            for a in state.get('approvals',[])]
        result['activity'],result['current_activity']=self._activity(run_id)
        result['events']=result['activity']  # Kept for older dashboard clients.
        with closing(self._db(run_id)) as db:
            preview=db.execute("""SELECT seq,json_extract(body,'$.time'),json_extract(body,'$.agent_id'),
                substr(json_extract(body,'$.data.text'),1,12000),json_extract(body,'$.data.partial')
                FROM events WHERE json_extract(body,'$.kind')='sdk_output_preview' ORDER BY seq DESC LIMIT 1""").fetchone()
        result['live_output']=self.clean({'seq':preview[0],'time':preview[1],'agent_id':preview[2],
            'kind':'sdk_output_preview','data':{'text':preview[3] or '','partial':bool(preview[4])}}) if preview else None
        for agent in result['agents']:
            recent=next((event for event in result['current_activity'] if event.get('agent_id')==agent['id']),None)
            agent['last_action']=recent['text'] if recent else ''
            agent['activity']=recent
        result['running']=writer_active(self.run_path(run_id)) or bool(self.active() and self._job.get('run_id')==run_id)
        result['interrupted']=state.get('status')=='RUNNING' and not result['running']
        from .workflow_graph import build_workflow
        result['workflow']=build_workflow(state,running=result['running'],
            report_exists=(self.run_path(run_id)/'SWARM_REPORT.md').is_file(),hypotheses=hypotheses,activity=result['current_activity'])
        result['operator_comments']=[dict(item,status='APPLIED') for item in state.get('operator_comments',[])]
        inbox=self.run_path(run_id)/'operator-inbox'
        if inbox.is_dir() and not _is_link(inbox):
            for entry in sorted(inbox.glob('*.json'))[-30:]:
                if _is_link(entry) or entry.stat().st_size>16384:continue
                try:result['operator_comments'].append(dict(json.loads(entry.read_text(encoding='utf-8')),status='QUEUED'))
                except (ValueError,OSError):continue
        return result

    def memory(self, run_id=None):
        if run_id:
            parent=self.run_path(run_id)/'context'
            if _is_link(parent):raise ValueError('Propojený kontext je odmítnut')
            path=parent/'prior-runs.json'
        else:path=self.runs_root/'RUN_MEMORY.json'
        if _is_link(path):raise ValueError('Propojený soubor paměti je odmítnut')
        result={'path':str(path),'scope':'captured' if run_id else 'shared','run_id':run_id,'exists':path.is_file()}
        if not result['exists']:return dict(result,entries=[],text='',message='Paměť zde zatím není vytvořená. Zobrazení ji nevytváří ani nepřepisuje.')
        if path.stat().st_size>4*1024*1024:raise ValueError('Paměť přesahuje 4 MiB; otevři soubor v editoru')
        text=path.read_text(encoding='utf-8-sig');data=json.loads(text)
        if not isinstance(data,dict) or data.get('schema_version')!=1 or not isinstance(data.get('entries'),list):raise ValueError('Nepodporovaný formát paměti')
        if any(not isinstance(row,dict) or not isinstance(row.get('candidates',[]),list) or any(not isinstance(c,dict) for c in row.get('candidates',[])) for row in data['entries']):raise ValueError('Neplatné záznamy paměti')
        return dict(result,entries=data['entries'],notice=data.get('notice',''),truncated=bool(data.get('truncated')),
                    skipped=data.get('skipped',[]),text=text,updated_at=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat())

    def report(self, run_id):
        path=self.run_path(run_id)/'SWARM_REPORT.md'
        if _is_link(path):raise ValueError('Propojený report je odmítnut')
        if not path.is_file():return {'run_id':run_id,'text':'Report zatím není vytvořený.'}
        if path.stat().st_size>12*1024*1024:raise ValueError('Report je příliš velký; otevři jej v editoru')
        return {'run_id':run_id,'text':path.read_text(encoding='utf-8')}

    def launch(self, args, kind, run_id=None):
        with self._lock:
            if self.active():raise ValueError('GUI už provádí jeden příkaz; počkej na dokončení nebo požádej o pauzu')
            environment=dict(os.environ,PYTHONUNBUFFERED='1',PYTHONIOENCODING='utf-8')
            if self._key:environment['OPENAI_API_KEY']=self._key
            else:environment.pop('OPENAI_API_KEY',None)
            argv=[sys.executable,'-u',str(PACKAGE_ROOT/'swarm.py'),*map(str,args)]
            self._job={'id':uuid.uuid4().hex,'kind':kind,'active':True,'exit_code':None,'run_id':run_id,'started_at':now()}
            self._pending_pause=False
            self._append('> '+subprocess.list2cmdline(['swarm.py',*map(str,args)]))
            options={'cwd':str(PACKAGE_ROOT),'env':environment,'stdout':subprocess.PIPE,
                     'stderr':subprocess.STDOUT,'stdin':subprocess.DEVNULL,'text':True,'encoding':'utf-8','errors':'replace','shell':False}
            if os.name=='nt':options['creationflags']=subprocess.CREATE_NO_WINDOW
            try:self._process=subprocess.Popen(argv,**options)
            except OSError:
                self._job.update(active=False,exit_code=-1)
                raise
            self._thread=threading.Thread(target=self._read_process,name='swarm-gui-cli',daemon=False)
            self._thread.start()
            return {'ok':True,'job':dict(self._job)}

    def _read_process(self):
        process=self._process
        try:
            for line in process.stdout:
                line=line.rstrip('\r\n')
                if not self._job.get('run_id'):
                    possible=Path(line.strip())
                    try:
                        if possible.parent.resolve()==self.runs_root and RUN_ID.fullmatch(possible.name):
                            self.run_path(possible.name)
                            self._job['run_id']=possible.name
                            if self._pending_pause:self.pause(possible.name)
                    except (ValueError,OSError):pass
                self._append(line)
        finally:
            code=process.wait()
            with self._lock:self._job.update(active=False,exit_code=code)
            self._append('Příkaz skončil, návratový kód: '+str(code))

    def start(self, payload):
        key=payload.get('profile','research')
        profile_details(self.project,key)
        if payload.get('api_key') is not None:self.settings({'api_key':payload['api_key']})
        if self.active():raise ValueError('Nejprve dokonči aktivní příkaz')
        config,_=profile_config(self.project,key);overrides=payload.get('overrides',{})
        validate_overrides(overrides)
        config.update(overrides)
        config['live_output_preview']=True
        objective=payload.get('objective')
        if objective is not None:config['operator_objective']=objective
        task=payload.get('task','')
        if not isinstance(task,str) or len(task)>12000:raise ValueError('Zadání musí mít nejvýše 12000 znaků')
        if task.strip():
            config['operator_objective']=(config.get('operator_objective') or 'Research Metaweb preservation mechanisms.')+'\n\nOPERATOR COMMENT:\n'+task.strip()
        validate_config(config)
        seed_agents(config)
        backend=payload.get('backend','openai')
        if backend not in {'demo','openai'}:raise ValueError('Neznámý backend')
        draft=self.runs_root/'.gui'/'profiles'
        for path in (self.runs_root/'.gui',draft):
            if _is_link(path):raise ValueError('Propojený GUI adresář je odmítnut')
        draft.mkdir(parents=True,exist_ok=True)
        path=draft/(uuid.uuid4().hex+'.json');atomic_write(path,json.dumps(config,ensure_ascii=False,indent=2))
        args=['start','--project',str(self.project),'--runs-root',str(self.runs_root),'--config',str(path),'--backend',backend]
        if payload.get('fetch_live',True):args+=['--fetch-live']
        return self.launch(args,'start')

    def resume(self, payload):
        run_id=payload.get('run_id');path=self.run_path(run_id)
        state=self._state(run_id);backend=state.get('backend') or 'openai'
        if backend not in {'openai','demo'}:raise ValueError('Neznámý backend běhu')
        args=['resume',str(path),'--backend',backend]
        for name in ('extend_steps','extend_tokens','extend_seconds','extend_rounds'):
            value=_integer(payload.get(name,0),name)
            if value:args+=['--'+name.replace('_','-'),str(value)]
        return self.launch(args,'resume',run_id)

    def pause(self, run_id):
        path=self.run_path(run_id)
        if _is_link(path/'PAUSE.flag') or _is_link(path/'PAUSE.flag.tmp'):raise ValueError('Propojený pause flag je odmítnut')
        atomic_write(path/'PAUSE.flag',now()+'\n')
        self._append('Požadavek na pauzu uložen pro '+run_id+'; probíhající omezená práce nejdřív doběhne.')
        return {'ok':True,'message':'Pauza vyžádána; aktuální omezený krok může doběhnout.'}

    def close_research(self, run_id):
        path=self.run_path(run_id)
        return self.launch(['close-research',str(path),'--report-only','--note','Uzavření z GUI: pouze závěrečná syntéza zachovaných podkladů'],'close-research',run_id)

    def comment(self, payload):
        path=self.run_path(payload.get('run_id'))
        from .operator_comments import enqueue_comment
        result=enqueue_comment(path,payload.get('text',''))
        return {'ok':True,'comment':result,'message':'Komentář zařazen. Runner jej převezme na další bezpečné hranici.'}

    def command(self, command):
        words=_words(command)
        if Path(words[0]).name.lower() in {'python','python.exe','python3','py','py.exe'}:words=words[1:]
        if words and Path(words[0]).name.lower()=='swarm.py':words=words[1:]
        aliases={'run.cmd':'research','run-http.cmd':'research','run-research.cmd':'research',
                 'run-supervised.cmd':'research','run-experimental.cmd':'experimental'}
        if words and words[0].lower() in aliases:
            if len(words)!=1:raise ValueError('U zkráceného launcheru použij parametry formuláře; plný swarm.py příkaz přijímá argumenty')
            return self.start({'profile':aliases[words[0].lower()]})
        allowed={'init','start','run','resume','pause','comment','status','approvals','report','verify','decide','unblock','select','finish-research','reconcile-budget','close-research','doctor'}
        if not words or words[0] not in allowed:raise ValueError('Tato konzole přijímá swarm.py příkazy, nikoli obecný shell; pro plný CMD použij Otevřít CMD')
        from .cli import parser
        try:args=parser().parse_args(words)
        except SystemExit:raise ValueError('Neplatná syntaxe swarm.py příkazu') from None
        if hasattr(args,'project') and Path(args.project).resolve()!=self.project:
            raise ValueError('Projekt příkazu musí odpovídat nastavení GUI; nejprve změň nastavení')
        if hasattr(args,'runs_root') and Path(args.runs_root).resolve()!=self.runs_root:
            raise ValueError('Složka běhů příkazu musí odpovídat nastavení GUI')
        if hasattr(args,'run_dir'):
            command_run=Path(args.run_dir).resolve()
            if command_run.parent!=self.runs_root:raise ValueError('Příkaz musí mířit do nastavené složky běhů')
            self.run_path(command_run.name)
        if words[0]=='pause':
            run_dir=Path(args.run_dir).resolve()
            if run_dir.parent!=self.runs_root:raise ValueError('Pauza musí mířit na nastavenou složku běhů')
            return self.pause(run_dir.name)
        if words[0]=='comment':
            return self.comment({'run_id':Path(args.run_dir).resolve().name,'text':args.text})
        if words[0]=='status' and self.active():
            run_dir=Path(args.run_dir).resolve()
            if run_dir.parent!=self.runs_root:raise ValueError('Stav musí mířit na nastavenou složku běhů')
            self._append(json.dumps(self.clean(self.run(run_dir.name)),ensure_ascii=False,indent=2))
            return {'ok':True,'message':'Stav vypsán v konzoli.'}
        return self.launch(words,'command',Path(args.run_dir).name if hasattr(args,'run_dir') else None)

    def open_cmd(self):
        if os.name!='nt':raise ValueError('Samostatné CMD je dostupné ve Windows; zde použij systémový terminál')
        environment=dict(os.environ)
        if self._key:environment['OPENAI_API_KEY']=self._key
        else:environment.pop('OPENAI_API_KEY',None)
        subprocess.Popen(['cmd.exe','/k'],cwd=str(PACKAGE_ROOT),env=environment,
                         creationflags=subprocess.CREATE_NEW_CONSOLE,shell=False)
        return {'ok':True,'message':'CMD otevřeno ve složce swarmu. Obsahuje klíč pouze v prostředí procesu.'}

    def approval(self, payload):
        run_id=payload.get('run_id');path=self.run_path(run_id)
        ident=payload.get('approval_id','');decision=payload.get('decision');note=payload.get('note','')
        if not isinstance(ident,str) or not re.fullmatch(r'APPROVAL-[A-Za-z0-9_-]+',ident):raise ValueError('Neplatné ID schválení')
        if decision not in {'approve','reject'} or not isinstance(note,str) or not 1<=len(note)<=4000:raise ValueError('Vyber rozhodnutí a napiš poznámku')
        return self.launch(['decide',str(path),ident,'--decision',decision,'--note',note],'approval',run_id)

    def shutdown(self):
        if self.active():
            self._pending_pause=True
            if self._job.get('run_id'):
                try:self.pause(self._job['run_id'])
                except (ValueError,OSError):pass
            print('GUI končí; aktivní CLI nebylo ukončeno násilím. Je vyžádána pauza na další bezpečné hranici.',flush=True)


def make_server(service, port=0):
    if type(port) is not int or not 0<=port<=65535:raise ValueError('Neplatný port')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send_body(self,status,body,kind='application/json; charset=utf-8'):
            self.send_response(status)
            self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers();self.wfile.write(body)
        def json(self,status,value):self.send_body(status,json.dumps(service.clean(value),ensure_ascii=False).encode('utf-8'))
        def auth(self):
            address='127.0.0.1:'+str(self.server.server_port)
            if self.headers.get('Host')!=address:return False
            origin=self.headers.get('Origin')
            if origin is not None and origin!='http://'+address:return False
            return secrets.compare_digest(self.headers.get('X-Swarm-Token','').encode('utf-8'),service.token.encode('ascii'))
        def do_GET(self):
            path=urlsplit(self.path)
            if path.path.startswith('/api/'):
                if not self.auth():return self.json(403,{'ok':False,'error':'Chybí oprávnění k lokálnímu GUI. Otevři adresu vypsanou při startu.'})
                try:
                    query=parse_qs(path.query);run_id=query.get('id',[''])[0]
                    if path.path=='/api/bootstrap':value=service.bootstrap()
                    elif path.path=='/api/runs':value=service.runs()
                    elif path.path=='/api/run':value=service.run(run_id)
                    elif path.path=='/api/job':value=service.job(int(query.get('cursor',['0'])[0]))
                    elif path.path=='/api/report':value=service.report(run_id)
                    elif path.path=='/api/memory':value=service.memory(run_id or None)
                    else:return self.json(404,{'ok':False,'error':'Neznámá API cesta'})
                    return self.json(200,value)
                except (ValueError,OSError,sqlite3.Error,json.JSONDecodeError) as error:return self.json(400,{'ok':False,'error':str(error)})
            asset={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/workflow.js':'workflow.js','/style.css':'style.css',
                   '/favicon.ico':'favicon.ico','/favicon.png':'favicon.png'}.get(path.path)
            if asset is None:return self.json(404,{'ok':False,'error':'Nenalezeno'})
            target=Path(__file__).parent/'gui_static'/asset
            if not target.is_file() or _is_link(target):return self.json(404,{'ok':False,'error':'Chybí GUI soubory'})
            kind='image/x-icon' if asset.endswith('.ico') else 'image/png' if asset.endswith('.png') else 'text/html; charset=utf-8' if asset.endswith('html') else 'text/css; charset=utf-8' if asset.endswith('css') else 'text/javascript; charset=utf-8'
            return self.send_body(200,target.read_bytes(),kind)
        def do_POST(self):
            if not self.auth():
                # Consume a small already-sent body before closing; Windows
                # otherwise resets the socket and can hide the 403 response.
                # Never parse/execute it or wait indefinitely on a false size.
                timeout=self.connection.gettimeout()
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if 0<size<=65536:
                        self.connection.settimeout(1)
                        self.rfile.read(size)
                except (ValueError,OSError):pass
                finally:self.connection.settimeout(timeout)
                return self.json(403,{'ok':False,'error':'Požadavek nemá platný GUI token/původ'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=65536:return self.json(413,{'ok':False,'error':'Neplatná velikost požadavku'})
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.json(415,{'ok':False,'error':'Očekáván JSON'})
                payload=json.loads(self.rfile.read(size))
                if not isinstance(payload,dict):raise ValueError('Očekáván objekt JSON')
                path=urlsplit(self.path).path
                if path=='/api/start':value=service.start(payload)
                elif path=='/api/resume':value=service.resume(payload)
                elif path=='/api/pause':value=service.pause(payload.get('run_id'))
                elif path=='/api/close':value=service.close_research(payload.get('run_id'))
                elif path=='/api/comment':value=service.comment(payload)
                elif path=='/api/command':value=service.command(payload.get('command'))
                elif path=='/api/settings':value=service.settings(payload)
                elif path=='/api/profiles':value=service.create_profile(payload)
                elif path=='/api/profiles/delete':value=service.delete_profile(payload)
                elif path=='/api/defaults':value=service.defaults(payload)
                elif path=='/api/defaults/reset':value=service.defaults(payload,reset=True)
                elif path=='/api/open-cmd':value=service.open_cmd()
                elif path=='/api/approval':value=service.approval(payload)
                else:return self.json(404,{'ok':False,'error':'Neznámá API cesta'})
                return self.json(200,value)
            except (ValueError,OSError,sqlite3.Error,json.JSONDecodeError) as error:return self.json(400,{'ok':False,'error':str(error)})
        def do_OPTIONS(self):return self.json(403,{'ok':False,'error':'Cross-origin přístup není podporován'})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    return server


def serve(project=None, runs_root=None, port=0, open_browser=True):
    service=GUIService(project,runs_root);server=make_server(service,port)
    address=f'http://127.0.0.1:{server.server_port}/#token={service.token}'
    print('Metaweb Swarm GUI (pouze tento počítač): '+address,flush=True)
    print('Ctrl+C bezpečně vyžádá pauzu aktivního běhu. Zavření browser tabu běh nezastaví.',flush=True)
    if open_browser:webbrowser.open(address)
    try:server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:pass
    finally:service.shutdown();server.server_close()
    return 0
