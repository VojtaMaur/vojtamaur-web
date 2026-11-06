'use strict';
/* Local SVG/HTML visualization; no CDN, simulation, model request or run writes. */
class SwarmWorkflow {
  constructor(actions) {
    this.actions=actions;this.$=id=>document.getElementById(id);this.focus=null;this.runId=null;this.signature='';this.stage='';this.query='';this.scale=1;this.x=0;this.y=0;this.fitNext=true;
    this.$('graph-stage').addEventListener('change',()=>this.chooseStage(this.$('graph-stage').value));
    this.$('graph-search').addEventListener('input',()=>{this.query=this.$('graph-search').value.trim().toLocaleLowerCase('cs');this.focus=null;this.fitNext=true;this.render();});
    this.$('graph-node').addEventListener('change',()=>this.choose(this.$('graph-node').value||null));
    this.$('graph-all').addEventListener('click',()=>{this.stage='';this.query='';this.$('graph-search').value='';this.choose(null);});
    this.$('graph-in').addEventListener('click',()=>this.zoom(1.25));this.$('graph-out').addEventListener('click',()=>this.zoom(.8));
    this.$('graph-fit').addEventListener('click',()=>this.fit());
    const viewport=this.$('graph-viewport');
    viewport.addEventListener('wheel',event=>{if(!event.ctrlKey)return;event.preventDefault();const box=viewport.getBoundingClientRect();this.zoom(event.deltaY<0?1.15:1/1.15,event.clientX-box.left,event.clientY-box.top);},{passive:false});
    viewport.addEventListener('pointerdown',event=>{if(event.button!==0||event.target.closest('button'))return;event.preventDefault();this.drag={id:event.pointerId,x:event.clientX,y:event.clientY,tx:this.x,ty:this.y};viewport.setPointerCapture(event.pointerId);viewport.classList.add('dragging');});
    viewport.addEventListener('pointermove',event=>{if(!this.drag||this.drag.id!==event.pointerId)return;this.x=this.drag.tx+event.clientX-this.drag.x;this.y=this.drag.ty+event.clientY-this.drag.y;this.transform();});
    const stop=()=>{this.drag=null;viewport.classList.remove('dragging');};viewport.addEventListener('pointerup',stop);viewport.addEventListener('pointercancel',stop);viewport.addEventListener('lostpointercapture',stop);
    new ResizeObserver(()=>{if(!this.$('panel-workflow').hidden&&this.fitNext)this.fit();}).observe(viewport);
  }
  el(tag,attrs={},...children) {
    const e=document.createElement(tag);for(const [k,v] of Object.entries(attrs)){if(k==='text')e.textContent=v??'';else if(k==='class')e.className=v;else if(k==='click')e.addEventListener('click',v);else e.setAttribute(k,String(v));}
    for(const c of children.flat())if(c!=null)e.append(c);return e;
  }
  label(status) {return ({RUNNING:'Pracuje',PENDING:'Čeká',PAUSED:'Pozastaveno',COMPLETED:'Dokončeno',BLOCKED:'Blokováno',LIMIT_REACHED:'Dosažen limit',REJECTED:'Zamítnuto',INTERRUPTED:'Proces neběží',UNREVIEWED:'Neposouzeno',INVESTIGATING:'Zkoumá se',DISCOVERED:'Navrženo',VERIFIED:'Ověřeno',PROTOTYPED:'Prototyp',RECORDED:'Zaznamenáno',DEFERRED:'Odloženo',IDEA_CREATED:'Rozpracováno v IDEA',APPROVED:'Schváleno',UNKNOWN:'Neznámé',PROMISING:'Slibné',REVISE:'K dopracování'})[status]||status||'Bez stavu';}
  kind(kind) {return ({agent:'Agent',hypothesis:'Námět',idea:'Nápad',test:'Test',experiment:'Experiment',approval:'Schválení',action:'Externí akce',report:'Report'})[kind]||kind;}
  update(run,force=false) {
    const graph=run.workflow||{nodes:[],edges:[],stages:[],notice:'Mapa pro tento běh zatím není dostupná.'};
    const changed=this.runId!==run.run_id;
    if(changed){this.runId=run.run_id;this.stage='';this.query='';this.$('graph-search').value='';this.focus=(graph.nodes.find(n=>n.kind==='agent'&&n.status==='RUNNING')||graph.nodes.find(n=>n.kind==='idea')||graph.nodes.find(n=>n.kind==='agent'))?.id||null;this.fitNext=true;this.signature='';}
    this.run=run;this.graph=graph;this.byId=new Map(graph.nodes.map(n=>[n.id,n]));
    if(this.focus&&!this.byId.has(this.focus)){this.focus=null;this.fitNext=true;}
    if(this.$('panel-workflow').hidden)return;
    const signature=JSON.stringify([graph,run.interrupted]);
    if(force||signature!==this.signature){this.signature=signature;this.render();}
  }
  chooseStage(stage) {this.stage=stage;this.query='';this.$('graph-search').value='';this.focus=null;this.fitNext=true;this.render();}
  choose(id) {this.focus=id;this.fitNext=true;this.render();}
  filtered() {return this.graph.nodes.filter(n=>(!this.stage||n.stage===this.stage)&&(!this.query||[n.label,n.ref,n.details.role,n.details.provider].join(' ').toLocaleLowerCase('cs').includes(this.query)));}
  render() {
    if(!this.graph)return;
    const $=this.$,e=this.el.bind(this),g=this.graph;
    const scroll=this.lastDetail===this.focus?$('graph-detail').scrollTop:0;
    const keyboard=document.activeElement?.dataset.graphId;
    $('graph-live').textContent=g.running?'● Živě · obnova každé 2,5 s':'Uložený stav běhu';$('graph-live').classList.toggle('is-live',g.running);
    $('graph-stages').replaceChildren(...g.stages.map((s,index)=>e('button',{type:'button',class:'graph-stage'+(this.stage===s.id?' selected':'')+(s.active?' working':''),'aria-pressed':this.stage===s.id,click:()=>this.chooseStage(this.stage===s.id?'':s.id)},e('span',{class:'graph-stage-index',text:String(index+1).padStart(2,'0')}),e('strong',{text:s.label}),e('span',{text:s.id==='execution'&&!s.count&&this.run.config?.task_style==='brainstorming'?'V tomto režimu vypnuté':s.count+(s.active?' · '+s.active+' pracuje':' záznamů')}))));
    if(!$('graph-stage').dataset.ready){$('graph-stage').replaceChildren(e('option',{value:'',text:'Všechny fáze'}),...g.stages.map(s=>e('option',{value:s.id,text:s.label})));$('graph-stage').dataset.ready='true';}$('graph-stage').value=this.stage;
    const active=g.nodes.filter(n=>n.kind==='agent'&&n.status==='RUNNING'&&g.running);
    $('graph-now').textContent=active.length?'Právě pracuje: '+active.map(n=>{const task=g.edges.find(edge=>edge.active&&edge.source===n.id);return n.label+(task?' → '+this.byId.get(task.target).label:'')+(n.details.activity?' · '+n.details.activity.slice(0,150):'');}).join(', '):this.run.interrupted?'Proces už neběží. Mapa ukazuje poslední checkpoint.':'Žádný agent právě neběží · '+this.label(this.run.status);
    const choices=this.filtered(),options=choices.map(n=>({value:n.id,text:this.kind(n.kind)+' · '+n.label+' · '+n.ref}));
    if(this.focus&&!choices.some(n=>n.id===this.focus))options.push({value:this.focus,text:this.byId.get(this.focus).label});
    const optionsKey=JSON.stringify(options);
    if(optionsKey!==this.optionsKey){$('graph-node').replaceChildren(e('option',{value:'',text:'Celá síť / filtrovaný výběr'}),...options.map(o=>e('option',o)));this.optionsKey=optionsKey;}
    $('graph-node').value=this.focus||'';
    let nodes,edges;
    if(this.focus){const ids=new Set([this.focus]);g.edges.forEach(edge=>{if(edge.source===this.focus||edge.target===this.focus){ids.add(edge.source);ids.add(edge.target);}});nodes=g.nodes.filter(n=>ids.has(n.id));edges=g.edges.filter(edge=>edge.source===this.focus||edge.target===this.focus);}
    else{nodes=choices;const ids=new Set(nodes.map(n=>n.id));edges=g.edges.filter(edge=>ids.has(edge.source)&&ids.has(edge.target));}
    $('graph-scope').textContent=(this.focus?'Přímé vazby':'Celá síť'+(this.stage||this.query?' · filtr':''))+' · '+nodes.length+' uzlů / '+edges.length+' vazeb';
    $('graph-notice').textContent=(g.notice||'')+(g.omitted_nodes?' Zobrazení je omezené; dalších '+g.omitted_nodes+' záznamů zůstává v auditu.':'');
    const positions=this.layout(nodes,edges);this.draw(nodes,edges,positions);this.detail();$('graph-detail').scrollTop=scroll;this.lastDetail=this.focus;
    if(keyboard){const button=[...$('graph-world').querySelectorAll('button')].find(b=>b.dataset.graphId===keyboard);button?.focus({preventScroll:true});}
    $('graph-empty').hidden=nodes.length>0;$('graph-empty').textContent=this.query?'Žádný uzel neodpovídá hledání.':'V této fázi zatím nejsou žádné záznamy.';
    if(this.fitNext)this.fit();else this.transform();
  }
  layout(nodes,edges) {
    const positions=new Map(),width=220,height=98,gapY=27,gapX=110;
    const stages=this.graph.stages.map(s=>s.id);
    let columns;
    if(this.focus){const inbound=new Set(edges.filter(e=>e.target===this.focus).map(e=>e.source));columns=[nodes.filter(n=>n.id!==this.focus&&inbound.has(n.id)),nodes.filter(n=>n.id===this.focus),nodes.filter(n=>n.id!==this.focus&&!inbound.has(n.id))];}
    else columns=stages.map(stage=>nodes.filter(n=>n.stage===stage)).filter(list=>list.length);
    const maxRows=Math.max(1,...columns.map(c=>c.length));
    this.worldWidth=Math.max(500,columns.length*(width+gapX)-gapX+80);this.worldHeight=Math.max(200,maxRows*(height+gapY)-gapY+70);
    columns.forEach((column,x)=>column.forEach((node,y)=>positions.set(node.id,{x:40+x*(width+gapX),y:35+(maxRows-column.length)*(height+gapY)/2+y*(height+gapY),width,height})));
    return positions;
  }
  draw(nodes,edges,positions) {
    const e=this.el.bind(this),world=this.$('graph-world');world.replaceChildren();world.style.width=this.worldWidth+'px';world.style.height=this.worldHeight+'px';
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('width',this.worldWidth);svg.setAttribute('height',this.worldHeight);svg.setAttribute('aria-hidden','true');svg.classList.add('graph-lines');
    const defs=document.createElementNS(ns,'defs'),marker=document.createElementNS(ns,'marker');marker.setAttribute('id','workflow-arrow');marker.setAttribute('markerWidth','7');marker.setAttribute('markerHeight','7');marker.setAttribute('refX','6');marker.setAttribute('refY','3.5');marker.setAttribute('orient','auto');const arrow=document.createElementNS(ns,'path');arrow.setAttribute('d','M0,0 L7,3.5 L0,7 Z');arrow.setAttribute('fill','#81948c');marker.append(arrow);defs.append(marker);svg.append(defs);
    const pairs=new Map();edges.forEach(edge=>{const k=[edge.source,edge.target].sort().join('|');if(!pairs.has(k))pairs.set(k,[]);pairs.get(k).push(edge);});
    edges.forEach(edge=>{
      const a=positions.get(edge.source),b=positions.get(edge.target);if(!a||!b)return;
      const siblings=pairs.get([edge.source,edge.target].sort().join('|')),offset=(siblings.indexOf(edge)-(siblings.length-1)/2)*20;
      const forward=b.x>a.x,x1=forward?a.x+a.width:a.x,x2=forward?b.x:b.x+b.width,y1=a.y+a.height/2+offset,y2=b.y+b.height/2+offset;
      const path=document.createElementNS(ns,'path');path.setAttribute('d',`M${x1},${y1} C${x1+(forward?60:-60)},${y1} ${x2+(forward?-60:60)},${y2} ${x2},${y2}`);path.setAttribute('class','graph-edge edge-'+edge.kind+(edge.active?' active':''));path.setAttribute('marker-end','url(#workflow-arrow)');svg.append(path);
      if(this.focus){const label=document.createElementNS(ns,'text');label.setAttribute('x',String((x1+x2)/2));label.setAttribute('y',String((y1+y2)/2-5));label.setAttribute('text-anchor','middle');label.setAttribute('class','graph-edge-label');label.textContent=edge.label+(edge.count>1?' ×'+edge.count:'');svg.append(label);}
    });world.append(svg);
    nodes.forEach(node=>{const p=positions.get(node.id);const button=e('button',{type:'button',class:'graph-node kind-'+node.kind+(node.id===this.focus?' selected':'')+(node.status==='RUNNING'&&this.graph.running?' working':''),'data-graph-id':node.id,title:node.label+' · '+this.label(node.status),'aria-label':this.kind(node.kind)+' '+node.label+', '+this.label(node.status),click:()=>{this.stage='';this.query='';this.$('graph-search').value='';this.choose(node.id);}},e('span',{class:'graph-node-kind',text:this.kind(node.kind)+' · '+(node.kind==='agent'?node.ref:node.ref.startsWith('HYP-')?node.ref.slice(0,12)+'…':node.ref)}),e('strong',{text:node.label}),e('span',{class:'graph-node-status status-'+node.status.toLowerCase(),text:this.label(node.status)}));button.style.left=p.x+'px';button.style.top=p.y+'px';button.style.width=p.width+'px';button.style.height=p.height+'px';world.append(button);});
  }
  detail() {
    const e=this.el.bind(this),panel=this.$('graph-detail'),node=this.byId.get(this.focus);panel.replaceChildren();
    if(!node){panel.append(e('div',{class:'eyebrow',text:'VZTAHY V BĚHU'}),e('h3',{text:'Vyber uzel v mapě'}),e('p',{text:'Klikni na agenta, námět nebo nápad. Zobrazí se jeho přímé vazby a uložené podrobnosti. Zúžení na fázi nebo hledání zpřehlední větší síť.'}),e('p',{class:'field-note',text:'Spojení neznamená automaticky přímou komunikaci ani dokončenou práci.'}));return;}
    panel.append(e('div',{class:'eyebrow',text:this.kind(node.kind)+' / '+node.ref}),e('h3',{text:node.label}),e('span',{class:'badge',text:this.label(node.status)}));
    const d=node.details||{};
    if(d.model)panel.append(e('p',{class:'graph-model',text:(d.tier||'')+' · '+d.model+' · '+d.rounds+' kol'}));
    for(const [key,title] of [['activity','Poslední zaznamenaná činnost'],['role','Typ role'],['mission','Zadání'],['summary','Shrnutí'],['reason','Důvod / omezení'],['next_action','Další krok'],['meaning','Význam záznamu']])if(d[key])panel.append(e('h4',{text:title}),e('p',{text:d[key]}));
    panel.append(e('button',{type:'button',class:'button small',text:node.kind==='agent'?'Otevřít činnost agenta →':node.kind==='report'?'Otevřít report →':'Otevřít příslušnou kartu →',click:()=>this.actions.open(node.kind,node.ref)}));
    const links=this.graph.edges.filter(edge=>edge.source===node.id||edge.target===node.id);panel.append(e('h4',{text:'Přímé vazby · '+links.length}));
    if(!links.length)panel.append(e('p',{text:'V uložených datech zatím nejsou žádné přímé vazby.'}));
    links.forEach(edge=>{const outgoing=edge.source===node.id,other=this.byId.get(outgoing?edge.target:edge.source);if(!other)return;panel.append(e('button',{type:'button',class:'graph-relation',click:()=>{this.stage='';this.query='';this.$('graph-search').value='';this.choose(other.id);}},e('span',{text:(outgoing?'→ ':'← ')+edge.label+(edge.count>1?' ×'+edge.count:'')}),e('strong',{text:other.label}),edge.detail?e('small',{text:edge.detail}):null));});
  }
  transform() {this.$('graph-world').style.transform=`translate(${this.x}px,${this.y}px) scale(${this.scale})`;this.$('graph-zoom').textContent=Math.round(this.scale*100)+' %';}
  zoom(factor,cx,cy) {const box=this.$('graph-viewport');cx??=box.clientWidth/2;cy??=box.clientHeight/2;const next=Math.max(.08,Math.min(2.5,this.scale*factor));this.x=cx-(cx-this.x)*next/this.scale;this.y=cy-(cy-this.y)*next/this.scale;this.scale=next;this.fitNext=false;this.transform();}
  fit() {const box=this.$('graph-viewport');if(!box.clientWidth||!box.clientHeight)return;this.scale=Math.max(.08,Math.min(1,(box.clientWidth-24)/(this.worldWidth||500),(box.clientHeight-24)/(this.worldHeight||200)));this.x=(box.clientWidth-this.worldWidth*this.scale)/2;this.y=(box.clientHeight-this.worldHeight*this.scale)/2;this.fitNext=false;this.transform();}
}
window.SwarmWorkflow=SwarmWorkflow;
