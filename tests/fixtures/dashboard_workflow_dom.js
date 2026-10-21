// Actual v3 app.js exercised with a DOM model; not native browser/PiP rendering.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.events = {}; this._text = ''; }
  append(...nodes) { nodes.forEach(node => { this.children.push(node); node.parentElement = this; }); }
  replaceChildren(...nodes) { this.children = []; this._text = ''; this.append(...nodes); }
  set textContent(value) { this._text = value; this.children = []; }
  get textContent() { return this._text + this.children.map(node => node.textContent).join(''); }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, handler) { this.events[name] = handler; }
  contains(node) { return this === node || this.children.some(child => child.contains(node)); }
  querySelectorAll(selector) { return descendants(this).filter(node => selector === 'details' ? node.tagName === 'DETAILS' :
    selector === 'details[open]' ? node.tagName === 'DETAILS' && node.open : selector === '[data-view-step]' ? node.dataset.viewStep : false); }
  focus() {}
}
const descendants = node => node.children.flatMap(child => [child, ...descendants(child)]);
const byClass = (root, name) => descendants(root).filter(node => (node.className || '').split(' ').includes(name));
const one = (root, name) => { const nodes = byClass(root, name); assert.strictEqual(nodes.length, 1, `expected one ${name}`); return nodes[0]; };
const clickStep = (root, id) => { const button = descendants(root).find(node => node.dataset.viewStep === id); assert(button); button.events.click(); };
function doc() {
  const nodes = new Map();
  return {documentElement: new Element('html'), head: new Element('head'), body: new Element('body'),
    baseURI: 'http://127.0.0.1:1234/fixture/', activeElement: null,
    getElementById(id) { if (!nodes.has(id)) nodes.set(id, new Element('div')); return nodes.get(id); },
    createElement(tag) { return new Element(tag); }, createDocumentFragment() { return new Element('fragment'); }, querySelectorAll() { return []; }};
}
const tick = () => new Promise(setImmediate);
(async () => {
  const document = doc(), pipDocument = doc(), sources = [], requests = [];
  const pip = {document: pipDocument, closed: false, addEventListener() {}, close() { this.closed = true; }, focus() {}};
  const selection = {kind:'foundry_build',project_id:'fixture',project_version:'1',run_id:'same-run',program_id:'program',prepared_event_id:'prepared-1'};
  const selection2 = {...selection, prepared_event_id:'prepared-2'};
  const payload = {runs:[{id:'one',selection},{id:'two',selection:selection2}],presentation:{theme:'dark'}};
  const context = {document, window:{documentPictureInPicture:{requestWindow:() => Promise.resolve(pip)},addEventListener(){},focus(){}},
    localStorage:{getItem(){return null;},setItem(){}}, setInterval(){}, URL,
    fetch:async (url) => { requests.push(url); return {ok:true,json:async()=>payload}; },
    EventSource:class {constructor(url){this.url=url;this.events={};sources.push(this);}addEventListener(n,f){this.events[n]=f;}close(){this.closed=true;}}};
  vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), context);
  await tick();
  const dashboard = document.getElementById('dashboard');
  const business = {items:[],current:'等待当前复核',completion:{completed:0,total:2,label:'检查'},work_progress:{completed:1,total:2,label:'已记录工作'},
    steps:[{step_id:'legacy',label:'旧版步骤',state:'PENDING'}], current_step_id:'legacy',pending:[],
    workflow:{steps:[{step_id:'past',label:'需求理解',state:'PASS',detail:'需求已读取',history:[{label:'原始失败',state:'FAILED',detail:'已保留失败记录',evidence_refs:['evidence-failure']}]},
      {step_id:'current',label:'当前复核',state:'PENDING',detail:'当前等待'},
      {step_id:'next',label:'整理交付',state:'NOT_STARTED',detail:'后续具名步骤'},
      {step_id:'last',label:'最终记录',state:'NOT_STARTED'}],current_step_id:'current'}};
  const snapshot = (sequence, value=business, selected=selection, session='session-1') => ({selection:selected,component:{id:'local-dashboard',version:'3'},business:value,
    observation:{observed_at:'2026-10-21T00:00:00Z',activity:{last_output_at:null},gaps:[]},transport:{session_id:session,sequence}});
  const emit = value => sources.at(-1).events.snapshot({data:JSON.stringify(value)});
  emit(snapshot(1));
  assert.strictEqual(one(dashboard,'percent').textContent, '50%');
  assert(one(dashboard,'work-progress').textContent.includes('累计工作进度（非验收通过率）'));
  assert(one(dashboard,'valid-acceptance').textContent.includes('当前有效验收：0 / 2'));
  assert(!one(dashboard,'valid-acceptance').className.includes('accepted'));
  assert(!dashboard.textContent.includes('旧版步骤'), 'prefer workflow over legacy steps');
  assert(dashboard.textContent.includes('整理交付') && dashboard.textContent.includes('后续步骤'));
  assert.strictEqual(one(dashboard,'viewed-step').dataset.viewedStep, 'current');
  document.getElementById('pip-button').events.click(); await tick();
  assert.strictEqual(sources.length,1); assert.strictEqual(document.documentElement.dataset.theme,'dark');
  assert.strictEqual(pipDocument.documentElement.dataset.theme,'dark');
  assert(one(pipDocument.body,'current-step').textContent.includes('当前复核'));
  assert.strictEqual(one(pipDocument.body,'valid-acceptance').textContent,'当前有效验收：0 / 2');
  assert(one(pipDocument.body,'valid-acceptance').title.includes('0 / 2 · 检查'));
  assert(one(pipDocument.body,'valid-acceptance')['aria-label'].includes('0 / 2 · 检查'));
  assert(one(dashboard,'valid-acceptance').textContent.includes('0 / 2 · 检查'));
  assert(one(pipDocument.body,'nearby-steps').textContent.includes('下一项 · 整理交付'));
  assert(one(pipDocument.body,'nearby-steps').textContent.includes('前项 · 需求理解'));
  assert(!one(pipDocument.body,'nearby-steps').textContent.includes('当前复核'), 'do not duplicate current step in nearby list');
  assert(one(pipDocument.body,'step-count').textContent.includes('步骤已完成 1 / 4'));
  clickStep(dashboard,'past');
  assert.strictEqual(one(dashboard,'viewed-step').dataset.viewedStep,'past');
  assert(one(dashboard,'viewed-step').textContent.includes('原始失败'));
  assert(one(dashboard,'viewed-step').textContent.includes('evidence-failure'));
  assert(one(pipDocument.body,'current-step').textContent.includes('当前复核'));
  assert(!pipDocument.body.textContent.includes('原始失败'));
  const updated = JSON.parse(JSON.stringify(business)); updated.workflow.current_step_id='next'; updated.workflow.steps[1].state='PASS';
  emit(snapshot(2,updated));
  assert.strictEqual(one(dashboard,'viewed-step').dataset.viewedStep,'past');
  assert(one(dashboard,'current-step').textContent.includes('整理交付'));
  assert(one(pipDocument.body,'current-step').textContent.includes('整理交付'));
  assert(one(pipDocument.body,'nearby-steps').textContent.includes('下一项 · 最终记录'));
  sources.at(-1).onerror();
  assert(dashboard.textContent.includes('连接中断')); assert.strictEqual(one(dashboard,'viewed-step').dataset.viewedStep,'past');
  document.getElementById('reconnect-button').events.click(); await tick();
  assert.strictEqual(sources.length,2); assert(sources[0].closed);
  emit(snapshot(3,updated)); assert.strictEqual(one(dashboard,'viewed-step').dataset.viewedStep,'past');
  sources[0].events.snapshot({data:JSON.stringify(snapshot(99,business))});
  assert(one(pipDocument.body,'current-step').textContent.includes('整理交付'), 'old subscription cannot change current');
  one(dashboard,'return-current').events.click(); assert.strictEqual(one(dashboard,'viewed-step').dataset.viewedStep,'next');
  clickStep(dashboard,'past');
  const removed = JSON.parse(JSON.stringify(updated)); removed.workflow.steps.shift(); emit(snapshot(4,removed));
  assert.strictEqual(one(dashboard,'viewed-step').dataset.viewedStep,'next');
  clickStep(dashboard,'last');
  document.getElementById('run-selector').value='two'; document.getElementById('run-selector').events.change();
  assert.strictEqual(byClass(dashboard,'viewed-step').length,0);
  emit(snapshot(1,business,selection2,'session-2'));
  assert.strictEqual(one(dashboard,'viewed-step').dataset.viewedStep,'current');
  assert(dashboard.textContent.includes('prepared-2')); assert(pipDocument.body.textContent.includes('prepared-2'));
  emit(snapshot(9,updated,selection));
  assert.strictEqual(one(dashboard,'viewed-step').dataset.viewedStep,'current');
  assert(dashboard.textContent.includes('不匹配'));
  const legacy = {...business}; delete legacy.workflow; delete legacy.work_progress;
  legacy.completion={completed:1,total:2,label:'原验收口径'};
  emit(snapshot(2,legacy,selection2,'session-2'));
  assert.strictEqual(byClass(dashboard,'work-progress').length,0);
  assert(one(dashboard,'completion').textContent.includes('原验收口径'));
  assert(one(dashboard,'viewed-step').textContent.includes('旧版步骤'));
  assert(one(pipDocument.body,'current-step').textContent.includes('旧版步骤'));
  const unavailable = {...business,completion:null}; emit(snapshot(3,unavailable,selection2,'session-2'));
  assert(one(dashboard,'valid-acceptance').textContent.includes('口径未提供'));
  assert(!one(dashboard,'valid-acceptance').className.includes('accepted'));
  const finished = JSON.parse(JSON.stringify(business));
  finished.current='EXPIRED · 授权已过期'; finished.pending=['授权已过期，后续执行需有效授权'];
  finished.completion.completed=2; finished.work_progress.completed=2;
  delete finished.workflow.current_step_id;
  finished.workflow.steps.forEach(step=>{step.state='PASS';}); finished.workflow.steps.at(-1).state='NOT_RUN';
  emit(snapshot(4,finished,selection2,'session-2'));
  assert.strictEqual(one(dashboard,'workflow-finished').textContent,'已记录步骤完成');
  assert(one(dashboard,'current-step').textContent.includes('当前有效验收已满足'));
  assert(one(dashboard,'current-step').textContent.includes('EXPIRED · 授权已过期'));
  assert(dashboard.textContent.includes('后续执行需有效授权'));
  assert(one(pipDocument.body,'current-step').textContent.includes('已记录步骤完成'));
  assert(one(pipDocument.body,'current-step').textContent.includes('EXPIRED · 授权已过期'));
  assert(pipDocument.body.textContent.includes('后续执行需有效授权'));
  const compactChildren = one(pipDocument.body,'compact-summary').children;
  assert(compactChildren.indexOf(one(pipDocument.body,'compact-alerts')) < compactChildren.indexOf(one(pipDocument.body,'compact-steps')),
    'exceptions must precede nearby steps in compact view');
  const historicOnly = JSON.parse(JSON.stringify(finished)); historicOnly.completion.completed=0;
  emit(snapshot(5,historicOnly,selection2,'session-2'));
  assert.strictEqual(one(dashboard,'percent').textContent,'100%');
  assert.strictEqual(byClass(dashboard,'workflow-finished').length,0, 'cumulative100 cannot imply acceptance');
  assert.strictEqual(byClass(pipDocument.body,'workflow-finished').length,0);
  const unfinished = JSON.parse(JSON.stringify(finished)); unfinished.workflow.steps[0].state='UNKNOWN';
  emit(snapshot(6,unfinished,selection2,'session-2'));
  assert.strictEqual(byClass(dashboard,'workflow-finished').length,0, 'unknown step cannot become complete');
  const stillCurrent = JSON.parse(JSON.stringify(finished)); stillCurrent.workflow.current_step_id='past';
  emit(snapshot(7,stillCurrent,selection2,'session-2'));
  assert.strictEqual(byClass(dashboard,'workflow-finished').length,0, 'explicit current step remains visible');
  const legacyComplete = JSON.parse(JSON.stringify(finished)); delete legacyComplete.workflow;
  emit(snapshot(8,legacyComplete,selection2,'session-2'));
  assert.strictEqual(byClass(dashboard,'workflow-finished').length,0, 'do not infer workflow completion for legacy source');
  assert(requests.every(url => url === 'api/runs'));
  assert.strictEqual(sources.filter(source=>!source.closed).length,1);
  assert(sources.every(source=>source.url.startsWith('api/events?run=')));
  console.log('workflow UI: cumulative50/acceptance0, history/sidebar, live PiP, future names, reconnect, selection, legacy fallback');
})().catch(error => { console.error(error); process.exitCode=1; });
