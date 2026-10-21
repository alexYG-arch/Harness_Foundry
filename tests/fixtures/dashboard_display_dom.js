// Engineering DOM model: API transitions and shared state, not native browser proof.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
class Element {
  constructor(tag) { this.tagName=tag.toUpperCase(); this.children=[]; this.dataset={}; this.events={}; this._text=''; this.hidden=false; this.disabled=false; this.attributes={}; }
  append(...nodes) { nodes.forEach(node=>{this.children.push(node);node.parentElement=this;}); }
  replaceChildren(...nodes) { this.children=[];this._text='';this.append(...nodes); }
  set textContent(value) { this._text=String(value);this.children=[]; }
  get textContent() { return this._text+this.children.map(node=>node.textContent).join(''); }
  setAttribute(name,value) { this[name]=value;this.attributes[name]=value; }
  removeAttribute(name) { delete this.attributes[name];delete this[name]; }
  getAttribute(name) { return this.attributes[name]; }
  addEventListener(name,handler) { this.events[name]=handler; }
  contains(node) { return this===node || this.children.some(child=>child.contains(node)); }
  querySelectorAll(selector) { return descendants(this).filter(node=>selector==='details' ? node.tagName==='DETAILS' : selector==='details[open]' ? node.tagName==='DETAILS'&&node.open : selector==='[data-view-step]' ? node.dataset.viewStep : false); }
  focus() { this.focused=true; }
}
const descendants=node=>node.children.flatMap(child=>[child,...descendants(child)]);
const byClass=(node,name)=>descendants(node).filter(child=>(child.className||'').split(' ').includes(name));
const one=(node,name)=>{const result=byClass(node,name);assert.strictEqual(result.length,1,`one ${name}`);return result[0];};
const tick=()=>new Promise(setImmediate);
function documentModel(url) {
  const nodes=new Map(), events={};
  return {documentElement:new Element('html'),head:new Element('head'),body:new Element('body'),baseURI:url,activeElement:null,events,
    fullscreenElement:null,fullscreenEnabled:true,visibilityState:'visible',
    getElementById(id){if(!nodes.has(id)) nodes.set(id,new Element('div'));return nodes.get(id);},
    createElement(tag){return new Element(tag);},createDocumentFragment(){return new Element('fragment');},querySelectorAll(){return [];},
    addEventListener(name,handler){events[name]=handler;}};
}
const selection={kind:'foundry_build',project_id:'fixture',project_version:'same',run_id:'same-run',program_id:'same-program',prepared_event_id:'CEVT-11111111111111111111111111111111'};
const selection2={...selection,prepared_event_id:'CEVT-11111111222222222222222211111111'};
function business() { return {title:'导出材料与复核',items:[],current:'等待当前复核',completion:{completed:0,total:2,label:'声明检查'},work_progress:{completed:2,total:4,label:'包含已确认返修'},pending:[],recent:[],
  workflow:{steps:[{step_id:'past',label:'需求理解',state:'PASS',detail:'已读取公开需求',history:[{label:'首次检查',state:'FAILED',detail:'原失败保留',evidence_refs:['original-failure']}]},
    {step_id:'current',label:'复核结果',state:'PENDING',detail:'等待独立检查'},
    {step_id:'next',label:'整理交付',state:'NOT_STARTED',detail:'后续计划步骤'}],current_step_id:'current'}}; }
async function setup(options={}) {
  const query=options.query===undefined?'?view=browser':options.query;
  const location=new URL('http://127.0.0.1:1234/token/'+query), document=documentModel(location.href);
  const sources=[],requests=[],windows=[],calls={pip:0,fullscreen:0,exit:0};
  let resolvePip, resolveFullscreen, rejectFullscreen;
  const window={location,document,addEventListener(){},focus(){},isSecureContext:true};window.self=window;window.top=window;
  if(options.framed) window.top={};
  const event=()=>document.events.fullscreenchange?.();
  document.documentElement.requestFullscreen=()=>{calls.fullscreen++;if(options.deferFullscreen)return new Promise((resolve,reject)=>{resolveFullscreen=()=>{document.fullscreenElement=document.documentElement;event();resolve();};rejectFullscreen=()=>reject(new Error('denied'));});if(options.fullscreenReject)return Promise.reject(new Error('denied'));document.fullscreenElement=document.documentElement;event();return Promise.resolve();};
  document.exitFullscreen=()=>{calls.exit++;document.fullscreenElement=null;event();return Promise.resolve();};
  if(options.fullscreen===false){document.fullscreenEnabled=false;delete document.documentElement.requestFullscreen;delete document.exitFullscreen;}
  if(options.pip!==false) window.documentPictureInPicture={requestWindow(){calls.pip++;if(options.pipReject)return Promise.reject(new Error('denied'));
    const handlers={};const pip={document:documentModel(location.href),closed:false,addEventListener(name,handler){handlers[name]=handler;},focus(){},
      close(){this.closed=true;handlers.pagehide?.();}};windows.push(pip);
    return options.deferPip ? new Promise(resolve=>{resolvePip=()=>resolve(pip);}) : Promise.resolve(pip);
  }};
  const payload={runs:[{id:'one',selection},{id:'two',selection:selection2}],presentation:{theme:'dark'}};
  const context={document,window,location,navigator:{userAgent:'Do not infer capabilities from this name'},URL,URLSearchParams,
    localStorage:{getItem(){return null;},setItem(){}},setInterval(){},setTimeout,clearTimeout,
    fetch:async url=>{requests.push(url);return {ok:true,json:async()=>payload};},
    EventSource:class{constructor(url){this.url=url;this.events={};sources.push(this);}addEventListener(name,handler){this.events[name]=handler;}close(){this.closed=true;}}};
  vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),context);await tick();
  const dashboard=document.getElementById('dashboard');
  const snapshot=(sequence,value=business(),selected=selection)=>({selection:selected,component:{id:'local-dashboard',version:'4'},business:value,
    observation:{observed_at:'2026-10-21T00:00:00Z',activity:{last_output_at:null},gaps:[]},transport:{session_id:selected.prepared_event_id,sequence}});
  const emit=(sequence,value=business(),selected=selection)=>sources.at(-1).events.snapshot({data:JSON.stringify(snapshot(sequence,value,selected))});
  const click=async id=>{const button=document.getElementById(id);assert(!button.hidden&&!button.disabled,`${id} visible and enabled`);button.events.click();await tick();};
  const esc=async()=>{document.fullscreenElement=null;event();await tick();};
  return {document,window,dashboard,sources,requests,windows,calls,click,esc,emit,snapshot,resolvePip:()=>resolvePip(),resolveFullscreen:()=>resolveFullscreen(),rejectFullscreen:()=>rejectFullscreen(),event};
}
const groups={
  async availability(){
    const embedded=await setup({query:'?view=embedded'});
    assert(embedded.document.getElementById('pip-button').hidden);assert(embedded.document.getElementById('fullscreen-button').hidden);
    assert.deepStrictEqual(embedded.calls,{pip:0,fullscreen:0,exit:0});
    assert(embedded.document.getElementById('view-notice').textContent.includes('Chat'));
    for(const query of ['', '?view=browser','?view=unknown']){
      const yes=await setup({query});assert(!yes.document.getElementById('pip-button').hidden);assert(!yes.document.getElementById('fullscreen-button').hidden);
      const noPip=await setup({query,pip:false});assert(noPip.document.getElementById('pip-button').hidden);assert(!noPip.document.getElementById('fullscreen-button').hidden);
      const noFull=await setup({query,fullscreen:false});assert(!noFull.document.getElementById('pip-button').hidden);assert(noFull.document.getElementById('fullscreen-button').hidden);
      const neither=await setup({query,pip:false,fullscreen:false});assert(neither.document.getElementById('pip-button').hidden&&neither.document.getElementById('fullscreen-button').hidden);
    }
  },
  async fullscreen(){
    const env=await setup();env.emit(1);
    await env.click('fullscreen-button');assert.strictEqual(env.calls.fullscreen,1);assert(env.document.fullscreenElement);assert(env.document.getElementById('fullscreen-button').textContent.includes('退出全屏'));
    await env.click('fullscreen-button');assert.strictEqual(env.calls.exit,1);assert.strictEqual(env.document.fullscreenElement,null);assert(!env.document.getElementById('fullscreen-button').textContent.includes('退出'));
    await env.click('fullscreen-button');await env.esc();assert(!env.document.getElementById('fullscreen-button').textContent.includes('退出'));
    assert.strictEqual(env.sources.length,1);assert.strictEqual(one(env.dashboard,'percent').textContent,'50%');
    const rejected=await setup({fullscreenReject:true});await rejected.click('fullscreen-button');assert.strictEqual(rejected.document.fullscreenElement,null);assert(!rejected.document.getElementById('fullscreen-button').disabled);assert(rejected.document.getElementById('view-notice').textContent.includes('全屏'));
    for (const denied of [false,true]) {
      const pending=await setup({deferFullscreen:true});await pending.click('fullscreen-button');
      assert.strictEqual(pending.document.fullscreenElement,null,'browser transition is not complete yet');
      assert(pending.document.getElementById('pip-button').disabled,'PiP must wait for pending fullscreen transition');
      assert(pending.document.getElementById('fullscreen-button').disabled,'duplicate fullscreen transition must wait');
      pending.document.getElementById('pip-button').events.click();pending.document.getElementById('fullscreen-button').events.click();await tick();
      assert.strictEqual(pending.calls.pip,0,'pending fullscreen cannot dispatch competing PiP');assert.strictEqual(pending.calls.fullscreen,1,'pending fullscreen cannot be requested twice');
      if(denied)pending.rejectFullscreen();else pending.resolveFullscreen();await tick();
      assert(!pending.document.getElementById('pip-button').disabled);assert(!pending.document.getElementById('fullscreen-button').disabled);
      assert.strictEqual(Boolean(pending.document.fullscreenElement),!denied);
      await pending.click('pip-button');assert.strictEqual(pending.calls.pip,1);assert.strictEqual(pending.document.fullscreenElement,null);assert.strictEqual(pending.sources.length,1);
    }

  },
  async pip_transition(){
    const env=await setup();env.emit(1);await env.click('pip-button');assert.strictEqual(env.windows.length,1);assert(!env.windows[0].closed);
    await env.click('pip-button');assert.strictEqual(env.calls.pip,1,'focus existing PiP without opening another');
    await env.click('fullscreen-button');assert(env.windows[0].closed);assert(env.document.fullscreenElement);assert.strictEqual(env.sources.length,1);
    await env.click('pip-button');assert.strictEqual(env.calls.pip,2);assert.strictEqual(env.document.fullscreenElement,null);assert(!env.windows[1].closed);assert.strictEqual(env.sources.length,1);
    const pending=await setup({deferPip:true});await pending.click('pip-button');assert(pending.document.getElementById('pip-button').disabled);
    await pending.click('fullscreen-button');pending.resolvePip();await tick();assert(pending.windows[0].closed,'late PiP must not appear after fullscreen was selected');assert(pending.document.fullscreenElement);assert(!pending.document.getElementById('pip-button').disabled);
    const rejected=await setup({pipReject:true});await rejected.click('pip-button');assert.strictEqual(rejected.windows.length,0);assert(!rejected.document.getElementById('pip-button').disabled);assert(rejected.document.getElementById('view-notice').textContent.includes('画中画'));
  },
  async shared_state(){
    const env=await setup();env.emit(1);await env.click('pip-button');const pip=env.windows[0].document;
    assert.strictEqual(one(env.dashboard,'percent').textContent,'50%');assert.strictEqual(one(pip.body,'percent').textContent,'50%');
    assert(one(env.dashboard,'valid-acceptance').textContent.includes('0 / 2'));assert(!one(env.dashboard,'valid-acceptance').className.includes('accepted'));
    assert.strictEqual(pip.documentElement.dataset.theme,'dark');assert.strictEqual(env.sources.length,1);
    descendants(env.dashboard).find(node=>node.dataset.viewStep==='past').events.click();
    assert(one(env.dashboard,'viewed-step').textContent.includes('original-failure'));assert(one(pip.body,'current-step').textContent.includes('复核结果'));
    const update=business();update.work_progress.completed=3;update.completion.completed=1;update.workflow.current_step_id='next';update.workflow.steps[1].state='PASS';env.emit(2,update);
    assert.strictEqual(one(env.dashboard,'viewed-step').dataset.viewedStep,'past');assert.strictEqual(one(pip.body,'percent').textContent,'75%');assert(one(pip.body,'current-step').textContent.includes('整理交付'));
    env.sources[0].onerror();assert.strictEqual(one(env.dashboard,'percent').textContent,'75%');assert(/断|中断/.test(env.dashboard.textContent));
    await env.click('reconnect-button');assert.strictEqual(env.sources.length,2);assert(env.sources[0].closed);env.emit(3,update);
    env.sources[0].events.snapshot({data:JSON.stringify(env.snapshot(99,business()))});assert.strictEqual(one(pip.body,'percent').textContent,'75%');
    const opts=env.document.getElementById('run-selector').children;assert.notStrictEqual(opts[0].textContent,opts[1].textContent,'same shortened ID still has unique scope number');
    env.document.getElementById('run-selector').value='two';env.document.getElementById('run-selector').events.change();env.emit(1,business(),selection2);
    assert.strictEqual(one(env.dashboard,'viewed-step').dataset.viewedStep,'current');assert(env.dashboard.textContent.includes(selection2.prepared_event_id));
    env.emit(2,update,selection);assert(one(env.dashboard,'current-step').textContent.includes('复核结果'),'wrong prepared cannot replace current');
    assert(env.requests.every(url=>url==='api/runs'));assert.strictEqual(env.sources.filter(source=>!source.closed).length,1);
  },
  async wording(){
    const env=await setup();const value=business();value.current='EXPIRED · 授权已过期';value.pending=['授权已过期，后续执行需有效授权'];value.work_progress.completed=4;
    env.emit(1,value);assert.strictEqual(one(env.dashboard,'percent').textContent,'100%');assert(one(env.dashboard,'valid-acceptance').textContent.includes('0 / 2'));assert(!one(env.dashboard,'valid-acceptance').className.includes('accepted'));
    assert(env.dashboard.textContent.includes('后续执行需有效授权'));assert(env.dashboard.textContent.includes('整理交付'));assert(env.dashboard.textContent.includes('尚未')||env.dashboard.textContent.includes('未开始'));
    await env.click('pip-button');assert(env.windows[0].document.body.textContent.includes('后续执行需有效授权'));
    const mapped=business();mapped.items=[{item_id:'MAKE-REPORT',label:'MAKE-REPORT · 声明检查已接受',state:'PASS'}];
    mapped.workflow={steps:[{step_id:'base:MAKE-REPORT/stage:0',label:'初次搭建 · MAKE-REPORT / 实施',state:'UNKNOWN',detail:'已记录启动，完成待核对；不据此声称仍在运行'}],current_step_id:'base:MAKE-REPORT/stage:0'};
    env.emit(2,mapped);assert(one(env.dashboard,'current-step').textContent.includes('任务 1'));assert(!one(env.dashboard,'current-step').textContent.includes('MAKE-REPORT'));assert(one(env.dashboard,'current-step').textContent.includes('尚未确认是否结束'));assert(env.dashboard.textContent.includes('初次搭建 · MAKE-REPORT / 实施'),'raw name remains available');
    mapped.workflow.steps[0].label='初次搭建 · MAKE-REPORT / 项目自定义阶段';env.emit(3,mapped);assert(one(env.dashboard,'current-step').textContent.includes('初次搭建 · MAKE-REPORT / 项目自定义阶段'),'unknown stage remains original');
    const legacy=business();delete legacy.work_progress;delete legacy.workflow;legacy.completion={completed:1,total:2,label:'原项目定义口径'};legacy.steps=[{step_id:'x',label:'项目自己的步骤名称',state:'UNKNOWN',detail:'项目尚未说明的状态'}];legacy.current_step_id='x';
    env.emit(4,legacy);assert(one(env.dashboard,'completion').textContent.includes('原项目定义口径'));assert(env.dashboard.textContent.includes('项目自己的步骤名称'));assert(env.dashboard.textContent.includes('项目尚未说明的状态'));
  }
};
(async()=>{const names=process.argv[3]?[process.argv[3]]:Object.keys(groups);for(const name of names){assert(groups[name]);await groups[name]();console.log(`display DOM ${name}: PASS`);}})().catch(error=>{console.error(error);process.exitCode=1;});
