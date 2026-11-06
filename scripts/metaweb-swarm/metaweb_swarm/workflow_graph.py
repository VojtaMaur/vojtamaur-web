"""Read-only, evidence-bound graph projection for the local dashboard.

Edges describe stored provenance, assignments and receipts, never inferred agent
messages. The stage sequence is a workflow schematic, not observed execution.
"""
MAX_NODES = 600
STAGES = [('coordination','Řízení'),('discovery','Průzkum'),('hypotheses','Náměty'),
          ('review','Kritika a rozpracování'),('ideas','Nápady'),('execution','Experimenty a akce'),('report','Report')]


def _text(value,limit=1800):
    return value[:limit] if isinstance(value,str) else ''


def build_workflow(state, *, running=False, report_exists=False, hypotheses=None, activity=None):
    nodes={};edges={};omitted=0
    def node(ident,kind,title,stage,status='',**details):
        nonlocal omitted
        if not isinstance(ident,str) or not ident:return
        key=kind+':'+ident
        if key not in nodes and len(nodes)>=MAX_NODES:omitted+=1;return
        nodes[key]={'id':key,'ref':ident,'kind':kind,'label':_text(title,240) or ident,
                    'stage':stage,'status':_text(status,80),'details':details}
        return key
    def edge(source,target,kind,label,detail='',active=False):
        if source not in nodes or target not in nodes or source==target:return
        key=(source,target,kind)
        if key in edges:
            edges[key]['count']+=int(kind=='review')
            # Preserve newest recorded judgment, never call it an active task.
            edges[key].update(detail=_text(detail,900) or edges[key]['detail'],active=edges[key]['active'] or active)
        else:edges[key]={'source':source,'target':target,'kind':kind,'label':label,
                         'detail':_text(detail,900),'active':bool(active),'count':1}
    activity_by_agent={item.get('agent_id'):item for item in activity or []}
    agents=state.get('agents',[])
    for a in agents:
        role=a.get('work_kind','DISCOVERY');stage={'COORDINATION':'coordination','REVIEW':'review','LOCAL':'execution','SYNTHESIS':'report'}.get(role,'discovery')
        if a.get('role')=='Candidate Developer':stage='review'
        status=a.get('status','UNKNOWN')
        if status=='RUNNING' and not running:status='INTERRUPTED'
        node(a.get('id'),'agent',a.get('display_name') or a.get('role'),stage,status,
             role=_text(a.get('role'),160),mission=_text(a.get('mission'),4000),
             model=_text(a.get('model'),160),tier=_text(a.get('model_tier'),20),
             activity=_text(activity_by_agent.get(a.get('id'),{}).get('text'),500),
             rounds=a.get('rounds',0),summary=_text(a.get('summary')),reason=_text(a.get('reason_for_stopping')))
    hyps=hypotheses if hypotheses is not None else state.get('brainstorm_hypotheses',[])
    for h in hyps:
        node(h.get('id'),'hypothesis',h.get('title') or h.get('provider'),'hypotheses',h.get('development_status') or h.get('status','UNREVIEWED'),
             summary=_text(h.get('mechanism')),provider=_text(h.get('provider'),160),meaning='Pracovní námět, nikoli ověřená nebo realizovaná IDEA.')
    for i in state.get('ideas',[]):
        node(i.get('id'),'idea',i.get('title') or i.get('provider'),'ideas',i.get('status','UNKNOWN'),
             summary=_text(i.get('summary') or i.get('mechanism')),reason=_text(i.get('blocker')),
             next_action=_text(i.get('next_action')),provider=_text(i.get('provider'),160))
    for group,kind,label in [('experiments','experiment','Docker experiment'),('tests','test','Záznam testu'),('approvals','approval','Schválení'),('external_actions','action','Externí akce')]:
        for item in state.get(group,[]):
            node(item.get('id'),kind,label+' · '+str(item.get('idea_id') or item.get('id') or ''),'execution',item.get('status','RECORDED'),
                 summary=_text(item.get('description') or item.get('summary') or item.get('reason')),
                 meaning='Záznam provedení sám nepotvrzuje správnost ani úplnost mechanismu.' if kind=='test' else '')
    receipts=[a.get('research_report_receipt') for a in agents if a.get('research_report_receipt')]
    if report_exists or receipts:
        node('SWARM_REPORT.md','report','SWARM_REPORT.md','report','RECORDED',
             summary='Uložený report běhu. Jeho existence sama neznamená, že všichni agenti dokončili práci nebo že byly nápady realizovány.')
    # Only IDs present in the captured state can become endpoints.
    for a in agents:
        agent='agent:'+a['id']
        edge('agent:'+str(a.get('parent_id')),agent,'spawn','vytvořil specialistu',a.get('creation_reason',''))
        for field in ('review_assignment','research_assignment'):
            task=a.get(field) or {};target=task.get('target_id')
            if not target:continue
            ref=next((key for key,n in nodes.items() if n['ref']==target and n['kind']!='agent'),None)
            live=running and a.get('status')=='RUNNING'
            edge(agent,ref,'assignment','pracuje na' if live else 'přidělený úkol',str(task.get('kind','')),active=live)
        dev=a.get('development_assignment')
        if isinstance(dev,str):edge(agent,'hypothesis:'+dev,'assignment','rozpracovává' if running and a.get('status')=='RUNNING' else 'přidělený námět',active=running and a.get('status')=='RUNNING')
    for h in hyps:
        for contributor in h.get('contributors',[]):edge('agent:'+str(contributor),'hypothesis:'+h['id'],'contribution','přispěl k námětu')
        if h.get('idea_id'):edge('hypothesis:'+h['id'],'idea:'+h['idea_id'],'promotion','rozpracováno v IDEA')
    for i in state.get('ideas',[]):
        for contributor in sorted(set(i.get('contributors',[]))|{i.get('agent_id','')}):edge('agent:'+str(contributor),'idea:'+i['id'],'contribution','přispěl k nápadu')
    for review in state.get('hypothesis_reviews',[]):
        edge('agent:'+str(review.get('agent_id')),'hypothesis:'+str(review.get('hypothesis_id')),'review','posoudil námět',str(review.get('verdict',''))+' · '+str(review.get('reason','')))
    for job in state.get('hypothesis_development',{}).get('jobs',[]):
        edge('agent:'+str(job.get('agent_id')),'hypothesis:'+str(job.get('hypothesis_id')),'development','rozpracoval námět',str(job.get('status',''))+' · '+str(job.get('reason','')))
        if job.get('idea_id'):edge('hypothesis:'+str(job.get('hypothesis_id')),'idea:'+str(job['idea_id']),'promotion','rozpracováno v IDEA',job.get('reason',''))
    critiques=list(state.get('critiques',[]))
    # Legacy checkpoints may only retain the latest critique on the idea.
    known={c.get('id') for c in critiques if c.get('id')}
    critiques += [dict(i['critique'],idea_id=i['id']) for i in state.get('ideas',[]) if isinstance(i.get('critique'),dict) and i['critique'].get('id') not in known]
    for c in critiques:edge('agent:'+str(c.get('agent_id')),'idea:'+str(c.get('idea_id')),'review','posoudil nápad',str(c.get('verdict',''))+' · '+str(c.get('reason','')))
    for group,kind in [('experiments','experiment'),('tests','test'),('approvals','approval'),('external_actions','action')]:
        for item in state.get(group,[]):
            ref=kind+':'+str(item.get('id'))
            edge('agent:'+str(item.get('agent_id')),ref,'execution','zaznamenal akci')
            edge('idea:'+str(item.get('idea_id')),ref,'evidence','má navázaný záznam')
            review=item.get('prototype_review') or {}
            edge('agent:'+str(review.get('agent_id')),ref,'review','posoudil test',str(review.get('verdict',''))+' · '+str(review.get('reason','')))
    for receipt in receipts:
        edge('agent:'+str(receipt.get('agent_id')),'report:SWARM_REPORT.md','report','zapsal závěr',receipt.get('time',''))
        for ident in receipt.get('idea_ids',[]):edge('idea:'+str(ident),'report:SWARM_REPORT.md','report','zahrnuto v závěru')
    stages=[]
    for key,label in STAGES:
        selected=[n for n in nodes.values() if n['stage']==key]
        stages.append({'id':key,'label':label,'count':len(selected),
                       'active':sum(n['kind']=='agent' and n['status']=='RUNNING' and running for n in selected)})
    return {'schema_version':1,'nodes':list(nodes.values()),'edges':list(edges.values()),'stages':stages,
            'omitted_nodes':omitted,'running':bool(running),'updated_at':state.get('updated_at'),
            'notice':'Šipky jsou uložené vztahy a úkoly, nikoli přímé zprávy mezi agenty. Agenti se střídají po omezených kolech a k posuzování se mohou vracet. Přehled fází je schéma, nikoli časová osa.'}
