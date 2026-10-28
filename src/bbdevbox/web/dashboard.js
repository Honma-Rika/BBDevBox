const $ = id => document.getElementById(id);
let selected = null, source = null, checked = new Set(), eventLines = [], cachedRuns = [];
let followLatest = !new URLSearchParams(location.search).get('run');
let selectionVersion = 0, pendingDetails = new Set(), loadingRuns = false, storageRoot = '';
const num = n => Number(n || 0).toLocaleString();
const pct = n => n === null ? '—' : (n * 100).toFixed(1) + '%';

function el(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
async function get(path) {
  const r = await fetch(path);
  if (!r.ok) throw Error(await r.text());
  return r.json();
}
function fail(e) {
  $('error').textContent = String(e);
  $('connection').textContent = '连接异常 · 自动重试';
}
function updateMode() {
  $('follow-latest').textContent = '跟随最新运行：' + (followLatest ? '开启' : '关闭（已固定）');
  $('follow-latest').setAttribute('aria-pressed', String(followLatest));
}
function renderRuns() {
  $('runs').replaceChildren();
  for (const r of cachedRuns) {
    const card = el('div', undefined, 'run' + (r.id === selected ? ' active' : ''));
    const line = el('div', undefined, 'row');
    const name = el('span', r.config.model.name);
    const box = el('input');
    box.type = 'checkbox';
    box.checked = checked.has(r.id);
    box.setAttribute('aria-label', '选择 ' + r.id);
    box.onclick = e => e.stopPropagation();
    box.onchange = () => box.checked ? checked.add(r.id) : checked.delete(r.id);
    line.append(name, box);
    const open = el('button', r.id);
    open.setAttribute('aria-label', '查看运行 ' + r.id);
    open.onclick = e => { e.stopPropagation(); selectRun(r.id); };
    card.append(line, open, el('p', r.status + (r.stale ? ' · STALE' : '') + ' · ' +
      r.counts.passed + '/' + r.total + ' attempts'));
    card.onclick = () => selectRun(r.id);
    $('runs').append(card);
  }
  if (!cachedRuns.length) $('runs').append(el('div', '还没有运行。使用 bbdevbox run 或 import-results。', 'empty'));
}
async function loadRuns() {
  if (loadingRuns) return;
  loadingRuns = true;
  try {
    cachedRuns = await get('/api/runs');
    if (followLatest && cachedRuns.length && selected !== cachedRuns[0].id) {
      selectRun(cachedRuns[0].id, false);
    }
    renderRuns();
    if (selected && !cachedRuns.some(r => r.id === selected)) {
      $('error').textContent = '当前数据目录 ' + storageRoot + ' 中找不到运行 ' + selected +
        '。请确认 run、status 和 serve 使用同一个 --root；或点击“跟随最新运行”。';
    }
  } catch (e) { fail(e); }
  finally { loadingRuns = false; }
}
function draw(data) {
  const rows = data.attempts, r = data.run;
  const ids = new Set(rows.map(a => a.task_id));
  const passed = new Set(rows.filter(a => a.status === 'passed').map(a => a.task_id));
  const done = rows.filter(a => ['passed', 'failed', 'error'].includes(a.status)).length;
  const input = rows.reduce((s, a) => s + a.input_tokens, 0);
  const output = rows.reduce((s, a) => s + a.output_tokens, 0);
  const estimated = rows.reduce((s, a) => s + a.estimated_calls, 0);
  $('title').textContent = r.config.model.name + ' / ' + r.id;
  $('protocol').textContent = r.config.sandbox.backend + ' · memory: ' + r.config.memory.mode;
  $('passed').textContent = passed.size + ' / ' + ids.size;
  $('completed').textContent = done + ' / ' + rows.length;
  $('tokens').textContent = num(input) + ' / ' + num(output);
  $('estimated').textContent = estimated ? estimated + ' 次调用含估算、缺失 usage 或历史总量' :
    '按已返回的 provider usage 统计';
  const age = Math.max(0, Math.floor(Date.now() / 1000 - r.heartbeat));
  $('heartbeat').textContent = r.status + ' · ' + age + 's';
  $('heartbeat').className = age > 30 && r.status === 'running' ? 'red' : '';
  $('progress').style.width = (rows.length ? 100 * done / rows.length : 0) + '%';
  $('attempts').replaceChildren();
  for (const a of rows) {
    const tr = el('tr');
    tr.title = a.error || '';
    const secs = a.started ? Math.max(0, (a.finished || Date.now() / 1000) - a.started).toFixed(0) + 's' : '—';
    for (const text of [a.task_id + ' / ' + (a.repetition + 1), a.domain, a.status,
      (a.agent || '—') + ' / ' + (a.phase || '—'), a.step, num(a.input_tokens + a.output_tokens), secs]) {
      tr.append(el('td', text));
    }
    tr.children[2].className = a.status === 'passed' ? 'green' : ['failed', 'error'].includes(a.status) ? 'red' : '';
    $('attempts').append(tr);
  }
}
async function detail() {
  const id = selected, version = selectionVersion;
  if (!id || pendingDetails.has(version)) return;
  pendingDetails.add(version);
  try {
    const data = await get('/api/run/' + encodeURIComponent(id));
    if (version !== selectionVersion || selected !== id) return;
    draw(data);
    $('error').textContent = '';
    $('connection').textContent = '已连接 · 每 2 秒校准';
  } catch (e) {
    if (version === selectionVersion) {
      fail('无法读取运行 ' + id + '；请检查 serve 的数据目录 ' + storageRoot + '。' + e);
    }
  } finally { pendingDetails.delete(version); }
}
function clearDetail(id) {
  $('title').textContent = '正在读取运行 ' + id;
  for (const field of ['passed', 'completed', 'tokens', 'heartbeat', 'protocol', 'estimated']) {
    $(field).textContent = '—';
  }
  $('attempts').replaceChildren();
  $('progress').style.width = '0%';
}
function selectRun(id, pin = true, updateUrl = true) {
  if (pin) followLatest = false;
  updateMode();
  if (updateUrl) {
    const url = new URL(location.href);
    if (followLatest) url.searchParams.delete('run');
    else url.searchParams.set('run', id);
    history.replaceState(null, '', url.pathname + url.search + url.hash);
  }
  if (selected === id) { renderRuns(); detail(); return; }
  selected = id;
  const version = ++selectionVersion;
  clearDetail(id);
  eventLines = [];
  $('events').textContent = '';
  if (source) source.close();
  const stream = new EventSource('/api/events?run=' + encodeURIComponent(id));
  source = stream;
  stream.onmessage = e => {
    if (version !== selectionVersion) return;
    const v = JSON.parse(e.data);
    const payload = v.kind === 'prompt_selected' ? {agent: v.payload.agent, sha256: v.payload.sha256} : v.payload;
    eventLines.push(new Date(v.ts * 1000).toLocaleTimeString() + ' ' + (v.attempt_id || 'run').slice(0, 8) +
      ' ' + v.kind + ' ' + JSON.stringify(payload));
    eventLines = eventLines.slice(-100);
    $('events').textContent = eventLines.join('\n');
    $('events').scrollTop = $('events').scrollHeight;
  };
  stream.addEventListener('done', () => stream.close());
  stream.onerror = () => {
    if (version === selectionVersion) $('connection').textContent = '事件流重连中 · 快照仍刷新';
  };
  renderRuns();
  detail();
}
function followNewest() {
  followLatest = true;
  updateMode();
  const url = new URL(location.href);
  url.searchParams.delete('run');
  history.replaceState(null, '', url.pathname + url.search + url.hash);
  if (cachedRuns.length) selectRun(cachedRuns[0].id, false);
  loadRuns();
}
async function comparison() {
  try {
    if (!checked.size) throw Error('请至少勾选一个运行');
    const r = await get('/api/compare?ids=' + encodeURIComponent([...checked].join(',')));
    $('comparison-panel').hidden = false;
    $('comparison').replaceChildren();
    $('warnings').textContent = r.warnings.join('\n');
    for (const run of r.runs) {
      const item = el('div');
      item.append(el('div', run.model + ' · ' + run.id + ' · ' + pct(run.common.macro_pass_at_1) +
        ' · errors ' + run.common.errors));
      const track = el('div', undefined, 'track'), bar = el('div', pct(run.common.macro_pass_at_1), 'bar');
      bar.style.width = ((run.common.macro_pass_at_1 || 0) * 100) + '%';
      track.append(bar); item.append(track); $('comparison').append(item);
    }
    $('metrics').textContent = JSON.stringify(r, null, 2);
    $('comparison-panel').scrollIntoView({behavior: 'smooth'});
    $('error').textContent = '';
  } catch (e) { fail(e); }
}
async function initialize() {
  try {
    const info = await get('/api/info');
    storageRoot = info.root;
    $('storage').textContent = '数据目录：' + storageRoot;
  } catch (e) { fail(e); }
  const requested = new URLSearchParams(location.search).get('run');
  if (requested) selectRun(requested);
  updateMode();
  await loadRuns();
}
$('refresh').onclick = () => { loadRuns(); detail(); };
$('compare').onclick = comparison;
$('follow-latest').onclick = followNewest;
addEventListener('popstate', () => {
  const id = new URLSearchParams(location.search).get('run');
  if (id) selectRun(id, true, false);
  else followNewest();
});
initialize();
setInterval(detail, 2000);
setInterval(loadRuns, 2000);
