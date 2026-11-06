'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const state = {bootstrap:null,runs:[],run:null,selected:null,tab:'agents',cursor:0,job:null,lines:[],lastCommand:'',commands:[],commandIndex:0,polling:false,followJob:false,report:'',editorMode:'run',defaultsResetArmed:false,activityAgent:'',activityRun:null,activitySignature:'',activityShown:null};
  const fragment = new URLSearchParams(location.hash.slice(1));
  const freshToken = fragment.get('token');
  if (freshToken) { sessionStorage.setItem('swarm-gui-token',freshToken); history.replaceState(null,'',location.pathname+location.search); }
  const token = freshToken || sessionStorage.getItem('swarm-gui-token') || '';
  const agentName = agent => agent.display_name || agent.role;
  const number = n => Number(n || 0).toLocaleString('cs-CZ');
  const money = n => n == null ? '—' : '$' + Number(n).toFixed(2);
  const time = seconds => { const s=Math.max(0,Math.floor(Number(seconds)||0));return Math.floor(s/3600)+' h '+Math.floor(s%3600/60)+' min'; };
  const shortDate = text => { const date=new Date(text);return Number.isNaN(date.getTime()) ? String(text||'') : date.toLocaleString('cs-CZ',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}); };
  const statuses={COMPLETED:'Dokončeno',RUNNING:'Pracuje',INTERRUPTED:'Přerušeno',PENDING:'Čeká',PAUSED:'Pozastaveno',BLOCKED:'Blokováno',LIMIT_REACHED:'Dosažen limit',REJECTED:'Zamítnuto',INVESTIGATING:'Zkoumá se',DISCOVERED:'Navrženo',VERIFIED:'Ověřeno',PROTOTYPED:'Prototyp',UNKNOWN:'Neznámé',APPROVED:'Schváleno'};
  const statusLabel = value => statuses[value] || value || '—';
  function element(tag,attrs={},...children) {
    const node=document.createElement(tag);
    for (const [key,value] of Object.entries(attrs)) {
      if (key==='class') node.className=value;
      else if (key==='text') node.textContent=value == null ? '' : String(value);
      else if (key.startsWith('on') && typeof value==='function') node.addEventListener(key.slice(2),value);
      else if (value!==undefined && value!==null) node.setAttribute(key,String(value));
    }
    for (const child of children.flat()) if (child!=null) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    return node;
  }
  function badge(value) { return element('span',{class:'badge '+String(value||'neutral').toLowerCase(),text:statusLabel(value)}); }
  function empty(text) { return element('div',{class:'empty-state',text}); }
  let toastTimer;
  function toast(text,error=false) { clearTimeout(toastTimer);$('toast').textContent=text;$('toast').classList.toggle('error',error);$('toast').hidden=false;toastTimer=setTimeout(()=>$('toast').hidden=true,error?9000:4500); }
  function notice(text,error=false) { $('notice').textContent=text;$('notice').classList.toggle('error',error);$('notice').hidden=!text; }
  async function api(path,body) {
    const options={headers:{'X-Swarm-Token':token},cache:'no-store'};
    if (body!==undefined) {options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(body);}
    const response=await fetch(path,options);
    let data;
    try {data=await response.json();} catch {throw new Error('Lokální server nevrátil čitelnou odpověď.');}
    if (!response.ok || data.ok===false) throw new Error(data.error||data.message||'Požadavek se nepodařilo provést.');
    return data;
  }
  async function act(path,body,button) {
    if(button)button.disabled=true;
    try {
      const response=await api(path,body);
      if(response.job) {state.job=response.job;state.followJob=path==='/api/start'||path==='/api/command';}
      toast(response.message||'Příkaz byl přijat.');
      if(['/api/settings','/api/defaults','/api/defaults/reset','/api/profiles','/api/profiles/delete'].includes(path))return response;
      await pollJob(); await refreshRuns();
      if(state.selected) await loadRun(state.selected,false);
      return response;
    } catch(error) {toast(error.message,true);return null;}
    finally {if(button)button.disabled=false;updateControls();}
  }
  function isActive() { return Boolean(state.job?.active); }
  function runPath(id=state.selected) {
    const root=state.bootstrap?.runs_root||'';
    return root.replace(/[\\/]$/,'')+(root.includes('\\')?'\\':'/')+id;
  }
  function quoted(text) {return '"'+String(text).replace(/"/g,'')+'"';}
  function currentCommand() {return state.lastCommand || (state.selected?'swarm.py resume '+quoted(runPath())+' --backend '+(state.run?.backend||'openai'):'run.cmd');}
  function clearSelection() {
    state.selected=null;state.run=null;state.report='';state.followJob=false;state.activityRun=null;state.activityAgent='';state.activitySignature='';state.activityShown=null;
    state.lastCommand='';state.commands=[];state.commandIndex=0;
    $('command-input').value='';$('runtime-comment').value='';
    $('run-content').hidden=true;$('welcome').hidden=false;
    $('top-location').textContent='Přehled';
    $('run-eyebrow').textContent='VÝZKUM, KTERÝ ZŮSTÁVÁ DOHLEDATELNÝ';
    $('run-title').textContent='Připraveno na další objev.';
    $('run-subtitle').textContent='Spusť nový výzkum nebo otevři některý z předchozích běhů.';
    $('run-status').replaceWith(element('span',{id:'run-status',class:'badge neutral',text:'PŘIPRAVENO'}));
    $('objective-text').textContent='';$('report-text').textContent='Report zatím není vybraný.';
    $('comment-state').textContent='';$('config-json').textContent='';
    $('agent-grid').replaceChildren();$('idea-list').replaceChildren();$('event-list').replaceChildren();$('approval-list').replaceChildren();$('activity-feed').replaceChildren();$('current-activity').replaceChildren();
    switchTab('agents');notice('');renderRuns();updateControls();
  }
  async function clipboard(text) {try {await navigator.clipboard.writeText(text);toast('Zkopírováno.');} catch {toast('Kopírování není dostupné. Text můžete označit ručně.',true);}}
  const workflow=new SwarmWorkflow({open:(kind,ref)=>{if(kind==='agent'){state.activityAgent=ref;switchTab('live');renderActivity();}else if(kind==='report'){switchTab('report');}else{switchTab(kind==='hypothesis'?'hypotheses':kind==='idea'?'ideas':'audit');
      const cards=[...document.querySelectorAll(kind==='hypothesis'?'#hypothesis-list details[data-hypothesis]':kind==='idea'?'#idea-list [data-idea]':'#approval-list [data-approval]')];
      const card=cards.find(card=>(card.dataset.hypothesis||card.dataset.idea||card.dataset.approval)===ref);
      if(card){if(card.tagName==='DETAILS')card.open=true;card.scrollIntoView({block:'center',behavior:'smooth'});}
    }}});
  function renderRuns() {
    const term=$('run-search').value.toLowerCase();
    const items=state.runs.filter(run => [run.id,run.objective,run.status].join(' ').toLowerCase().includes(term));
    $('run-list').replaceChildren(...items.map(run => {
      const date=run.id?.match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/);
      const title=date ? date[3]+'. '+date[2]+'. '+date[1]+' · '+date[4]+':'+date[5] : run.id;
      const b=element('button',{class:'run-item'+(state.selected===run.id?' selected':''),'aria-current':state.selected===run.id?'page':'false',onclick:()=>loadRun(run.id)});
      b.append(element('div',{class:'run-top'},element('span',{text:title}),element('span',{class:'tiny-status'},element('i'),statusLabel(run.interrupted?'INTERRUPTED':run.status))));
      b.append(element('small',{text:run.id,title:run.id}),element('small',{text:(run.task_style==='brainstorming'?'Brainstorming':'Experimentální')+' · '+number(run.ideas)+' nápadů · '+number(run.hypotheses)+' námětů'}));
      return b;
    }));
    if(!items.length)$('run-list').append(element('div',{class:'sidebar-empty',text:state.runs.length?'Nic nenalezeno.':'Zatím žádné běhy. Začněte novým výzkumem.'}));
  }
  async function refreshRuns() {
    const data=await api('/api/runs');state.runs=data.runs||[];renderRuns();
    if(!state.selected && state.runs.length) await loadRun(state.runs[0].id,false);
  }
  function taskText(agent) {
    if(state.run?.interrupted&&agent.status==='RUNNING')return 'Proces už neběží; lze pokračovat z checkpointu.';
    if(agent.status==='COMPLETED')return agent.reason_for_stopping||agent.summary||'Přidělená práce je dokončená.';
    if(['BLOCKED','LIMIT_REACHED'].includes(agent.status)&&agent.reason_for_stopping)return agent.reason_for_stopping;
    const latest=(state.run.current_activity||[]).find(item=>item.agent_id===agent.id);
    if(agent.status==='RUNNING'&&latest?.text)return latest.text;
    if(agent.current_task) {
      if(typeof agent.current_task==='string')return agent.current_task;
      const label=[agent.current_task.kind,agent.current_task.target_id,agent.current_task.stage].filter(x=>x&&x!=='NONE').join(' · ');
      if(label)return label;
    }
    if(agent.last_action){const label=typeof agent.last_action==='string'?agent.last_action:agent.last_action.text||agent.last_action.kind;if(label)return label;}
    const assignment=agent.review_assignment||agent.research_assignment;
    if(assignment && assignment.kind!=='NONE')return [assignment.kind,assignment.target_id].filter(Boolean).join(' · ');
    return agent.status==='RUNNING'?'Pracuje na přiděleném zadání…':'Bez aktivního úkolu · čeká na další kolo.';
  }
  function agentCard(agent) {
    const config=state.run.config||{};
    const limit=agent.round_limit||config.role_round_limits?.[agent.role]||config.max_agent_rounds||0;
    const interrupted=state.run?.interrupted&&agent.status==='RUNNING';
    const card=element('article',{class:'agent-card'+(agent.status==='RUNNING'&&!interrupted?' active-agent':'')});
    const identity=element('div',{class:'agent-identity'},element('div',{class:'agent-avatar',text:agentName(agent)?.split(/[ /]+/).filter(Boolean).slice(0,2).map(x=>x[0]).join('')||'A'}),element('div',{},element('div',{class:'agent-name',text:agentName(agent)}),element('div',{class:'agent-id',text:agent.id+(agent.parent_id?' · emergentní':'')})));
    card.append(element('div',{class:'agent-card-top'},identity,badge(interrupted?'INTERRUPTED':agent.status)));
    card.append(element('div',{class:'agent-meta'},element('span',{class:'tier '+(agent.model_tier||''),text:agent.model_tier||'tier'}),element('span',{text:agent.model||config.model||'Nenastaveno'}),element('span',{text:'· '+number(agent.rounds)+' / '+limit+' kol'})));
    card.append(element('div',{class:'agent-task',text:taskText(agent)}));
    const details=element('details',{},element('summary',{text:'Zadání a poslední závěr'}));
    if(agent.mission)details.append(element('p',{text:agent.mission}));
    if(agent.summary)details.append(element('p',{text:agent.summary}));
    if(agent.usage)details.append(element('p',{text:'Spotřeba: '+number(agent.usage.total_tokens)+' tokenů'}));
    if(agent.handoff_leads?.length)details.append(element('p',{text:'Předání: '+agent.handoff_leads.join(' · ')}));
    card.append(details);
    card.append(element('button',{type:'button',class:'activity-link',text:'Zobrazit činnost →',onclick:()=>{state.activityAgent=agent.id;switchTab('live');renderActivity();}}));
    return card;
  }
  function activityTime(value) {
    const date=new Date(value);
    return Number.isNaN(date.getTime())?String(value||''):date.toLocaleTimeString('cs-CZ',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
  }
  function activityDetail(value) {return value==null?'':typeof value==='string'?value:JSON.stringify(value,null,2);}
  function renderActivity() {
    const run=state.run,agents=run.agents||[],filter=$('activity-filter'),feed=$('activity-feed');
    const changedRun=state.activityRun!==run.run_id;
    if(changedRun){state.activityRun=run.run_id;state.activityAgent='';state.activitySignature='';}
    if(state.activityAgent&&!agents.some(agent=>agent.id===state.activityAgent))state.activityAgent='';
    const signature=agents.map(agent=>agent.id+':'+agentName(agent)).join('|');
    if(filter.dataset.agents!==signature){filter.replaceChildren(element('option',{value:'',text:'Celý tým'}),...agents.map(agent=>element('option',{value:agent.id,text:agentName(agent)+' · '+agent.id})));filter.dataset.agents=signature;}
    filter.value=state.activityAgent;
    const latest=new Map((run.current_activity||[]).map(item=>[item.agent_id,item]));
    const current=agents.filter(agent=>!state.activityAgent||agent.id===state.activityAgent);
    $('current-activity').replaceChildren(...current.map(agent=>{
      const entry=latest.get(agent.id),interrupted=run.interrupted&&agent.status==='RUNNING';
      const card=element('article',{class:'activity-current-card'+(agent.status==='RUNNING'&&!interrupted?' is-working':'')});
      card.append(element('div',{class:'activity-current-heading'},element('strong',{text:agentName(agent)}),badge(interrupted?'INTERRUPTED':agent.status)));
      const task=taskText(agent),detail=activityDetail(entry?.detail);
      card.append(element('p',{text:task}));
      if(detail&&detail.trim()!==String(task).trim())card.append(element('div',{class:'activity-current-detail',text:detail}));
      card.append(element('small',{text:agent.id+(entry?.time?' · poslední aktivita '+activityTime(entry.time):' · zatím bez zaznamenaného volání nástroje')}));
      return card;
    }));
    if(!current.length)$('current-activity').append(empty('Aktivita se objeví, jakmile začne pracovat první agent.'));
    const all=run.activity||run.events||[],matching=all.filter(item=>!state.activityAgent||item.agent_id===state.activityAgent),entries=matching.slice(-400);
    $('activity-count').textContent=number(entries.length)+' posledních záznamů'+(matching.length>400?' z '+number(matching.length):'')+' · podrobnosti rozbalíte u jednotlivých událostí';
    const newSignature=run.run_id+'|'+state.activityAgent+'|'+JSON.stringify(entries);
    if(state.tab==='live'&&state.activitySignature!==newSignature){
      const scrollTop=feed.scrollTop,atBottom=feed.scrollHeight-feed.clientHeight-feed.scrollTop<55;
      const expanded=new Set([...feed.querySelectorAll('details[open]')].map(item=>item.dataset.key));
      const names=new Map(agents.map(agent=>[agent.id,agentName(agent)]));
      feed.replaceChildren(...entries.map((entry,index)=>{
        const key=String(entry.seq??entry.time+'-'+index),detail=activityDetail(entry.detail);
        const line=element('article',{class:'activity-entry'});
        line.append(element('div',{class:'activity-entry-meta'},element('time',{text:activityTime(entry.time),datetime:entry.time||''}),element('strong',{text:names.get(entry.agent_id)||entry.agent_id||'Swarm'}),element('span',{text:entry.kind||'aktivita'})));
        line.append(element('p',{text:entry.text||'Událost bez textového popisu.'}));
        if(detail){const details=element('details',{},element('summary',{text:'Podrobnosti'}),element('pre',{text:detail}));details.dataset.key=key;details.open=expanded.has(key);line.append(details);}
        return line;
      }));
      if(!entries.length)feed.append(empty('Zatím žádné záznamy pro tento výběr. U starších běhů nemusí být podrobnosti nástrojů uložené.'));
      if(state.activityShown!==run.run_id||($('activity-follow').checked&&atBottom))feed.scrollTop=feed.scrollHeight;
      else feed.scrollTop=scrollTop;
      state.activitySignature=newSignature;state.activityShown=run.run_id;
    }
    const preview=run.live_output,out=$('live-text'),atBottom=out.scrollHeight-out.clientHeight-out.scrollTop<40,oldTop=out.scrollTop;
    $('live-label').textContent=preview?[preview.agent_id,shortDate(preview.time),preview.data?.partial?'Generuje…':'Odpověď dokončena'].filter(Boolean).join(' · '):'';
    const text=preview?.data?.text||'Zatím žádný veřejný text odpovědi. Agent může mezitím hledat nebo používat nástroje; sledujte podrobný průběh výše. U starších běhů textový náhled nemusí být uložený.';
    if(out.textContent!==text){out.textContent=text;out.scrollTop=atBottom?out.scrollHeight:oldTop;}
  }
  function renderIdeas() {
    const ideas=state.run.ideas||[];
    $('idea-list').replaceChildren(...ideas.map(idea => {
      const card=element('article',{class:'idea-card','data-idea':idea.id},element('div',{class:'idea-heading'},element('div',{},element('div',{class:'idea-id',text:idea.id}),element('h3',{text:idea.title||idea.provider})),badge(idea.status)));
      card.append(element('p',{text:idea.summary||idea.mechanism||'Dosud bez shrnutí.'}));
      if(idea.critique)card.append(element('div',{class:'idea-extra',text:'Posouzení: '+(idea.critique.verdict||'—')+' · '+(idea.critique.reason||'')}));
      if(idea.next_action)card.append(element('div',{class:'idea-extra',text:'Další krok: '+idea.next_action}));
      if(idea.blocker)card.append(element('div',{class:'idea-extra',text:'Překážka: '+idea.blocker}));
      card.append(element('div',{class:'idea-extra',text:'Platby: '+(idea.payment||'UNKNOWN')+(idea.closure_provisional?' · Provizorně zachycený návrh, identita není potvrzená.':'')}));
      return card;
    }));
    if(!ideas.length)$('idea-list').append(empty('Zatím žádný formálně zapsaný nápad. První směry mohou být zachycené na samostatné kartě Náměty.'));
    const hypotheses=state.run.hypotheses||[],open=new Set([...$('hypothesis-list').querySelectorAll('details[open]')].map(node=>node.dataset.hypothesis));
    const development=state.run.hypothesis_development||{};
    $('development-summary').replaceChildren(...(development.jobs||[]).map(job=>element('p',{class:'field-note',text:'Rozpracování '+job.hypothesis_id+' · '+job.status+(job.idea_id?' → '+job.idea_id:'')+(job.reason?' · '+job.reason:'')})));
    if(development.reason)$('development-summary').append(element('p',{class:'field-note',text:development.reason}));
    $('hypothesis-tab-count').textContent=number(hypotheses.length);
    $('hypothesis-count').textContent=number(hypotheses.length)+' pracovních směrů';
    $('hypothesis-list').replaceChildren(...hypotheses.slice(0,100).map(item=>{
      const id=item.id||item.hypothesis_id||item.title;
      const card=element('details',{class:'hypothesis-card'});card.dataset.hypothesis=id;card.open=open.has(id);
      card.append(element('summary',{},element('span',{class:'idea-id',text:item.id||item.hypothesis_id||'HYP'}),element('strong',{text:item.title||item.provider||'Pracovní hypotéza'}),element('span',{class:'hypothesis-label',text:'Neověřené'})));
      const body=element('div',{class:'hypothesis-body'});
      if(item.development_status||item.idea_id)body.append(element('p',{text:'Rozpracování: '+(item.development_status||'')+(item.idea_id?' → '+item.idea_id:'')}));
      if(item.mechanism)body.append(element('p',{text:item.mechanism}));
      for(const r of (state.run.hypothesis_reviews||[]).filter(r=>r.hypothesis_id===item.id))body.append(element('p',{text:'Předběžná kritika · '+r.agent_id+' · '+r.verdict+': '+r.reason}),element('p',{text:'Další krok: '+(r.next_action||'Neurčen')}));
      if(item.provider)body.append(element('p',{text:'Služba / prostředí: '+item.provider}));
      if(item.unknowns?.length)body.append(element('h3',{text:'Co zbývá zjistit'}),element('ul',{},...item.unknowns.map(unknown=>element('li',{text:unknown}))));
      if(item.source_urls?.length)body.append(element('details',{},element('summary',{text:'Zdroje průzkumu'}),element('pre',{text:item.source_urls.join('\n')})));
      body.append(element('div',{class:'field-note',text:[item.screen_status,item.contributors?.length?'Přispěli: '+item.contributors.join(', '):'',item.last_updated?shortDate(item.last_updated):''].filter(Boolean).join(' · ')}));
      card.append(body);return card;
    }));
    if(!hypotheses.length)$('hypothesis-list').append(empty('Zatím žádné zachycené hypotézy. U starších běhů tento pracovní přehled nemusí být k dispozici.'));
    if(hypotheses.length>100)$('hypothesis-list').append(element('p',{class:'field-note',text:'Zobrazeno prvních 100 hypotéz. Úplné podklady zůstávají v auditních artefaktech běhu.'}));
  }
  function renderParameters() {
    const c=state.run.config||{};
    const rows=[['Režim',c.task_style],['Autonomie',c.run_mode],['Externí rozsah',c.external_scope],['Schvalování',c.approval_required?'Vyžadováno':'Vypnuto'],['Experimenty',c.experiments],['Instalace balíčků',c.package_installation],['Max. tokenů',number(c.max_total_tokens)],['Aktivní čas',time(c.max_active_seconds)],['Max. kol',number(c.max_steps)],['Max. agentů',number(c.max_agents)],['Tahů v kole',number(c.max_turns)],['USD limit',c.estimated_budget_usd==null?'Nenastaven':money(c.estimated_budget_usd)]];
    $('parameter-grid').replaceChildren(...rows.map(([label,value])=>element('div',{class:'parameter-item'},element('span',{text:label}),String(value??'—'))));
    $('config-json').textContent=JSON.stringify(c,null,2);
  }
  function renderAudit() {
    const pending=(state.run.approvals||[]).filter(x=>x.status==='PENDING');
    $('approval-list').replaceChildren(...pending.map(item => {
      const card=element('div',{class:'approval-card'},element('h3',{text:item.description||item.action?.description||item.id}),element('pre',{text:JSON.stringify(item,null,2)}));
      const decide=async decision=>{
        if(!confirm((decision==='approve'?'Schválit':'Zamítnout')+' tuto konkrétní akci?'))return;
        const note=prompt('Stručný důvod rozhodnutí:');if(!note?.trim())return;
        await act('/api/approval',{run_id:state.selected,approval_id:item.id,decision,note});
      };
      card.append(element('div',{class:'approval-actions'},element('button',{class:'button primary',text:'Schválit',onclick:()=>decide('approve')}),element('button',{class:'button',text:'Zamítnout',onclick:()=>decide('reject')})));
      return card;
    }));
    if(!pending.length)$('approval-list').append(empty('Žádná akce právě nečeká na schválení.'));
    const events=state.run.events||[];
    $('event-list').replaceChildren(...events.slice(-50).reverse().map(event=>{
      const label=[event.agent_id,event.text||event.kind].filter(Boolean).join(' · ');
      return element('div',{class:'event-item'},element('span',{class:'event-time',text:shortDate(event.time)}),element('span',{class:'event-text',text:label}));
    }));
    if(!events.length)$('event-list').append(element('div',{class:'empty-state',text:'Zatím bez zaznamenané aktivity.'}));
  }
  function updateControls() {
    const running=Boolean(state.run?.running);
    $('resume-open').disabled=!state.selected||isActive()||running;
    $('pause-run').disabled=!state.selected||!running;
    $('close-run').disabled=!state.selected||isActive()||running;
    $('new-run').disabled=isActive();
    $('welcome-new').disabled=isActive();
  }
  function renderRun() {
    const run=state.run,c=run.config||{},agents=run.agents||[],ideas=run.ideas||[];
    $('welcome').hidden=true;$('run-content').hidden=false;
    $('top-location').textContent=run.run_id;$('run-eyebrow').textContent='BĚH / '+run.run_id;
    $('run-title').textContent=c.task_style==='brainstorming'?'Výzkum a brainstorming':'Experimentální realizace';
    $('run-subtitle').textContent=run.interrupted?'Proces už neběží; lze pokračovat z checkpointu.':run.stop_reason||'Běh je připravený.';
    const status=badge(run.interrupted?'INTERRUPTED':run.status);status.id='run-status';$('run-status').replaceWith(status);
    $('stat-tokens').textContent=number(run.usage?.total_tokens);
    $('token-limit').textContent='z '+number(c.max_total_tokens)+' tokenů';
    $('token-meter').style.width=Math.min(100,(run.usage?.total_tokens||0)/(c.max_total_tokens||1)*100)+'%';
    $('stat-time').textContent=time(run.active_seconds);$('time-limit').textContent='limit '+time(c.max_active_seconds);
    $('stat-cost').textContent=money(run.usage_estimated_usd);
    $('stat-ideas').textContent=number(ideas.length)+' + '+number((run.hypotheses||[]).length)+' námětů';
    $('step-limit').textContent=number(ideas.length)+' návrhů · '+number(run.steps)+' z '+number(c.max_steps)+' kol';
    $('mode-label').textContent=(c.task_style==='brainstorming'?'Brainstorming · bez realizace':'Experimentální prototyp · '+c.run_mode)+(run.research_closure?.report_only?' · závěrečná syntéza':'');
    $('objective-text').textContent=run.objective||'Zadání není k dispozici.';
    $('agent-count').textContent=agents.length;$('idea-count').textContent=ideas.length;
    const open=new Set([...document.querySelectorAll('.agent-card details[open]')].map(node=>node.closest('.agent-card').dataset.agent));
    $('agent-grid').replaceChildren(...agents.map(a=>{const card=agentCard(a);card.dataset.agent=a.id;if(open.has(a.id))card.querySelector('details').open=true;return card;}));
    if(!agents.length)$('agent-grid').append(empty('V tomto běhu nejsou žádní agenti.'));
    $('agent-progress-note').textContent=(run.interrupted?'Přerušeno · ':agents.filter(a=>a.status==='RUNNING').length+' pracuje · ')+agents.filter(a=>a.status==='COMPLETED').length+' dokončeno';
    renderIdeas();renderParameters();renderAudit();renderActivity();updateControls();workflow.update(run);
    const comments=run.operator_comments||[];
    const pendingComments=run.pending_comments||run.pending_operator_comments||comments.filter(c=>c.status==='QUEUED');
    $('comment-state').textContent=run.status==='COMPLETED'?'Komentář sám dokončený běh znovu nespustí; pro nové zadání založte nový běh.':pendingComments.length?number(pendingComments.length)+' komentářů čeká na další kolo.':comments.length?'Poslední předaný komentář: '+(comments[comments.length-1].text||comments[comments.length-1].comment||'zaznamenán'):'';
  }
  async function loadRun(id,showError=true) {
    try {
      const data=await api('/api/run?id='+encodeURIComponent(id));
      if(state.selected!==id)state.report='';
      state.selected=id;state.run=data.state||data;
      renderRun();renderRuns();notice('');
      if(state.tab==='report')await loadReport();
    } catch(error) {if(showError)toast(error.message,true);}
  }
  async function loadReport() {
    if(!state.selected)return;
    try {const result=await api('/api/report?id='+encodeURIComponent(state.selected));state.report=result.text||'Report zatím nevznikl.';$('report-text').textContent=state.report;}
    catch(error){$('report-text').textContent=error.message;}
  }
  function switchTab(tab) {
    state.tab=tab;
    document.querySelectorAll('[data-tab]').forEach(button=>{const selected=button.dataset.tab===tab;button.classList.toggle('active',selected);button.setAttribute('aria-selected',String(selected));});
    document.querySelectorAll('.tab-panel').forEach(panel=>panel.hidden=panel.id!=='panel-'+tab);
    if(tab==='workflow'&&state.run)workflow.update(state.run,true);
    if(tab==='report')loadReport();
    if(tab==='live'&&state.run)renderActivity();
  }
  function appendConsole(lines) {
    if(!lines.length)return;
    const out=$('console-output'),atBottom=out.scrollHeight-out.scrollTop-out.clientHeight<45;
    state.lines.push(...lines);state.lines=state.lines.slice(-900);out.textContent=state.lines.join('\n');
    if(atBottom)out.scrollTop=out.scrollHeight;
  }
  async function pollJob() {
    const data=await api('/api/job?cursor='+state.cursor);
    state.cursor=data.cursor??state.cursor;state.job=data.job||null;
    appendConsole((data.lines||[]).map(line=>typeof line==='string'?line:line.text||''));
    $('job-status').textContent=state.job?.active?'běží · '+state.job.kind:state.job?('ukončeno · exit '+(state.job.exit_code??'—')):'připraveno';
    if(state.followJob&&state.job?.run_id){state.followJob=false;await loadRun(state.job.run_id,false);}
    updateControls();
  }
  async function poll() {
    if(state.polling)return;state.polling=true;
    try {
      await pollJob();
      if(state.selected)await loadRun(state.selected,false);
      const data=await api('/api/runs');state.runs=data.runs||[];renderRuns();
      $('connection-dot').classList.add('online');$('connection-text').textContent='Připojeno k lokálnímu GUI';
    } catch(error) {$('connection-dot').classList.remove('online');$('connection-text').textContent='Připojení přerušeno';}
    finally{state.polling=false;}
  }
  function profile() {return state.bootstrap?.profiles.find(p=>p.id===$('profile-select').value);}
  function roleTier(role,config) {
    return config.role_model_tiers?.[role]||({'Meta-Archivist / Orchestrator':'flag','Loophole Archivist':'flag','Hostile Reviewer':'flag','Synthesizer / Reporter':'flag','Infrastructure Scout':'cheap','Role Architect':'cheap'}[role]||'strong');
  }
  function updateRoleModels() {
    document.querySelectorAll('.role-edit-row').forEach(row=>{const tier=row.querySelector('select').value;row.querySelector('small').textContent=$('model-'+tier).value||'Model není nastaven';});
  }
  function loadProfile() {
    const p=profile();if(!p)return;
    state.defaultsResetArmed=false;$('defaults-reset').textContent='Obnovit původní profil';
    const c=p.config||{},editingDefaults=state.editorMode==='defaults';
    state.profileDeleteArmed=false;
    $('profile-name').value=p.custom?p.name:'';
    $('profile-delete').hidden=!p.custom;$('profile-delete').textContent='Smazat profil';
    $('profile-update').hidden=!p.custom;
    $('defaults-reset').hidden=!editingDefaults||p.custom;
    $('editor-scope').textContent=editingDefaults?'Uloží se pro příští nové běhy s tímto profilem. Existující běhy se nezmění. Uložení nespouští model ani nový běh.':'Úpravy platí pouze pro tento nový běh. Uložené výchozí nastavení profilu nezmění.';
    $('full-objective').value=p.objective||c.operator_objective||'';
    $('custom-agents').replaceChildren();(c.custom_agents||[]).forEach(addCustomAgent);
    $('profile-defaults-note').textContent=p.custom?'Vlastní uložený profil. Změny můžete uložit výše, nebo je použít jen pro tento běh.':p.has_saved_defaults?'Načtené vlastní výchozí nastavení tohoto profilu.':'Načtený původní profil projektu; vlastní výchozí nastavení zatím není uložené.';
    $('profile-description').textContent=c.task_style==='brainstorming'?'Výzkum → nezávislá kritika → report. Bez Dockeru, instalace balíčků a externích zápisů.':'Volitelná experimentální realizace. Docker/PyPI a externí oprávnění podle zachyceného profilu.';
    $('experimental-warning').hidden=c.task_style==='brainstorming';
    $('start-button').textContent=editingDefaults?'Uložit výchozí nastavení':c.task_style==='brainstorming'?'Spustit nový běh ↗':'Spustit experimentální běh ↗';
    for(const tier of ['cheap','strong','flag'])$('model-'+tier).value=c.model_tiers?.[tier]||c.model||'';
    for(const [id,key] of [['limit-tokens','max_total_tokens'],['limit-steps','max_steps'],['limit-agents','max_agents'],['limit-turns','max_turns'],['limit-output','max_output_tokens']])$(id).value=c[key]||1;
    $('limit-minutes').value=Math.ceil((c.max_active_seconds||3600)/60);
    $('limit-concurrency').value=c.max_concurrent_agents||1;
    $('development-count').value=c.brainstorm_development_candidates??3;
    $('development-rounds').value=c.brainstorm_development_rounds??2;
    $('development-settings').hidden=c.task_style!=='brainstorming';
    $('limit-usd').value=c.estimated_budget_usd??'';
    $('defaults-reset').disabled=!p.has_saved_defaults;
    $('profile-policy').textContent=JSON.stringify(Object.fromEntries(['task_style','run_mode','external_scope','approval_required','experiments','package_installation','http_access','max_external_actions'].map(k=>[k,c[k]])),null,2);
    const roles=state.bootstrap.role_catalog||p.agents||p.roles||[];
    const selected=new Set(c.seed_roles?.length?c.seed_roles:roles.map(r=>r.role));
    const header=element('div',{class:'role-edit-header'},element('span',{text:'Role'}),element('span',{text:'Tier'}),element('span',{text:'Max. kol',title:'Maximální počet pracovních kol tohoto agenta'}));
    $('role-editor').replaceChildren(header,...roles.filter(r=>c.task_style!=='brainstorming'||r.role!=='Prototyper').map(r=>{
      const row=element('div',{class:'role-edit-row'});row.dataset.role=r.role;
      const input=element('input',{type:'checkbox','aria-label':'Zapnout '+r.role});input.checked=selected.has(r.role);
      const name=element('input',{type:'text',class:'role-display-name',maxlength:160,value:c.role_display_names?.[r.role]||r.role,'aria-label':'Název agenta '+r.role});
      const identity=element('div',{},element('div',{class:'role-name-editor'},input,name),element('small'));
      identity.append(element('div',{class:'role-type',text:'Role: '+r.role}));
      const tier=element('select',{'aria-label':'Tier pro '+r.role},...['cheap','strong','flag'].map(t=>element('option',{value:t,text:t})));tier.value=roleTier(r.role,c);tier.addEventListener('change',updateRoleModels);
      const rounds=element('input',{type:'number',min:1,value:c.role_round_limits?.[r.role]||c.max_agent_rounds||3,'aria-label':'Počet kol pro '+r.role});
      const mission=element('textarea',{rows:3,maxlength:4000,'aria-label':'Zadání role '+r.role});mission.value=c.role_assignments?.[r.role]||r.mission||'';mission.className='role-mission';
      const details=element('details',{},element('summary',{text:'Upravit zadání role'}),mission);identity.append(details);
      row.append(identity,tier,rounds);return row;
    }));updateRoleModels();
  }
  function addCustomAgent(agent={}) {
    const row=element('div',{class:'custom-agent objective-card'});
    row.append(element('label',{class:'field'},'Název role',element('input',{class:'custom-name',maxlength:160,required:true,value:agent.role||''})),
      element('label',{class:'field'},'Zadání',element('textarea',{rows:3,maxlength:4000,required:true,text:agent.mission||''})),
      element('label',{class:'field'},'Modelový tier',element('select',{},...['cheap','strong','flag'].map(t=>element('option',{value:t,text:t})))),
      element('label',{class:'field'},'Max. kol',element('input',{type:'number',min:1,max:100,value:agent.rounds||3,required:true})),
      element('button',{type:'button',class:'button small',text:'Odebrat agenta',onclick:()=>row.remove()}));
    row.querySelector('select').value=agent.model_tier||'strong';$('custom-agents').append(row);
  }
  $('add-custom-agent').addEventListener('click',()=>addCustomAgent());
  function showEditor(mode='run') {
    if(!state.bootstrap)return;
    state.editorMode=mode;const defaults=mode==='defaults';
    $('editor-eyebrow').textContent=defaults?'TRVALE ULOŽENÉ PROFILY':'NOVÝ IZOLOVANÝ BĚH';
    $('editor-title').textContent=defaults?'Výchozí nastavení':'Nastavte směr výzkumu.';
    $('editor-scope').textContent=defaults?'Uloží se pro příští nové běhy s tímto profilem. Existující běhy se nezmění. Uložení nespouští model ani nový běh.':'Úpravy platí pouze pro tento nový běh. Uložené výchozí nastavení profilu nezmění.';
    $('objective-label').textContent=defaults?'Výchozí zadání profilu':'Celé zadání tohoto běhu';
    $('new-task-field').hidden=defaults;$('new-task').disabled=defaults;$('new-task').value='';
    $('launch-section').hidden=defaults;$('defaults-reset').hidden=!defaults;
    $('start-note').textContent=defaults?'Uložení bez API volání.':'Vznikne nový běh mimo produkční strom.';
    loadProfile();
    $('new-key-note').textContent=state.bootstrap.api_key_present?'API klíč je nastaven. Nový OpenAI běh bude placený.':'API klíč zatím není nastaven. Přidejte ho v Nastavení připojení, nebo zvolte offline demo.';
    $('new-dialog').showModal();
  }
  function showNew() {showEditor('run');}
  function replaceProfile(fresh) {
    const index=state.bootstrap.profiles.findIndex(item=>item.id===fresh.id);
    if(index>=0)state.bootstrap.profiles[index]=fresh;
    else state.bootstrap.profiles.push(fresh);
    renderProfileOptions(fresh.id);
  }
  function renderProfileOptions(selected=$('profile-select').value) {
    $('profile-select').replaceChildren(...state.bootstrap.profiles.map(p=>element('option',{value:p.id,text:p.custom?p.name+' · vlastní':p.label||p.name||p.id})));
    $('profile-select').value=state.bootstrap.profiles.some(p=>p.id===selected)?selected:'research';
  }
  async function persistProfile(create,button) {
    let settings;try{settings=overrides();}catch(error){toast(error.message,true);return;}
    const name=$('profile-name').value.trim();
    if(!name){toast('Vyplňte název vlastního profilu.',true);$('profile-name').focus();return;}
    const result=await act(create?'/api/profiles':'/api/defaults',{profile:profile().id,name,overrides:settings,objective:$('full-objective').value.trim()},button);
    if(result?.profile){replaceProfile(result.profile);loadProfile();toast(create?'Nový profil uložen. Najdete ho v nabídce Režim a profil.':'Změny profilu uložené. Žádný běh se nespustil.');}
  }
  $('profile-save-as').addEventListener('click',event=>persistProfile(true,event.currentTarget));
  $('profile-update').addEventListener('click',event=>persistProfile(false,event.currentTarget));
  $('profile-name').addEventListener('input',()=>{state.profileDeleteArmed=false;$('profile-delete').textContent='Smazat profil';});
  $('profile-delete').addEventListener('click',async event=>{
    const p=profile();if(!p?.custom)return;
    if(!state.profileDeleteArmed){state.profileDeleteArmed=true;event.currentTarget.textContent='Potvrdit smazání profilu';toast('Druhým kliknutím smažete jen uložený profil. Dřívější běhy zůstanou.');return;}
    const result=await act('/api/profiles/delete',{profile:p.id},event.currentTarget);
    if(result){state.bootstrap.profiles=state.bootstrap.profiles.filter(item=>item.id!==p.id);renderProfileOptions(result.base_profile);loadProfile();toast('Profil smazán. Dřívější běhy zůstaly zachované.');}
  });
  function overrides() {
    const tiers=Object.fromEntries(['cheap','strong','flag'].map(t=>[t,$('model-'+t).value.trim()]));
    const result={brainstorm_development_candidates:Number($('development-count').value),brainstorm_development_rounds:Number($('development-rounds').value),model_tiers:tiers,seed_roles:[],role_display_names:{},role_model_tiers:{},role_round_limits:{},role_assignments:{},custom_agents:[],max_active_seconds:Number($('limit-minutes').value)*60,max_concurrent_agents:Number($('limit-concurrency').value),estimated_budget_usd:$('limit-usd').value===''?null:Number($('limit-usd').value)};
    for(const [id,key] of [['limit-tokens','max_total_tokens'],['limit-steps','max_steps'],['limit-agents','max_agents'],['limit-turns','max_turns'],['limit-output','max_output_tokens']])result[key]=Number($(id).value);
    document.querySelectorAll('.role-edit-row').forEach(row=>{if(!row.querySelector('input[type=checkbox]').checked)return;const role=row.dataset.role;result.seed_roles.push(role);result.role_display_names[role]=row.querySelector('.role-display-name').value.trim();result.role_assignments[role]=row.querySelector('.role-mission').value.trim();result.role_model_tiers[role]=row.querySelector('select').value;result.role_round_limits[role]=Number(row.querySelector('input[type=number]').value);});
    document.querySelectorAll('.custom-agent').forEach(row=>result.custom_agents.push({role:row.querySelector('.custom-name').value.trim(),mission:row.querySelector('textarea').value.trim(),model_tier:row.querySelector('select').value,rounds:Number(row.querySelector('input[type=number]').value)}));
    if(!result.seed_roles.length)throw new Error('Vyberte alespoň jednu roli.');
    if(result.max_agents<result.seed_roles.length+result.custom_agents.length)throw new Error('Maximum agentů musí pojmout celý vybraný výchozí tým.');
    if(result.max_concurrent_agents>result.max_agents)throw new Error('Souběžně nemůže pracovat více agentů, než je jejich maximum.');
    if(Object.values(result.role_display_names).some(name=>!name))throw new Error('Zapnutí agenti musí mít název.');
    if(Object.values(result.role_assignments).some(mission=>!mission))throw new Error('Zapnuté role musí mít vyplněné zadání.');
    const names=[...result.seed_roles,...result.custom_agents.map(agent=>agent.role)];
    if(new Set(names.map(name=>name.toLowerCase())).size!==names.length)throw new Error('Každý agent musí mít jedinečný název role.');
    return result;
  }
  document.querySelectorAll('.dialog-close').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
  document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>switchTab(button.dataset.tab)));
  let memoryData=null,memoryRequest=0;
  function renderMemory() {
    if(!memoryData)return;
    const term=$('memory-search').value.trim().toLowerCase();let candidates=0,sketchCount=0;
    const rows=(memoryData.entries||[]).filter(row=>JSON.stringify(row).toLowerCase().includes(term));
    const cards=rows.map(row=>{
      const card=element('article',{class:'idea-card'});
      card.append(element('div',{class:'idea-heading'},element('h3',{text:row.run_id||'Neznámý běh'}),badge(row.status)),element('p',{text:row.summary||'Bez shrnutí.'}));
      const matches=(row.candidates||[]).filter(c=>!term||JSON.stringify(c).toLowerCase().includes(term)||String(row.run_id).toLowerCase().includes(term));
      candidates+=matches.length;
      const sketches=(row.hypotheses||[]).filter(h=>!term||JSON.stringify(h).toLowerCase().includes(term)||String(row.run_id).toLowerCase().includes(term));
      sketchCount+=sketches.length; if(sketches.length)card.append(element('h3',{text:'Předběžné náměty · neověřené'}));
      for(const h of sketches){const detail=element('details',{class:'memory-candidate'},element('summary',{text:h.id+' · '+h.title+' · námět, neověřeno'}),element('p',{text:h.mechanism}),element('p',{text:'Nejistoty: '+(h.unknowns||[]).join('; ')}),element('p',{text:h.ref}));card.append(detail);}
      for(const c of matches.slice(0,100)){
        const detail=element('details',{class:'memory-candidate'},element('summary',{text:[c.id,c.title||c.provider,statusLabel(c.status)].filter(Boolean).join(' · ')}));
        for(const [label,value] of [['Mechanismus',c.mechanism],['Překážka',c.blocker],['Další krok',c.next_action],['Reference',c.ref]])if(value)detail.append(element('p',{text:label+': '+value}));
        detail.append(element('p',{text:'Zaznamenané lokální otestování: '+(c.tested_claim?'ano (historický záznam)':'ne')+' · artefakty: '+number(c.artifact_count)}));
        card.append(detail);
      }
      if(matches.length>100)card.append(element('p',{text:'Zobrazeno prvních 100 kandidátů tohoto běhu. Zpřesněte hledání nebo otevřete JSON.'}));
      card.append(element('button',{type:'button',class:'button small',text:'Otevřít původní běh',onclick:async()=>{try{await api('/api/run?id='+encodeURIComponent(row.run_id));$('memory-dialog').close();await loadRun(row.run_id);}catch(error){toast(error.message,true);}}}));
      return card;
    });
    $('memory-entries').replaceChildren(...cards);
    if(!cards.length)$('memory-entries').append(empty(memoryData.exists?'Žádné odpovídající záznamy.':memoryData.message));
    $('memory-stats').textContent=number(rows.length)+' / '+number(memoryData.entries.length)+' běhů · '+number(candidates)+' kandidátů · '+number(sketchCount)+' předběžných námětů'+(memoryData.truncated?' · Paměť je zkrácená.':'')+(memoryData.skipped?.length?' · Vynechané záznamy: '+number(memoryData.skipped.length):'');
  }
  async function loadMemory() {
    const request=++memoryRequest;
    $('memory-stats').textContent='Načítání…';$('memory-entries').replaceChildren();$('memory-json').textContent='';memoryData=null;$('memory-copy').disabled=true;
    try{
      const captured=$('memory-source').value==='captured';
      const data=await api('/api/memory'+(captured?'?id='+encodeURIComponent(state.selected):''));
      if(request!==memoryRequest)return;
      memoryData=data;$('memory-path').textContent=data.path+(data.updated_at?' · změněno '+shortDate(data.updated_at):'');$('memory-json').textContent=data.text||'Soubor neexistuje.';$('memory-copy').disabled=!data.exists;renderMemory();
    }catch(error){if(request===memoryRequest){$('memory-stats').textContent=error.message;$('memory-path').textContent='';}}
  }
  $('memory-open').addEventListener('click',()=>{$('memory-source').value='shared';$('memory-source').querySelector('[value=captured]').disabled=!state.selected;$('memory-search').value='';$('memory-dialog').showModal();loadMemory();});
  $('memory-source').addEventListener('change',loadMemory);$('memory-refresh').addEventListener('click',loadMemory);$('memory-search').addEventListener('input',renderMemory);$('memory-copy').addEventListener('click',()=>{if(memoryData?.exists)clipboard(memoryData.text);});
  $('new-run').addEventListener('click',showNew);$('welcome-new').addEventListener('click',showNew);
  $('defaults-open').addEventListener('click',()=>showEditor('defaults'));
  $('defaults-reset').addEventListener('click',async event=>{
    if(!state.defaultsResetArmed){
      state.defaultsResetArmed=true;event.currentTarget.textContent='Potvrdit obnovení profilu';
      $('editor-scope').textContent='Potvrďte druhým kliknutím: uložené vlastní zadání, tým, modely a limity tohoto profilu se odstraní a načte se původní profil projektu. Existující běhy se nezmění a žádný běh se nespustí.';
      return;
    }
    const result=await act('/api/defaults/reset',{profile:$('profile-select').value},event.currentTarget);
    if(result?.profile){replaceProfile(result.profile);loadProfile();toast('Obnoven původní profil projektu. Žádný běh se nespustil.');}
  });
  $('activity-filter').addEventListener('change',()=>{state.activityAgent=$('activity-filter').value;renderActivity();});
  $('activity-follow').addEventListener('change',()=>{if($('activity-follow').checked)$('activity-feed').scrollTop=$('activity-feed').scrollHeight;});
  $('home').addEventListener('click',event=>{event.preventDefault();$('main').scrollIntoView({behavior:'smooth'});});
  $('refresh-runs').addEventListener('click',()=>refreshRuns().catch(e=>toast(e.message,true)));
  $('run-search').addEventListener('input',renderRuns);$('profile-select').addEventListener('change',loadProfile);
  ['cheap','strong','flag'].forEach(t=>$('model-'+t).addEventListener('input',updateRoleModels));
  $('new-form').addEventListener('submit',async event=>{
    event.preventDefault();let settings;try{settings=overrides();}catch(error){toast(error.message,true);return;}
    if(state.editorMode==='defaults'){
      const result=await act('/api/defaults',{profile:$('profile-select').value,overrides:settings,objective:$('full-objective').value.trim(),...(profile().custom?{name:$('profile-name').value.trim()}:{})},$('start-button'));
      if(result?.profile){replaceProfile(result.profile);$('new-dialog').close();toast('Výchozí nastavení profilu je uložené pro nové běhy. Žádný běh se nespustil.');}
      return;
    }
    const result=await act('/api/start',{profile:$('profile-select').value,overrides:settings,objective:$('full-objective').value.trim(),task:$('new-task').value.trim(),backend:$('backend-select').value,fetch_live:$('fetch-live').checked},$('start-button'));
    if(result){$('new-dialog').close();state.followJob=true;}
  });
  $('resume-open').addEventListener('click',()=>{$('resume-form').reset();$('resume-dialog').showModal();});
  $('resume-form').addEventListener('submit',async event=>{
    event.preventDefault();
    const result=await act('/api/resume',{run_id:state.selected,extend_tokens:Number($('extend-tokens').value),extend_seconds:Number($('extend-minutes').value)*60,extend_steps:Number($('extend-steps').value),extend_rounds:Number($('extend-rounds').value)},event.submitter);
    if(result)$('resume-dialog').close();
  });
  $('pause-run').addEventListener('click',event=>act('/api/pause',{run_id:state.selected},event.currentTarget));
  $('close-run').addEventListener('click',async event=>{
    if(!confirm('Připravit konečnou syntézu pouze ze stávajících podkladů? Další výzkum a kritika se zastaví. Příprava sama nevolá model; placenou syntézu pak spustíte tlačítkem Pokračovat.'))return;
    const result=await act('/api/close',{run_id:state.selected},event.currentTarget);
    if(result)toast('Připravuje se závěrečná syntéza. Po dokončení příkazu ji spusťte tlačítkem Pokračovat.');
  });
  $('comment-form').addEventListener('submit',async event=>{
    event.preventDefault();const text=$('runtime-comment').value.trim();if(!text)return;
    const result=await act('/api/comment',{run_id:state.selected,text},event.submitter);if(result)$('runtime-comment').value='';
  });
  $('copy-report').addEventListener('click',()=>clipboard(state.report));
  $('copy-command').addEventListener('click',()=>clipboard(currentCommand()));
  $('open-cmd').addEventListener('click',event=>act('/api/open-cmd',{},event.currentTarget));
  $('terminal-toggle').addEventListener('click',()=>{const collapsed=document.querySelector('.terminal').classList.toggle('collapsed');$('terminal-body').hidden=collapsed;document.querySelector('.workspace').classList.toggle('terminal-collapsed',collapsed);$('terminal-toggle').textContent=collapsed?'⌃':'⌄';});
  $('clear-console').addEventListener('click',()=>{state.lines=[];$('console-output').textContent='';});
  $('command-form').addEventListener('submit',async event=>{
    event.preventDefault();const command=$('command-input').value.trim();if(!command)return;
    state.lastCommand=command;state.commands.push(command);state.commandIndex=state.commands.length;
    appendConsole(['› '+command]);$('command-input').value='';
    await act('/api/command',{command},event.submitter);
  });
  $('command-input').addEventListener('keydown',event=>{
    if(!['ArrowUp','ArrowDown'].includes(event.key)||!state.commands.length)return;
    event.preventDefault();state.commandIndex=Math.min(state.commands.length,Math.max(0,state.commandIndex+(event.key==='ArrowUp'?-1:1)));$('command-input').value=state.commands[state.commandIndex]||'';
  });
  function openSettings(focusKey=false) {
    $('project-path').value=state.bootstrap?.project||'';$('runs-path').value=state.bootstrap?.runs_root||'';
    $('api-key').value='';$('api-key').type='password';$('show-key').checked=false;
    $('remember-key').checked=Boolean(state.bootstrap?.api_key_saved||!state.bootstrap?.api_key_present);
    $('forget-key').hidden=!state.bootstrap?.api_key_present;
    $('settings-dialog').showModal();if(focusKey)$('api-key').focus();
  }

  $('key-status').addEventListener('click',()=>openSettings(true));
  $('forget-key').addEventListener('click',async event=>{
    const result=await act('/api/settings',{forget_api_key:true},event.currentTarget);
    if(result){$('api-key').value='';$('remember-key').checked=false;await bootstrap(false);$('forget-key').hidden=true;}
  });
  $('show-key').addEventListener('change',()=>{$('api-key').type=$('show-key').checked?'text':'password';});
  $('settings-form').addEventListener('submit',async event=>{
    event.preventDefault();const values={project:$('project-path').value.trim(),runs_root:$('runs-path').value.trim(),remember_api_key:$('remember-key').checked};
    if($('api-key').value.trim())values.api_key=$('api-key').value.trim();
    const result=await act('/api/settings',values,event.submitter);
    if(result){
      $('api-key').value='';$('show-key').checked=false;$('api-key').type='password';$('settings-dialog').close();
      if(values.runs_root!==state.bootstrap?.runs_root||values.project!==state.bootstrap?.project)clearSelection();
      await bootstrap(false);
    }
  });
  async function bootstrap(initial=true) {
    try {
      state.bootstrap=await api('/api/bootstrap');
      $('key-status').textContent=state.bootstrap.api_key_saved?'Nastavení · klíč uložen':state.bootstrap.api_key_present?'Nastavení · klíč nastaven':'Nastavení / API klíč';
      const current=$('profile-select').value;
      renderProfileOptions(current);
      loadProfile();await refreshRuns();await pollJob();notice('');
      $('connection-dot').classList.add('online');$('connection-text').textContent='Připojeno k lokálnímu GUI';
      if(initial)setInterval(poll,2500);
    } catch(error){notice(token?error.message:'Chybí přístupový token. Otevřete adresu vypsanou při spuštění GUI (včetně části #token=…).',true);$('connection-text').textContent='Nepřipojeno';}
  }
  bootstrap();
})();
