"""Early, explicitly unreviewed research hypotheses, separate from admitted IDEA."""
import hashlib,json
from urllib.parse import urlsplit,urlunsplit
from .storage import canonical,now
from .context import redact_text

def _url(value):
    try:
        p=urlsplit(str(value));host=p.hostname
        if p.scheme not in {'http','https'} or not host:return ''
        return urlunsplit((p.scheme,host+((':'+str(p.port)) if p.port else ''),p.path,'',''))[:1000]
    except ValueError:return ''

def _item(agent_id,title,mechanism,provider='',unknowns=(),source_urls=(),screen_status='',time='',seq=None):
    title=redact_text(str(title).strip())[:180];mechanism=redact_text(str(mechanism).strip())[:3500]
    key=hashlib.sha256(canonical([' '.join(title.casefold().split()),' '.join(mechanism.casefold().split())]).encode()).hexdigest()[:16]
    return {'id':'HYP-'+key,'title':title,'mechanism':mechanism,'provider':redact_text(str(provider))[:180],
            'unknowns':[redact_text(str(s))[:500] for s in unknowns][:8],
            'source_urls':[u for u in (_url(s) for s in source_urls) if u][:8],
            'status':'UNREVIEWED','screen_status':screen_status,'contributors':[agent_id],
            'created_at':time or now(),'last_updated':time or now(),'source_event_seq':seq,
            'meaning':'Working hypothesis only. Not admitted IDEA, verified novelty, scientific rejection or implemented preservation.'}

def _merge(items,item):
    existing=next((i for i in items if i['id']==item['id']),None)
    if existing:
        existing['contributors']=list(dict.fromkeys(existing['contributors']+item['contributors']))
        existing['source_urls']=list(dict.fromkeys(existing['source_urls']+item['source_urls']))[:8]
        existing['last_updated']=item['last_updated']
        if item.get('screen_status'):existing['screen_status']=item['screen_status']
        return existing
    if len(items)>=100:raise ValueError('Hypothesis portfolio full; revise current hypotheses or submit useful IDEA candidates')
    items.append(item);return item

def record(api,title,mechanism,unknowns,provider='',source_urls=None):
    if api.engine.state['config'].get('task_style')!='brainstorming' or api.agent.get('work_kind')!='DISCOVERY':raise ValueError('Hypotheses are for brainstorming discovery roles')
    if not isinstance(title,str) or not 1<=len(title.strip())<=180 or not isinstance(mechanism,str) or not 1<=len(mechanism.strip())<=3500:raise ValueError('Title needs 1..180 and mechanism 1..3500 characters')
    if not isinstance(unknowns,list) or len(unknowns)>8 or any(not isinstance(s,str) or len(s)>500 for s in unknowns):raise ValueError('Use up to 8 short unknowns')
    if source_urls is not None and (not isinstance(source_urls,list) or len(source_urls)>8):raise ValueError('Use up to 8 source URLs')
    with api.engine.mutex:
        item=_merge(api.engine.state.setdefault('brainstorm_hypotheses',[]),_item(api.agent['id'],title,mechanism,provider,unknowns,source_urls or []))
        api.event('hypothesis_recorded',item)
    return item

def capture_screen(api,provider,service_url,proposed_change,result):
    if api.engine.state['config'].get('task_style')!='brainstorming' or api.agent.get('work_kind')!='DISCOVERY' or not isinstance(proposed_change,str) or not proposed_change.strip():return
    with api.engine.mutex:
        items=api.engine.state.setdefault('brainstorm_hypotheses',[])
        if len(items)>=100:return
        item=_merge(items,_item(api.agent['id'],str(provider)+' — pracovní hypotéza',proposed_change,provider,
                    ['Primary evidence, novelty and preservation suitability need independent review.'],[service_url],str(result.get('status',''))))
        api.event('hypothesis_recorded',item)

def from_events(events):
    items=[]
    for event in events:
        data=event.get('data',{})
        if event.get('kind')!='sdk_tool_started' or data.get('name')!='screen_carrier':continue
        args=data.get('arguments',{})
        try:args=json.loads(args) if isinstance(args,str) else args
        except ValueError:continue
        if not isinstance(args,dict) or not isinstance(args.get('proposed_change'),str) or not args['proposed_change'].strip():continue
        provider=str(args.get('provider') or 'Unspecified carrier')[:150]
        item=_item(event.get('agent_id'),provider+' — pracovní hypotéza',args['proposed_change'],provider,
                ['Historical screening proposal, not independently admitted or reviewed.'],[args.get('service_url','')],time=event.get('time',''),seq=event.get('seq'))
        if len(items)<100 or any(i['id']==item['id'] for i in items):_merge(items,item)
    return items

def from_audit(db):
    rows=db.execute("""SELECT seq,json_extract(body,'$.agent_id'),json_extract(body,'$.time'),
        substr(json_extract(body,'$.data.arguments'),1,20000) FROM events
        WHERE json_extract(body,'$.kind')='sdk_tool_started' AND json_extract(body,'$.data.name')='screen_carrier'
        ORDER BY seq DESC LIMIT 200""").fetchall()
    return from_events([{'seq':seq,'agent_id':agent,'time':time,'kind':'sdk_tool_started','data':{'name':'screen_carrier','arguments':args}} for seq,agent,time,args in reversed(rows)])

def capture_existing(engine):
    with engine.mutex:
        items=engine.state.setdefault('brainstorm_hypotheses',[])
        for item in from_audit(engine.store.db):
            if len(items)<100 or any(i['id']==item['id'] for i in items):_merge(items,item)
        engine.store.commit(engine.state,'hypothesis_portfolio_retained',{'count':len(items),'meaning':'Unreviewed sketches, separate from admitted IDEA'})
