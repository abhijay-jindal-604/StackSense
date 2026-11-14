'use strict';
/* StackSense UI, "Fitting Bay": plain ES2020, no build step, no network beyond the local API.
   Every number on screen comes from /api/*. The part index numbers (01 visor, 02 spine, 03 core,
   04 cradle, 05+ bolt-ons) are labels for the print sheet only, never data. */

// ---------------------------------------------------------------- constants
const INR_PER_USD = 88; // fixed display rate; stated next to every rupee figure, never part of the JSON
const SEV_ORDER = ['critical', 'warning', 'info'];
const SEV_CLASS = { critical: 'crit', warning: 'warn', info: 'info' };
const SEV_WORD = { critical: 'critical', warning: 'warning', info: 'note' };
/* layer -> robot part; the order is the order of the part tabs */
const PARTS = [
  { layer: 'frontend', part: 'visor', idx: '01', sub: 'frontend' },
  { layer: 'backend', part: 'spine', idx: '02', sub: 'backend' },
  { layer: 'database', part: 'core', idx: '03', sub: 'database' },
  { layer: 'hosting', part: 'cradle', idx: '04', sub: 'hosting' },
];
const PART_OF = Object.fromEntries(PARTS.map((p) => [p.layer, p]));
const LAYER_OF = Object.fromEntries(PARTS.map((p) => [p.part, p.layer]));
/* questionnaire step -> the part it fits (statement steps; Requirements fit the bolt-ons) */
const STEP_PART = { 1: 'visor', 2: 'core', 3: 'spine', 4: 'cradle', 5: 'cradle', 6: 'bolt', 7: 'core' };
/* score-line ranges, copied from scoring.py W (plan 5.3); the About screen shows these */
const SCORE_RANGES = [
  ['priorities (your 1–5 weights)', '0 … +10'], ['skill fit', '−8 … +4'], ['requirement fit', '−12 … +10'],
  ['type affinity', '−3 … +3'], ['budget fit', '−8 … +3'], ['lock-in', '−2.5 … 0'], ['overengineering', '−10 … 0'],
];
const SVG_NS = 'http://www.w3.org/2000/svg';

// ---------------------------------------------------------------- helpers
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'value') el.value = v;
    else if (k === 'checked' || k === 'disabled' || k === 'selected') { if (v) el[k] = true; }
    else el.setAttribute(k, v === true ? '' : v);
  }
  addKids(el, kids);
  return el;
}
function addKids(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k.nodeType ? k : document.createTextNode(String(k)));
  }
}
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => [...(r || document).querySelectorAll(s)];
const titleCase = (s) => String(s).replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
const words = (s) => String(s).replace(/_/g, ' ');
const isObj = (v) => v && typeof v === 'object' && !Array.isArray(v);
function getp(o, path) { return path.split('.').reduce((a, k) => (a == null ? undefined : a[k]), o); }
function setp(o, path, v) {
  const ks = path.split('.');
  let c = o;
  ks.slice(0, -1).forEach((k) => { if (!isObj(c[k])) c[k] = {}; c = c[k]; });
  c[ks[ks.length - 1]] = v;
}
function delp(o, path) {
  const ks = path.split('.');
  const stack = [o];
  let c = o;
  for (const k of ks.slice(0, -1)) { if (!isObj(c[k])) return; c = c[k]; stack.push(c); }
  delete c[ks[ks.length - 1]];
  for (let i = ks.length - 2; i >= 0; i--) {
    if (Object.keys(stack[i + 1]).length === 0) delete stack[i][ks[i]]; else break;
  }
}
const fmtVal = (v) => (v === undefined ? '(not set)' : typeof v === 'string' ? v : JSON.stringify(v));
const nf = new Intl.NumberFormat('en-US');
const nfIN = new Intl.NumberFormat('en-IN');
const usd = (n) => nf.format(n);
const band = (c) => (c ? usd(c.min) + '–' + usd(c.max) : '–');
const inr = (n) => '₹' + nfIN.format(Math.round(n * INR_PER_USD));
const sgn = (v) => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(2);
/* a short name for a tag bar: drop parentheses and "for the ..." clauses */
function short(s, max = 30) {
  let t = String(s || '').replace(/\s*\([^)]*\)/g, '').replace(/ for the [^+]*/g, ' ').replace(/\s+\+\s+/g, ' + ').replace(/\s+/g, ' ').trim();
  if (t.length > max) t = t.slice(0, max - 1).replace(/\s+\S*$/, '') + '…';
  return t;
}
async function api(path, opts) {
  try {
    const r = await fetch(path, opts);
    const text = await r.text();
    let data = null;
    try { data = JSON.parse(text); } catch (e) { /* not JSON */ }
    return { ok: r.ok, status: r.status, text, data };
  } catch (e) { return { ok: false, status: 0, text: '', data: null }; }
}
const post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type: type || 'application/json' }));
  const a = h('a', { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function copyText(text, btn) {
  try { await navigator.clipboard.writeText(text); btn.textContent = 'Copied'; }
  catch (e) { btn.textContent = 'Copy failed: select the text instead'; }
}
const reduce = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const SHOT = () => document.documentElement.hasAttribute('data-shot');

// ---------------------------------------------------------------- state
const S = {
  health: null, schema: null, fields: [], steps: [], scenarios: [],
  scenario: {}, scenarioName: '', fill: false,
  result: null, raw: null, running: false,
  errMap: {}, valid: null, touched: new Set(), showAll: false,
  sel: 'backend', tab: 'warnings',
  kb: null, sources: null, kbRec: {}, kbSel: null, kbFilter: { group: 'spine', status: '', q: '' },
  sens: null, sensBase: '', whatif: null, upload: null, status: {}, demo: null, fitParts: null,
};
const main = () => document.getElementById('main');
const put = (el, ...kids) => addKids(el, kids);

// ---------------------------------------------------------------- boot
async function boot() {
  const q = new URLSearchParams(location.search);
  FB.parts();
  main().append(h('p', { class: 'loading', role: 'status' }, 'Opening the bay'));
  const [health, schema, scn] = await Promise.all([api('/api/health'), api('/api/schema'), api('/api/scenarios')]);
  S.health = health.data; S.schema = schema.data; S.scenarios = scn.data || [];
  if (S.schema) {
    S.fields = S.schema.groups.flatMap((g) => g.fields.map((f) => ({ ...f, group: g.name })));
    const by = new Map();
    for (const g of S.schema.groups) {
      const n = g.fields[0] ? g.fields[0].step : 0;
      if (!by.has(n)) by.set(n, []);
      by.get(n).push(g.name);
    }
    S.steps = [...by.entries()].sort((a, b) => a[0] - b[0]).map(([n, names]) => ({ n, name: names.join(' and ').replace(/&/g, 'and') }));
  }
  renderChrome();
  await loadDemo();
  const sid = q.get('scenario');
  if (sid) await loadScenario(sid, { silent: true });
  if (q.get('stratum')) S.sel = q.get('stratum');
  if (q.get('tab')) S.tab = q.get('tab');
  if (q.get('fill') === '1') S.fill = true;
  if (q.get('run') === '1' && sid) await run({ noNav: true });
  window.addEventListener('hashchange', route);
  route();
}

/* the hero shows a real run of public scenario P2 */
async function loadDemo() {
  const sc = await api('/api/scenarios/P2');
  if (!sc.ok || !isObj(sc.data)) return;
  const r = await post('/api/recommend', { scenario: sc.data, fill_defaults: false, llm: false });
  if (r.ok && r.data && r.data.stack) S.demo = { scenario: sc.data, result: r.data };
}

function renderChrome() {
  const hd = S.health;
  $('#meta').replaceChildren(h('span', {}, h('i', { class: 'dot' }), 'deterministic · LLM ' + (hd ? hd.llm : 'unknown')));
  $('#footer').replaceChildren(
    h('span', {}, 'engine ', h('code', {}, hd ? hd.engine_version : 'unknown')),
    h('span', {}, 'knowledge base ', h('code', {}, hd ? hd.kb_version : 'unknown')),
    h('span', {}, 'same input, same output, byte for byte'));
}

/* one nav, the same eight items on every screen; result-only items stay in place, disabled */
const NAV = [['#/', 'Fitting bay', 'start'], ['#/q/1', 'Questionnaire', 'q'], ['#/review', 'Pre-fit check', 'review'],
  ['#/result', 'Fitted body', 'result', 1], ['#/whatif', 'What-if', 'whatif', 1], ['#/sens', 'Sensitivity', 'sens', 1],
  ['#/kb', 'Parts catalogue', 'kb'], ['#/about', 'How it decides', 'about']];
function paintNav(cur) {
  $('#nav').replaceChildren(...NAV.map(([href, label, key, needs]) => {
    if (needs && !S.result) return h('span', { class: 'navoff', 'aria-disabled': 'true', title: 'Run a scenario first' }, label);
    return h('a', { href, 'aria-current': key === cur ? 'page' : false }, label);
  }));
}

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [p, qs] = raw.split('?');
  return { parts: p.split('/').filter(Boolean), q: new URLSearchParams(qs || '') };
}
function route() {
  const { parts, q } = parseHash();
  const v = parts[0] || 'start';
  const m = main();
  m.replaceChildren();
  m.className = '';
  S.edit = null; S.onEdit = null;
  window.scrollTo(0, 0);
  if (!S.schema) { put(m, h('p', { class: 'err-text' }, 'The API did not answer. Start the server with: python3 -m stacksense serve')); return; }
  paintNav(v);
  document.body.dataset.view = v;
  const views = { start: viewStart, q: () => viewQuestion(Number(parts[1]) || 1, q.get('f')), review: viewReview, result: viewResult, whatif: viewWhatIf, sens: viewSens, kb: viewKb, about: viewAbout };
  (views[v] || viewStart)();
  document.title = 'StackSense: ' + ({ start: 'fitting bay', q: 'questionnaire', review: 'pre-fit check', result: 'fitted body', whatif: 'what-if', sens: 'sensitivity', kb: 'parts catalogue', about: 'how it decides' }[v] || 'fitting bay');
}
const go = (hash) => { if (location.hash === hash) route(); else location.hash = hash; };

/* print-sheet rules (shown only in the print theme used by ?shot=1) */
function sheetHead(left, right) {
  return h('header', { class: 'sheet-head', 'aria-hidden': 'true' }, h('div', { class: 'row' }, h('span', {}, 'StackSense · Fitting bay — ' + left), h('span', {}, right || scenarioTitle())));
}
function sheetFoot(title) {
  const hd = S.health || {};
  return h('footer', { class: 'sheet-foot', 'aria-hidden': 'true' }, h('div', { class: 'sub' }, h('span', {}, 'kb ' + (hd.kb_version || '') + ' · same answers, same body'), h('span', {}, 'Synergy ’26 · StackSense')), h('b', {}, title));
}
const hd2 = (id, title, lede, sub, acts) => h('div', { class: 'hd' }, h('div', {}, h('h2', { class: 'h2', id }, title), lede ? h('p', { class: 'lede' }, lede, sub ? h('span', {}, ' ' + sub) : null) : null), acts ? h('div', { class: 'acts' }, acts) : null);

// ---------------------------------------------------------------- scenarios
async function loadScenario(id, opts) {
  const r = await api('/api/scenarios/' + encodeURIComponent(id));
  if (!r.ok || r.data == null) { S.upload = { error: 'Could not load ' + id + ': ' + ((r.data && r.data.error) || 'unreadable file') }; if (!(opts && opts.silent)) route(); return false; }
  setScenario(r.data, id);
  if (opts && opts.run) { await run(); return true; }
  if (!(opts && opts.silent)) go('#/q/1');
  return true;
}
function setScenario(obj, name) {
  S.scenario = obj; S.scenarioName = name || ''; S.result = null; S.raw = null; S.errMap = {}; S.touched = new Set(); S.showAll = false; S.whatif = null; S.upload = null; S.fitParts = null;
  scheduleValidate(0);
}
function scenarioTitle() {
  const n = isObj(S.scenario) && getp(S.scenario, 'project.name');
  return n || S.scenarioName || 'untitled scenario';
}

// ---------------------------------------------------------------- validation
let vTimer = null;
function scheduleValidate(delay = 250) {
  clearTimeout(vTimer);
  vTimer = setTimeout(async () => {
    const r = await post('/api/validate', { scenario: S.scenario, fill_defaults: false });
    if (!r.ok || !r.data) return;
    S.valid = r.data;
    S.errMap = {};
    for (const e of r.data.errors || []) {
      const key = String(e.field).replace(/\[.*$/, '');
      (S.errMap[key] = S.errMap[key] || []).push(e);
    }
    paintFieldMessages();
    paintDraft();
    const rv = document.getElementById('review-errors');
    if (rv) viewReviewErrors(rv);
  }, delay);
}

// ---------------------------------------------------------------- shared drawing
function nest(html, x, y, w, hh, vb) { return html.replace(/<svg class="bot([^"]*)"[^>]*>/, `<svg class="bot$1" x="${x}" y="${y}" width="${w}" height="${hh}" viewBox="${vb}" style="overflow:visible">`); }
const C = FB.C;
function miniBay(w, hh, { lamp = w / 2, floor = hh - 70, extra = '' } = {}) {
  return `<rect width="${w}" height="${hh}" fill="var(--wall)"/>
   <path d="M-20 40 L${w * .5} ${floor - 10} M${w * .5} 40 L-20 ${floor - 10} M${w * .5 + 20} 40 L${w + 20} ${floor - 10} M${w + 20} 40 L${w * .5 + 20} ${floor - 10}" stroke="var(--girder)" stroke-width="16" opacity=".85"/>
   <rect x="0" y="0" width="${w}" height="26" fill="var(--girder)"/><rect y="22" width="${w}" height="4" fill="var(--girder-hi)" opacity=".6"/>
   <polygon points="${lamp - 20},58 ${lamp + 20},58 ${lamp + w * .34},${floor + 30} ${lamp - w * .34},${floor + 30}" fill="url(#fb-cone)"/>
   <rect y="${floor}" width="${w}" height="${hh - floor}" fill="var(--floor)"/><rect y="${floor}" width="${w}" height="4" fill="var(--floor-2)"/>
   <ellipse cx="${lamp}" cy="${floor + 26}" rx="${w * .36}" ry="22" fill="url(#fb-pool)"/>
   <path d="M${lamp} 26 V38" stroke="${C.ink}" stroke-width="3"/><path d="M${lamp - 26} 60 Q${lamp - 22} 38 ${lamp} 38 Q${lamp + 22} 38 ${lamp + 26} 60 Z" fill="#2E3A36" stroke="${C.ink}" stroke-width="3"/><ellipse cx="${lamp}" cy="60" rx="26" ry="4" fill="${C.ink}"/><ellipse cx="${lamp}" cy="61" rx="18" ry="3" fill="var(--cone)"/>${extra}`;
}
const stageSVG = (w, hh, inner, label) => `<svg viewBox="0 0 ${w} ${hh}" ${label ? `role="img" aria-label="${esc(label)}"` : 'aria-hidden="true"'}>${inner}</svg><div class="grain"></div>`;
const MONO = 'style="font-family:var(--mono)"';

/* supporting services -> bolt-ons */
function boltKind(slot, layer) {
  const last = String(slot || '').split('.').pop();
  if (FB.SLOT[last]) return last;
  if (FB.SLOT[layer]) return layer;
  return 'other';
}
const slotName = (slot) => words(String(slot).replace(/^other\./, '').replace(/\./g, ' / '));
/* the bolt-ons of a result, in display order: fitted services, then gaps. idx 05+ follows this order. */
function boltsOf(res) {
  const st = (res && res.stack) || {};
  const out = (st.supporting || []).map((s, i) => ({ kind: boltKind(s.slot, s.layer), state: 'fit', name: s.choice, slot: s.slot, sel: 'sup:' + i }));
  const gaps = (res && res.decision_trace && res.decision_trace.supporting && res.decision_trace.supporting.gaps) || [];
  gaps.forEach((g, i) => out.push({ kind: boltKind(g.slot, g.layer), state: 'gap', name: 'no part fits', slot: g.slot, sel: 'gap:' + i, message: g.message }));
  out.forEach((b, i) => { b.idx = String(5 + i).padStart(2, '0'); });
  return out;
}
function gaugeOf(res) {
  const c = res && res.estimated_monthly_cost_usd, bv = res && res.budget_verdict;
  if (!c) return { low: 0, high: 0, budget: 0 };
  return { low: c.min, high: c.max, budget: bv ? bv.budget_usd : c.min };
}
/* trace helpers */
function traceLayers(res) { return (res && res.decision_trace && res.decision_trace.layers) || {}; }
function traceTop(res, id) {
  const L = traceLayers(res);
  for (const k of Object.keys(L)) { const t = (L[k].top || []).find((x) => x.id === id); if (t) return { t, layer: k, L: L[k] }; }
  return null;
}
function traceRejected(res, name) {
  const L = traceLayers(res);
  for (const k of Object.keys(L)) { const t = (L[k].rejected || []).find((x) => x.name === name || x.tech_id === name); if (t) return t; }
  return null;
}
function idsOf(it) { return it.kb_ids && it.kb_ids.length ? it.kb_ids : it.kb_id ? [it.kb_id] : []; }
function partScore(res, layer) {
  const it = res.stack && res.stack[layer]; if (!it) return null;
  const id = idsOf(it)[0]; const tt = id && traceTop(res, id);
  return tt ? { total: tt.t.total, of: tt.L.candidates, tl: tt.layer } : null;
}
function inputValue(path) {
  const v = getp(isObj(S.scenario) ? S.scenario : {}, path);
  return v === undefined ? undefined : Array.isArray(v) ? v.join(', ') : typeof v === 'string' ? v : JSON.stringify(v);
}

// ---------------------------------------------------------------- start: hero + bay door
function viewStart() {
  const m = main();
  m.classList.add('wide');
  put(m, heroSection(), doorSection());
}
function heroSection() {
  const D = S.demo;
  const sec = h('section', { class: 'hero', id: 'hero', 'aria-label': 'StackSense fitting bay' });
  put(sec, sheetHead('technical data', D ? 'P2 · ' + (getp(D.scenario, 'project.name') || 'P2') : ''));
  const stage = h('div', { class: 'stage', id: 'stage' });
  const scene = document.createElementNS(SVG_NS, 'svg');
  scene.setAttribute('class', 'scene'); scene.id = 'scene'; scene.setAttribute('viewBox', '0 0 1600 900'); scene.setAttribute('preserveAspectRatio', 'xMaxYMax slice');
  scene.setAttribute('role', 'img');
  scene.setAttribute('aria-label', 'A robot chassis hangs in a dark robotics bay. Its visor, spine and core gauge are fitted and tagged; the hosting cradle waits for the budget answer.');
  const replay = h('div', { class: 'replay' }, h('button', { type: 'button', id: 'replay', html: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 6a4 4 0 1 0 1.2-2.8M2 1.5V4h2.5" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>Replay the fitting' }));
  const edge = h('div', { class: 'edge', id: 'edge' });
  stage.append(scene, h('div', { class: 'grain' }), replay, edge);
  const res = D && D.result, sc = D && D.scenario;
  const nw = res ? (res.warnings || []).filter((w) => w.severity !== 'info').length : 0;
  const tp = h('div', { class: 'tp' },
    h('div', { class: 'layer l-soot' }), h('div', { class: 'layer l-weld' }), h('div', { class: 'layer l-ink' }), h('div', { class: 'layer l-paper' }),
    h('div', { class: 'inp' },
      h('h1', { html: 'Every answer <em>bolts on</em> a part.' }),
      h('p', { class: 'lede' }, 'Your project rolls in as a bare chassis. ', h('span', {}, 'Tell the bay your team, budget, deadline and the laws you answer to; it fits each part and tags it with the answer that put it there.')),
      h('div', { class: 'acts' },
        h('button', { class: 'btn p', type: 'button', onclick: () => { setScenario({}, ''); go('#/q/1'); } }, 'Start the fitting ', h('span', { class: 'arr' }, '→')),
        h('button', { class: 'btn', type: 'button', onclick: () => loadScenario('P2', { run: true }) }, 'Load ' + (sc ? getp(sc, 'project.name') : 'P2'))),
      res ? h('dl', { class: 'proof' },
        h('dt', {}, 'scenario'), h('dd', {}, 'P2 · ' + getp(sc, 'project.name') + ' · ' + words(getp(sc, 'project.type') || '') + (getp(sc, 'infrastructure.data_residency') && getp(sc, 'infrastructure.data_residency') !== 'none' ? ', ' + titleCase(getp(sc, 'infrastructure.data_residency')) : '')),
        h('dt', {}, 'status'), h('dd', { class: 'w' }, words(res.status) + (nw ? ' · ' + nw : '')),
        h('dt', {}, 'runs on'), h('dd', {}, 'Python stdlib, no pip install')) : null));
  const tags = h('div', { class: 'tags', id: 'tags' });
  put(sec, stage, tp, tags);
  if (res) put(sec, heroDock(sc, res));
  put(sec, h('div', { class: 'below' }), h('footer', { class: 'sheet-foot', 'aria-hidden': 'true' }, h('div', { class: 'sub' }, h('span', {}, 'deterministic · LLM ' + ((S.health || {}).llm || 'off') + ' · Python stdlib'), h('span', {}, '01 visor · 02 spine · 03 core · 04 cradle')), h('b', {}, 'Fitting bay — assembly diagram')));
  requestAnimationFrame(() => buildHeroScene(sec));
  return sec;
}
function heroDock(sc, res) {
  const g = gaugeOf(res);
  const budget = getp(sc, 'budget.monthly_infra_usd');
  const inp = h('input', { id: 'bud', inputmode: 'numeric', value: budget, 'aria-describedby': 'inr msg', autocomplete: 'off' });
  const msg = h('div', { class: 'msg ok', id: 'msg', 'aria-live': 'polite' });
  const inrEl = h('span', { class: 'inr', id: 'inr' });
  const set = (v) => {
    const max = FB.gaugeScale({ ...g, budget: v }), a = FB.ang(v, max);
    $$('#scene .gauge').forEach((gg) => {
      const n = gg.querySelector('.needle'); n.style.animation = 'none'; n.style.setProperty('--aB', a + 'deg');
      gg.querySelector('.face').setAttribute('fill', v >= g.low && v <= g.high ? C.face : C.faceOut);
    });
    const cn = $('#cneedle'); if (cn) cn.textContent = usd(v);
    inrEl.textContent = '≈ ' + inr(v) + ' at ₹' + INR_PER_USD + ' per USD, display only';
    if (v < g.low) { msg.className = 'msg'; msg.textContent = `Below the band: USD ${usd(v)} won't cover the low estimate of USD ${usd(g.low)}. The run will say so with BUDGET_EXCEEDED.`; }
    else if (v > g.high) { msg.className = 'msg ok'; msg.textContent = `Above the band: USD ${usd(v)} covers even the high estimate of USD ${usd(g.high)}.`; }
    else { msg.className = 'msg ok'; msg.textContent = `Inside the band: the estimate for ${getp(sc, 'project.name')} is USD ${band(res.estimated_monthly_cost_usd)}.`; }
  };
  inp.addEventListener('input', () => {
    const v = parseInt(inp.value.replace(/\D/g, ''), 10);
    if (!isNaN(v)) set(Math.min(v, 99999)); else { msg.className = 'msg'; msg.textContent = 'Write a whole number of US dollars, for example 150.'; }
  });
  setTimeout(() => set(budget), 0);
  const f = S.fields.find((x) => x.path === 'budget.monthly_infra_usd');
  return h('form', { class: 'dock', id: 'dock', onsubmit: (e) => e.preventDefault(), 'aria-label': 'Questionnaire, budget step' },
    h('div', { class: 'hzs hazard-edge', 'aria-hidden': 'true' }),
    h('ol', { class: 'steps' }, S.steps.map((s) => h('li', { class: s.n < 4 ? 'done' : s.n === 4 ? 'now' : '', 'aria-current': s.n === 4 ? 'step' : false }, s.name, h('span', {}, s.n < 4 ? 'bolted' : '')))),
    h('div', { class: 'q' },
      h('div', { class: 'k' }, 'step 4 of ' + S.steps.length + ' · ', h('code', {}, 'budget.monthly_infra_usd')),
      h('h2', {}, f ? f.label : 'Monthly infrastructure budget'),
      h('p', { class: 'why' }, 'The bay prices every part. If the estimate runs past this, the cost gauge turns hazard yellow and the tag says so. It never overruns quietly.'),
      h('div', { class: 'row' }, h('div', { class: 'money' }, h('label', { for: 'bud' }, 'USD'), inp, h('span', { class: 'per' }, '/ month')), inrEl),
      msg),
    h('div', { class: 'moves' },
      h('div', { class: 'k' }, 'this answer moves'),
      h('div', { class: 'chips' }, h('span', { class: 'chip hz' }, 'cradle · hosting'), h('span', { class: 'chip' }, 'cost gauge'), h('span', { class: 'chip' }, 'warnings')),
      h('p', { class: 'muted', style: 'margin:0;font-size:13.5px' }, 'Try 40 or 400: the needle in the core moves now; the parts are chosen when you run the fitting.'),
      h('button', { class: 'btn p', id: 'fitcradle', type: 'button', onclick: () => {
        const v = parseInt(inp.value.replace(/\D/g, ''), 10);
        const s2 = JSON.parse(JSON.stringify(sc)); if (!isNaN(v)) setp(s2, 'budget.monthly_infra_usd', v);
        setScenario(s2, 'P2'); run();
      } }, 'Fit the cradle ', h('span', { class: 'arr' }, '→'))));
}
function buildHeroScene(sec) {
  const scene = $('#scene', sec); if (!scene) return;
  const D = S.demo;
  const res = D && D.result, sc = D && D.scenario;
  const G = res ? gaugeOf(res) : { low: 0, high: 0, budget: 0 };
  const RX = 910, RY = 146;
  const bay = FB.bay({ lamps: [790, 1110, 1430], floorY: 770, scaffold: [330, 1480], carts: [600, 1490], bayMark: [1110, 420] });
  function lampSparks(x, t0, seed) {
    let r = seed; const rnd = () => (r = (r * 9301 + 49297) % 233280) / 233280; let s = `<g class="lsp" style="--t0:${t0}s">`;
    for (let i = 0; i < 16; i++) { const dx = (rnd() - .5) * 110, dy = 170 + rnd() * 360, len = 8 + rnd() * 10; s += `<line x1="${x + (rnd() - .5) * 40}" y1="134" x2="${x + (rnd() - .5) * 40}" y2="${134 + len}" style="--i:${i};--dx:${dx.toFixed(0)}px;--dy:${dy.toFixed(0)}px;--d:${(.9 + rnd() * .6).toFixed(2)}s"/>`; }
    return s + '</g>';
  }
  const fogBank = (y, o) => [...Array(9)].map((_, i) => `<ellipse cx="${i * 200 + ((i * 37) % 60)}" cy="${y + ((i * 53) % 24)}" rx="${150 + (i * 29) % 70}" ry="${34 + (i * 17) % 18}" fill="var(--fog)" opacity="${o}"/>`).join('');
  const boom = (x, y, w, hh) => `<rect x="${x}" y="${y}" width="${w}" height="${hh}" fill="${C.s3}" stroke="${C.ink}" stroke-width="3"/><rect x="${x}" y="${y + 3}" width="${w}" height="4" fill="${C.s2}"/><path d="M${x} ${y + hh - 5} H${x + w}" stroke="${C.cu}" stroke-width="2.4"/>`;
  const jaw = (d) => `<path d="${d}" fill="${C.or}" stroke="${C.ink}" stroke-width="2.4" stroke-linejoin="round"/>`;
  const armV = `<g class="arm" style="--arm:armL;--t:4.8s">${boom(-1000, 103, 1092, 22)}<rect x="40" y="103" width="44" height="22" fill="url(#fb-hz)" stroke="${C.ink}" stroke-width="2.4"/>
    <circle cx="100" cy="114" r="15" fill="${C.s2}" stroke="${C.ink}" stroke-width="3"/><circle cx="100" cy="114" r="5" fill="${C.ink}"/>
    <rect x="112" y="98" width="16" height="32" fill="${C.s1}" stroke="${C.ink}" stroke-width="2.6"/>${jaw('M126 96 L146 96 L152 104 L134 106 Z')}${jaw('M126 132 L146 132 L152 124 L134 122 Z')}</g>`;
  const armS = `<g class="arm" style="--arm:armR;--t:6.1s">${boom(272, 305, 1200, 22)}<rect x="320" y="305" width="44" height="22" fill="url(#fb-hz)" stroke="${C.ink}" stroke-width="2.4"/>
    <circle cx="268" cy="316" r="15" fill="${C.s2}" stroke="${C.ink}" stroke-width="3"/><circle cx="268" cy="316" r="5" fill="${C.ink}"/>
    <rect x="236" y="300" width="18" height="32" fill="${C.s1}" stroke="${C.ink}" stroke-width="2.6"/>${jaw('M238 298 L222 298 L216 306 L232 307 Z')}${jaw('M238 334 L222 334 L216 326 L232 325 Z')}</g>`;
  const prong = (a) => { const r1 = 31, r2 = 42, [x1, y1] = [Math.cos(a) * r1, Math.sin(a) * r1], [x2, y2] = [Math.cos(a) * r2, Math.sin(a) * r2]; return `<path d="M${x1} ${y1} L${x2} ${y2}" stroke="${C.ink}" stroke-width="7" stroke-linecap="round"/><path d="M${x1} ${y1} L${x2} ${y2}" stroke="${C.or}" stroke-width="3.6" stroke-linecap="round"/>`; };
  const armC = `<g class="arm" style="--arm:armD;--t:7.4s"><g transform="translate(200 220) rotate(-42)">${boom(58, -11, 1100, 22)}<rect x="110" y="-11" width="44" height="22" fill="url(#fb-hz)" stroke="${C.ink}" stroke-width="2.4"/>
    <circle cx="52" cy="0" r="15" fill="${C.s2}" stroke="${C.ink}" stroke-width="3"/><circle cx="52" cy="0" r="5" fill="${C.ink}"/>
    <path d="M38 -30 A42 42 0 0 1 38 30" fill="none" stroke="${C.ink}" stroke-width="9"/><path d="M38 -30 A42 42 0 0 1 38 30" fill="none" stroke="${C.s1}" stroke-width="4.5"/>${prong(-.9)}${prong(.9)}${prong(0)}</g></g>`;
  const lock = (x, y, t, seed, px = 22) => `<g style="--t:${t}s">${FB.flash(x, y, 'flash')}${FB.sparks(x, y, 14, seed, 'spk')}${FB.cloud(x + px, y - 10, .85, 'puff')}</g>`;
  const fx = `<g class="fx-scene">${lock(146, 114, 5.35, 11, -30)}${lock(232, 316, 6.65, 23)}${lock(200, 220, 7.95, 37)}
    <g style="--t:8.0s;--jx:-80px">${FB.cloud(160, 222, .9, 'jet')}</g><g style="--t:8.05s;--jx:80px">${FB.cloud(240, 222, .9, 'jet')}</g>
    <g style="--fx:-120px">${FB.cloud(150, 640, 1.1, 'land')}</g><g style="--fx:120px">${FB.cloud(250, 640, 1.1, 'land')}</g><g style="--fx:-40px">${FB.cloud(190, 650, .9, 'land')}</g></g>`;
  let robot = FB.bot({ hang: true, inline: true, parts: { cradle: 'wait' }, gauge: G });
  robot = robot.replace(/<svg class="bot[^>]*>/, `<svg class="bot" x="${RX}" y="${RY}" width="400" height="660" viewBox="0 0 400 660" style="overflow:visible">`)
    .replace('<g class="fx"></g>', `${armV}${armS}${armC}${fx}`)
    .replace('<g class="eyes">', '<rect class="lens-dim" x="164" y="97" width="72" height="20" rx="5" fill="#11161D"/><g class="eyes">');
  function callout(o) {
    const [px, py] = [RX + o.at[0], RY + o.at[1]];
    const side = o.x < px ? 'lt' : 'rt';
    const ex = side === 'rt' ? o.x - 26 : o.x + o.w + 26, by = o.y + o.ey;
    return `<g class="cg ${side}" style="--t:${o.t}s"><g class="ln"><path class="leader ${o.hz ? 'hz' : ''}" d="M${px} ${py} L${ex} ${by} L${side === 'rt' ? o.x : o.x + o.w} ${by}"/></g>
      <circle class="pin ${o.hz ? 'hz' : ''}" cx="${px}" cy="${py}" r="7"/>
      <foreignObject class="cbox" x="${o.x}" y="${o.y}" width="${o.w}" height="${o.h}"><div class="co ${o.hz ? 'wait' : ''}" xmlns="http://www.w3.org/1999/xhtml">${o.html}</div></foreignObject></g>`;
  }
  const box = (idx, pic, k, why, bar, extra = '') => `<div class="box"><div class="idx${idx % 2 ? '' : ' mu'}" aria-hidden="true">${String(idx).padStart(2, '0')}</div><div class="pic">${pic}</div><div><div class="k">${k}</div><div class="why">${why}</div>${extra}</div></div><div class="bar">${esc(bar)}</div>`;
  const fact = (path, label) => { const v = getp(sc || {}, path); return v === undefined ? '' : `<b>${esc(label)}</b> ${esc(Array.isArray(v) ? v.join(', ') : v)}`; };
  const st = (res && res.stack) || {};
  const C1 = {
    visor: box(1, FB.closeup('visor'), 'visor · frontend', [fact('project.platforms', 'platforms'), fact('requirements.seo_critical', 'seo_critical')].filter(Boolean).join('<br>'), short(st.frontend && st.frontend.choice)),
    spine: box(2, FB.closeup('spine'), 'spine · backend', [fact('team.size', 'team'), fact('timeline.mvp_weeks', 'mvp weeks')].filter(Boolean).join('<br>'), short(st.backend && st.backend.choice)),
    core: box(3, `<span id="cgauge">${FB.closeup('core', { gauge: G })}</span>`, 'core · database', [fact('infrastructure.data_residency', 'residency'), fact('compliance', 'compliance')].filter(Boolean).join('<br>'), short(st.database && st.database.choice), `<div class="read"><span>band <b>${band(res && res.estimated_monthly_cost_usd)}</b></span><span>needle <b id="cneedle">${usd(G.budget)}</b></span></div>`),
    cradle: box(4, FB.closeup('cradle'), 'cradle · hosting', 'waiting on your budget ↓', 'Not fitted yet'),
  };
  const calls = SHOT() ? [
    { at: [247, 104], x: 1232, y: 112, w: 316, h: 134, ey: 50, t: 5.6, html: C1.visor },
    { at: [224, 316], x: 1232, y: 266, w: 316, h: 134, ey: 50, t: 6.9, html: C1.spine },
    { at: [230, 220], x: 1232, y: 420, w: 316, h: 168, ey: 50, t: 8.6, html: C1.core },
    { at: [300, 628], x: 1232, y: 606, w: 316, h: 134, ey: 50, t: 10.0, hz: 1, html: C1.cradle }] : [
    { at: [247, 104], x: 1232, y: 146, w: 316, h: 150, ey: 62, t: 5.6, html: C1.visor },
    { at: [180, 316], x: 622, y: 412, w: 290, h: 150, ey: 62, t: 6.9, html: C1.spine },
    { at: [230, 220], x: 1232, y: 330, w: 316, h: 168, ey: 62, t: 8.6, html: C1.core },
    { at: [300, 628], x: 1232, y: 604, w: 316, h: 150, ey: 62, t: 10.0, hz: 1, html: C1.cradle }];
  scene.innerHTML = `<defs><marker id="fb-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 Z" fill="#1A2029"/></marker></defs>
    <g>${bay.back}</g><g class="lamps">${bay.lamps}</g>
    <g class="fog-back">${fogBank(780, .07)}${fogBank(812, .09)}</g>
    <g class="drop">${robot}</g>
    <path class="floorline" d="M1228 752 C1150 830 980 860 860 900"/>
    <g class="lsps">${lampSparks(790, .5, 7)}${lampSparks(1110, 1.1, 13)}${lampSparks(1430, 1.6, 29)}</g>
    <g class="fog-front">${fogBank(858, .06)}</g>
    <rect class="dark" width="1600" height="900"/>
    ${res ? `<g class="calls">${calls.map(callout).join('')}</g>` : ''}`;
  $('#tags', sec).innerHTML = res ? ['visor', 'spine', 'core', 'cradle'].map((k) => `<div class="co ${k === 'cradle' ? 'wait' : ''}">${C1[k].replace('id="cgauge"', '').replace('id="cneedle"', '')}</div>`).join('') : '';
  const edgeEl = $('#edge', sec);
  function edge() {
    const w = edgeEl.clientWidth, hh = edgeEl.clientHeight; if (!w) return;
    let r = 7; const rnd = () => (r = (r * 9301 + 49297) % 233280) / 233280, j = (a) => (rnd() - .5) * a;
    const pts = [], step = 18, t = 5;
    for (let x = 0; x <= w; x += step) pts.push([x, t + j(6)]); for (let y = step; y <= hh; y += step) pts.push([w - t + j(6), y]);
    for (let x = w - step; x >= 0; x -= step) pts.push([x, hh - t + j(6)]); for (let y = hh - step; y > 0; y -= step) pts.push([t + j(6), y]);
    const inner = 'M' + pts.map((p) => p.map((v) => v.toFixed(1)).join(' ')).join(' L') + ' Z';
    const nicks = [...Array(14)].map(() => { const side = rnd() < .5, x = side ? rnd() * w : (rnd() < .5 ? 0 : w), y = side ? (rnd() < .5 ? 0 : hh) : rnd() * hh; return `<circle cx="${x.toFixed(0)}" cy="${y.toFixed(0)}" r="${(4 + rnd() * 9).toFixed(1)}" fill="var(--paper)"/>`; }).join('');
    edgeEl.innerHTML = `<svg viewBox="0 0 ${w} ${hh}" preserveAspectRatio="none"><path d="M-2 -2 H${w + 2} V${hh + 2} H-2 Z ${inner}" fill="var(--paper)" fill-rule="evenodd"/>${nicks}<path d="${inner}" fill="none" stroke="#0B0F14" stroke-width="1.5" opacity=".55"/></svg>`;
  }
  function fit() {
    if (!scene.isConnected) { removeEventListener('resize', fit); return; }
    const narrow = innerWidth <= 1000;
    scene.setAttribute('viewBox', narrow ? '820 70 580 820' : '0 0 1600 900');
    scene.setAttribute('preserveAspectRatio', narrow ? 'xMidYMax slice' : 'xMaxYMax slice');
    edge();
  }
  addEventListener('resize', fit); fit();
  const play = () => { sec.classList.remove('play'); void sec.offsetWidth; sec.classList.add('play'); };
  const seen = (() => { try { return sessionStorage.getItem('fb-intro'); } catch (e) { return '1'; } })();
  if (!reduce() && !seen && !SHOT()) { play(); try { sessionStorage.setItem('fb-intro', '1'); } catch (e) { /* private mode */ } }
  $('#replay', sec).onclick = play;
}

/* ---- the bay door: three ways in */
let doorsOpened = false;
function doorSection() {
  const sec = h('section', { class: 'doorwrap', id: 's-door', 'aria-labelledby': 'door-h' });
  const pub = S.scenarios.filter((s) => s.category === 'public');
  const edge = S.scenarios.filter((s) => s.category !== 'public');
  const lamp = '<svg viewBox="-42 0 84 300" aria-hidden="true"><polygon points="-22,62 22,62 64,176 -64,176" fill="url(#fb-cone)" opacity=".8"/><path d="M0 0 V30" stroke="var(--frame-ink)" stroke-width="3"/><path d="M-34 62 Q-30 30 0 30 Q30 30 34 62 Z" fill="#2E3A36" stroke="var(--frame-ink)" stroke-width="3"/><path d="M-24 50 Q-16 38 -2 37" stroke="#5B6B64" stroke-width="2.4" fill="none"/><ellipse cy="62" rx="34" ry="5" fill="var(--frame-ink)"/><ellipse cy="63" rx="24" ry="4" fill="var(--cone)"/></svg>';
  const door = (label, inside) => h('div', { class: 'door' }, h('div', { class: 'frame' }, h('div', { class: 'lintel' }, h('b', {}, label)), h('div', { class: 'opening' }, inside, h('div', { class: 'shutter', 'aria-hidden': 'true' }, h('span', {}, label)))), h('div', { class: 'door-foot' }));
  const scenBtn = (s) => {
    const st = S.status[s.id];
    const sev = !st ? h('span', { class: 'sev info' }, '…') : st.status === 'ok' ? h('span', { class: 'sev ok' }, 'ok') : st.status === 'ok_with_warnings' ? h('span', { class: 'sev warn' }, st.n + ' warning' + (st.n === 1 ? '' : 's')) : h('span', { class: 'sev crit' }, words(st.status));
    return h('button', { class: 'scen', type: 'button', 'data-id': s.id, onclick: () => loadScenario(s.id, { run: true }) }, h('b', {}, s.id), h('span', {}, s.title, h('small', {}, st ? st.line : '')), sev);
  };
  const edgeSel = h('select', { class: 'inp', id: 'edge-sel', 'aria-label': 'Edge-case scenario' }, edge.map((s) => h('option', { value: s.id }, s.id + ' · ' + (s.title === s.id ? 'file without a project name' : s.title))));
  /* upload door */
  const file = h('input', { type: 'file', accept: '.json,application/json', id: 'up-file', class: 'sr', onchange: (e) => readUpload(e.target.files[0]) });
  const drop = h('label', { class: 'drop', id: 'drop', for: 'up-file', tabindex: '0', onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); file.click(); } } },
    h('span', { html: '<svg viewBox="0 0 44 44" aria-hidden="true"><rect x="8" y="12" width="28" height="24" fill="none" stroke="currentColor" stroke-width="2.5"/><path d="M22 4 V24 M15 11 L22 4 L29 11" fill="none" stroke="var(--hazard)" stroke-width="2.5"/></svg>' }),
    h('span', { style: 'font-weight:600' }, 'Drop a scenario JSON'), h('span', { class: 'k' }, '§3 schema · up to 1 MB · or click to choose'), file);
  ['dragover', 'dragenter'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', (e) => readUpload(e.dataTransfer.files[0]));
  const paste = h('div', { class: 'paste', hidden: true },
    h('label', { for: 'paste-in', class: 'k' }, 'paste the scenario JSON'),
    h('textarea', { id: 'paste-in', class: 'inp', rows: 6, spellcheck: 'false' }),
    h('button', { class: 'btn s', type: 'button', onclick: () => readText($('#paste-in').value, 'pasted JSON') }, 'Use this JSON'));
  const upErr = S.upload ? h('div', { class: 'err', role: 'alert' }, h('span', { 'aria-hidden': 'true' }, '✕'), h('span', {}, S.upload.error, S.upload.raw ? h('button', { class: 'linkbtn', type: 'button', onclick: () => sendRawAnyway() }, ' Send it to the engine anyway') : null)) : null;
  const doors = h('div', { class: 'doors', id: 'doors' },
    h('div', { class: 'dlamp a', html: lamp }), h('div', { class: 'dlamp b', html: lamp }),
    door('FROM SCRATCH', h('div', { class: 'inside' },
      h('div', { class: 'bigfig' }, S.steps.length + ' steps'),
      h('p', { class: 'why', style: 'margin:0;color:var(--ink)' }, 'About ' + S.fields.length + ' answers. Each one says why the bay asks and which parts it moves.'),
      h('ul', { class: 'steplist' }, S.steps.map((s) => h('li', {}, s.name))),
      h('button', { class: 'btn p', type: 'button', style: 'margin-top:auto', onclick: () => { setScenario({}, ''); go('#/q/1'); } }, 'Start the fitting ', h('span', { class: 'arr' }, '→')))),
    door('SCENARIOS', h('div', { class: 'inside', style: 'gap:0' },
      h('div', { class: 'k', style: 'margin-bottom:6px' }, 'public scenarios · statement §6'),
      h('div', { id: 'scen-list' }, pub.map(scenBtn)),
      h('div', { class: 'edgepick' }, h('label', { class: 'k', for: 'edge-sel' }, 'edge library · ' + edge.length), edgeSel,
        h('button', { class: 'btn g s', type: 'button', onclick: () => loadScenario(edgeSel.value, { run: true }) }, 'Run it')),
      h('div', { class: 'edgechips' }, ['H13', 'H23', 'H21_empty_object'].filter((id) => edge.some((s) => s.id === id)).map((id) => h('button', { class: 'chip ghost', type: 'button', onclick: () => loadScenario(id, { run: true }) }, id.replace(/_/g, ' ') + ' · ' + (edge.find((s) => s.id === id).title === id ? 'empty file' : edge.find((s) => s.id === id).title)))))),
    door('UPLOAD', h('div', { class: 'inside' }, drop, upErr,
      h('button', { class: 'btn g s', type: 'button', style: 'margin-top:auto;align-self:flex-start', onclick: () => { paste.hidden = !paste.hidden; if (!paste.hidden) $('#paste-in').focus(); } }, 'Paste JSON instead'), paste)));
  put(sec, h('div', { class: 'door-stage' },
    (() => { const s = document.createElementNS(SVG_NS, 'svg'); s.setAttribute('class', 'scene'); s.setAttribute('viewBox', '0 0 1600 900'); s.setAttribute('preserveAspectRatio', 'xMidYMax slice'); s.setAttribute('aria-hidden', 'true'); s.innerHTML = `<g>${FB.bay({ lamps: [], floorY: 900 }).back}</g>`; return s; })(),
    h('div', { class: 'grain' }),
    h('button', { class: 'reshut', id: 'reshut', type: 'button', onclick: () => { doors.classList.add('shut'); setTimeout(() => doors.classList.remove('shut'), reduce() ? 0 : 900); } }, 'close the shutters again'),
    h('div', { class: 'door-head' }, h('h2', { class: 'h2', id: 'door-h' }, 'Three ways into the bay'), h('p', { class: 'lede' }, 'Every way in stops at the same engine, ', h('span', {}, 'so the parts depend only on your answers, never on how you arrived.'))),
    doors,
    h('div', { class: 'bayfloor', 'aria-hidden': 'true' }, h('i'), h('i'), h('i'), h('span', { class: 'dash' }))));
  /* resting state is open; the first visit rolls the shutters up once (not under reduced motion or ?shot=1) */
  if (!doorsOpened) {
    doorsOpened = true;
    if (!reduce() && !SHOT()) {
      doors.classList.add('instant', 'shut');
      requestAnimationFrame(() => { void doors.offsetWidth; doors.classList.remove('instant'); requestAnimationFrame(() => requestAnimationFrame(() => doors.classList.remove('shut'))); });
    }
  }
  fillStatuses();
  return sec;
}
/* public-scenario status lines are real runs, cached for the visit */
async function fillStatuses() {
  const pub = S.scenarios.filter((s) => s.category === 'public' && !S.status[s.id]);
  for (const s of pub) {
    const sc = await api('/api/scenarios/' + s.id);
    if (!sc.ok) continue;
    const r = await post('/api/recommend', { scenario: sc.data, fill_defaults: false, llm: false });
    if (!r.ok || !r.data) continue;
    const res = r.data;
    const type = getp(sc.data, 'project.type'), resid = getp(sc.data, 'infrastructure.data_residency'), comp = getp(sc.data, 'compliance');
    const line = [words(type || ''), [resid && resid !== 'none' ? titleCase(resid) : 'no residency', ...(Array.isArray(comp) ? comp.filter((c) => c !== 'none').map((c) => c.toUpperCase().replace(/_/g, ' ')) : [])].join(', ')].filter(Boolean).join(' · ');
    S.status[s.id] = { status: res.status, n: (res.warnings || []).filter((w) => w.severity !== 'info').length, line };
    const btn = $(`#scen-list [data-id="${s.id}"]`);
    if (btn) btn.replaceWith(((s2) => { const st = S.status[s2.id]; const sev = st.status === 'ok' ? h('span', { class: 'sev ok' }, 'ok') : st.status === 'ok_with_warnings' ? h('span', { class: 'sev warn' }, st.n + ' warning' + (st.n === 1 ? '' : 's')) : h('span', { class: 'sev crit' }, words(st.status)); return h('button', { class: 'scen', type: 'button', 'data-id': s2.id, onclick: () => loadScenario(s2.id, { run: true }) }, h('b', {}, s2.id), h('span', {}, s2.title, h('small', {}, st.line)), sev); })(s));
  }
}
function readUpload(file) {
  if (!file) return;
  if (file.size > 1024 * 1024) { S.upload = { error: 'This file is larger than 1 MB; the engine accepts up to 1 MB.' }; route(); return; }
  const fr = new FileReader();
  fr.onload = () => readText(String(fr.result), file.name.replace(/\.json$/i, ''));
  fr.readAsText(file);
}
function readText(text, name) {
  text = String(text).replace(/^﻿/, '');
  try {
    const obj = JSON.parse(text);
    S.upload = null; setScenario(obj, name); run();
  } catch (e) {
    S.upload = { error: 'This is not valid JSON: ' + e.message, raw: text };
    route();
    const d = $('#s-door'); if (d) d.scrollIntoView();
  }
}
function sendRawAnyway() { const raw = S.upload.raw; setScenario(raw, 'uploaded text'); run(); }

// ---------------------------------------------------------------- questionnaire
const AVAIL_DOWNTIME = (v) => {
  const pct = Number(v); if (!(pct > 0 && pct < 100)) return '';
  const min = (100 - pct) / 100 * 730 * 60;
  return min >= 120 ? 'about ' + (min / 60).toFixed(1) + ' hours of downtime a month' : 'about ' + Math.round(min) + ' minutes of downtime a month';
};
function fieldStep(n) { return S.fields.filter((f) => f.step === n); }
function stepDone(n) { const fs = fieldStep(n); return fs.filter((f) => getp(S.scenario, f.path) !== undefined).length + '/' + fs.length; }
function stepComplete(n) {
  const fs = fieldStep(n); const set = fs.filter((f) => getp(S.scenario, f.path) !== undefined);
  return set.length > 0 && fs.filter((f) => f.required).every((f) => getp(S.scenario, f.path) !== undefined);
}
function partFitted(part) { const steps = Object.keys(STEP_PART).filter((k) => STEP_PART[k] === part).map(Number); return steps.length && steps.every(stepComplete); }
const AFFECT_PART = { frontend: 'visor', backend: 'spine', database: 'core', hosting: 'cradle', supporting: 'bolt-ons', cost: 'cost gauge', warnings: 'warnings', architecture_style: 'architecture' };

function quizStage(curPart) {
  const sc = S.scenario;
  const st = (p) => (partFitted(p) ? 'fit' : p === curPart ? 'wait' : 'empty');
  const bot = FB.bot({ parts: { visor: st('visor'), spine: st('spine'), core: st('core'), cradle: st('cradle') }, gauge: { low: 0, high: 0, budget: getp(sc, 'budget.monthly_infra_usd') || 0 }, lit: partFitted('core'), id: 'qbot' });
  const tag = (x, y, tx, ty, text, hz) => { const w = Math.ceil(text.length * 7.8 + 20); tx = Math.min(tx, 400 - 12 - w); return `<g class="qtag"><path class="leader ${hz ? 'hz' : ''}" d="M${x} ${y} L${tx} ${ty}"/><circle class="pin ${hz ? 'hz' : ''}" cx="${x}" cy="${y}" r="5"/>
    <g transform="translate(${tx} ${ty - 15})"><rect width="${w}" height="26" fill="${hz ? 'var(--hazard)' : 'var(--weld)'}" stroke="#0B0F14" stroke-width="2"/><text x="9" y="17.5" ${MONO} font-size="12.5" font-weight="500" fill="#11161D">${esc(text)}</text></g></g>`; };
  const val = (p) => { const v = getp(sc, p); return v === undefined ? null : Array.isArray(v) ? v.join(' + ') : String(v); };
  const T = {
    visor: partFitted('visor') ? (val('project.platforms') || 'visor fitted') : 'visor: open',
    spine: partFitted('spine') ? 'team ' + (val('team.size') || '?') + (getp(sc, 'team.has_devops') === false ? ' · no devops' : '') : 'spine: open',
    cradle: partFitted('cradle') ? 'USD ' + (val('budget.monthly_infra_usd') || '?') + ' / month' : 'cradle: open',
  };
  return stageSVG(400, 560, miniBay(400, 560, { lamp: 150, floor: 500 }) + nest(bot, -10, 40, 300, 495, '50 40 300 620') +
    tag(232, 118, 270, 104, T.visor, !partFitted('visor')) + tag(222, 286, 244, 300, T.spine, !partFitted('spine')) + tag(180, 488, 262, 470, T.cradle, !partFitted('cradle')),
  'The project chassis on the fitting stand. Fitted parts: ' + (['visor', 'spine', 'core', 'cradle'].filter(partFitted).join(', ') || 'none') + '.');
}

function viewQuestion(n, focusPath) {
  const m = main();
  const step = S.steps.find((s) => s.n === n) || S.steps[0];
  if (!step) return;
  const fields = fieldStep(step.n);
  const groups = [...new Set(fields.map((f) => f.group))];
  const part = STEP_PART[step.n];
  const before = S.fitParts || new Set(['visor', 'spine', 'core', 'cradle'].filter(partFitted));
  const idx = S.steps.findIndex((s) => s.n === step.n);
  const next = S.steps[idx + 1];
  put(m, sheetHead('questionnaire — fitting stand', scenarioTitle() + ' · ' + step.name.toLowerCase()));
  put(m, h('div', { class: 'quiz' },
    h('div', { class: 'stand' },
      h('div', { class: 'mini', id: 'quiz-stage', html: quizStage(part) }),
      h('ol', { class: 'rail', 'aria-label': 'Questionnaire steps' }, S.steps.map((s) => {
        const done = stepComplete(s.n);
        return h('li', { class: s.n === step.n ? 'now' : done ? 'done' : '' }, h('a', { href: '#/q/' + s.n, 'aria-current': s.n === step.n ? 'step' : false }, s.name), h('span', {}, s.n === step.n ? '' : done ? 'bolted' : stepDone(s.n)));
      }))),
    h('div', { class: 'panel form' },
      h('div', { class: 'top2' }, h('div', {}, h('div', { class: 'k' }, 'step ' + step.n + ' of ' + S.steps.length + ' · ' + scenarioTitle()), h('h2', { class: 'h2', style: 'font-size:36px;margin-top:6px' }, step.name)),
        h('span', { class: 'chip hz', style: 'margin-top:6px' }, part === 'bolt' ? 'fits the bolt-ons' : 'fits the ' + part)),
      h('p', { class: 'why', style: 'font-size:15px' }, 'Fields marked required must be answered before the engine can run, or the pre-fit check can fill them with documented defaults.'),
      groups.map((g) => h('section', { 'aria-label': g }, groups.length > 1 ? h('h3', { class: 'h3 grp-h' }, g) : null, fields.filter((f) => f.group === g).map(fieldRow))),
      h('div', { class: 'formfoot' },
        idx > 0 ? h('a', { class: 'btn g', href: '#/q/' + S.steps[idx - 1].n }, '← Back to ' + S.steps[idx - 1].name) : h('a', { class: 'btn g', href: '#/' }, '← Bay door'),
        h('span', { class: 'live', id: 'quiz-live', 'aria-live': 'polite' }),
        next ? h('a', { class: 'btn p', href: '#/q/' + next.n }, 'Next: ' + next.name + ' ', h('span', { class: 'arr' }, '→')) : h('a', { class: 'btn p', href: '#/review' }, 'Pre-fit check ', h('span', { class: 'arr' }, '→'))),
      draftDrawer())));
  put(m, sheetFoot('Questionnaire · fitting stand'));
  paintFieldMessages();
  /* a part that became complete since the last step bolts on (occasional action: gets the weld) */
  const now = new Set(['visor', 'spine', 'core', 'cradle'].filter(partFitted));
  const fresh = [...now].filter((p) => !before.has(p));
  S.fitParts = now;
  const svg = $('#qbot');
  if (svg && fresh.length) {
    fresh.forEach((p, i) => { const g = svg.querySelector(`.pt[data-part="${p}"]`); if (g) { g.classList.remove('fit'); g.classList.add('empty'); setTimeout(() => FB.boltOn(svg, p, p === 'cradle' || p === 'core' ? 'top' : i % 2 ? 'left' : 'right'), 120 + i * 140); } });
    $('#quiz-live').textContent = fresh.join(' and ') + ' bolted. The part itself is chosen when you run the fitting.';
  }
  if (focusPath) {
    const el = document.querySelector('[data-path="' + CSS.escape(focusPath) + '"]');
    if (el) { el.classList.add('focus-flash'); el.scrollIntoView({ block: 'center' }); const i = el.querySelector('input,select,textarea,button'); if (i) i.focus(); }
  }
  ensureKbForHints();
}

function fieldRow(f) {
  const id = 'f-' + f.path.replace(/\./g, '-');
  const cur = getp(S.scenario, f.path);
  const ctl = control(f, id, cur);
  const labelEl = (f.type === 'boolean' || (f.type === 'enum' && f.enum.length <= 5) || (f.type === 'integer' && f.minimum === 1 && f.maximum === 5) || (f.type === 'list' && f.item_enum))
    ? h('div', { class: 'lab', id: id + '-l' }, f.label) : h('label', { class: 'lab', for: id }, f.label);
  const aff = (f.affects || []).map((a) => AFFECT_PART[a] || words(a));
  return h('div', { class: 'field', 'data-path': f.path },
    h('div', { class: 'labrow' }, labelEl, f.required ? h('span', { class: 'chip ghost' }, 'required') : null, f.extra ? h('span', { class: 'chip hz' }, 'StackSense addition') : null, f.constraint === 'hard' ? h('span', { class: 'chip crit' }, 'clamp: never bent') : null),
    h('p', { class: 'why' }, f.why || 'Not used by the engine.', f.default != null ? ' If left blank: ' + fmtVal(f.default) + (f.unit ? ' ' + f.unit : '') + '.' : ''),
    h('div', { class: 'ctlwrap' }, ctl),
    h('div', { class: 'fmsg hint', 'data-hint': f.path }),
    h('div', { class: 'fmsg err-text', 'data-err': f.path, role: 'alert' }),
    h('div', { class: 'affects' }, aff.length ? ['affects ', aff.map((a) => h('span', { class: 'chip' }, a))] : null, h('code', {}, f.path)));
}

function commit(f, val, blank) {
  const tgt = S.edit || S.scenario;
  if (blank) delp(tgt, f.path); else setp(tgt, f.path, val);
  if (S.edit) { if (S.onEdit) S.onEdit(); return; }
  S.touched.add(f.path);
  S.result = null; S.raw = null; paintNav((parseHash().parts[0]) || 'start');
  scheduleValidate();
  paintDraft();
  paintHint(f);
}
function opt(name, value, label, checked, onchange, sub) {
  const id = name + '-' + String(value).replace(/\W/g, '_');
  return h('label', { class: 'opt', for: id }, h('input', { type: 'radio', name, id, value, checked, onchange }), h('span', {}, label, sub ? h('small', { class: 'sub' }, sub) : null));
}
function control(f, id, cur) {
  const name = id + '-r';
  const refresh = () => viewQuestionRefresh();
  const clear = h('button', { class: 'btn g s clr', type: 'button', onclick: () => { commit(f, null, true); refresh(); } }, 'Clear (use default)');
  if (f.type === 'boolean') {
    const mk = (v, l) => opt(name, String(v), l, cur === v, () => commit(f, v));
    return h('div', { class: 'opts', role: 'radiogroup', 'aria-labelledby': id + '-l', id }, mk(true, 'Yes'), mk(false, 'No'), h('button', { class: 'btn g s clr', type: 'button', onclick: () => { commit(f, null, true); refresh(); } }, 'Not set'));
  }
  if (f.type === 'enum') {
    if (f.enum.length <= 5) {
      return h('div', {}, h('div', { class: 'opts', role: 'radiogroup', 'aria-labelledby': id + '-l', id },
        f.enum.map((v) => opt(name, v, f.path === 'requirements.availability' ? v + '%' : words(v), cur === v, () => { commit(f, v); paintHint(f); }, f.path === 'requirements.availability' ? AVAIL_DOWNTIME(v).replace(' of downtime a month', ' a month') : null))),
      f.required ? null : clear);
    }
    return h('select', { class: 'inp', id, onchange: (e) => commit(f, e.target.value, e.target.value === '') },
      h('option', { value: '' }, f.required ? 'Choose one' : 'Not set'), f.enum.map((v) => h('option', { value: v, selected: cur === v }, words(v))));
  }
  if (f.type === 'integer' && f.minimum === 1 && f.maximum === 5) {
    const opts = [1, 2, 3, 4, 5].map((v) => opt(name, String(v), String(v), cur === v, () => commit(f, v)));
    return h('div', {}, h('div', { class: 'opts seg5', role: 'radiogroup', 'aria-labelledby': id + '-l', id }, opts),
      h('div', { class: 'segscale' }, h('span', {}, '1 least important'), h('span', {}, '5 most important')), clear);
  }
  if (f.type === 'list' && f.item_enum) {
    const sel = new Set(Array.isArray(cur) ? cur : []);
    return h('div', { class: 'opts', role: 'group', 'aria-labelledby': id + '-l', id }, f.item_enum.map((v) => {
      const cid = id + '-' + v;
      return h('label', { class: 'opt', for: cid }, h('input', { type: 'checkbox', id: cid, value: v, checked: sel.has(v), onchange: (e) => {
        if (e.target.checked) sel.add(v); else sel.delete(v);
        const arr = f.item_enum.filter((x) => sel.has(x));
        commit(f, arr, arr.length === 0 && !f.required);
      } }), h('span', {}, words(v)));
    }));
  }
  if (f.type === 'list') return tagInput(f, id, Array.isArray(cur) ? cur.slice() : []);
  if (f.type === 'integer' || f.type === 'number') {
    const inp = h('input', { class: 'inp', id, type: 'number', inputmode: f.type === 'integer' ? 'numeric' : 'decimal', min: f.minimum, max: f.maximum, step: f.type === 'integer' ? 1 : 'any', value: cur == null ? '' : cur,
      style: 'max-width:14em', onchange: (e) => { const t = e.target.value.trim(); commit(f, t === '' ? null : Number(t), t === ''); }, onblur: () => S.touched.add(f.path), oninput: (e) => { const t = e.target.value.trim(); if (t === '') commit(f, null, true); else if (!isNaN(Number(t))) commit(f, Number(t)); } });
    return h('div', { class: 'unit-wrap' }, inp, f.unit ? h('span', { class: 'unit' }, f.unit) : null);
  }
  if (f.ui === 'textarea') return h('textarea', { class: 'inp', id, rows: 4, oninput: (e) => commit(f, e.target.value, e.target.value === '') }, cur || '');
  return h('input', { class: 'inp', id, type: 'text', value: cur == null ? '' : cur, oninput: (e) => commit(f, e.target.value, e.target.value === '') });
}
function viewQuestionRefresh() { if (S.edit) { if (S.repaint) S.repaint(); return; } const { parts, q } = parseHash(); main().replaceChildren(); viewQuestion(Number(parts[1]) || 1, q.get('f')); }

function tagInput(f, id, arr) {
  const box = h('div', { class: 'taginput' });
  const listId = 'dl-' + id;
  const input = h('input', { id, type: 'text', list: listId, placeholder: 'type and press Enter…', 'aria-label': f.label + ': type a value and press Enter', autocomplete: 'off' });
  const dl = h('datalist', { id: listId }, hintsFor(f).map((v) => h('option', { value: v })));
  const sync = () => commit(f, arr.slice(), arr.length === 0);
  const paint = () => {
    box.replaceChildren(...arr.map((v, i) => h('span', { class: 'chip' }, v, h('button', { type: 'button', 'aria-label': 'Remove ' + v, onclick: () => { arr.splice(i, 1); paint(); sync(); input.focus(); } }, '✕'))), input, dl);
  };
  const add = () => { const parts = input.value.split(',').map((s) => s.trim()).filter(Boolean); parts.forEach((p) => { if (!arr.includes(p)) arr.push(p); }); input.value = ''; if (parts.length) { paint(); sync(); } };
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add(); } else if (e.key === 'Backspace' && !input.value && arr.length) { arr.pop(); paint(); sync(); } });
  input.addEventListener('change', add);
  input.addEventListener('blur', add);
  paint();
  return box;
}
function hintsFor(f) {
  if (!S.kb) return [];
  if (f.path === 'team.languages') return [...new Set(S.kb.records.flatMap((r) => r.languages || []))].sort();
  if (f.path === 'infrastructure.existing_systems') return [...new Set(S.kb.records.map((r) => r.name))].sort();
  return [];
}
async function ensureKb() {
  if (S.kb) return S.kb;
  const r = await api('/api/kb'); if (r.ok) S.kb = r.data; return S.kb;
}
async function ensureSources() {
  if (!S.sources) { const r = await api('/api/sources'); S.sources = new Map((r.data || []).map((s) => [s.key, s])); }
  return S.sources;
}
async function ensureKbForHints() {
  if (S.kb) return;
  await ensureKb();
  document.querySelectorAll('datalist').forEach((dl) => {
    const f = S.fields.find((x) => 'dl-f-' + x.path.replace(/\./g, '-') === dl.id);
    if (f) dl.replaceChildren(...hintsFor(f).map((v) => h('option', { value: v })));
  });
}

function clientHint(f) {
  const v = getp(S.scenario, f.path); const sc = S.scenario;
  if (f.path === 'requirements.availability' && v != null) return AVAIL_DOWNTIME(v) ? 'At ' + v + '% that allows ' + AVAIL_DOWNTIME(v) + '.' : '';
  if (f.path === 'scale.users_12_months' && v != null && getp(sc, 'scale.users_at_launch') > v) return 'Users after 12 months is lower than users at launch. Is that intended?';
  if (f.path === 'scale.peak_concurrent_users' && v != null && getp(sc, 'scale.users_12_months') < v) return 'Peak concurrent users cannot exceed total users.';
  if (f.path === 'timeline.mvp_weeks' && v != null && v < 4) return 'Under 4 weeks leaves very little room for anything but a managed platform.';
  if (f.path === 'budget.monthly_infra_usd' && v === 0) return 'A zero budget limits the engine to free tiers; the result states whether that holds.';
  if (f.path === 'budget.monthly_infra_usd' && typeof v === 'number' && v > 0) return '≈ ' + inr(v) + ' a month at ₹' + INR_PER_USD + ' per USD, display only.';
  if (f.path === 'team.size' && v != null && v < 1) return 'A team has at least one engineer.';
  if (f.path === 'team.languages' && Array.isArray(v) && v.length === 0) return 'List at least one language the team already uses.';
  return '';
}
function paintHint(f) {
  if (!f) return;
  const el = document.querySelector('[data-hint="' + CSS.escape(f.path) + '"]');
  if (el) el.textContent = clientHint(f);
}
function paintFieldMessages() {
  document.querySelectorAll('.field[data-path]').forEach((row) => {
    const p = row.dataset.path;
    const f = S.fields.find((x) => x.path === p);
    const has = getp(S.scenario, p) !== undefined;
    const errs = (S.touched.has(p) || has || S.showAll) ? (S.errMap[p] || []) : [];
    const e = row.querySelector('[data-err]');
    if (e) e.textContent = errs.map((x) => x.message).join(' ');
    row.classList.toggle('has-err', errs.length > 0);
    paintHint(f);
  });
}
function paintDraft() {
  const pre = document.getElementById('draft-pre');
  if (pre) pre.textContent = JSON.stringify(S.scenario, null, 2);
}
function draftDrawer() {
  return h('details', { class: 'json', id: 'draft', open: S.draftOpen ? true : false, ontoggle: (e) => { S.draftOpen = e.target.open; } },
    h('summary', {}, 'input JSON so far'),
    h('div', { class: 'row' },
      h('button', { class: 'btn g s', type: 'button', onclick: () => download((S.scenarioName || 'scenario') + '.json', JSON.stringify(S.scenario, null, 2) + '\n') }, 'Download input JSON'),
      h('button', { class: 'btn g s', type: 'button', onclick: (e) => copyText(JSON.stringify(S.scenario, null, 2), e.target) }, 'Copy')),
    h('pre', { id: 'draft-pre', tabindex: '0' }, JSON.stringify(S.scenario, null, 2)));
}

// ---------------------------------------------------------------- pre-fit check
function viewReview() {
  const m = main();
  S.showAll = true;
  const rows = [];
  const walk = (o, pre) => { if (!isObj(o)) return; Object.keys(o).forEach((k) => { const p = pre ? pre + '.' + k : k; if (isObj(o[k]) && !S.fields.some((f) => f.path === p)) walk(o[k], p); else rows.push([p, o[k]]); }); };
  if (isObj(S.scenario)) walk(S.scenario, '');
  const known = (p) => S.fields.find((f) => f.path === p);
  const hard = rows.filter(([p]) => known(p) && known(p).constraint === 'hard');
  const soft = rows.filter(([p]) => !known(p) || known(p).constraint !== 'hard');
  const missingDef = S.fields.filter((f) => getp(S.scenario, f.path) === undefined && f.default != null);
  const missingReq = S.fields.filter((f) => getp(S.scenario, f.path) === undefined && f.required);
  const clamp = (x, y) => `<g transform="translate(${x} ${y})"><path d="M-9 -10 H5 V-5 H-3 V5 H5 V10 H-9 Z" fill="var(--crit)" stroke="#0B0F14" stroke-width="2"/><path d="M5 0 H12 M8.5 -4 V4" stroke="var(--ink)" stroke-width="2.4"/></g>`;
  const bot = FB.bot({ parts: { visor: 'empty', spine: 'empty', core: 'empty', cradle: 'empty' }, id: 'rbot' });
  const stage = stageSVG(330, 470, miniBay(330, 470, { lamp: 165, floor: 376 }) + nest(bot, 40, 40, 250, 370, '60 50 280 620') +
    (hard.length ? clamp(44, 390) + clamp(286, 390) : '') + `<text x="165" y="452" text-anchor="middle" ${MONO} font-size="12" fill="var(--muted)">${hard.length} clamp${hard.length === 1 ? '' : 's'} hold the cradle</text>`,
  'Bare chassis: no parts bolted yet; ' + hard.length + ' hard answers clamp the body.');
  const tr = ([p, v], kind) => {
    const f = known(p);
    const treat = kind === 'hard' ? h('span', { class: 'treat', style: 'color:var(--crit)' }, (v === 'any' || v === 'none' || (Array.isArray(v) && (!v.length || v.includes('none')))) ? 'clamp, but open' : 'clamp: never bent')
      : f ? h('span', { class: 'treat', style: 'color:var(--info)' }, f.constraint === 'info' ? 'shown only' : 'spring') : h('span', { class: 'treat', style: 'color:var(--muted)' }, 'not in schema');
    return h('tr', {}, h('td', {}, h('code', {}, p)), h('td', {}, fmtVal(v)), h('td', {}, treat, f ? h('a', { class: 'stepln', href: '#/q/' + f.step + '?f=' + p }, 'step ' + f.step) : null));
  };
  const holder = h('div', { id: 'review-errors' });
  const sw = (on, labelId, onclick, disabled) => h('button', { class: 'sw', type: 'button', role: 'switch', 'aria-checked': on ? 'true' : 'false', 'aria-labelledby': labelId, disabled, onclick });
  const llm = (S.health || {}).llm || 'off';
  put(m, sheetHead('pre-fit check — answers before assembly'),
    hd2('rev-h', 'Pre-fit check', 'Everything you said, exactly as the engine will receive it.', 'Clashes and missing answers show here, not after the run.'),
    holder,
    h('div', { class: 'review' },
      h('div', { class: 'panel pad' }, h('div', { class: 'mini', id: 'rev-stage', style: 'margin:-24px -24px 0', html: stage }),
        h('div', { class: 'counts' }, h('div', {}, h('b', {}, hard.length), h('span', {}, 'clamps')), h('div', {}, h('b', {}, soft.length), h('span', {}, 'springs')), h('div', {}, h('b', {}, missingDef.length), h('span', {}, 'defaults'))),
        h('p', { class: 'why', style: 'margin-top:12px' }, 'Nothing is bolted yet. Clamps hold the bay to an answer; springs bend toward it and warn when they can’t.')),
      h('div', { class: 'panel pad' },
        h('div', { class: 'grp', html: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4 H15 V8 H9 V16 H15 V20 H5 Z" fill="var(--crit)" stroke="#0B0F14" stroke-width="1.5"/><path d="M15 12 H21 M18 9 V15" stroke="var(--ink)" stroke-width="2.4"/></svg>Clamps · never bent' }),
        hard.length ? h('table', { class: 'resp' }, h('thead', {}, h('tr', {}, h('th', {}, 'answer'), h('th', {}, 'value'), h('th', {}, 'the bay treats it as'))), h('tbody', {}, hard.map((r) => tr(r, 'hard')))) : h('p', { class: 'muted' }, 'No hard constraints answered yet.'),
        h('div', { class: 'grp', html: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12 L7 5 L10 19 L13 5 L16 19 L19 5 L21 12" fill="none" stroke="var(--info)" stroke-width="2.2" stroke-linejoin="round"/></svg>Springs · bend, then warn' }),
        soft.length ? h('table', { class: 'resp' }, h('tbody', {}, soft.map((r) => tr(r, 'soft')))) : h('p', { class: 'muted' }, 'Nothing entered yet.'),
        h('div', { class: 'grp', html: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" fill="none" stroke="var(--muted)" stroke-width="2" stroke-dasharray="3 2"/><path d="M8 12 H16" stroke="var(--muted)" stroke-width="2"/></svg>Left blank' }),
        missingDef.length || missingReq.length ? h('table', { class: 'resp' }, h('tbody', {}, [...missingReq.filter((f) => f.default == null), ...missingDef].map((f) => h('tr', {}, h('td', {}, h('code', {}, f.path)), h('td', { class: 'muted' }, f.default != null ? 'missing → ' + fmtVal(f.default) : 'missing'), h('td', {}, h('span', { class: 'treat', style: 'color:var(--muted)' }, f.required ? (f.default != null ? 'required · default available' : 'required') : 'documented default')))))) : h('p', { class: 'muted' }, 'Every field is answered.')),
      h('div', { class: 'panel pad' },
        h('div', { class: 'opt2' }, sw(S.fill, 'o1', (e) => { S.fill = !S.fill; e.currentTarget.setAttribute('aria-checked', S.fill ? 'true' : 'false'); }), h('div', { id: 'o1' }, h('b', {}, 'Fill missing answers with documented defaults'), h('div', { class: 'why' }, 'Each one is listed under Assumptions. Leave it off to see exactly which answers are missing.'))),
        h('div', { class: 'opt2', style: 'box-shadow:none' }, sw(false, 'o2', null, true), h('div', { id: 'o2' }, h('b', {}, 'Reword tags with an LLM'), h('div', { class: 'why' }, 'The LLM is ' + llm + ' in this build. Wording only; the parts are identical either way.'))),
        h('button', { class: 'btn p', id: 'run-btn', type: 'button', style: 'width:100%;margin-top:14px', onclick: () => run() }, 'Run the fitting ', h('span', { class: 'arr' }, '→')),
        h('a', { class: 'btn g', href: '#/q/1', style: 'width:100%;margin-top:10px' }, 'Edit answers'),
        h('p', { class: 'k', style: 'margin:12px 0 0' }, 'same answers, same body: no clock, no randomness'))),
    draftDrawer(), sheetFoot('Pre-fit check · clamps and springs'));
  scheduleValidate(0);
  if (S.valid) viewReviewErrors(holder);
}
function viewReviewErrors(holder) {
  const v = S.valid; if (!v) return;
  const notices = v.notices || [];
  holder.replaceChildren();
  put(holder,
    v.errors.length ? h('div', { class: 'strip cr' }, h('span', { class: 'tag crit' }, v.errors.length + ' to fix'), h('div', {}, h('b', {}, 'The bay can’t read ' + v.errors.length + ' answer' + (v.errors.length > 1 ? 's' : '') + ' yet'), h('div', { class: 'why', style: 'margin:2px 0 0' }, 'Fix them below, or switch on documented defaults for the missing ones.')))
      : notices.length ? h('div', { class: 'strip hz' }, h('span', { class: 'tag hz' }, 'heads up'), h('div', {}, h('b', {}, notices.length + ' notice' + (notices.length > 1 ? 's' : '')), h('div', { class: 'why', style: 'margin:2px 0 0' }, noteText(notices[0]))))
        : h('div', { class: 'strip ok' }, h('span', { class: 'tag' }, 'ready'), h('div', {}, h('b', {}, 'Every answer passes the engine’s checks'), h('div', { class: 'why', style: 'margin:2px 0 0' }, 'Run the fitting when you’re ready.'))),
    v.errors.length ? h('div', { class: 'panel pad', style: 'margin-bottom:20px' }, errorTable(v.errors)) : null,
    notices.length > 1 ? h('div', { class: 'panel pad', style: 'margin-bottom:20px' }, h('div', { class: 'sect', style: 'margin-top:0' }, 'notices'), h('ul', { class: 'alist' }, notices.map((n) => h('li', {}, noteText(n))))) : null);
}
const noteText = (n) => (typeof n === 'string' ? n : n && (n.message || n.text) ? (n.field ? n.field + ': ' : '') + (n.message || n.text) : JSON.stringify(n));

function allowed(f) {
  if (!f) return '';
  if (f.enum) return 'one of: ' + f.enum.join(', ');
  if (f.item_enum) return 'a list of any of: ' + f.item_enum.join(', ');
  const b = [];
  if (f.minimum != null) b.push((f.exclusive_min ? 'greater than ' : 'at least ') + f.minimum);
  if (f.maximum != null) b.push('at most ' + f.maximum);
  return f.type + (b.length ? ', ' + b.join(' and ') : '');
}
function errorTable(errs) {
  return h('table', { class: 'resp errt' }, h('thead', {}, h('tr', {}, h('th', {}, 'answer'), h('th', {}, 'you sent'), h('th', {}, 'what the bay accepts'))),
    h('tbody', {}, errs.map((e) => {
      const key = String(e.field).replace(/\[.*$/, '');
      const f = S.fields.find((x) => x.path === key);
      const val = e.field === '$' ? undefined : getp(isObj(S.scenario) ? S.scenario : {}, key);
      return h('tr', {}, h('td', {}, h('code', {}, e.field), f ? h('div', {}, h('a', { class: 'stepln', href: '#/q/' + f.step + '?f=' + f.path }, 'open in step ' + f.step)) : null),
        h('td', { class: 'bad' }, e.field === '$' ? 'not a JSON object' : val === undefined ? 'nothing (missing)' : JSON.stringify(val)),
        h('td', { class: 'fix' }, e.message, allowed(f) ? h('div', { class: 'why' }, 'Accepts ' + allowed(f) + '.') : null));
    })));
}

// ---------------------------------------------------------------- run
async function run(opts) {
  S.running = true;
  const btn = document.getElementById('run-btn'); if (btn) { btn.disabled = true; btn.textContent = 'Fitting'; }
  const r = await post('/api/recommend', { scenario: S.scenario, fill_defaults: S.fill, llm: false });
  S.running = false;
  if (!r.ok || !r.data) {
    main().replaceChildren(h('div', { class: 'strip cr', role: 'alert' }, h('span', { class: 'tag crit' }, 'error'), h('div', {}, h('b', {}, 'The engine could not be reached'), h('div', { class: 'why' }, (r.data && r.data.error) || 'HTTP ' + r.status))));
    return;
  }
  S.result = r.data; S.raw = r.text;
  S.sel = firstSel(r.data);
  if (!(opts && opts.noNav)) go('#/result');
}
function firstSel(res) { const st = res.stack; if (!st) return 'backend'; if (S.sel && selItem(S.sel, res)) return S.sel; return 'backend'; }
function selItem(sel, res) {
  const st = (res || S.result).stack; if (!st) return null;
  if (sel.startsWith('sup:')) return (st.supporting || [])[Number(sel.slice(4))] || null;
  if (sel.startsWith('gap:')) { const g = ((res || S.result).decision_trace || {}).supporting; return g && g.gaps && g.gaps[Number(sel.slice(4))] ? { gap: g.gaps[Number(sel.slice(4))] } : null; }
  return st[sel] || null;
}

// ---------------------------------------------------------------- fitted body
function statusInfo(res) {
  const s = res.status;
  if (s === 'ok') return { cls: 'ok', tag: 'ok', tc: '' };
  if (s === 'ok_with_warnings') return { cls: 'ok', tag: 'ok with warnings', tc: 'hz' };
  if (s === 'invalid_input') return { cls: 'cr', tag: 'invalid input', tc: 'crit' };
  return { cls: 'cr', tag: words(s), tc: 'crit' };
}
function viewResult() {
  const m = main();
  const res = S.result;
  if (!res) {
    put(m, hd2('res-h', 'Nothing fitted yet', 'Load a scenario or answer the questionnaire, then run the fitting.'),
      h('div', { class: 'row' }, h('a', { class: 'btn p', href: '#/' }, 'Pick a scenario'), S.scenarioName || Object.keys(S.scenario || {}).length ? h('button', { class: 'btn', type: 'button', onclick: () => run() }, 'Run ' + scenarioTitle()) : null));
    return;
  }
  if (res.status === 'invalid_input') return viewInvalid(res);
  if (!res.stack) return viewInfeasible(res);
  const si = statusInfo(res);
  const c = res.estimated_monthly_cost_usd, bv = res.budget_verdict;
  const bolts = boltsOf(res);
  const gaps = bolts.filter((b) => b.state === 'gap');
  const costLine = c ? 'USD ' + band(c) + ' a month' + (bv ? ' against a USD ' + usd(bv.budget_usd) + ' budget' : '') + ' (≈ ' + inr(c.min) + '–' + inr(c.max).replace('₹', '') + ' at ₹' + INR_PER_USD + ' per USD).' : '';
  const gapLine = gaps.length ? ' ' + gaps.length + ' bolt-on' + (gaps.length > 1 ? 's have' : ' has') + ' no part that passes the hard constraints.' : '';
  put(m, sheetHead('fitted body — technical data', (res.scenario_id ? res.scenario_id + ' · ' : '') + scenarioTitle()),
    h('div', { class: 'strip ' + si.cls, role: 'status' }, h('span', { class: 'tag ' + si.tc }, si.tag),
      h('div', {}, h('b', { id: 'res-h' }, 'Fitted: a ' + words(res.architecture_style || '') + ' body for ' + scenarioTitle()), h('div', { class: 'why', style: 'margin:2px 0 0' }, costLine + gapLine)),
      h('div', { class: 'acts' }, h('a', { class: 'btn g s', href: '#/whatif' }, 'What-if'), h('button', { class: 'btn s', type: 'button', onclick: () => download((res.scenario_id || 'scenario') + '_output.json', S.raw) }, 'Download JSON'))),
    h('p', { class: 'summary' }, res.summary),
    res.relaxed_constraints && res.relaxed_constraints.length ? h('div', { class: 'strip hz' }, h('span', { class: 'tag hz' }, 'relaxed'), h('div', {}, h('b', {}, 'Constraints the bay loosened, and said so'), h('ul', { class: 'alist' }, res.relaxed_constraints.map((r) => h('li', {}, noteText(r)))))) : null);
  const xp = h('div', { class: 'exploded', id: 'xp' });
  const boltrow = h('div', { class: 'boltrow', id: 'bolts', role: 'group', 'aria-label': 'Bolt-ons: supporting services' }, bolts.map((b) =>
    h('button', { class: 'bc' + (b.state === 'gap' ? ' gap' : ''), type: 'button', 'data-sel': b.sel, 'aria-pressed': S.sel === b.sel ? 'true' : 'false', onclick: () => pick(b.sel) },
      h('span', { class: 'idx print-only' + (b.state === 'gap' ? ' hz' : '') }, b.idx), h('span', { class: 'bpic', html: FB.closeup('bolt', { kind: b.kind, state: b.state }) }),
      h('span', { class: 'btxt' }, h('span', {}, slotName(b.slot)), h('b', {}, b.state === 'gap' ? b.name : short(b.name, 40))))));
  const ptabs = h('div', { class: 'ptabs', role: 'tablist', id: 'ptabs', 'aria-label': 'Parts' }, PARTS.map((p) =>
    h('button', { role: 'tab', type: 'button', 'data-p': p.layer, 'aria-selected': S.sel === p.layer ? 'true' : 'false', 'aria-controls': 'detail', onclick: () => pick(p.layer) }, h('small', {}, p.sub), titleCase(p.part))));
  put(m, h('div', { class: 'res' },
    h('div', {}, xp, boltrow, h('div', { class: 'panel notes' }, tabsBlock(res))),
    h('div', { class: 'panel detail-wrap' }, ptabs, h('div', { class: 'detail', id: 'detail', role: 'tabpanel', 'aria-live': 'polite' }), costPanel(res))),
    sheetFoot('Fitted body · assembly diagram'));
  drawExploded(res, xp);
  renderDetail();
}
/* exploded scene: robot with four callouts, all live data */
const RXo = 250, RYo = 40;
const at = (x, y) => [RXo + (x - 70), RYo + (y + 10)];
const XC = { frontend: { pin: [153, 104], x: 10, y: 70, w: 310, h: 160, ey: 60 }, backend: { pin: [180, 316], x: 10, y: 318, w: 310, h: 160, ey: 60 },
  database: { pin: [230, 220], x: 572, y: 180, w: 310, h: 160, ey: 60 }, hosting: { pin: [300, 628], x: 572, y: 540, w: 310, h: 160, ey: 60 } };
function calloutInfo(res, layer) {
  const it = res.stack[layer];
  if (layer === 'database') { const g = gaugeOf(res); return ['<b>band</b> ' + band(res.estimated_monthly_cost_usd), '<b>needle</b> ' + usd(g.budget) + ' budget']; }
  return ((it && it.driven_by) || []).slice(0, 2).map((p) => { const v = inputValue(p); return '<b>' + esc(p.split('.').pop()) + '</b> ' + esc(v === undefined ? '(default)' : v.length > 24 ? v.slice(0, 22) + '…' : v); });
}
function drawExploded(res, xp) {
  const G = gaugeOf(res);
  const bot = FB.bot({ hang: true, sel: PART_OF[S.sel] ? PART_OF[S.sel].part : null, gauge: G, bolts: boltsOf(res).map((b) => ({ kind: b.kind, state: b.state })), interactive: true, id: 'resbot',
    parts: Object.fromEntries(PARTS.map((p) => [p.part, res.stack[p.layer] ? 'fit' : 'empty'])),
    labels: Object.fromEntries(PARTS.map((p) => [p.part, titleCase(p.part) + ': ' + p.sub + ', ' + ((res.stack[p.layer] || {}).choice || 'nothing needed')])) });
  const xcallout = (p) => {
    const o = XC[p.layer], [px, py] = at(...o.pin), left = o.x < px, ex = left ? o.x + o.w + 22 : o.x - 22, by = o.y + o.ey;
    const it = res.stack[p.layer]; const sc = partScore(res, p.layer);
    const pic = p.part === 'core' ? FB.closeup('core', { gauge: G }) : FB.closeup(p.part);
    const info = calloutInfo(res, p.layer).map((l) => `<span class="sub" style="display:block">${l}</span>`).join('');
    return `<path class="leader" d="M${px} ${py} L${ex} ${by} L${left ? o.x + o.w : o.x} ${by}"/><circle class="pin" cx="${px}" cy="${py}" r="6"/>
      <foreignObject x="${o.x}" y="${o.y}" width="${o.w}" height="${o.h}"><button xmlns="http://www.w3.org/1999/xhtml" type="button" class="xco" data-p="${p.layer}" aria-pressed="${S.sel === p.layer}" aria-label="${esc(titleCase(p.part) + ', ' + p.sub + ': ' + (it ? it.choice : 'nothing needed'))}"><span class="box"><span class="idx print-only">${p.idx}</span><span class="pic">${pic}</span><span><span class="k">${p.part} · ${p.sub}</span>${info}${sc ? `<span class="sub" style="display:block">score <b>${sc.total}</b></span>` : ''}</span></span><span class="bar">${esc(it ? short(it.choice) : 'nothing needed')}</span></button></foreignObject>`;
  };
  xp.innerHTML = stageSVG(900, 780, miniBay(900, 780, { lamp: 450, floor: 700 }) + nest(bot, RXo, RYo, 260, 680, '70 -10 260 680').replace('<svg class="bot', '<svg data-click class="bot') +
    PARTS.map(xcallout).join(''), 'Exploded view of the fitted body for ' + scenarioTitle() + '.');
  $$('.xco', xp).forEach((b) => { b.onclick = () => pick(b.dataset.p); });
  $$('#resbot .pt', xp).forEach((g) => { const l = LAYER_OF[g.dataset.part]; g.onclick = () => pick(l); g.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(l); } }; });
}
function pick(sel) {
  if (sel === S.sel) return;
  S.sel = sel;
  $$('#ptabs button').forEach((b) => b.setAttribute('aria-selected', b.dataset.p === sel ? 'true' : 'false'));
  $$('#xp .xco').forEach((b) => b.setAttribute('aria-pressed', b.dataset.p === sel ? 'true' : 'false'));
  $$('#bolts .bc').forEach((b) => b.setAttribute('aria-pressed', b.dataset.sel === sel ? 'true' : 'false'));
  $$('#resbot .pt').forEach((g) => g.classList.toggle('sel', LAYER_OF[g.dataset.part] === sel));
  const d = $('#detail'); if (!d) return;
  if (reduce()) { renderDetail(); return; }
  d.classList.add('swap'); setTimeout(() => { renderDetail(); d.classList.remove('swap'); }, 150);
}
function chipFor(path) {
  const f = S.fields.find((x) => x.path === path);
  const v = inputValue(path);
  const vv = v !== undefined && v.length > 48 ? v.slice(0, 46) + '…' : v;
  const label = [h('b', {}, path), v === undefined ? ' (default)' : ' = ' + vv];
  return f ? h('a', { class: 'chip', href: '#/q/' + f.step + '?f=' + path, title: 'Open this answer' }, label) : h('span', { class: 'chip' }, label);
}
const keyName = (k) => words(k).replace(/ fit$/, ' fit');
function renderDetail() {
  const box = document.getElementById('detail'); if (!box) return;
  const res = S.result; const it = selItem(S.sel, res);
  if (!it) { box.replaceChildren(h('p', { class: 'muted' }, 'Select a part.')); return; }
  if (it.gap) {
    const g = it.gap;
    box.replaceChildren(h('div', { class: 'dname' }, h('div', {}, h('span', { class: 'tag hz' }, 'bolt-on · ' + slotName(g.slot)), h('h3', {}, 'No part fits'))),
      h('p', { class: 'dwhy' }, g.message), h('p', { class: 'muted' }, 'The gap is listed under Warnings as ', h('code', {}, g.code || 'SUPPORTING_GAP'), '. Nothing is fitted silently in its place.'));
    return;
  }
  const isSup = S.sel.startsWith('sup:');
  const P = PART_OF[S.sel];
  const ids = idsOf(it);
  const parts = [];
  /* score lines */
  const bars = h('div', { class: 'bars' });
  let total = null, of = null;
  if (isSup) {
    const sel = res.decision_trace && res.decision_trace.supporting && (res.decision_trace.supporting.selected || []).find((x) => x.id === it.kb_id && x.slot === it.slot);
    if (sel && sel.ranked && sel.ranked.length) {
      total = sel.total; of = sel.ranked.length;
      const mx = Math.max(...sel.ranked.map((r) => Math.abs(r.total)), 1);
      sel.ranked.forEach((r) => bars.append(...barRow(r.id + (r.id === sel.id ? ' (chosen)' : ''), r.total, mx)));
    }
  } else {
    ids.forEach((id) => {
      const tt = traceTop(res, id); if (!tt) return;
      if (total == null) { total = tt.t.total; of = tt.L.candidates; }
      const mx = Math.max(...tt.t.contributions.map((c) => Math.abs(c.value)), 1);
      if (ids.length > 1) bars.append(h('div', { class: 'barhead' }, tt.t.name + ' · total ' + tt.t.total));
      tt.t.contributions.forEach((c) => bars.append(...barRow(keyName(c.key), c.value, mx, c.reason)));
    });
  }
  parts.push(h('div', { class: 'dname' },
    h('div', {}, h('span', { class: 'tag' }, isSup ? 'bolt-on · ' + slotName(it.slot) : titleCase(P.part) + ' · ' + P.sub), h('h3', {}, it.choice)),
    total != null ? h('div', { class: 'score' }, h('span', {}, 'score'), h('b', {}, String(total)), h('span', {}, 'of ' + of + ' candidates')) : null));
  parts.push(h('p', { class: 'dwhy' }, it.justification));
  parts.push(h('div', { class: 'sect' }, 'driven by'), (it.driven_by || []).length ? h('div', { class: 'chips' }, it.driven_by.map(chipFor)) : h('p', { class: 'muted' }, 'No single input drove this choice.'));
  if (bars.childNodes.length) parts.push(h('div', { class: 'sect' }, isSup ? 'peer totals, highest wins' : 'score lines · open a line for its reason'), bars);
  /* runners-up and cuts */
  const alts = it.alternatives || [];
  const L = !isSup && ids.length ? (traceTop(res, ids[0]) || {}).L : null;
  const cuts = L ? (L.rejected || []).filter((r) => !alts.some((a) => a.choice === r.name)).slice(0, 4) : [];
  parts.push(h('div', { class: 'sect' }, 'runners-up, and parts the bay cut'));
  if (alts.length || cuts.length) {
    parts.push(h('table', { class: 'alt' }, h('tbody', {},
      alts.map((a) => { const rej = traceRejected(res, a.choice); return h('tr', {}, h('td', {}, a.choice), h('td', {}, rej ? h('span', { class: 'sev crit' }, 'cut') : h('span', { class: 'mono' }, 'runner-up')), h('td', { class: 'muted' }, rej ? rej.reason_text : a.why_not, rej && rej.fields && rej.fields.length ? h('div', { class: 'chips', style: 'margin-top:6px' }, rej.fields.map(chipFor)) : null)); }),
      cuts.map((r) => h('tr', {}, h('td', {}, r.name), h('td', {}, h('span', { class: 'sev crit' }, r.unverified ? 'cut · unverified' : 'cut')), h('td', { class: 'muted' }, r.reason_text))))));
  } else parts.push(h('p', { class: 'muted' }, 'No other candidate survived the filters for this slot.'));
  parts.push(h('div', { class: 'sect' }, 'trade-offs you accept'), (it.tradeoffs || []).length ? h('ul', { class: 'tlist' }, it.tradeoffs.map((t) => h('li', {}, t))) : h('p', { class: 'muted' }, 'None recorded.'));
  const srcBox = h('div', { id: 'srcs' });
  parts.push(h('div', { class: 'sect' }, 'sources'), srcBox);
  box.replaceChildren(...parts);
  requestAnimationFrame(() => requestAnimationFrame(() => $$('#detail .bars i').forEach((i) => i.style.setProperty('--s', i.dataset.s))));
  loadSources(ids, srcBox);
}
function barRow(label, val, mx, reason) {
  const s = Math.min(Math.abs(val) / mx, 1).toFixed(3);
  const lab = reason ? h('details', { class: 'bl' }, h('summary', {}, label), h('div', { class: 'bar-detail' }, reason)) : h('span', {}, label);
  return [lab, h('span', { class: 't' }, h('i', { class: val < 0 ? 'n' : '', 'data-s': s })), h('span', { class: 'v' }, sgn(val))];
}
async function loadSources(ids, box) {
  if (!ids.length) { box.append(h('p', { class: 'muted' }, 'This part has no knowledge-base record.')); return; }
  await ensureSources();
  const keys = new Set();
  for (const id of ids) {
    if (!S.kbRec[id]) { const r = await api('/api/kb/' + encodeURIComponent(id)); if (r.ok) S.kbRec[id] = r.data; }
    ((S.kbRec[id] && S.kbRec[id].sources) || []).forEach((k) => keys.add(k));
  }
  if (!box.isConnected) return;
  const list = [...keys].sort();
  box.replaceChildren(list.length ? h('ul', { class: 'srcs' }, list.map((k) => { const s = S.sources.get(k); return h('li', {}, s ? [h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, s.title), h('span', { class: 'muted' }, ' · accessed ' + s.accessed)] : k); })) : h('p', { class: 'muted' }, 'No sources attached.'));
}

// ---- cost panel + tabs
function costPanel(res) {
  const c = res.estimated_monthly_cost_usd, bv = res.budget_verdict; if (!c) return h('span');
  const G = gaugeOf(res);
  const cls = bv && /exceed|over/.test(bv.verdict) ? 'crit' : bv && bv.verdict === 'tight' ? 'warn' : 'ok';
  return h('div', { class: 'costbox' },
    h('div', { class: 'cg-g', html: FB.closeup('core', { gauge: G }) }),
    h('div', {}, h('div', { class: 'sect', style: 'margin-top:0' }, 'cost band and budget · core gauge'),
      h('div', { class: 'costbig' }, 'USD ' + band(c), h('small', {}, ' / month')),
      h('p', { class: 'muted', style: 'margin:4px 0 0' }, '≈ ' + inr(c.min) + '–' + inr(c.max).replace('₹', '') + ' at ₹' + INR_PER_USD + ' per USD (display only; the JSON stays in USD).'),
      bv ? h('p', { style: 'margin:8px 0 0' }, h('span', { class: 'sev ' + cls }, words(bv.verdict)), ' ', 'Budget USD ' + usd(bv.budget_usd) + '. ' + budgetSentence(bv)) : null));
}
function budgetSentence(bv) {
  if (/exceed|over/.test(bv.verdict)) return 'Even the low end of the estimate is above the budget; the bay does not hide this.';
  if (bv.verdict === 'tight') return 'The budget covers the low end of the estimate but not necessarily the high end.';
  if (bv.verdict === 'within' || bv.verdict === 'headroom') return 'The whole estimated band sits inside the budget.';
  if (/free/.test(bv.verdict)) return 'The stack runs on free tiers at this scale.';
  return '';
}
function tabsBlock(res) {
  const W = res.warnings || [];
  const costLines = (res.decision_trace && res.decision_trace.cost_lines) || [];
  const notes = [...(res.compliance_notes || []).map((n) => ['compliance', n]), ...(res.integration_notes || []).map((n) => ['integration', n])];
  const tabs = [
    ['warnings', 'Warnings', W.length, () => warningsPane(W)],
    ['notes', 'Notes', notes.length, () => notesPane(notes)],
    ['assumptions', 'Assumptions', (res.assumptions || []).length, () => assumptionsPane(res)],
    ['cost', 'Cost lines', costLines.length, () => costPane(res, costLines)],
    ['json', 'Raw JSON', null, () => jsonPane()],
  ];
  if (!tabs.some((t) => t[0] === S.tab)) S.tab = 'warnings';
  const panel = h('div', { class: 'tabpanel', role: 'tabpanel', id: 'tabpanel', tabindex: '0' });
  const list = h('div', { class: 'subtabs', role: 'tablist', 'aria-label': 'Result details', style: 'margin-top:0' });
  const paint = () => {
    list.querySelectorAll('button').forEach((b) => { const on = b.dataset.tab === S.tab; b.setAttribute('aria-selected', on ? 'true' : 'false'); b.tabIndex = on ? 0 : -1; });
    panel.setAttribute('aria-labelledby', 'tab-' + S.tab);
    panel.replaceChildren(tabs.find((t) => t[0] === S.tab)[3]());
  };
  tabs.forEach(([k, label, n]) => list.append(h('button', { role: 'tab', type: 'button', 'data-tab': k, id: 'tab-' + k, onclick: () => { S.tab = k; paint(); },
    onkeydown: (e) => { const i = tabs.findIndex((t) => t[0] === S.tab); if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { S.tab = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length][0]; paint(); list.querySelector('[data-tab="' + S.tab + '"]').focus(); } } }, label, n != null ? h('em', {}, String(n)) : null)));
  const wrap = h('div', { class: 'tabs' }, list, panel);
  paint();
  return wrap;
}
function warningsPane(W) {
  if (!W.length) return h('p', { class: 'muted pane' }, 'The engine raised no warnings.');
  const rows = [];
  SEV_ORDER.forEach((sev) => W.filter((w) => w.severity === sev).forEach((w) => rows.push(h('tr', {},
    h('td', { style: 'width:120px' }, h('span', { class: 'sev ' + SEV_CLASS[sev] }, SEV_WORD[sev])),
    h('td', {}, h('div', {}, w.message), h('div', { class: 'wcode' }, h('code', {}, w.code)), w.fields && w.fields.length ? h('div', { class: 'chips', style: 'margin-top:6px' }, w.fields.map(chipFor)) : null)))));
  return h('table', { class: 'warns' }, h('tbody', {}, rows));
}
function assumptionsPane(res) {
  return h('div', { class: 'pane' }, h('p', { class: 'muted', style: 'margin-top:0' }, 'Everything the bay assumed because you did not say. Nothing here is hidden.'),
    h('ul', { class: 'alist' }, (res.assumptions || []).map((a) => h('li', {}, noteText(a)))),
    res.estimated_monthly_cost_usd && (res.estimated_monthly_cost_usd.assumptions || []).length ? [h('div', { class: 'sect' }, 'cost assumptions'), h('ul', { class: 'alist' }, res.estimated_monthly_cost_usd.assumptions.map((a) => h('li', {}, a)))] : null);
}
function costPane(res, lines) {
  if (!lines.length) return h('p', { class: 'muted pane' }, 'No per-part cost lines in this response.');
  return h('div', { class: 'scrollx' }, h('table', { class: 'costt' }, h('thead', {}, h('tr', {}, ['slot', 'part', 'min USD', 'max USD', 'basis'].map((t) => h('th', {}, t)))),
    h('tbody', {}, lines.map((l) => h('tr', {}, h('td', {}, slotName(l.slot)), h('td', {}, l.name), h('td', { class: 'num' }, usd(l.min)), h('td', { class: 'num' }, usd(l.max)), h('td', { class: 'muted' }, l.basis + (l.derived ? ' (derived)' : '')))))));
}
function notesPane(notes) {
  if (!notes.length) return h('p', { class: 'muted pane' }, 'No compliance or integration notes apply to this input. Regulation notes for this run, if any, are under Warnings.');
  return h('ul', { class: 'alist pane' }, notes.map(([k, n]) => h('li', {}, h('span', { class: 'chip ghost' }, k), ' ', noteText(n))));
}
function jsonPane() {
  const name = (S.result.scenario_id || 'scenario') + '_output.json';
  return h('div', { class: 'pane' }, h('div', { class: 'row' },
    h('button', { class: 'btn g s', type: 'button', onclick: () => download(name, S.raw) }, 'Download ' + name),
    h('button', { class: 'btn g s', type: 'button', onclick: (e) => copyText(S.raw, e.target) }, 'Copy'),
    h('span', { class: 'k' }, 'exactly the bytes the API returned: ' + nf.format(S.raw.length) + ' characters')),
  h('pre', { class: 'json-box', tabindex: '0', 'aria-label': 'Raw JSON response', id: 'raw-json' }, S.raw));
}

// ---- rejected (invalid input): the reject bin
function viewInvalid(res) {
  const m = main();
  const errs = res.validation_errors || [];
  const missing = errs.filter((e) => /missing/i.test(e.message));
  const first = errs.map((e) => S.fields.find((f) => f.path === String(e.field).replace(/\[.*$/, ''))).find(Boolean);
  const W = 480, H = 520;
  const part = (k, x, y, r, s) => `<g transform="translate(${x} ${y}) rotate(${r}) scale(${s})"><use href="#fbp-${k}" transform="translate(-200 -${FB.PART[k].at[1]})"/></g>`;
  const tag = (x1, y1, x2, y2, t) => `<path d="M${x1} ${y1} Q${(x1 + x2) / 2} ${Math.max(y1, y2) + 30} ${x2} ${y2}" fill="none" stroke="var(--ink)" stroke-width="1.6"/><circle cx="${x1}" cy="${y1}" r="3.5" fill="var(--crit)" stroke="#0B0F14" stroke-width="1.5"/>
    <g transform="translate(${x2 - 4} ${y2 - 2}) rotate(${(x2 % 7) - 3})"><rect width="${t.length * 7.2 + 16}" height="24" fill="var(--crit)" stroke="#0B0F14" stroke-width="2"/><circle cx="8" cy="12" r="3" fill="#0B0F14"/><text x="15" y="16.5" ${MONO} font-size="12" font-weight="500" fill="#11161D">${esc(t)}</text></g>`;
  const bin = `<g><path d="M70 300 L410 300 L388 470 L92 470 Z" fill="#3A4450" stroke="#0B0F14" stroke-width="3.5"/>
    <path d="M330 300 L410 300 L388 470 L330 470 Z" fill="#2C3540"/><path d="M330 300 L410 300 L388 470 L330 470 Z" fill="url(#fb-dots)"/>
    ${[130, 190, 250, 310, 370].map((x) => `<path d="M${x} 318 L${x - 4 * (x - 240) / 170} 452" stroke="#0B0F14" stroke-width="2" opacity=".6"/>`).join('')}
    <rect x="58" y="284" width="364" height="22" fill="url(#fb-hz)" stroke="#0B0F14" stroke-width="3"/>
    <text x="240" y="402" text-anchor="middle" style="font-family:var(--disp)" font-size="36" fill="#0B0F14" opacity=".55">REJECT</text>
    <rect x="96" y="470" width="30" height="14" fill="#0B0F14"/><rect x="354" y="470" width="30" height="14" fill="#0B0F14"/></g>`;
  const SLOTS = [[150, 248, 30, 72], [236, 232, 160, 40], [318, 240, 300, 96], [372, 226, 352, 150], [262, 288, 60, 150], [196, 282, 40, 208]];
  const lab = (e) => { const t = String(e.field); return t.length > 26 ? '…' + t.slice(-25) : t; };
  const tags = errs.slice(0, 6).map((e, i) => tag(...SLOTS[i], lab(e))).join('') + (errs.length > 6 ? `<text x="240" y="508" text-anchor="middle" ${MONO} font-size="13" fill="var(--muted)">+ ${errs.length - 6} more in the table</text>` : '');
  const stage = stageSVG(W, H, miniBay(W, H, { lamp: 240, floor: 480 }) +
    `<g>${part('visor', 150, 262, -28, 1.05)}${part('spine', 236, 252, 62, 1.1)}<g transform="translate(316 258) rotate(18) scale(1.25)">${FB.gauge({ low: 0, high: 0, budget: 0 }, { lit: false })}</g>${part('cradle', 250, 300, -6, .9)}</g>${bin}
     <g transform="translate(372 236)">${FB.boltShape('realtime', 'fit')}</g>` + tags,
  'A reject bin holding a helmet, spine, gauge and cradle, each tied to one of the ' + errs.length + ' errors.');
  put(m, sheetHead('rejected — input errors', (res.scenario_id ? res.scenario_id + ' · ' : '') + scenarioTitle()),
    hd2('inv-h', 'Parts rejected', 'The bay couldn’t read ' + errs.length + ' answer' + (errs.length === 1 ? '' : 's') + ' in ' + scenarioTitle() + ',', 'so it fitted nothing. Fix these and run again.'),
    h('div', { class: 'rej' },
      h('div', { class: 'mini', id: 'bin', html: stage }),
      h('div', { class: 'panel pad' }, errorTable(errs),
        h('div', { class: 'row', style: 'margin-top:18px' },
          first ? h('a', { class: 'btn p', href: '#/q/' + first.step + '?f=' + first.path }, 'Fix in the questionnaire ', h('span', { class: 'arr' }, '→')) : null,
          missing.length && !S.fill ? h('button', { class: 'btn', type: 'button', onclick: () => { S.fill = true; run({ noNav: true }).then(() => route()); } }, 'Run again with documented defaults') : null,
          h('button', { class: 'btn g', type: 'button', onclick: () => download((res.scenario_id || 'scenario') + '_errors.json', JSON.stringify(errs, null, 2) + '\n') }, 'Download the error list')),
        h('p', { class: 'why', style: 'margin-top:14px' }, missing.length === errs.length ? 'Every problem is a missing answer. Documented defaults can fill them; each one would be listed under Assumptions.' : 'Documented defaults only fill answers that are missing. Answers that are present but wrong are never guessed.'),
        (res.assumptions || []).length ? h('div', {}, h('div', { class: 'sect' }, 'defaults that would apply'), h('ul', { class: 'alist' }, res.assumptions.map((a) => h('li', {}, noteText(a))))) : null)),
    h('div', { class: 'panel notes', style: 'margin-top:20px' }, h('div', { class: 'subtabs', role: 'tablist', style: 'margin-top:0' }, h('button', { role: 'tab', type: 'button', 'aria-selected': 'true' }, 'Raw JSON')), jsonPane()),
    sheetFoot('Rejected · parts returned'));
}

// ---- can't assemble (infeasible): two clamps arc at each other
function viewInfeasible(res) {
  const m = main();
  const crit = (res.warnings || []).filter((w) => w.severity === 'critical');
  const nfz = res.nearest_feasible || [];
  const c0 = crit[0];
  const sides = (nfz.length >= 2 ? nfz.slice(0, 2).map((n) => n.field) : (c0 && c0.fields) || []).slice(0, 2);
  const lab = (p) => p ? p.split('.').pop() + ' = ' + (inputValue(p) === undefined ? '(default)' : inputValue(p)) : '';
  const W = 620, H = 560;
  const bot = FB.bot({ parts: { visor: 'fit', spine: 'fit', core: 'fit', cradle: 'bad' }, gauge: { low: 0, high: 0, budget: 0 }, lit: false, id: 'cbot' });
  const plate = (x, fill, lock) => `<g transform="translate(${x} 300)"><rect x="-60" y="-70" width="120" height="136" rx="6" fill="${C.s1}" stroke="#0B0F14" stroke-width="3.5"/>
    <rect x="-60" y="-70" width="120" height="136" rx="6" fill="url(#fb-dots)" opacity=".5"/><rect x="-48" y="-58" width="96" height="112" fill="none" stroke="#0B0F14" stroke-width="2"/>
    ${[[-50, -60], [50, -60], [-50, 56], [50, 56]].map(([a, b]) => `<circle cx="${a}" cy="${b}" r="3.5" fill="${C.sh}" stroke="#0B0F14" stroke-width="1.4"/>`).join('')}
    ${lock ? `<path d="M-14 -6 V-16 A14 14 0 0 1 14 -16 V-6" fill="none" stroke="#0B0F14" stroke-width="6"/><rect x="-22" y="-8" width="44" height="34" fill="${fill}" stroke="#0B0F14" stroke-width="3"/><circle cx="0" cy="6" r="4" fill="#0B0F14"/>`
    : `<path d="M-26 -22 H10 V-12 H-14 V12 H10 V22 H-26 Z" fill="${fill}" stroke="#0B0F14" stroke-width="3"/><path d="M10 0 H26 M18 -8 V8" stroke="#0B0F14" stroke-width="4"/>`}</g>`;
  const arcP = 'M176 210 L214 236 L204 248 L246 262 L238 276 L282 284 L276 296 L318 300 L312 314 L356 312 L350 326 L392 322 L386 334 L436 330';
  const arcQ = 'M178 226 L222 252 L210 258 L256 272 L246 280 L296 290 L286 302 L334 306 L326 318 L374 318 L362 330 L438 342';
  const tl = (x, y, w, t, fill) => `<rect x="${x}" y="${y}" width="${w}" height="30" fill="${fill}" stroke="#0B0F14" stroke-width="2"/><text x="${x + 10}" y="${y + 20}" fill="#11161D">${esc(t)}</text>`;
  const L1 = lab(sides[0]), L2 = lab(sides[1]);
  const w1 = Math.min(290, L1.length * 9.2 + 22), w2 = Math.min(290, L2.length * 9.2 + 22);
  const stage = stageSVG(W, H, miniBay(W, H, { lamp: 310, floor: 500 }) +
    `<g opacity=".45">${nest(bot, 210, 90, 200, 330, '60 40 280 620')}</g>` + plate(118, C.or, false) + plate(502, C.mu, true) +
    `<g class="crackle"><path class="arc" d="${arcP}" stroke="#0B0F14" stroke-width="9"/><path class="arc" d="${arcP}" stroke="${C.mu}" stroke-width="5"/><path class="arc" d="${arcP}" stroke="#FFF4DA" stroke-width="1.8"/></g>
     <g class="crackle b"><path class="arc" d="${arcQ}" stroke="#0B0F14" stroke-width="6"/><path class="arc" d="${arcQ}" stroke="${C.or}" stroke-width="3"/></g>
     ${FB.sparks(306, 302, 14, 5, 's1')}${FB.flash(306, 302, 'f1')}${FB.cloud(420, 250, .7)}
     <g ${MONO} font-size="15" font-weight="500">${L1 ? tl(20, 410, w1, L1, 'var(--weld)') : ''}${L2 ? tl(W - 20 - w2, 410, w2, L2, 'var(--crit)') : ''}</g>`,
  'Two clamps arc at each other: ' + (L1 || 'one answer') + ' and ' + (L2 || 'another') + '. The cradle between them cannot be fitted.');
  const parseTo = (n) => { const raw = String(n.relax || '').split('->').pop().trim(); const f = S.fields.find((x) => x.path === n.field); if (!f) return raw; if (f.type === 'integer' || f.type === 'number') return Number(raw); if (f.type === 'boolean') return raw === 'true'; if (f.type === 'list') return raw.replace(/[[\]]/g, '').split(',').map((s) => s.trim()).filter(Boolean); return raw; };
  put(m, sheetHead('can’t assemble — hard-constraint clash', (res.scenario_id ? res.scenario_id + ' · ' : '') + scenarioTitle()),
    hd2('inf-h', 'Can’t assemble', 'Answers in ' + scenarioTitle() + ' ask for parts that can’t share one body.', 'The bay won’t fake it.'),
    h('div', { class: 'clash' },
      h('div', { class: 'mini', id: 'clash-stage', html: stage }),
      h('div', {},
        h('div', { class: 'strip cr', style: 'margin-bottom:16px' }, h('span', { class: 'tag crit' }, 'clash'), h('div', {}, h('b', {}, c0 ? words(c0.code).toLowerCase().replace(/^./, (x) => x.toUpperCase()) : 'No stack satisfies every hard constraint'), h('div', { class: 'why', style: 'margin:4px 0 0;color:var(--ink)' }, c0 ? c0.message : res.summary))),
        h('div', { class: 'panel pad' },
          h('div', { class: 'sect', style: 'margin-top:0' }, 'change one answer and it fits'),
          nfz.length ? h('table', { class: 'nf' }, h('tbody', {}, nfz.map((n) => h('tr', {},
            h('td', {}, h('code', {}, n.field || ''), h('div', { class: 'why' }, (n.relax || '').replace('->', '→')), n.message ? h('div', { class: 'why' }, n.message) : null),
            h('td', {}, h('span', { class: 'sev ok' }, 'fits')),
            h('td', { style: 'text-align:right' }, n.field ? h('button', { class: 'btn g s', type: 'button', onclick: () => { S.whatif = { path: n.field, preset: parseTo(n), auto: true }; go('#/whatif'); } }, 'Try it') : null))))) : h('p', { class: 'muted' }, 'The bay found no single change that makes this feasible.'),
          h('div', { class: 'sect' }, 'warnings'), warningsPane(res.warnings || [])))),
    h('div', { class: 'panel notes', style: 'margin-top:20px' }, tabsBlock(res)),
    sheetFoot('Can’t assemble · clash diagram'));
}

// ---------------------------------------------------------------- what-if
function viewWhatIf() {
  const m = main();
  put(m, sheetHead('what-if — one answer changed'));
  if (!S.result) { put(m, hd2('wi-h', 'What if', 'Run a scenario first.', 'The what-if changes one answer of the scenario you ran.'), h('a', { class: 'btn p', href: '#/' }, 'Pick a scenario')); return; }
  const w = S.whatif && S.whatif.base === S.result ? S.whatif : (S.whatif = { path: (S.whatif && S.whatif.path) || 'infrastructure.data_residency', preset: S.whatif && S.whatif.preset, auto: S.whatif && S.whatif.auto, base: S.result, diff: null });
  if (!S.fields.some((f) => f.path === w.path)) w.path = S.fields[0].path;
  const holder = h('div', { class: 'wival' });
  const out = h('div', { id: 'wf-out' });
  const curChip = h('span', { class: 'chip' });
  const sel = h('select', { id: 'wifield', onchange: (e) => { w.path = e.target.value; w.diff = null; w.preset = undefined; paintCtl(); out.replaceChildren(); } },
    S.fields.map((f) => h('option', { value: f.path, selected: f.path === w.path }, f.path)));
  function paintCtl(keep) {
    const f = S.fields.find((x) => x.path === w.path);
    if (!keep) { w.scenario = JSON.parse(JSON.stringify(isObj(S.scenario) ? S.scenario : {})); if (w.preset !== undefined) setp(w.scenario, w.path, w.preset); }
    S.edit = w.scenario; S.repaint = () => paintCtl(true); S.onEdit = null;
    const cur = inputValue(w.path);
    curChip.textContent = cur === undefined ? '(not set)' : cur;
    holder.replaceChildren(control(f, 'wf-in', getp(w.scenario, f.path)));
  }
  const refit = h('button', { class: 'btn p', id: 'refit', type: 'button', onclick: () => doRefit() }, 'Refit ', h('span', { class: 'arr' }, '→'));
  async function doRefit() {
    refit.disabled = true;
    const r = await post('/api/diff', { a: S.scenario, b: w.scenario, fill_defaults: S.fill });
    refit.disabled = false;
    if (!r.ok || !r.data) { out.replaceChildren(h('div', { class: 'strip cr' }, h('span', { class: 'tag crit' }, 'error'), h('div', {}, h('b', {}, 'The engine could not run this change'), h('div', { class: 'why' }, (r.data && r.data.error) || 'HTTP ' + r.status)))); return; }
    w.diff = r.data; w.value = getp(w.scenario, w.path);
    out.replaceChildren(diffView(S.result, w.diff, w.path, w.value, true));
  }
  put(m, hd2('wi-h', 'What if', 'Change one answer.', 'The bay refits and outlines every part that moved, in hazard yellow.'),
    h('div', { class: 'wibar' }, h('label', { class: 'k', for: 'wifield' }, 'answer'), sel, curChip, h('span', { class: 'muted', 'aria-hidden': 'true' }, '→'), h('span', { class: 'sr' }, 'new value'), holder, refit),
    out, sheetFoot('What-if · before and after'));
  paintCtl();
  if (w.diff) put(out, diffView(S.result, w.diff, w.path, w.value, false));
  else if (w.auto) { w.auto = false; doRefit(); }
}
const supKey = (k) => k.replace(/^supporting\./, '');
function diffView(a, d, path, value, animate) {
  const L = d.layers || {};
  const core = PARTS.filter((p) => L[p.layer] && L[p.layer].changed);
  const supK = Object.keys(L).filter((k) => k.startsWith('supporting.'));
  const supChanged = supK.filter((k) => L[k].changed);
  /* before: the result as run */
  const gA = gaugeOf(a);
  const bvA = a.budget_verdict;
  const budgetB = (() => { const v = getp(isObj(S.whatif.scenario) ? S.whatif.scenario : {}, 'budget.monthly_infra_usd'); return typeof v === 'number' ? v : gA.budget; })();
  const gB = d.cost && d.cost.to ? { low: d.cost.to.min, high: d.cost.to.max, budget: budgetB } : { low: 0, high: 0, budget: budgetB };
  const boltsA = boltsOf(a).map((b) => ({ kind: b.kind, state: b.state }));
  const boltsB = supK.filter((k) => L[k].to != null).map((k) => ({ kind: boltKind(supKey(k), supKey(k).split('.')[0]), state: L[k].changed ? 'diff' : 'fit' }));
  supK.filter((k) => L[k].to == null && L[k].from != null).forEach((k) => boltsB.push({ kind: boltKind(supKey(k), supKey(k).split('.')[0]), state: 'gap' }));
  const stA = d.status && d.status.from, stB = d.status && d.status.to;
  const botA = FB.bot({ hang: true, gauge: gA, bolts: boltsA, id: 'wia' });
  const botB = stB === 'infeasible' || stB === 'invalid_input' ? FB.bot({ hang: true, parts: { cradle: 'bad' }, gauge: gB, lit: false, id: 'wib' })
    : FB.bot({ hang: true, parts: Object.fromEntries(PARTS.map((p) => [p.part, L[p.layer] && L[p.layer].changed ? 'diff' : L[p.layer] && L[p.layer].to == null ? 'empty' : 'fit'])), gauge: gB, bolts: boltsB, id: 'wib' });
  const stage = (bot, label) => stageSVG(520, 620, miniBay(520, 620, { lamp: 260, floor: 560 }) + nest(bot, 135, 10, 250, 600, '70 -10 260 680'), label);
  const names = (side) => PARTS.filter((p) => p.layer !== 'frontend').map((p) => short(L[p.layer] && L[p.layer][side], 24)).filter(Boolean).join(' · ');
  const wa = d.warnings || { added: [], removed: [] };
  const cost = d.cost || {};
  const delta = (n) => (n > 0 ? '+' : n < 0 ? '−' : '±') + usd(Math.abs(n || 0));
  const exceeded = (wa.added || []).includes('BUDGET_EXCEEDED');
  const val = Array.isArray(value) ? value.join(', ') : value === undefined ? '(not set)' : String(value);
  const wrap = h('div', {},
    h('div', { class: 'pair' },
      h('div', { class: 'side' }, h('div', { class: 'mini', id: 'wi-a', html: stage(botA, 'Before: ' + scenarioTitle() + ' as answered.') }),
        h('div', { class: 'meta' }, h('div', { class: 'k' }, 'before · ' + scenarioTitle() + ' as answered'), h('h3', {}, names('from') || words(stA || '')), h('div', { class: 'why' }, words(d.architecture_style ? d.architecture_style.from : a.architecture_style) + ' · USD ' + band(cost.from) + ' · ' + (a.warnings || []).filter((x) => x.severity !== 'info').length + ' warnings'))),
      h('div', { class: 'deltas' },
        h('div', { class: 'dl' }, h('span', {}, 'cost per month'), h('b', { class: (cost.delta_max || 0) > 0 ? 'up' : 'down' }, cost.changed ? delta(cost.delta_min) + ' / ' + delta(cost.delta_max) : 'no change'), h('span', {}, band(cost.from) + ' → ' + band(cost.to))),
        h('div', { class: 'dl' }, h('span', {}, 'parts moved'), h('b', {}, core.length + ' of 4'), h('span', {}, '+ ' + supChanged.length + ' bolt-on' + (supChanged.length === 1 ? '' : 's'))),
        h('div', { class: 'dl' }, h('span', {}, 'warnings'), h('b', {}, '+' + (wa.added || []).length + ' / −' + (wa.removed || []).length), h('span', {}, exceeded ? 'budget now exceeded' : (wa.removed || []).includes('BUDGET_EXCEEDED') ? 'budget no longer exceeded' : 'codes listed below')),
        d.architecture_style ? h('div', { class: 'dl' }, h('span', {}, 'architecture'), h('b', { style: 'font-size:17px' }, words(d.architecture_style.to || '–')), h('span', {}, d.architecture_style.changed ? 'was ' + words(d.architecture_style.from) : 'unchanged')) : null,
        stA !== stB ? h('div', { class: 'dl' }, h('span', {}, 'status'), h('b', { style: 'font-size:17px' }, words(stB || '')), h('span', {}, 'was ' + words(stA || ''))) : null),
      h('div', { class: 'side' }, h('div', { class: 'mini', id: 'wi-b', html: stage(botB, 'After: ' + core.length + ' parts and ' + supChanged.length + ' bolt-ons changed.') }),
        h('div', { class: 'meta' }, h('div', { class: 'k' }, 'after · ' + path.split('.').pop() + ' = ' + val), h('h3', {}, names('to') || words(stB || '')), h('div', { class: 'why' }, words(d.architecture_style ? d.architecture_style.to : '') + ' · USD ' + band(cost.to) + (exceeded ? ' · BUDGET_EXCEEDED' : ''))))),
    h('div', { class: 'panel', style: 'margin-top:20px' }, (core.length || supChanged.length) ? h('table', { class: 'chg resp' }, h('thead', {}, h('tr', {}, h('th', {}, 'part'), h('th', {}, 'before'), h('th', {}, 'after'), h('th', {}, 'driven by'))),
      h('tbody', {}, [...core.map((p) => [p.part + ' · ' + p.sub, L[p.layer]]), ...supChanged.map((k) => ['bolt-on · ' + slotName(supKey(k)), L[k]])].map(([n, x]) =>
        h('tr', {}, h('td', {}, n), h('td', {}, x.from == null ? 'no part fits' : x.from), h('td', {}, x.to == null ? 'no part fits' : x.to), h('td', {}, (x.drivers && x.drivers.length ? x.drivers : d.changed_fields || []).map((p) => h('code', { style: 'display:block' }, p)))))))
      : h('p', { class: 'pane' }, 'Nothing in the body moved. ', (d.changed_fields || []).length ? 'The answer changed, but every part still scores highest.' : ''),
    (wa.added || []).length || (wa.removed || []).length ? h('div', { class: 'pane wcodes' }, (wa.added || []).map((c) => h('span', { class: 'chip hz' }, '+ ' + c)), (wa.removed || []).map((c) => h('span', { class: 'chip ghost' }, '− ' + c))) : null));
  if (animate && !reduce()) requestAnimationFrame(() => {
    const svg = $('#wib'); if (!svg) return;
    core.forEach((p, i) => setTimeout(() => FB.boltOn(svg, p.part, p.part === 'visor' ? 'left' : p.part === 'spine' ? 'right' : 'top'), i * 110));
    setTimeout(() => svg.querySelectorAll('.bolt.diff .bolt-in').forEach((b, i) => b.animate([{ opacity: 0, transform: 'scale(.9)' }, { opacity: 1, transform: 'none' }], { duration: 240, delay: (i % 3) * 30, easing: 'cubic-bezier(.23,1,.32,1)', fill: 'backwards' })), core.length * 110 + 300);
  });
  return wrap;
}

// ---------------------------------------------------------------- sensitivity
const LAYER_PART = (l) => (PART_OF[l] ? PART_OF[l].part : l.startsWith('supporting') ? 'bolt' : l);
async function viewSens() {
  const m = main();
  const named = S.scenarios.filter((s) => s.category === 'public');
  if (!S.sensBase) S.sensBase = S.scenarios.some((s) => s.id === S.scenarioName) ? S.scenarioName : 'P2';
  const tbody = h('tbody', {}, h('tr', {}, h('td', { colspan: '6', class: 'muted' }, 'Flipping each StackSense addition alone on ' + S.sensBase + '…')));
  const foot = h('p', { class: 'k', style: 'margin-top:12px' });
  const sel = h('select', { class: 'themebtn', 'aria-label': 'Base scenario', style: 'min-height:40px', onchange: (e) => { S.sensBase = e.target.value; S.sens = null; route(); } },
    [...named, ...S.scenarios.filter((s) => s.category !== 'public' && s.id === S.scenarioName)].map((s) => h('option', { value: s.id, selected: s.id === S.sensBase }, s.id + ' · ' + s.title)));
  const title = (S.scenarios.find((s) => s.id === S.sensBase) || {}).title || S.sensBase;
  put(m, sheetHead('sensitivity — one flip per row', 'base ' + S.sensBase + ' · ' + title),
    hd2('sens-h', 'Sensitivity · ' + title, 'One row per StackSense addition, flipped alone on ' + S.sensBase + '.', 'Hazard yellow on the little body marks the parts that moved.', sel),
    h('div', { class: 'panel scrollx' }, h('table', { class: 'sens resp' }, h('thead', {}, h('tr', {}, h('th', { style: 'width:36px' }, h('span', { class: 'sr' }, 'parts')), h('th', {}, 'answer'), h('th', {}, 'flip'), h('th', {}, 'parts that moved'), h('th', {}, 'warnings'), h('th', {}, 'USD / month'))), tbody)),
    foot, sheetFoot('Sensitivity · parts that moved'));
  const r = S.sens && S.sens.scenario_id === S.sensBase ? { ok: true, data: S.sens } : await api('/api/sensitivity?base=' + encodeURIComponent(S.sensBase));
  if (!r.ok || !r.data) { tbody.replaceChildren(h('tr', {}, h('td', { colspan: '6', class: 'err-text' }, (r.data && r.data.error) || 'Could not load the table.'))); return; }
  S.sens = r.data;
  const rows = r.data.rows || [];
  tbody.replaceChildren(...rows.map((x) => {
    const moved = [...new Set((x.changed_layers || []).map(LAYER_PART))];
    const what = (x.changed_layers || []).map((l) => l.replace(/^supporting\./, '').replace(/^other\./, '').replace(/_/g, '/'));
    const wl = [...(x.warnings_added || []).map((c) => '+' + c), ...(x.warnings_removed || []).map((c) => '−' + c)];
    const costCh = x.cost_from && x.cost_to && (x.cost_from.min !== x.cost_to.min || x.cost_from.max !== x.cost_to.max);
    return h('tr', {},
      h('td', { html: FB.glyph(moved) }),
      h('td', {}, h('code', {}, x.field)),
      h('td', { class: 'mono' }, (x.from == null ? 'absent' : fmtVal(x.from)) + ' → ' + fmtVal(x.to)),
      h('td', {}, moved.length ? [moved.map((p) => h('span', { class: 'chip hz' }, p === 'bolt' ? 'bolt-ons' : p)), ' ', h('span', { class: 'why', style: 'display:inline' }, what.join(', '))] : h('span', { class: 'none' }, 'nothing moved')),
      h('td', { class: 'mono' + (wl.length ? '' : ' none') }, wl.length ? wl.join(' ') : 'none'),
      h('td', { class: 'mono tnum' }, band(x.cost_from) + (costCh ? ' → ' + band(x.cost_to) : '')));
  }));
  foot.replaceChildren('live from ', h('code', {}, '/api/sensitivity?base=' + S.sensBase), ' · base USD ' + band(r.data.cost) + ', ' + words(r.data.status || ''));
}

// ---------------------------------------------------------------- parts catalogue
const GROUPS = [
  { key: 'visor', label: 'Visor', layers: ['frontend_web', 'frontend_mobile', 'frontend_desktop', 'frontend_game'], sub: 'frontend' },
  { key: 'spine', label: 'Spine', layers: ['backend'], sub: 'backend' },
  { key: 'core', label: 'Core', layers: ['database'], sub: 'database' },
  { key: 'cradle', label: 'Cradle', layers: ['hosting'], sub: 'hosting' },
  { key: 'bolt', label: 'Bolt-ons', layers: null, sub: 'supporting services' },
];
const groupOf = (layer) => (GROUPS.find((g) => g.layers && g.layers.includes(layer)) || GROUPS[4]);
async function viewKb() {
  const m = main();
  put(m, sheetHead('parts catalogue — knowledge base', 'kb ' + ((S.health || {}).kb_version || '')), h('p', { class: 'loading', id: 'kb-load', role: 'status' }, 'Loading the catalogue'));
  const kb = await ensureKb();
  await ensureSources();
  if (!kb) { m.replaceChildren(h('p', { class: 'err-text' }, 'The knowledge base could not be loaded.')); return; }
  $('#kb-load') && $('#kb-load').remove();
  const st = kb.stats || {};
  const mpl = st.maintained_per_layer || {};
  const count = (g) => (g.layers ? g.layers.reduce((a, l) => a + (mpl[l] || 0), 0) : Object.keys(mpl).filter((l) => !GROUPS.some((x) => x.layers && x.layers.includes(l))).reduce((a, l) => a + mpl[l], 0));
  const F = S.kbFilter;
  const cutFor = new Map();
  if (S.result) Object.values(traceLayers(S.result)).forEach((L) => (L.rejected || []).forEach((r) => cutFor.set(r.tech_id, r)));
  const seg = h('div', { class: 'seg kbseg', role: 'group', 'aria-label': 'Layer' }, h('span', { class: 'thumb' }), GROUPS.map((g) => h('button', { type: 'button', 'aria-pressed': F.group === g.key ? 'true' : 'false', onclick: () => { F.group = g.key; S.kbSel = null; paint(); } }, g.label + ' ' + count(g))));
  const q = h('input', { class: 'inp', id: 'kb-q', type: 'search', value: F.q, placeholder: 'search by name', oninput: (e) => { F.q = e.target.value; paint(); } });
  const stSel = h('select', { class: 'inp', id: 'kb-status', onchange: (e) => { F.status = e.target.value; paint(); } }, h('option', { value: '' }, 'every status'), [...new Set(kb.records.map((r) => r.status))].sort().map((s) => h('option', { value: s, selected: F.status === s }, words(s))));
  const shelfH = h('h3', {}); const cards = h('div', { class: 'cards', id: 'shelf1' });
  const detail = h('div', { id: 'kb-detail', 'aria-live': 'polite' });
  const retired = kb.records.filter((r) => r.status !== 'maintained');
  const ico = (r) => { const g = groupOf(r.layer); return g.key === 'bolt' ? FB.closeup('bolt', { kind: boltKind(r.layer, r.layer) }) : FB.closeup(g.key, { gauge: { low: 30, high: 60, budget: 45 } }); };
  const regs = (r) => ['india', 'eu', 'us'].filter((k) => (r.regions[k] || []).length).map((k) => (k === 'india' ? 'India' : k.toUpperCase()) + ' ' + r.regions[k].slice(0, 2).join(', ') + (r.regions[k].length > 2 ? ' …' : '')).join('; ') || (r.self_hostable ? 'wherever you host it' : 'none listed');
  const card = (r) => {
    const cut = cutFor.get(r.id);
    const tag = r.status !== 'maintained' ? [words(r.status), r.status === 'maintenance_only' ? 'hz' : 'steel'] : cut ? [cut.unverified ? 'unverified' : 'cut for ' + (S.result.scenario_id || 'this run'), cut.unverified ? 'hz' : 'crit'] : ['active', ''];
    const att = Object.entries(r.attest || {}).filter(([, v]) => v === 'yes' || v === 'addon').map(([k, v]) => k.replace(/_/g, ' ').toUpperCase() + (v === 'addon' ? ' (add-on)' : ''));
    const src = (r.sources || [])[0] && S.sources.get(r.sources[0]);
    const dl = r.status !== 'maintained'
      ? [['status', words(r.status) + (r.supported_until ? ' · until ' + r.supported_until : '')], ['use instead', (kb.records.find((x) => x.id === r.replaced_by) || {}).name || r.replaced_by || '—']]
      : [['regions', regs(r)], cut ? ['why cut', cut.reason_text] : ['attests', att.join(', ') || 'none listed'], ['self-host', r.self_hostable ? 'yes' : 'no'], r.languages && r.languages.length ? ['languages', r.languages.slice(0, 3).join(', ')] : null].filter(Boolean);
    const open = () => { S.kbSel = r.id; showRec(r); $$('.box2', m).forEach((b) => b.setAttribute('aria-pressed', b.dataset.id === r.id ? 'true' : 'false')); };
    return h('article', { class: 'box2' + (r.status !== 'maintained' && r.status !== 'maintenance_only' ? ' retired' : '') + (cut ? ' cut' : ''), tabindex: '0', role: 'button', 'data-id': r.id, 'aria-pressed': S.kbSel === r.id ? 'true' : 'false', 'aria-label': r.name + ', ' + tag[0] + '. Open details', onclick: open, onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } } },
      h('div', { class: 'ico' }, h('span', { html: ico(r) }), h('span', { class: 'tag ' + tag[1] }, tag[0])),
      h('h4', {}, r.name), h('dl', {}, dl.map(([a, b]) => [h('dt', {}, a), h('dd', {}, b)])),
      src ? h('span', { class: 'src' }, src.url.replace(/^https?:\/\/(www\.)?/, '').slice(0, 48)) : null);
  };
  const showRec = (r) => {
    const rep = r.replaced_by && kb.records.find((x) => x.id === r.replaced_by);
    detail.replaceChildren(h('div', { class: 'panel pad kbd' },
      h('div', { class: 'dname' }, h('div', {}, h('span', { class: 'tag' }, groupOf(r.layer).label + ' · ' + words(r.layer)), h('h3', {}, r.name)), h('button', { class: 'btn g s', type: 'button', onclick: () => { S.kbSel = null; detail.replaceChildren(); } }, 'Close')),
      h('p', { class: 'muted' }, r.kind + ' · status ' + words(r.status) + (r.supported_until ? ' · supported until ' + r.supported_until : '') + ' · ops burden ' + r.ops_burden + '/5 · licence ' + r.licence),
      rep ? h('p', {}, 'Replacement: ', h('button', { class: 'linkbtn', type: 'button', onclick: () => showRec(rep) }, rep.name)) : null,
      h('div', { class: 'cols2' },
        h('div', {}, h('div', { class: 'sect' }, 'strengths'), h('ul', { class: 'tlist' }, (r.strengths || []).map((x) => h('li', {}, x))), h('div', { class: 'sect' }, 'trade-offs'), h('ul', { class: 'tlist' }, (r.tradeoffs || []).map((x) => h('li', {}, x)))),
        h('div', {}, h('div', { class: 'sect' }, 'facts the filters check'), h('ul', { class: 'tlist' }, (r.facts || []).map((f) => h('li', {}, f.text, ' ', h('span', { class: 'chip ghost' }, 'confidence ' + f.confidence)))),
          h('div', { class: 'sect' }, 'regions with data centres'), h('p', { style: 'margin:0' }, regs(r)),
          h('div', { class: 'sect' }, 'compliance attestations'), h('div', { class: 'chips' }, Object.entries(r.attest || {}).map(([k, v]) => h('span', { class: 'chip' + (v === 'yes' ? '' : ' ghost') }, k + ': ' + v))))),
      h('div', { class: 'sect' }, 'sources'), h('ul', { class: 'srcs' }, (r.sources || []).map((k) => { const s = S.sources.get(k); return h('li', {}, s ? [h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, s.title), h('span', { class: 'muted' }, ' · accessed ' + s.accessed)] : k); }))));
    detail.scrollIntoView({ block: 'nearest' });
  };
  const paint = () => {
    $$('button', seg).forEach((b, i) => b.setAttribute('aria-pressed', GROUPS[i].key === F.group ? 'true' : 'false'));
    requestAnimationFrame(() => placeThumb(seg));
    const g = GROUPS.find((x) => x.key === F.group) || GROUPS[1];
    const ql = F.q.toLowerCase();
    const recs = kb.records.filter((r) => groupOf(r.layer) === g && (!F.status || r.status === F.status) && (!ql || (r.name + ' ' + r.id).toLowerCase().includes(ql)))
      .sort((a, b) => (a.status === 'maintained' ? 0 : 1) - (b.status === 'maintained' ? 0 : 1) || (cutFor.has(b.id) ? 1 : 0) - (cutFor.has(a.id) ? 1 : 0) || a.name.localeCompare(b.name));
    const total = kb.records.filter((r) => groupOf(r.layer) === g).length;
    shelfH.replaceChildren(g.label + ' shelf ', h('span', {}, g.sub + ' · ' + recs.length + ' of ' + total + ' shown' + (cutFor.size ? ' · cut for ' + (S.result.scenario_id || 'your run') + ' in red' : '')));
    cards.replaceChildren(...recs.map(card));
  };
  put(m, hd2('kb-h', 'Parts catalogue', 'Every part the bay can fit, the facts it checks and where each fact comes from.', nf.format(st.records) + ' parts, ' + nf.format(st.sources_cited_by_records) + ' cited sources, kb ' + st.kb_version + '.', seg),
    h('div', { class: 'kbtools' }, h('label', { for: 'kb-q', class: 'k' }, 'search'), q, h('label', { for: 'kb-status', class: 'k' }, 'status'), stSel),
    detail,
    h('div', { class: 'shelf' }, shelfH, cards, h('div', { class: 'board' })),
    h('div', { class: 'shelf' }, h('h3', {}, 'Retired or closing ', h('span', {}, retired.length + ' across all layers · the bay warns before fitting these')), h('div', { class: 'cards', id: 'shelf2' }, retired.map(card)), h('div', { class: 'board' })),
    sheetFoot('Parts catalogue · cited facts'));
  paint();
  if (S.kbSel) { const r = kb.records.find((x) => x.id === S.kbSel); if (r) showRec(r); }
}
function placeThumb(seg) { const on = seg.querySelector('[aria-pressed=true]') || seg.querySelector('button'); const th = seg.querySelector('.thumb'); if (!on || !on.offsetWidth || !th) return; th.style.transform = `translateX(${on.offsetLeft}px) scaleX(${on.offsetWidth / 100})`; }
addEventListener('resize', () => $$('.seg').forEach(placeThumb));

// ---------------------------------------------------------------- how it decides
function viewAbout() {
  const m = main(); const hd = S.health || {};
  const res = S.result && S.result.stack ? S.result : S.demo && S.demo.result;
  const sc = S.result && S.result.stack ? S.scenario : S.demo && S.demo.scenario;
  const be = res && res.stack.backend;
  const sco = res ? partScore(res, 'backend') : null;
  const tt = be && traceTop(res, idsOf(be)[0]);
  const cut = tt && (tt.L.rejected || [])[0];
  const drv = ((be && be.driven_by) || []).map((p) => { const v = getp(sc || {}, p); return v === undefined ? null : Array.isArray(v) ? v.join(', ') : String(v); }).filter(Boolean).slice(0, 3);
  const W = 1200, H = 380, BY = 290;
  const crate = (x, y, t, c) => `<g transform="translate(${x} ${y})"><rect x="-30" y="-36" width="60" height="36" fill="${c || C.s1}" stroke="#0B0F14" stroke-width="2.6"/><path d="M-30 -24 H30" stroke="#0B0F14" stroke-width="1.6"/><text x="0" y="-8" text-anchor="middle" ${MONO} font-size="10.5" font-weight="500" fill="#11161D">${esc(String(t).slice(0, 9))}</text></g>`;
  const rollers = [...Array(30)].map((_, i) => `<circle cx="${30 + i * 39}" cy="${BY + 12}" r="9" fill="${C.s3}" stroke="#0B0F14" stroke-width="2"/><circle cx="${30 + i * 39}" cy="${BY + 12}" r="2.5" fill="${C.sh}"/>`).join('');
  const belt = `<rect x="10" y="${BY}" width="${W - 20}" height="24" fill="${C.ink}"/>${rollers}<rect x="10" y="${BY - 6}" width="${W - 20}" height="8" fill="${C.s2}" stroke="#0B0F14" stroke-width="2"/>
    ${[...Array(12)].map((_, i) => `<rect x="${40 + i * 98}" y="${BY + 24}" width="10" height="${H - BY - 24}" fill="var(--girder)"/>`).join('')}<rect x="10" y="${BY + 40}" width="${W - 20}" height="10" fill="url(#fb-hz)" opacity=".9"/>`;
  const hopper = `<path d="M40 70 L200 70 L160 170 L80 170 Z" fill="${C.s2}" stroke="#0B0F14" stroke-width="3"/><path d="M40 70 L200 70 L196 80 L44 80 Z" fill="url(#fb-hz)"/><rect x="100" y="170" width="40" height="60" fill="${C.s3}" stroke="#0B0F14" stroke-width="3"/>
    ${crate(84, 112, drv[0] || 'answer')}${crate(150, 124, drv[1] || 'answer')}${crate(118, 96, drv[2] || 'answer')}`;
  const gate = `<g transform="translate(360 0)"><rect x="-70" y="80" width="18" height="${BY - 80}" fill="${C.s3}" stroke="#0B0F14" stroke-width="3"/><rect x="52" y="80" width="18" height="${BY - 80}" fill="${C.s3}" stroke="#0B0F14" stroke-width="3"/>
    <rect x="-70" y="70" width="140" height="26" fill="url(#fb-hz)" stroke="#0B0F14" stroke-width="3"/><g id="ln-bars">${[-36, -12, 12, 36].map((x) => `<path d="M${x} 96 V${BY - 60}" stroke="${C.s1}" stroke-width="5"/><path d="M${x} 96 V${BY - 60}" stroke="#0B0F14" stroke-width="1.2"/>`).join('')}</g>
    ${cut ? `<path d="M70 ${BY - 10} Q120 ${BY + 10} 140 ${BY + 70}" fill="none" stroke="var(--crit)" stroke-width="3" stroke-dasharray="7 5"/>${crate(160, BY + 62, cut.name, 'var(--crit)')}` : ''}</g>`;
  const s = sco ? sco.total : 0;
  const scale = `<g transform="translate(600 0)"><g id="ln-plat"><rect x="-80" y="${BY - 30}" width="160" height="24" fill="${C.s2}" stroke="#0B0F14" stroke-width="3"/></g><rect x="-10" y="150" width="20" height="${BY - 180}" fill="${C.s3}" stroke="#0B0F14" stroke-width="3"/>
    <g id="ln-gauge" transform="translate(0 120) scale(1.7)">${FB.gauge({ low: 0, high: Math.max(s, 1), budget: s }, {})}</g>${sco ? `<text x="0" y="216" text-anchor="middle" style="font-family:var(--disp)" font-size="22" fill="var(--ink)" stroke="var(--wall)" stroke-width="6" paint-order="stroke" stroke-linejoin="round">${s}</text>` : ''}</g>`;
  const assembler = `<g transform="translate(830 0)"><rect x="-6" y="30" width="20" height="90" fill="${C.s3}" stroke="#0B0F14" stroke-width="3"/><g id="ln-arm"><path d="M4 120 L-40 190 L-14 ${BY - 60}" fill="none" stroke="#0B0F14" stroke-width="16" stroke-linejoin="round"/><path d="M4 120 L-40 190 L-14 ${BY - 60}" fill="none" stroke="${C.s1}" stroke-width="10" stroke-linejoin="round"/>
    <circle cx="4" cy="120" r="12" fill="${C.mu}" stroke="#0B0F14" stroke-width="2.6"/><circle cx="-40" cy="190" r="12" fill="${C.mu}" stroke="#0B0F14" stroke-width="2.6"/>
    <g transform="translate(-14 ${BY - 70}) scale(.32)"><use href="#fbp-visor" transform="translate(-200 -108)"/></g></g></g>`;
  const printer = `<g transform="translate(1060 0)"><rect x="-70" y="140" width="140" height="${BY - 150}" fill="${C.s2}" stroke="#0B0F14" stroke-width="3"/><rect x="-54" y="160" width="108" height="34" fill="${C.ink}"/><circle cx="-36" cy="177" r="5" fill="${C.or}"/>
    <g id="ln-tag"><path d="M-20 ${BY - 60} h96 l10 22 h-96 z" fill="${C.or}" stroke="#0B0F14" stroke-width="2.4"/><text x="34" y="${BY - 44}" text-anchor="middle" ${MONO} font-size="11" font-weight="500" fill="#11161D">driven_by</text></g></g>`;
  const travel = `<g class="crate" id="crate">${crate(80, BY - 6, 'answer')}</g>`;
  const label = 'The bay as a conveyor: answers drop from a hopper' + (cut ? ', pass a hazard gate that cuts ' + cut.name : ', pass the hard-filter gate') + (sco ? ', are weighed on a gauge at ' + s : ', are weighed') + ', assembled, and leave with a driven_by tag.';
  const line = h('div', { class: 'line', id: 'line', html: stageSVG(W, H, `<rect width="${W}" height="${H}" fill="var(--wall)"/>${[0, 1, 2, 3].map((i) => `<path d="M${i * 320} 20 L${i * 320 + 300} ${BY - 20} M${i * 320 + 300} 20 L${i * 320} ${BY - 20}" stroke="var(--girder)" stroke-width="14" opacity=".7"/>`).join('')}${belt}${hopper}${gate}${scale}${assembler}${printer}${travel}<g class="fx"></g>`, label) });
  const runBtn = h('button', { class: 'btn g', id: 'runline', type: 'button' }, 'Run one answer down the line ', h('span', { class: 'arr' }, '→'));
  const stations = h('div', { class: 'stations' },
    h('div', {}, h('span', { class: 'tag steel' }, 'in'), h('b', {}, 'Your answers'), h('p', {}, 'The §3 schema, checked field by field. Wrong types stop here.')),
    h('div', {}, h('span', { class: 'tag crit' }, 'cut'), h('b', {}, 'Hard filters'), h('p', {}, 'Residency, compliance, deployment and an explicit cloud. Unknown facts fail closed.')),
    h('div', {}, h('span', { class: 'tag' }, 'score'), h('b', {}, 'Every survivor'), h('p', {}, '21 score lines per part: your priorities, skill fit, requirement fit, budget, lock-in and 16 more, summed.')),
    h('div', {}, h('span', { class: 'tag' }, 'fit'), h('b', {}, 'Combine'), h('p', {}, 'Parts that work together. The budget is checked against the band, never passed silently.')),
    h('div', {}, h('span', { class: 'tag info' }, 'tag'), h('b', {}, 'Explain'), h('p', {}, 'Reasons are built from the score lines and the filter cuts, not written per scenario.')));
  const tr = S.result && S.result.decision_trace;
  const seenKeys = tr && tr.layers ? [...new Set(Object.values(tr.layers).flatMap((l) => (l.top || []).flatMap((t) => t.contributions.map((c) => c.key))))].sort() : [];
  put(m, sheetHead('how it decides — pipeline', 'deterministic · LLM ' + (hd.llm || 'off')),
    hd2('ab-h', 'How the bay decides', 'No model picks the parts.', 'The same answers always give the same body, down to the byte.', runBtn),
    line, stations,
    h('div', { class: 'cols', style: 'grid-template-columns:1fr 1fr;margin-top:20px' },
      h('div', { class: 'panel pad' }, h('div', { class: 'sect', style: 'margin-top:0' }, 'score lines and their range · weights from scoring.py'),
        h('table', {}, h('tbody', {}, SCORE_RANGES.map(([a, b]) => h('tr', {}, h('td', {}, a), h('td', { class: 'mono', style: 'text-align:right;white-space:nowrap' }, b))),
          h('tr', {}, h('td', { colspan: '2', class: 'muted' }, '14 more lines: ops, scale, reuse, availability, latency, timeline, traffic, workload, geo, data, GDPR, growth, device, security. 21 in all.')))),
        seenKeys.length ? h('div', {}, h('div', { class: 'sect' }, 'score lines used in your last run (' + seenKeys.length + ')'), h('div', { class: 'chips' }, seenKeys.map((k) => h('code', { class: 'chip ghost' }, k))),
          h('p', { class: 'k', style: 'margin-top:10px' }, 'constants: ' + Object.entries(tr.constants || {}).map(([k, v]) => k + ' = ' + v).join(', '))) : h('p', { class: 'muted' }, 'Run a scenario to list the score lines and constants it used.')),
      h('div', { class: 'panel pad' }, h('div', { class: 'sect', style: 'margin-top:0' }, 'promises'),
        h('p', { style: 'margin:0 0 12px' }, 'Hard constraints are never relaxed silently. If one can’t be met you get ', h('b', {}, 'Can’t assemble'), ', or a critical warning that names it.'),
        h('p', { style: 'margin:0 0 12px' }, 'No clock and no randomness: run it twice and the JSON is identical.'),
        h('p', { style: 'margin:0 0 12px' }, 'LLM: ', h('span', { class: 'chip ghost' }, hd.llm || 'off'), ' When on, it may only suggest answers from your description and reword explanations; the chosen stack is identical either way.'),
        h('p', { class: 'k', style: 'margin:0' }, 'engine ' + (hd.engine_version || '') + ' · knowledge base ' + (hd.kb_version || '')))),
    sheetFoot('How it decides · the line'));
  wireLine(runBtn, stations);
}
/* one answer down the line: the crate is the lead; each station reacts on the crate's arrival */
function wireLine(btn, stationsEl) {
  const svg = $('#line svg'), cr = $('#crate'), cards = [...stationsEl.children];
  const bars = $('#ln-bars'), plat = $('#ln-plat'), arm = $('#ln-arm'), tag = $('#ln-tag'), needle = $('#ln-gauge .needle');
  const aB = +$('#ln-gauge .gauge').dataset.budgetAngle;
  const OUT = 'cubic-bezier(.23,1,.32,1)', IO = 'cubic-bezier(.77,0,.175,1)';
  let runId = 0;
  const lit = (i) => cards.forEach((c, j) => c.classList.toggle('lit', j === i));
  const wait = (ms, t) => new Promise((r) => setTimeout(r, ms)).then(() => { if (t !== runId || !svg.isConnected) throw 0; });
  const go2 = (el, kf, o, t) => el.animate(kf, Object.assign({ fill: 'forwards' }, o)).finished.then(() => { if (t !== runId) throw 0; });
  const stopAll = () => [cr, bars, plat, arm, tag, needle].forEach((e) => e && e.getAnimations().forEach((a) => a.cancel()));
  const X = (x) => `translateX(${x}px)`;
  btn.onclick = async () => {
    const t = ++runId; stopAll();
    if (reduce()) { try { for (let i = 0; i < 5; i++) { lit(i); await wait(700, t); } lit(-1); } catch (e) { /* interrupted */ } return; }
    try {
      lit(0); tag.animate([{ opacity: 0 }], { duration: 0, fill: 'forwards' });
      await go2(cr, [{ transform: 'translate(0,-70px)', opacity: 0 }, { transform: 'translate(0,0)', opacity: 1 }], { duration: 320, easing: OUT }, t);
      await wait(60, t);
      bars.animate([{ transform: 'translateY(0)' }, { transform: 'translateY(-14px)' }], { duration: 200, delay: 380, easing: OUT, fill: 'forwards' });
      await go2(cr, [{ transform: X(0) }, { transform: X(280) }], { duration: 560, easing: IO }, t);
      lit(1);
      bars.animate([{ transform: 'translateY(-14px)' }, { transform: 'translateY(0)' }], { duration: 220, delay: 120, easing: IO, fill: 'forwards' });
      await wait(260, t);
      await go2(cr, [{ transform: X(280) }, { transform: X(520) }], { duration: 520, easing: IO }, t);
      lit(2);
      plat.animate([{ transform: 'translateY(0)' }, { transform: 'translateY(4px)', offset: .35 }, { transform: 'translateY(0)' }], { duration: 420, easing: OUT });
      cr.animate([{ transform: X(520) }, { transform: 'translate(520px,4px)', offset: .35 }, { transform: X(520) }], { duration: 420, easing: OUT });
      await go2(needle, [{ transform: 'rotate(-120deg)' }, { transform: `rotate(${aB}deg)` }], { duration: 600, easing: OUT }, t);
      await wait(200, t);
      await go2(cr, [{ transform: X(520) }, { transform: X(750) }], { duration: 480, easing: IO }, t);
      lit(3);
      await go2(arm, [{ transform: 'translateY(0)' }, { transform: 'translateY(18px)' }], { duration: 160, easing: IO }, t);
      FB.fxAt(svg, 830, 250, { n: 12, px: 26, py: 30 });
      await go2(arm, [{ transform: 'translateY(18px)' }, { transform: 'translateY(0)' }], { duration: 220, delay: 120, easing: OUT }, t);
      await go2(cr, [{ transform: X(750), opacity: 1 }, { transform: X(940), opacity: 1, offset: .7 }, { transform: X(980), opacity: 0 }], { duration: 440, easing: IO }, t);
      lit(4);
      await go2(tag, [{ transform: 'translateX(-36px)', opacity: 0 }, { transform: 'translateX(0)', opacity: 1 }], { duration: 280, easing: OUT }, t);
      await wait(900, t);
      cr.getAnimations().forEach((a) => a.cancel());
      cr.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 300, easing: 'ease' });
      lit(-1);
    } catch (e) { /* interrupted by a new run or a screen change */ }
  };
}

boot();
