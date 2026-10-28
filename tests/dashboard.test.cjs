// Regression checks run the shipped script with a minimal DOM and controlled API latency.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const code = readFileSync(path.join(__dirname, '../src/bbdevbox/web/dashboard.js'), 'utf8');
class Element {
  constructor() { this.textContent = ''; this.children = []; this.style = {}; this.attributes = {}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this.attributes[key] = value; }
  scrollIntoView() {}
}
function row(id) {
  return {id, status: 'completed', config: {model: {name: 'fixture'}, sandbox: {backend: 'docker'},
    memory: {mode: 'off'}}, counts: {passed: 1}, total: 1, heartbeat: Date.now() / 1000};
}
const settle = async () => { for (let i = 0; i < 4; i++) await new Promise(setImmediate); };
function page(ids, search = '', overrides = {}) {
  const elements = new Map(), streams = [], state = {runs: ids.map(row)};
  const element = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const location = {href: 'http://localhost:8765/' + search, search};
  class Stream {
    constructor(url) { this.url = url; this.handlers = {}; streams.push(this); }
    addEventListener(name, handler) { this.handlers[name] = handler; }
    close() { this.closed = true; }
  }
  const context = vm.createContext({document: {getElementById: element, createElement: () => new Element()},
    URL, URLSearchParams, location, EventSource: Stream, console, setInterval: () => {},
    addEventListener: () => {}, history: {replaceState: (_, __, url) => {
      location.href = new URL(url, location.href).href;
      location.search = new URL(location.href).search;
    }}, fetch: async url => {
      if (overrides[url]) return overrides[url]();
      let data;
      if (url === '/api/info') data = {root: '/actual/runs'};
      else if (url === '/api/runs') data = state.runs;
      else {
        const id = decodeURIComponent(url.replace('/api/run/', ''));
        const run = state.runs.find(r => r.id === id);
        if (!run) return {ok: false, text: async () => 'Unknown run'};
        data = {run, attempts: []};
      }
      return {ok: true, json: async () => data};
    }});
  vm.runInContext(code, context);
  return {context, elements, element, streams, state, location};
}
test('default page follows a newly created run, not only the first page load', async () => {
  const p = page(['old']); await settle();
  assert.match(p.element('title').textContent, /old$/);
  assert.equal(p.element('storage').textContent, '数据目录：/actual/runs');
  p.state.runs.unshift(row('new'));
  await p.context.loadRuns(); await settle();
  assert.match(p.element('title').textContent, /new$/);
  assert.equal(p.location.search, '');
});
test('explicit run link pins selection across refreshes and manual selection updates the URL', async () => {
  const p = page(['new', 'old'], '?run=old'); await settle();
  assert.match(p.element('title').textContent, /old$/);
  p.state.runs.unshift(row('newest'));
  await p.context.loadRuns(); await settle();
  assert.match(p.element('title').textContent, /old$/);
  p.context.selectRun('new'); await settle();
  assert.equal(p.location.search, '?run=new');
  p.element('follow-latest').onclick(); await settle();
  assert.match(p.element('title').textContent, /newest$/);
  assert.equal(p.location.search, '');
});
test('a slow response or done event from the previous run cannot replace the new selection', async () => {
  let finishOld;
  const oldResponse = new Promise(resolve => { finishOld = resolve; });
  const p = page(['old', 'new'], '', {'/api/run/old': () => oldResponse}); await settle();
  const oldStream = p.streams[0];
  p.context.selectRun('new'); await settle();
  const newStream = p.streams[1];
  assert.match(p.element('title').textContent, /new$/);
  finishOld({ok: true, json: async () => ({run: row('old'), attempts: []})}); await settle();
  assert.match(p.element('title').textContent, /new$/);
  oldStream.handlers.done();
  assert.equal(newStream.closed, undefined);
});
test('a run absent from this root does not silently display another run', async () => {
  const p = page(['other-root-run'], '?run=missing'); await settle();
  assert.match(p.element('title').textContent, /missing$/);
  assert.match(p.element('error').textContent, /actual\/runs/);
  assert.equal(p.element('passed').textContent, '—');
  assert.equal(p.location.search, '?run=missing');
});
