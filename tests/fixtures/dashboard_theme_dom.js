// Engineering DOM fixture: actual app.js, no claim about native browser rendering.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.events = {}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this[name] = value; }
  querySelectorAll() { return []; }
  addEventListener(name, handler) { this.events[name] = handler; }
  contains() { return false; }
  focus() {}
}
function doc() {
  const nodes = new Map();
  return {documentElement: new Element('html'), head: new Element('head'), body: new Element('body'),
    baseURI: 'http://127.0.0.1:1234/fixture/', activeElement: null,
    getElementById(id) { if (!nodes.has(id)) nodes.set(id, new Element('div')); return nodes.get(id); },
    createElement(tag) { return new Element(tag); }, createDocumentFragment() { return new Element('fragment'); },
    querySelectorAll() { return []; }};
}
(async () => {
  for (const supplied of [undefined, 'system', 'light', 'dark']) {
    const document = doc(), pipDocument = doc(), sources = [];
    const pip = {document: pipDocument, closed: false, addEventListener() {}, close() { this.closed = true; }, focus() {}};
    const selection = {kind: 'harness_run', project_id: 'fixture', project_version: '1', run_id: 'same-record'};
    const payload = {runs: [{id: 'one', selection}]};
    if (supplied !== undefined) payload.presentation = {theme: supplied};
    const context = {document, window: {documentPictureInPicture: {requestWindow: () => Promise.resolve(pip)}, addEventListener() {}, focus() {}},
      localStorage: {getItem() { return null; }, setItem() {}}, setInterval() {}, URL,
      fetch: async () => ({ok: true, json: async () => payload}),
      EventSource: class { constructor(url) { this.url = url; this.events = {}; sources.push(this); } addEventListener(n, f) { this.events[n] = f; } close() {} }};
    vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), context);
    await new Promise(setImmediate);
    assert.strictEqual(document.documentElement.dataset.theme, supplied || 'system');
    assert.strictEqual(sources.length, 1);
    document.getElementById('pip-button').events.click();
    await new Promise(setImmediate);
    assert.strictEqual(pipDocument.documentElement.dataset.theme, supplied || 'system');
    assert.strictEqual(sources.length, 1, 'opening PiP must share the original subscription');
    sources[0].events.snapshot({data: JSON.stringify({selection, component: {id:'local-dashboard',version:'2'},
      business:{items:[],completion:{completed:1,total:2,label:'fixture'},current:'actual fixture step',steps:[],pending:[]},
      observation:{observed_at:'2026-10-19T00:00:00Z',activity:{last_output_at:null},gaps:[]},
      transport:{session_id:'fixture',sequence:1}})});
    assert.strictEqual(pipDocument.documentElement.dataset.theme, document.documentElement.dataset.theme);
    assert.strictEqual(sources.length, 1);
    assert(pipDocument.body.children.length, 'PiP fixture must actually render');
  }
  console.log('4 configurations: shared theme and one subscription');
})().catch(error => { console.error(error); process.exitCode = 1; });
