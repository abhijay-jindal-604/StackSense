'use strict';
/* StackSense UI: plain ES2020, no build step, no network beyond the local API. */

// ---------------------------------------------------------------- helpers
const INR_PER_USD = 88; // fixed display rate; shown to the reader, never part of the JSON
const SEV_ORDER = ['critical', 'warning', 'info'];
const SEV_CLASS = { critical: 'crit', warning: 'warn', info: 'info' };
const SEV_WORD = { critical: 'Critical', warning: 'Warning', info: 'Note' };
const LAYERS = [
  ['frontend', 'Frontend', 'fe', 'client'],
  ['backend', 'Backend', 'be', 'server'],
  ['database', 'Database', 'db', 'data'],
  ['hosting', 'Hosting', 'ho', 'bedrock'],
];
const SEAMS = [
  { after: 'frontend', label: 'Edge and identity', layers: ['cdn', 'auth', 'realtime'] },
  { after: 'backend', label: 'Services between code and data', layers: ['cache', 'queue', 'search', 'storage', 'payments', 'ml', 'other'] },
  { after: 'hosting', label: 'Delivery and operations', layers: ['ci_cd', 'observability'] },
];
const SVG_NS = 'http://www.w3.org/2000/svg';

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') el.className = v;
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
function svg(name) {
  const paths = {
    crit: '<path d="M8.5 2h7L22 8.5v7L15.5 22h-7L2 15.5v-7z" fill="currentColor"/><path d="M12 7v6" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/><circle cx="12" cy="16.6" r="1.4" fill="#fff"/>',
    warn: '<path d="M12 2.5L22.5 21h-21z" fill="currentColor"/><path d="M12 9v5.5" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/><circle cx="12" cy="17.4" r="1.3" fill="#fff"/>',
    info: '<circle cx="12" cy="12" r="10" fill="currentColor"/><path d="M12 11v6" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/><circle cx="12" cy="7.4" r="1.4" fill="#fff"/>',
    ok: '<circle cx="12" cy="12" r="10" fill="currentColor"/><path d="M7 12.5l3.2 3.2L17 9" stroke="#fff" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
  };
  const s = document.createElementNS(SVG_NS, 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true');
  s.innerHTML = paths[name] || paths.info;
  return s;
}
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
async function api(path, opts) {
  const r = await fetch(path, opts);
  const text = await r.text();
  let data = null;
  try { data = JSON.parse(text); } catch (e) { /* not JSON */ }
  return { ok: r.ok, status: r.status, text, data };
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

// ---------------------------------------------------------------- state
const S = {
  health: null, schema: null, fields: [], steps: [], scenarios: [],
  scenario: {}, scenarioName: '', fill: false,
  result: null, raw: null, running: false,
  errMap: {}, valid: null, touched: new Set(), showAll: false,
  sel: 'backend', tab: 'warnings',
  kb: null, sources: null, kbRec: {}, kbSel: null, kbFilter: { layer: '', status: '', q: '' },
  sens: null, whatif: null, flash: null, upload: null,
};
const main = () => document.getElementById('main');

// ---------------------------------------------------------------- boot
async function boot() {
  const q = new URLSearchParams(location.search);
  if (q.get('shot') === '1') document.body.classList.add('shot');
  main().append(h('p', { class: 'loading', role: 'status' }, 'Loading StackSense'));
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
  const sid = q.get('scenario');
  if (sid) await loadScenario(sid, { silent: true });
  if (q.get('stratum')) S.sel = q.get('stratum');
  if (q.get('tab')) S.tab = q.get('tab');
  if (q.get('fill') === '1') S.fill = true;
  if (q.get('run') === '1' && sid) await run({ noNav: true });
  window.addEventListener('hashchange', route);
  route();
}

function renderChrome() {
  const hd = S.health;
  document.getElementById('footer').replaceChildren(
    h('span', {}, 'Engine ', h('code', {}, hd ? hd.engine_version : 'unknown')),
    h('span', {}, 'Knowledge base ', h('code', {}, hd ? hd.kb_version : 'unknown')),
    h('span', {}, 'Deterministic: the same input gives the same output, byte for byte.'),
  );
  document.getElementById('llm-state').textContent = 'LLM wording: ' + (hd ? hd.llm : 'unknown');
}

const NAV = [['#/', 'Start', 'start'], ['#/q/1', 'Questionnaire', 'q'], ['#/review', 'Review', 'review'], ['#/result', 'Result', 'result'], ['#/whatif', 'What-if', 'whatif'], ['#/kb', 'Knowledge base', 'kb'], ['#/about', 'About', 'about']];
function paintNav(cur) {
  document.getElementById('nav').replaceChildren(...NAV.map(([href, label, key]) =>
    h('a', { href, 'aria-current': key === cur ? 'page' : false }, label)));
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
  S.edit = null;
  window.scrollTo(0, 0);
  if (!S.schema) { m.append(h('p', { class: 'err-text' }, 'The API did not answer. Start the server with: python3 -m stacksense serve')); return; }
  paintNav(v === 'start' ? 'start' : v);
  const views = { start: viewStart, q: () => viewQuestion(Number(parts[1]) || 1, q.get('f')), review: viewReview, result: viewResult, whatif: viewWhatIf, kb: viewKb, about: viewAbout };
  (views[v] || viewStart)();
  document.title = 'StackSense: ' + ({ start: 'start', q: 'questionnaire', review: 'review', result: 'result', whatif: 'what-if', kb: 'knowledge base', about: 'about' }[v] || 'start');
}
const go = (hash) => { if (location.hash === hash) route(); else location.hash = hash; };

// ---------------------------------------------------------------- scenarios
async function loadScenario(id, opts) {
  const r = await api('/api/scenarios/' + encodeURIComponent(id));
  if (!r.ok || r.data == null) { S.upload = { error: 'Could not load ' + id + ': ' + ((r.data && r.data.error) || 'unreadable file') }; if (!(opts && opts.silent)) route(); return false; }
  setScenario(r.data, id);
  if (!(opts && opts.silent)) go('#/q/1');
  return true;
}
function setScenario(obj, name) {
  S.scenario = obj; S.scenarioName = name || ''; S.result = null; S.raw = null; S.errMap = {}; S.touched = new Set(); S.showAll = false; S.whatif = null; S.upload = null;
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

// ---------------------------------------------------------------- start screen
function viewStart() {
  const m = main();
  const groups = {};
  for (const s of S.scenarios) (groups[s.category] = groups[s.category] || []).push(s);
  const catName = { public: 'Public scenarios (P1 to P6)', edge: 'Edge library: contradictions, bad input, regulation, sensitivity' };
  const file = h('input', { type: 'file', accept: '.json,application/json', id: 'up-file', class: 'sr', onchange: (e) => readUpload(e.target.files[0]) });
  const drop = h('div', { class: 'drop', id: 'drop' },
    h('p', {}, h('label', { for: 'up-file', class: 'btn small', style: 'cursor:pointer' }, 'Choose a JSON file'), ' or drop one here. A scenario file is a single JSON object with the statement section 3 fields.'),
    S.upload ? h('p', { class: 'err-text', role: 'alert' }, S.upload.error) : null,
    S.upload && S.upload.raw ? h('button', { class: 'btn small', onclick: () => sendRawAnyway() }, 'Send it to the engine anyway') : null);
  ['dragover', 'dragenter'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', (e) => readUpload(e.dataTransfer.files[0]));
  m.append(h('div', { class: 'start' },
    h('div', {},
      h('h1', {}, 'Read your stack like a core sample'),
      h('p', { class: 'lede' }, 'Describe the project once. StackSense returns every layer, from the client down to the hosting bedrock, with the input values that put it there, what it beat, and what it costs.'),
      h('div', { class: 'actions' },
        h('button', { class: 'action', onclick: () => { setScenario({}, ''); go('#/q/1'); } }, h('span', { class: 'n' }, 'A'), h('span', {}, h('strong', {}, 'Start the questionnaire'), h('span', { class: 'd' }, 'Seven short steps; each field says why it is asked.'))),
        h('a', { class: 'action', href: '#scenarios', onclick: (e) => { e.preventDefault(); document.getElementById('scn').scrollIntoView(); document.querySelector('#scn .scn').focus(); }, style: 'text-decoration:none;color:inherit' }, h('span', { class: 'n' }, 'B'), h('span', {}, h('strong', {}, 'Load a public scenario'), h('span', { class: 'd' }, nf.format(S.scenarios.length) + ' scenarios, from the six public briefs to edge cases.'))),
        h('div', { class: 'action', style: 'cursor:default;display:block' }, h('div', { style: 'display:grid;grid-template-columns:auto 1fr;gap:12px' }, h('span', { class: 'n' }, 'C'), h('span', {}, h('strong', {}, 'Upload scenario JSON'), h('span', { class: 'd' }, 'Parse errors appear right here.'))), file, drop))),
    h('div', { id: 'scn' },
      S.scenarios.length ? Object.keys(groups).map((c) =>
        h('section', { class: 'scn-group', 'aria-label': catName[c] || c },
          h('h3', {}, catName[c] || titleCase(c)),
          h('div', { class: 'scn-grid' }, groups[c].map((s) =>
            h('button', { class: 'scn ' + (c === 'public' ? '' : 'edge'), 'aria-pressed': S.scenarioName === s.id ? 'true' : 'false', onclick: () => loadScenario(s.id) },
              h('span', { class: 'id' }, s.id.length > 14 ? s.id.replace(/_/g, ' ') : s.id), h('span', { class: 't' }, s.title === s.id ? 'File without a project name' : s.title)))))) : h('p', { class: 'muted' }, 'No scenario files found.'))));
}
function readUpload(file) {
  if (!file) return;
  const fr = new FileReader();
  fr.onload = () => {
    const text = String(fr.result).replace(/^﻿/, '');
    try {
      const obj = JSON.parse(text);
      S.upload = null; setScenario(obj, file.name.replace(/\.json$/i, '')); go('#/q/1');
    } catch (e) {
      S.upload = { error: 'This file is not valid JSON: ' + e.message, raw: text };
      route();
    }
  };
  fr.readAsText(file);
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

function viewQuestion(n, focusPath) {
  const m = main();
  const step = S.steps.find((s) => s.n === n) || S.steps[0];
  if (!step) return;
  const fields = fieldStep(step.n);
  const groups = [...new Set(fields.map((f) => f.group))];
  m.append(h('div', { class: 'qhead' },
    h('div', {}, h('h2', {}, 'Step ' + step.n + ' of ' + S.steps.length + ': ' + step.name), h('p', { class: 'muted' }, 'Scenario: ' + scenarioTitle() + '. Fields marked required must be filled before the engine can run, or you can let it use documented defaults on the review step.')),
    h('div', { class: 'row' }, h('a', { class: 'btn small', href: '#/review' }, 'Review and run'))));
  m.append(h('div', { class: 'qwrap' },
    h('ol', { class: 'steps', 'aria-label': 'Questionnaire steps' }, S.steps.map((s) =>
      h('li', {}, h('a', { href: '#/q/' + s.n, 'aria-current': s.n === step.n ? 'step' : false }, h('span', { class: 'num' }, s.n), h('span', {}, s.name), h('span', { class: 'dot' }, stepDone(s.n)))))),
    h('div', {},
      groups.map((g) => h('section', { 'aria-label': g }, groups.length > 1 ? h('h3', { style: 'margin:16px 0 8px' }, g) : null, fields.filter((f) => f.group === g).map(fieldRow))),
      h('div', { class: 'qnav' },
        step.n > 1 ? h('a', { class: 'btn', href: '#/q/' + (step.n - 1) }, 'Back') : h('span'),
        step.n < S.steps.length ? h('a', { class: 'btn primary', href: '#/q/' + (step.n + 1) }, 'Next: ' + S.steps[S.steps.findIndex((s) => s.n === step.n) + 1].name) : h('a', { class: 'btn primary', href: '#/review' }, 'Review')),
      draftDrawer())));
  paintFieldMessages();
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
  return h('div', { class: 'field', 'data-path': f.path },
    h('div', { class: 'ctl' },
      h('div', { class: 'flabel' }, h('label', { for: id }, f.label), f.required ? h('span', { class: 'tag req' }, 'required') : null, f.extra ? h('span', { class: 'tag extra' }, 'StackSense addition') : null),
      h('div', { class: 'fpath' }, f.path),
      h('div', { style: 'margin-top:8px' }, ctl),
      h('div', { class: 'fmsg hint', 'data-hint': f.path }),
      h('div', { class: 'fmsg err-text', 'data-err': f.path, role: 'alert' })),
    h('div', { class: 'why' }, h('strong', {}, 'Why we ask'), f.why || 'Not used by the engine.',
      f.default != null ? h('div', { style: 'margin-top:8px' }, 'If left blank: ' + fmtVal(f.default) + (f.unit ? ' ' + f.unit : '')) : null,
      f.affects && f.affects.length ? h('div', { style: 'margin-top:8px' }, h('strong', {}, 'Affects'), h('ul', { class: 'chips' }, f.affects.map((a) => h('li', { class: 'chip' }, a)))) : null));
}

function commit(f, val, blank) {
  const tgt = S.edit || S.scenario;
  if (blank) delp(tgt, f.path); else setp(tgt, f.path, val);
  if (S.edit) return;
  S.touched.add(f.path);
  S.result = null; S.raw = null;
  scheduleValidate();
  paintDraft();
  paintHint(f);
}
function opt(name, value, label, checked, onchange, sub, labelId) {
  const id = name + '-' + String(value).replace(/\W/g, '_');
  return h('label', { class: 'opt', for: id }, h('input', { type: 'radio', name, id, value, checked, onchange }), h('span', {}, label, sub ? h('small', { class: 'sub' }, sub) : null));
}
function control(f, id, cur) {
  const name = id + '-r';
  const clear = h('button', { class: 'btn small', type: 'button', style: 'margin-top:8px', onclick: () => { commit(f, null, true); viewQuestionRefresh(); } }, 'Clear (use default)');
  if (f.type === 'boolean') {
    const mk = (v, l) => opt(name, String(v), l, cur === v, () => commit(f, v));
    return h('div', { class: 'opts', role: 'radiogroup', 'aria-label': f.label, id }, mk(true, 'Yes'), mk(false, 'No'), h('button', { class: 'btn small', type: 'button', onclick: () => { commit(f, null, true); viewQuestionRefresh(); } }, 'Not set'));
  }
  if (f.type === 'enum') {
    if (f.enum.length <= 5) {
      return h('div', {}, h('div', { class: 'opts', role: 'radiogroup', 'aria-label': f.label, id },
        f.enum.map((v) => opt(name, v, f.path === 'requirements.availability' ? v + '%' : words(v), cur === v, () => { commit(f, v); paintAvail(f); }, f.path === 'requirements.availability' ? AVAIL_DOWNTIME(v).replace(' of downtime a month', ' a month') : null))),
        f.required ? null : clear);
    }
    return h('select', { class: 'in', id, onchange: (e) => commit(f, e.target.value, e.target.value === '') },
      h('option', { value: '' }, f.required ? 'Choose one' : 'Not set'), f.enum.map((v) => h('option', { value: v, selected: cur === v }, words(v))));
  }
  if (f.type === 'integer' && f.minimum === 1 && f.maximum === 5) {
    const opts = [1, 2, 3, 4, 5].map((v) => opt(name, String(v), String(v), cur === v, () => commit(f, v)));
    return h('div', {}, h('div', { class: 'seg', role: 'radiogroup', 'aria-label': f.label + ', 1 least to 5 most important', id }, opts),
      h('div', { class: 'segscale' }, h('span', {}, '1 least important'), h('span', {}, '5 most important')), clear);
  }
  if (f.type === 'list' && f.item_enum) {
    const sel = new Set(Array.isArray(cur) ? cur : []);
    return h('div', { class: 'opts', role: 'group', 'aria-label': f.label, id }, f.item_enum.map((v) => {
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
    const inp = h('input', { class: 'in', id, type: 'number', inputmode: f.type === 'integer' ? 'numeric' : 'decimal', min: f.minimum, max: f.maximum, step: f.type === 'integer' ? 1 : 'any', value: cur == null ? '' : cur,
      style: 'max-width:14em', onchange: (e) => { const t = e.target.value.trim(); commit(f, t === '' ? null : Number(t), t === ''); }, onblur: () => S.touched.add(f.path), oninput: (e) => { const t = e.target.value.trim(); if (t === '') commit(f, null, true); else if (!isNaN(Number(t))) commit(f, Number(t)); } });
    return h('div', { class: 'unit-wrap' }, inp, f.unit ? h('span', { class: 'unit' }, f.unit) : null);
  }
  if (f.ui === 'textarea') return h('textarea', { class: 'in', id, rows: 4, oninput: (e) => commit(f, e.target.value, e.target.value === '') }, cur || '');
  return h('input', { class: 'in', id, type: 'text', value: cur == null ? '' : cur, oninput: (e) => commit(f, e.target.value, e.target.value === '') });
}
function viewQuestionRefresh() { if (S.edit) { if (S.repaint) S.repaint(); return; } const { parts, q } = parseHash(); main().replaceChildren(); viewQuestion(Number(parts[1]) || 1, q.get('f')); }

function tagInput(f, id, arr) {
  const box = h('div', { class: 'tags' });
  const listId = 'dl-' + id;
  const input = h('input', { id, type: 'text', list: listId, 'aria-label': f.label + ': type a value and press Enter', autocomplete: 'off' });
  const dl = h('datalist', { id: listId }, hintsFor(f).map((v) => h('option', { value: v })));
  const sync = () => commit(f, arr.slice(), arr.length === 0);
  const paint = () => {
    box.replaceChildren(...arr.map((v, i) => h('span', { class: 'tag-x' }, v, h('button', { type: 'button', 'aria-label': 'Remove ' + v, onclick: () => { arr.splice(i, 1); paint(); sync(); input.focus(); } }, '×'))), input, dl);
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
async function ensureKbForHints() {
  if (S.kb) return;
  await ensureKb();
  document.querySelectorAll('datalist').forEach((dl) => {
    const f = S.fields.find((x) => 'dl-f-' + x.path.replace(/\./g, '-') === dl.id);
    if (f) dl.replaceChildren(...hintsFor(f).map((v) => h('option', { value: v })));
  });
}
function paintAvail() { paintHint(S.fields.find((x) => x.path === 'requirements.availability')); }

function clientHint(f) {
  const v = getp(S.scenario, f.path); const sc = S.scenario;
  if (f.path === 'requirements.availability' && v != null) return AVAIL_DOWNTIME(v) ? 'At ' + v + '% that allows ' + AVAIL_DOWNTIME(v) + '.' : '';
  if (f.path === 'scale.users_12_months' && v != null && getp(sc, 'scale.users_at_launch') > v) return 'Users after 12 months is lower than users at launch. Is that intended?';
  if (f.path === 'scale.peak_concurrent_users' && v != null && getp(sc, 'scale.users_12_months') < v) return 'Peak concurrent users cannot exceed total users.';
  if (f.path === 'timeline.mvp_weeks' && v != null && v < 4) return 'Under 4 weeks leaves very little room for anything but a managed platform.';
  if (f.path === 'budget.monthly_infra_usd' && v === 0) return 'A zero budget limits the engine to free tiers; the result states whether that holds.';
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
  return h('details', { class: 'drawer', id: 'draft', open: S.draftOpen ? true : false, ontoggle: (e) => { S.draftOpen = e.target.open; } },
    h('summary', {}, 'Input JSON (the scenario as built so far)'),
    h('div', { class: 'drawer-actions' },
      h('button', { class: 'btn small', onclick: () => download((S.scenarioName || 'scenario') + '.json', JSON.stringify(S.scenario, null, 2) + '\n') }, 'Download input JSON'),
      h('button', { class: 'btn small', onclick: (e) => copyText(JSON.stringify(S.scenario, null, 2), e.target) }, 'Copy')),
    h('pre', { id: 'draft-pre' }, JSON.stringify(S.scenario, null, 2)));
}

// ---------------------------------------------------------------- review
function viewReview() {
  const m = main();
  m.append(h('div', { class: 'qhead' }, h('div', {}, h('h2', {}, 'Review: ' + scenarioTitle()), h('p', { class: 'muted' }, 'This is exactly what the engine will receive.'))));
  S.showAll = true;
  const rows = [];
  const walk = (o, pre) => { if (!isObj(o)) return; Object.keys(o).forEach((k) => { const p = pre ? pre + '.' + k : k; if (isObj(o[k]) && !S.fields.some((f) => f.path === p)) walk(o[k], p); else rows.push([p, o[k]]); }); };
  if (isObj(S.scenario)) walk(S.scenario, '');
  const known = (p) => S.fields.find((f) => f.path === p);
  m.append(h('div', { class: 'panel' },
    h('h3', {}, 'Input values (' + rows.length + ')'),
    rows.length ? h('div', { class: 'kbscroll' }, h('table', { class: 'rtable' }, h('thead', {}, h('tr', {}, h('th', {}, 'Field'), h('th', {}, 'Value'), h('th', {}, 'Step'))),
      h('tbody', {}, rows.map(([p, v]) => h('tr', {}, h('td', { class: 'p' }, p), h('td', {}, fmtVal(v), known(p) ? null : h('span', { class: 'tag', style: 'margin-left:8px' }, 'not in schema')),
        h('td', {}, known(p) ? h('a', { href: '#/q/' + known(p).step + '?f=' + p }, 'Step ' + known(p).step) : '')))))) : h('p', { class: 'muted' }, 'Nothing has been entered yet.')));
  const holder = h('div', { id: 'review-errors' });
  m.append(holder);
  m.append(h('div', { class: 'panel' },
    h('label', { class: 'togg' }, h('input', { type: 'checkbox', checked: S.fill, onchange: (e) => { S.fill = e.target.checked; } }),
      h('span', {}, h('strong', {}, 'Fill missing required fields with documented defaults'), h('br'), h('span', { class: 'muted' }, 'The engine lists every default it used under Assumptions. Leave this off to see exactly which fields are missing.'))),
    h('div', { class: 'row', style: 'margin-top:16px' }, h('button', { class: 'btn primary', id: 'run-btn', onclick: () => run() }, 'Run the engine'), h('a', { class: 'btn', href: '#/q/1' }, 'Edit answers'))));
  m.append(draftDrawer());
  scheduleValidate(0);
  if (S.valid) viewReviewErrors(holder);
}
function viewReviewErrors(holder) {
  const v = S.valid; if (!v) return;
  holder.replaceChildren(
    h('div', { class: 'panel' }, h('h3', {}, 'Validation: ' + (v.errors.length ? v.errors.length + ' problem' + (v.errors.length > 1 ? 's' : '') : 'no problems')),
      v.errors.length ? errorList(v.errors) : h('p', {}, 'Every field passes the same checks the engine applies.'),
      v.notices && v.notices.length ? h('div', {}, h('h4', { style: 'margin-top:16px' }, 'Notices'), h('ul', { class: 'alist' }, v.notices.map((n) => h('li', {}, noteText(n))))) : null));
}
const noteText = (n) => (typeof n === 'string' ? n : n && (n.message || n.text) ? (n.field ? n.field + ': ' : '') + (n.message || n.text) : JSON.stringify(n));

function allowed(f) {
  if (!f) return '';
  if (f.enum) return 'Allowed values: ' + f.enum.join(', ');
  if (f.item_enum) return 'Allowed values (any number of): ' + f.item_enum.join(', ');
  const b = [];
  if (f.minimum != null) b.push((f.exclusive_min ? 'greater than ' : 'at least ') + f.minimum);
  if (f.maximum != null) b.push('at most ' + f.maximum);
  return b.length ? 'Allowed: ' + f.type + ', ' + b.join(' and ') : 'Expected type: ' + f.type;
}
function errorList(errs) {
  return h('ul', { class: 'alist', style: 'list-style:none;padding:0' }, errs.map((e) => {
    const key = String(e.field).replace(/\[.*$/, '');
    const f = S.fields.find((x) => x.path === key);
    const val = e.field === '$' ? undefined : getp(isObj(S.scenario) ? S.scenario : {}, key);
    return h('li', { class: 'wi crit' }, svg('crit'),
      h('div', {}, h('div', { class: 'wt' }, f ? f.label + ' ' : '', h('code', {}, e.field)), h('div', { class: 'wm' }, e.message),
        h('div', { class: 'muted' }, e.field === '$' ? 'The input is not a JSON object.' : 'You entered: ' + (val === undefined ? 'nothing (missing)' : fmtVal(val)) + (allowed(f) ? '. ' + allowed(f) + '.' : '')),
        f ? h('a', { href: '#/q/' + f.step + '?f=' + f.path }, 'Open this field') : null));
  }));
}

// ---------------------------------------------------------------- run
async function run(opts) {
  S.running = true;
  const btn = document.getElementById('run-btn'); if (btn) { btn.disabled = true; btn.textContent = 'Running'; }
  const r = await post('/api/recommend', { scenario: S.scenario, fill_defaults: S.fill, llm: false });
  S.running = false;
  if (!r.ok || !r.data) {
    main().replaceChildren(h('div', { class: 'banner crit', role: 'alert' }, svg('crit'), h('div', {}, h('h2', {}, 'The engine could not be reached'), h('p', {}, (r.data && r.data.error) || 'HTTP ' + r.status))));
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
  return st[sel] || null;
}

// ---------------------------------------------------------------- result
function statusInfo(res) {
  const s = res.status;
  if (s === 'ok') return { cls: 'ok', icon: 'ok', head: 'A stack fits this project' };
  if (s === 'ok_with_warnings') return { cls: 'warn', icon: 'warn', head: 'A stack fits, with warnings you should read' };
  if (s === 'invalid_input') return { cls: 'crit', icon: 'crit', head: 'The input could not be used' };
  return { cls: 'crit', icon: 'crit', head: 'No stack satisfies every hard constraint' };
}
function viewResult() {
  const m = main();
  const res = S.result;
  if (!res) {
    m.append(h('div', { class: 'panel' }, h('h2', {}, 'No result yet'), h('p', {}, 'Load a scenario or fill the questionnaire, then run the engine.'), h('div', { class: 'row' }, h('a', { class: 'btn primary', href: '#/' }, 'Pick a scenario'), S.scenarioName || Object.keys(S.scenario || {}).length ? h('button', { class: 'btn', onclick: () => run() }, 'Run ' + scenarioTitle()) : null)));
    return;
  }
  const si = statusInfo(res);
  m.append(h('div', { class: 'banner ' + si.cls, role: 'status' }, svg(si.icon), h('div', {},
    h('h2', {}, si.head), h('p', {}, res.summary), h('p', { class: 'muted' }, 'Scenario ', h('b', {}, scenarioTitle()), res.scenario_id ? ' (' + res.scenario_id + ')' : '', ' · status ', h('code', {}, res.status), res.llm_used ? ' · LLM wording used' : ' · no LLM wording'))));
  if (res.status === 'invalid_input') return viewInvalid(res);
  if (!res.stack) return viewInfeasible(res);

  const cost = res.estimated_monthly_cost_usd, bv = res.budget_verdict;
  const arch = res.decision_trace && res.decision_trace.architecture;
  m.append(h('div', { class: 'meta-line' },
    h('div', {}, h('span', { class: 'k' }, 'Architecture style'), h('span', { class: 'v' }, titleCase(res.architecture_style))),
    cost ? h('div', {}, h('span', { class: 'k' }, 'Cost band, per month'), h('span', { class: 'v' }, 'USD ' + nf.format(cost.min) + ' to ' + nf.format(cost.max))) : null,
    bv ? h('div', {}, h('span', { class: 'k' }, 'Against budget'), h('span', { class: 'v ' + (/exceed|over/.test(bv.verdict) ? 'sev-crit' : bv.verdict === 'tight' ? 'sev-warn' : 'sev-ok') }, titleCase(bv.verdict) + ' (USD ' + nf.format(bv.budget_usd) + ')')) : null,
    h('div', {}, h('span', { class: 'k' }, 'Warnings'), h('span', { class: 'v' }, String((res.warnings || []).length)))));
  if (arch && arch.reason) m.append(h('p', { class: 'muted', style: 'max-width:80ch' }, 'Why this architecture style: ', arch.reason));
  if (res.relaxed_constraints && res.relaxed_constraints.length) m.append(relaxedPanel(res));

  m.append(h('div', { class: 'res' },
    h('div', {}, coreColumn(res, S.sel, selectStratum), legend()),
    h('div', {}, h('div', { class: 'detail', id: 'detail', 'aria-live': 'polite' }), costPanel(res), tabsBlock(res))));
  paintDetail();
}
function relaxedPanel(res) {
  return h('div', { class: 'panel', style: 'border-left:6px solid var(--sev-warn)' }, h('h3', {}, 'Constraints the engine relaxed'),
    h('p', { class: 'muted' }, 'A requirement could not be met exactly, so it was loosened and the stack below reflects that. Nothing was relaxed silently.'),
    h('ul', { class: 'alist' }, res.relaxed_constraints.map((r) => h('li', {}, noteText(r)))));
}
function legend() {
  return h('div', { class: 'legend' }, LAYERS.map(([, name, cls]) => h('span', {}, h('i', { style: 'background:var(--l-' + cls + ')' }), name)), h('span', {}, h('i', { style: 'background:var(--l-su)' }), 'Supporting services'));
}
function selectStratum(key) {
  S.sel = key;
  document.querySelectorAll('[data-sel]').forEach((b) => b.setAttribute('aria-pressed', b.dataset.sel === key ? 'true' : 'false'));
  paintDetail();
}
function supportingByLayer(st) {
  const idx = {};
  (st.supporting || []).forEach((s, i) => { (idx[s.layer] = idx[s.layer] || []).push([s, i]); });
  return idx;
}
function coreColumn(res, sel, onSelect, changed) {
  const st = res.stack; const sup = supportingByLayer(st);
  const known = new Set(SEAMS.flatMap((s) => s.layers));
  const parts = [];
  LAYERS.forEach(([key, name, cls, depth]) => {
    const it = st[key];
    parts.push(h('div', { class: 'sw' }, h('span', { class: 'depth', style: 'top:10px' }, depth),
      h('button', { class: 'band ' + cls + (changed && changed.has(key) ? ' changed' : ''), 'data-sel': key, 'aria-pressed': sel === key ? 'true' : 'false', onclick: () => onSelect && onSelect(key) },
        h('span', { class: 'ln' }, name), h('span', { class: 'ch' }, it ? it.choice : 'Nothing needed'))));
    SEAMS.filter((s) => s.after === key).forEach((seam) => {
      const items = Object.keys(sup).filter((l) => seam.layers.includes(l) || (seam.layers.includes('other') && !known.has(l))).flatMap((l) => sup[l]).sort((a, b) => a[1] - b[1]);
      parts.push(h('div', { class: 'seam' + (items.length ? '' : ' empty') }, h('span', { class: 'sl' }, seam.label),
        h('div', { class: 'chips' }, items.map(([s, i]) => h('button', { class: 'chip', 'data-sel': 'sup:' + i, 'aria-pressed': sel === 'sup:' + i ? 'true' : 'false', title: s.choice, onclick: () => onSelect && onSelect('sup:' + i) },
          h('span', { class: 'sl2' }, words(s.slot.replace(/^other\./, '')) + ':'), ' ' + shortName(s.choice))))));
    });
  });
  return h('div', { class: 'core', role: 'group', 'aria-label': 'Stack strata, top is the client, bottom is the hosting' }, parts);
}
const shortName = (s) => (String(s).length > 34 ? String(s).slice(0, 32).replace(/\s+\S*$/, '') + '…' : s);

// ---- detail
function chipFor(path) {
  const f = S.fields.find((x) => x.path === path);
  const v = getp(isObj(S.scenario) ? S.scenario : {}, path);
  const label = h('span', {}, h('b', {}, path), v === undefined ? ' (default)' : ' = ' + (Array.isArray(v) ? v.join(', ') : fmtVal(v)));
  return f ? h('a', { class: 'chip', href: '#/q/' + f.step + '?f=' + path, title: 'Open this input' }, label) : h('span', { class: 'chip' }, label);
}
function traceTop(res, id) {
  const L = res.decision_trace && res.decision_trace.layers; if (!L) return null;
  for (const k of Object.keys(L)) { const t = (L[k].top || []).find((x) => x.id === id); if (t) return t; }
  return null;
}
function traceRejected(res, name) {
  const L = res.decision_trace && res.decision_trace.layers; if (!L) return null;
  for (const k of Object.keys(L)) { const t = (L[k].rejected || []).find((x) => x.name === name || x.tech_id === name); if (t) return t; }
  return null;
}
function paintDetail() {
  const box = document.getElementById('detail'); if (!box) return;
  const res = S.result; const it = selItem(S.sel, res);
  if (!it) { box.replaceChildren(h('p', {}, 'Select a layer.')); return; }
  const isSup = S.sel.startsWith('sup:');
  const layerName = isSup ? 'Supporting service: ' + words(it.slot.replace(/^other\./, '')) : (LAYERS.find((l) => l[0] === S.sel) || [0, S.sel])[1];
  const ids = it.kb_ids && it.kb_ids.length ? it.kb_ids : it.kb_id ? [it.kb_id] : [];
  const parts = [
    h('div', { class: 'lyr' }, layerName), h('h2', {}, it.choice),
    h('p', { class: 'just' }, it.justification),
    h('h4', {}, 'Driven by'),
    h('ul', { class: 'chips' }, (it.driven_by || []).map((p) => h('li', {}, chipFor(p)))),
  ];
  if (!(it.driven_by || []).length) parts.push(h('p', { class: 'muted' }, 'No single input drove this choice.'));
  parts.push(h('h4', {}, 'Alternatives considered'));
  if ((it.alternatives || []).length) {
    parts.push(h('ul', { class: 'alts' }, it.alternatives.map((a) => {
      const rej = traceRejected(res, a.choice);
      return h('li', {}, h('span', { class: 'an' }, a.choice), rej ? h('span', { class: 'badge filtered' }, 'Filtered by a hard constraint (' + rej.rule + ')') : null, h('div', {}, a.why_not),
        rej && rej.fields && rej.fields.length ? h('ul', { class: 'chips', style: 'margin-top:4px' }, rej.fields.map((p) => h('li', {}, chipFor(p)))) : null);
    })));
  } else parts.push(h('p', { class: 'muted' }, 'No other candidate survived the filters for this slot.'));
  parts.push(h('h4', {}, 'Trade-offs you accept'));
  parts.push((it.tradeoffs || []).length ? h('ul', { class: 'tlist' }, it.tradeoffs.map((t) => h('li', {}, t))) : h('p', { class: 'muted' }, 'None recorded.'));
  // decision trace
  const trace = h('div', { class: 'bars' });
  let any = false;
  if (isSup) {
    const sel = res.decision_trace && res.decision_trace.supporting && res.decision_trace.supporting.selected && res.decision_trace.supporting.selected.find((x) => x.id === it.kb_id && x.slot === it.slot);
    if (sel && sel.ranked && sel.ranked.length) {
      any = true; const mx = Math.max(...sel.ranked.map((r) => Math.abs(r.total)), 1);
      sel.ranked.forEach((r) => trace.append(barRow(r.id + (r.id === sel.id ? ' (chosen)' : ''), r.total, mx)));
    }
  } else {
    for (const id of ids) {
      const t = traceTop(res, id); if (!t) continue; any = true;
      const mx = Math.max(...t.contributions.map((c) => Math.abs(c.value)), 1);
      if (ids.length > 1) trace.append(h('div', { class: 'muted', style: 'margin-top:6px' }, t.name + ': total ' + t.total));
      t.contributions.forEach((c) => trace.append(barRow(words(c.key), c.value, mx, c.reason)));
    }
  }
  if (any) parts.push(h('h4', {}, 'Score breakdown (decision trace)'), h('p', { class: 'muted' }, isSup ? 'Peer totals for this slot, highest wins.' : 'Contribution of each scoring rule to the winning candidate. Open a row for the reason.'), trace);
  const srcBox = h('div', { id: 'srcs' });
  parts.push(h('h4', {}, 'Sources'), srcBox);
  box.replaceChildren(...parts);
  loadSources(ids, srcBox);
}
function barRow(label, val, mx, reason) {
  const pct = Math.min(100, Math.abs(val) / mx * 100);
  const row = h('div', { class: 'bar' }, h('span', {}, label),
    h('span', { class: 'track' }, h('span', { class: 'fill' + (val < 0 ? ' neg' : ''), style: 'left:0;width:' + pct.toFixed(1) + '%' })),
    h('span', { class: 'val' }, (val > 0 ? '+' : '') + val));
  if (!reason) return row;
  return h('details', {}, h('summary', { style: 'list-style:none;cursor:pointer' }, row), h('div', { class: 'bar-detail' }, reason));
}
async function loadSources(ids, box) {
  if (!ids.length) { box.append(h('p', { class: 'muted' }, 'This component has no knowledge-base record.')); return; }
  if (!S.sources) { const r = await api('/api/sources'); S.sources = new Map((r.data || []).map((s) => [s.key, s])); }
  const keys = new Set();
  for (const id of ids) {
    if (!S.kbRec[id]) { const r = await api('/api/kb/' + id); if (r.ok) S.kbRec[id] = r.data; }
    ((S.kbRec[id] && S.kbRec[id].sources) || []).forEach((k) => keys.add(k));
  }
  if (!box.isConnected) return;
  const list = [...keys].sort();
  box.replaceChildren(list.length ? h('ul', { class: 'srcs' }, list.map((k) => { const s = S.sources.get(k); return h('li', {}, s ? [h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, s.title), ' (accessed ' + s.accessed + ')'] : k); })) : h('p', { class: 'muted' }, 'No sources attached.'));
}

// ---- cost + tabs
function inr(n) { return nfIN.format(Math.round(n * INR_PER_USD)); }
function costPanel(res) {
  const c = res.estimated_monthly_cost_usd, bv = res.budget_verdict; if (!c) return h('span');
  const maxScale = Math.max(c.max * 1.1, bv ? bv.budget_usd * 1.3 : 0, 1);
  const pos = (v) => (Math.min(v, maxScale) / maxScale * 100).toFixed(2) + '%';
  return h('div', { class: 'panel', style: 'margin-top:16px' }, h('h3', {}, 'Cost band and budget'),
    h('div', { class: 'cost-big' }, 'USD ' + nf.format(c.min) + ' to ' + nf.format(c.max) + ' per month'),
    h('p', { class: 'muted' }, 'About INR ' + inr(c.min) + ' to ' + inr(c.max) + ' at a fixed USD 1 = INR ' + INR_PER_USD + ' (display only; the JSON stays in USD).'),
    bv ? h('div', { role: 'img', 'aria-label': 'Cost band from ' + c.min + ' to ' + c.max + ' dollars against a budget of ' + bv.budget_usd, class: 'gauge' },
      h('div', { class: 'band-r', style: 'left:' + pos(c.min) + ';width:calc(' + pos(c.max) + ' - ' + pos(c.min) + ')' }),
      h('div', { class: 'mark' + (bv.budget_usd > maxScale * .7 ? ' r' : ''), style: 'left:' + pos(bv.budget_usd) }, h('span', {}, 'Budget USD ' + nf.format(bv.budget_usd)))) : null,
    bv ? h('p', {}, h('b', {}, 'Verdict: ' + titleCase(bv.verdict) + '. '), budgetSentence(bv)) : null);
}
function budgetSentence(bv) {
  if (/exceed|over/.test(bv.verdict)) return 'Even the low end of the estimate is above the budget; the engine does not hide this.';
  if (bv.verdict === 'tight') return 'The budget covers the low end of the estimate but not necessarily the high end.';
  if (bv.verdict === 'within' || bv.verdict === 'headroom') return 'The whole estimated band sits inside the budget.';
  return '';
}
function tabsBlock(res) {
  const W = res.warnings || [];
  const costLines = (res.decision_trace && res.decision_trace.cost_lines) || [];
  const notes = [...(res.compliance_notes || []).map((n) => ['Compliance', n]), ...(res.integration_notes || []).map((n) => ['Integration', n])];
  const tabs = [
    ['warnings', 'Warnings (' + W.length + ')', () => warningsPane(W)],
    ['assumptions', 'Assumptions (' + (res.assumptions || []).length + ')', () => assumptionsPane(res)],
    ['cost', 'Cost lines (' + costLines.length + ')', () => costPane(res, costLines)],
    ['notes', 'Compliance and integration (' + notes.length + ')', () => notesPane(notes)],
    ['json', 'Raw JSON', () => jsonPane()],
  ];
  if (!tabs.some((t) => t[0] === S.tab)) S.tab = 'warnings';
  const panel = h('div', { class: 'tabpanel', role: 'tabpanel', id: 'tabpanel', tabindex: '0' });
  const list = h('div', { class: 'tablist', role: 'tablist', 'aria-label': 'Result details' });
  const paint = () => {
    list.querySelectorAll('button').forEach((b) => b.setAttribute('aria-selected', b.dataset.tab === S.tab ? 'true' : 'false'));
    panel.replaceChildren(tabs.find((t) => t[0] === S.tab)[2]());
  };
  tabs.forEach(([k, label]) => list.append(h('button', { role: 'tab', 'data-tab': k, id: 'tab-' + k, onclick: () => { S.tab = k; paint(); },
    onkeydown: (e) => { const i = tabs.findIndex((t) => t[0] === S.tab); if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { S.tab = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length][0]; paint(); list.querySelector('[data-tab="' + S.tab + '"]').focus(); } } }, label)));
  const wrap = h('div', { class: 'tabs' }, list, panel);
  paint();
  return wrap;
}
function warningsPane(W) {
  if (!W.length) return h('p', {}, 'The engine raised no warnings.');
  return h('div', {}, SEV_ORDER.map((sev) => {
    const items = W.filter((w) => w.severity === sev); if (!items.length) return null;
    const c = SEV_CLASS[sev];
    return h('section', { class: 'warn-group', 'aria-label': SEV_WORD[sev] }, h('h4', { class: 'sev-' + c }, svg(c), SEV_WORD[sev] + ' (' + items.length + ')'),
      items.map((w) => h('div', { class: 'wi ' + c }, h('span', { class: 'sev-' + c }, svg(c)), h('div', {},
        h('div', { class: 'wt' }, SEV_WORD[sev] + ': ', h('code', {}, w.code)), h('p', { class: 'wm' }, w.message),
        w.fields && w.fields.length ? h('ul', { class: 'chips' }, w.fields.map((p) => h('li', {}, chipFor(p)))) : null))));
  }));
}
function assumptionsPane(res) {
  return h('div', {}, h('p', { class: 'muted' }, 'Everything the engine assumed because you did not say. Nothing here is hidden.'),
    h('ul', { class: 'alist' }, (res.assumptions || []).map((a) => h('li', {}, noteText(a)))),
    res.estimated_monthly_cost_usd && (res.estimated_monthly_cost_usd.assumptions || []).length ? [h('h4', { style: 'margin:16px 0 8px' }, 'Cost assumptions'), h('ul', { class: 'alist' }, res.estimated_monthly_cost_usd.assumptions.map((a) => h('li', {}, a)))] : null);
}
function costPane(res, lines) {
  if (!lines.length) return h('p', {}, 'No per-component cost lines in this response.');
  return h('div', { class: 'kbscroll' }, h('table', { class: 'rtable' }, h('thead', {}, h('tr', {}, ['Slot', 'Component', 'Min USD', 'Max USD', 'Basis'].map((t) => h('th', {}, t)))),
    h('tbody', {}, lines.map((l) => h('tr', {}, h('td', {}, words(l.slot)), h('td', {}, l.name), h('td', {}, nf.format(l.min)), h('td', {}, nf.format(l.max)), h('td', {}, l.basis + (l.derived ? ' (derived)' : '')))))));
}
function notesPane(notes) {
  if (!notes.length) return h('p', {}, 'No compliance or integration notes apply to this input.');
  return h('ul', { class: 'alist' }, notes.map(([k, n]) => h('li', {}, h('span', { class: 'tag' }, k), ' ', noteText(n))));
}
function jsonPane() {
  const name = (S.result.scenario_id || 'scenario') + '_output.json';
  return h('div', {}, h('div', { class: 'row' },
    h('button', { class: 'btn small', onclick: () => download(name, S.raw) }, 'Download ' + name),
    h('button', { class: 'btn small', onclick: (e) => copyText(S.raw, e.target) }, 'Copy'),
    h('span', { class: 'muted' }, 'Exactly the bytes the API returned: ' + nf.format(S.raw.length) + ' characters.')),
    h('pre', { class: 'json-box', tabindex: '0', 'aria-label': 'Raw JSON response', id: 'raw-json' }, S.raw));
}

// ---- invalid / infeasible
function viewInvalid(res) {
  const m = main();
  m.append(h('div', { class: 'panel' }, h('h3', {}, 'Problems found (' + (res.validation_errors || []).length + ')'), h('p', { class: 'muted' }, 'No stack was produced. Each item shows what you entered and what is allowed.'),
    errorList(res.validation_errors || []),
    h('div', { class: 'row', style: 'margin-top:16px' },
      (res.validation_errors || []).some((e) => S.fields.some((f) => f.path === String(e.field).replace(/\[.*$/, ''))) ? h('a', { class: 'btn primary', href: '#/q/' + S.fields.find((f) => f.path === String(res.validation_errors[0].field).replace(/\[.*$/, '')).step }, 'Fix it in the questionnaire') : null,
      h('button', { class: 'btn', onclick: () => { S.fill = true; run({ noNav: true }).then(() => route()); } }, 'Run again, filling missing required fields with documented defaults'))));
  if ((res.assumptions || []).length) m.append(h('div', { class: 'panel' }, h('h3', {}, 'Defaults that would apply'), h('ul', { class: 'alist' }, res.assumptions.map((a) => h('li', {}, noteText(a))))));
  m.append(h('div', { class: 'tabs' }, h('div', { class: 'tablist' }, h('button', { role: 'tab', 'aria-selected': 'true' }, 'Raw JSON')), h('div', { class: 'tabpanel' }, jsonPane())));
}
function viewInfeasible(res) {
  const m = main();
  const crit = (res.warnings || []).filter((w) => w.severity === 'critical');
  m.append(h('div', { class: 'panel' }, h('h3', {}, 'What would make it feasible'),
    (res.nearest_feasible || []).length ? h('ul', { class: 'alist', style: 'list-style:none;padding:0' }, res.nearest_feasible.map((n) => h('li', { class: 'wi info' }, svg('info'),
      h('div', {}, h('div', { class: 'wt' }, isObj(n) ? n.relax || n.field : String(n)), h('p', { class: 'wm' }, isObj(n) ? n.message : ''),
        isObj(n) && n.field && S.fields.find((f) => f.path === n.field) ? h('a', { href: '#/q/' + S.fields.find((f) => f.path === n.field).step + '?f=' + n.field }, 'Open ' + n.field) : null)))) : h('p', {}, 'The engine found no single change that makes this feasible.')));
  if (crit.length) m.append(h('div', { class: 'panel' }, h('h3', {}, 'Critical warnings'), warningsPane(crit)));
  m.append(tabsBlock(res));
}

// ---------------------------------------------------------------- what-if
function viewWhatIf() {
  const m = main();
  m.append(h('div', { class: 'qhead' }, h('div', {}, h('h2', {}, 'What-if'), h('p', { class: 'muted' }, 'Change one input and see which layers move. Both runs use the live engine; the comparison is computed here.'))));
  if (!S.result || !S.result.stack) { m.append(h('div', { class: 'panel' }, h('p', {}, 'Run a scenario with a recommended stack first.'), h('a', { class: 'btn', href: '#/' }, 'Pick a scenario'))); }
  else {
    const w = S.whatif || (S.whatif = { path: S.fields[0].path, scenario: null, result: null });
    const holder = h('div', { id: 'wf-ctl' });
    const out = h('div', { id: 'wf-out' });
    const sel = h('select', { class: 'in', id: 'wf-field', style: 'max-width:28em', onchange: (e) => { w.path = e.target.value; w.result = null; paintCtl(); out.replaceChildren(); } },
      S.fields.map((f) => h('option', { value: f.path, selected: f.path === w.path }, f.label + ' (' + f.path + ')')));
    function paintCtl(keep) {
      const f = S.fields.find((x) => x.path === w.path);
      if (!keep) w.scenario = JSON.parse(JSON.stringify(S.scenario));
      S.edit = w.scenario;
      S.repaint = () => paintCtl(true);
      holder.replaceChildren(h('label', { for: 'wf-in', class: 'muted' }, 'New value'), control(f, 'wf-in', getp(w.scenario, f.path)));
    }
    m.append(h('div', { class: 'panel' }, h('label', { for: 'wf-field', style: 'font-weight:600;display:block;margin-bottom:8px' }, 'Field to change'), sel, h('div', { style: 'margin-top:12px' }, holder),
      h('div', { class: 'row', style: 'margin-top:16px' }, h('button', { class: 'btn primary', onclick: async () => {
        const r = await post('/api/recommend', { scenario: w.scenario, fill_defaults: S.fill, llm: false });
        if (!r.ok || !r.data) { out.replaceChildren(h('p', { class: 'err-text' }, 'The engine could not run this change.')); return; }
        w.result = r.data; out.replaceChildren(diffView(S.result, r.data, w.path, w.scenario));
      } }, 'Run what-if'), h('span', { class: 'muted' }, 'Base: ' + scenarioTitle()))));
    paintCtl();
    m.append(out);
    if (w.result) out.append(diffView(S.result, w.result, w.path, w.scenario));
  }
  const sens = h('div', { class: 'panel' });
  const base = S.scenarioName || (S.result && S.result.scenario_id) || '';
  const paintSens = (body) => sens.replaceChildren(h('h3', {}, 'Sensitivity table'), body);
  paintSens(h('div', {}, h('p', { class: 'muted' }, 'One row per extra field: what changes when a StackSense input is added to the base scenario.'),
    h('button', { class: 'btn small', onclick: async () => {
      const r = await api('/api/sensitivity?base=' + encodeURIComponent(base));
      if (r.status === 501 || r.status === 404) { paintSens(h('p', {}, 'Not available in this build.')); return; }
      if (!r.ok || !r.data) { paintSens(h('p', { class: 'err-text' }, (r.data && r.data.error) || 'Could not load.')); return; }
      const rows = Array.isArray(r.data) ? r.data : r.data.rows || [];
      paintSens(h('table', { class: 'diff-table' }, h('thead', {}, h('tr', {}, ['Field', 'From', 'To', 'Changed layers'].map((t) => h('th', {}, t)))),
        h('tbody', {}, rows.map((x) => h('tr', {}, h('td', {}, x.field), h('td', {}, fmtVal(x.from)), h('td', {}, fmtVal(x.to)), h('td', {}, (x.changed_layers || []).join(', ') || 'none'))))));
    } }, 'Load sensitivity table')));
  m.append(sens);
}
function diffView(a, b, path, scn) {
  const sig = (r, k) => { const it = r.stack && r.stack[k]; return it ? it.choice : '(none)'; };
  const changed = new Set(LAYERS.map((l) => l[0]).filter((k) => sig(a, k) !== sig(b, k)));
  const supSet = (r) => new Set(((r.stack && r.stack.supporting) || []).map((s) => s.slot + '=' + s.choice));
  const sa = supSet(a), sb = supSet(b);
  const supChanged = [...sb].filter((x) => !sa.has(x)).length + [...sa].filter((x) => !sb.has(x)).length;
  const count = (r, sev) => (r.warnings || []).filter((w) => w.severity === sev).length;
  const rows = [['Status', a.status, b.status],
    ['Cost band (USD per month)', a.estimated_monthly_cost_usd ? a.estimated_monthly_cost_usd.min + ' to ' + a.estimated_monthly_cost_usd.max : '-', b.estimated_monthly_cost_usd ? b.estimated_monthly_cost_usd.min + ' to ' + b.estimated_monthly_cost_usd.max : '-'],
    ['Budget verdict', a.budget_verdict ? a.budget_verdict.verdict : '-', b.budget_verdict ? b.budget_verdict.verdict : '-'],
    ['Architecture style', a.architecture_style, b.architecture_style],
    ...SEV_ORDER.map((s) => [SEV_WORD[s] + ' warnings', String(count(a, s)), String(count(b, s))])];
  const col = (r, title, ch) => h('div', { class: 'mini' }, h('h3', {}, title), r.stack ? coreColumn(r, '', null, ch) : h('p', { class: 'muted' }, 'No stack: ' + r.status));
  return h('div', { class: 'stack' }, h('div', { class: 'wf' }, col(a, 'Base: ' + scenarioTitle(), null), col(b, 'What-if: ' + path + ' = ' + fmtVal(getp(scn, path)), changed)),
    h('div', { class: 'panel' }, h('h3', {}, changed.size ? changed.size + ' core layer' + (changed.size > 1 ? 's' : '') + ' changed' + (supChanged ? ' and ' + supChanged + ' supporting-service difference' + (supChanged > 1 ? 's' : '') : '') : supChanged ? 'Core layers unchanged; ' + supChanged + ' supporting-service difference' + (supChanged > 1 ? 's' : '') : 'Nothing in the stack changed'),
      changed.size && b.stack ? h('ul', { class: 'alist' }, [...changed].map((k) => h('li', {}, h('b', {}, titleCase(k) + ': '), sig(a, k) + ' becomes ' + sig(b, k) + '. Driven by ', h('ul', { class: 'chips', style: 'display:inline-flex' }, ((b.stack[k] && b.stack[k].driven_by) || []).map((p) => h('li', {}, h('span', { class: 'chip' }, p))))))) : null,
      h('table', { class: 'diff-table' }, h('thead', {}, h('tr', {}, h('th', {}, 'Measure'), h('th', {}, 'Base'), h('th', {}, 'What-if'))), h('tbody', {}, rows.map(([k, x, y]) => h('tr', {}, h('td', {}, k), h('td', {}, titleCase(x)), h('td', {}, titleCase(y) + (x !== y ? '  (changed)' : ''))))))));
}

// ---------------------------------------------------------------- knowledge base
async function viewKb() {
  const m = main();
  m.append(h('h2', {}, 'Knowledge base'), h('p', { class: 'muted' }, 'Every candidate the engine can choose, with the facts and sources behind the hard filters.'), h('p', { class: 'loading', id: 'kb-load' }, 'Loading the knowledge base'));
  const kb = await ensureKb();
  if (!kb) { m.replaceChildren(h('p', { class: 'err-text' }, 'The knowledge base could not be loaded.')); return; }
  if (!S.sources) { const r = await api('/api/sources'); S.sources = new Map((r.data || []).map((s) => [s.key, s])); }
  document.getElementById('kb-load').remove();
  const layers = [...new Set(kb.records.map((r) => r.layer))].sort();
  const statuses = [...new Set(kb.records.map((r) => r.status))].sort();
  const F = S.kbFilter;
  const tbody = h('tbody'); const detail = h('div', { id: 'kb-detail', 'aria-live': 'polite' }); const count = h('p', { class: 'muted', role: 'status' });
  const paint = () => {
    const q = F.q.toLowerCase();
    const rows = kb.records.filter((r) => (!F.layer || r.layer === F.layer) && (!F.status || r.status === F.status) && (!q || (r.name + ' ' + r.id).toLowerCase().includes(q))).sort((a, b) => a.layer.localeCompare(b.layer) || a.name.localeCompare(b.name));
    count.textContent = rows.length + ' of ' + kb.records.length + ' records';
    tbody.replaceChildren(...rows.map((r) => {
      const retired = r.status !== 'maintained';
      const regs = ['india', 'eu', 'us'].filter((k) => (r.regions[k] || []).length).map((k) => k === 'india' ? 'India' : k.toUpperCase()).join(', ') || 'none listed';
      const open = () => { S.kbSel = r.id; paint(); showRec(r); };
      return h('tr', { tabindex: '0', class: (retired ? 'retired ' : '') + (S.kbSel === r.id ? 'sel' : ''), onclick: open, onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } } },
        h('td', {}, h('span', { class: 'nm' }, r.name), retired && r.replaced_by ? h('div', { class: 'muted' }, 'replaced by ' + r.replaced_by) : null), h('td', {}, words(r.layer)), h('td', {}, retired ? h('b', { class: 'sev-crit' }, words(r.status)) : words(r.status)), h('td', {}, regs), h('td', {}, String(r.ops_burden)));
    }));
  };
  const showRec = (r) => {
    const rep = r.replaced_by && kb.records.find((x) => x.id === r.replaced_by);
    detail.replaceChildren(h('div', { class: 'kbd' }, h('h3', {}, r.name), h('p', { class: 'muted' }, words(r.layer) + ' · ' + r.kind + ' · status ' + words(r.status) + (r.supported_until ? ' · supported until ' + r.supported_until : '')),
      rep ? h('p', {}, 'Replacement: ', h('a', { href: '#', onclick: (e) => { e.preventDefault(); S.kbSel = rep.id; paint(); showRec(rep); } }, rep.name)) : null,
      h('h4', {}, 'Strengths'), h('ul', { class: 'tlist' }, (r.strengths || []).map((x) => h('li', {}, x))),
      h('h4', {}, 'Trade-offs'), h('ul', { class: 'tlist' }, (r.tradeoffs || []).map((x) => h('li', {}, x))),
      h('h4', {}, 'Facts'), h('ul', { class: 'tlist' }, (r.facts || []).map((f) => h('li', {}, f.text, ' ', h('span', { class: 'tag' }, 'confidence ' + f.confidence)))),
      h('h4', {}, 'Compliance attestations'), h('ul', { class: 'chips' }, Object.entries(r.attest || {}).map(([k, v]) => h('li', { class: 'chip' }, k + ': ' + v))),
      h('h4', {}, 'Sources'), h('ul', { class: 'srcs' }, (r.sources || []).map((k) => { const s = S.sources.get(k); return h('li', {}, s ? [h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, s.title), ' (accessed ' + s.accessed + ')'] : k); }))));
    detail.scrollIntoView({ block: 'nearest' });
  };
  const sel = (label, id, opts, key) => h('div', {}, h('label', { for: id }, label), h('select', { class: 'in', id, onchange: (e) => { F[key] = e.target.value; paint(); } }, h('option', { value: '' }, 'All'), opts.map((o) => h('option', { value: o, selected: F[key] === o }, words(o)))));
  m.append(h('div', { class: 'kbwrap' },
    h('div', { class: 'stats' }, h('span', {}, h('b', {}, nf.format(kb.stats.records)), ' records'), h('span', {}, h('b', {}, nf.format(kb.stats.sources_registered)), ' sources registered'), h('span', {}, h('b', {}, (kb.stats.non_maintained || []).length), ' retired or deprecated, shown struck through')),
    h('div', { class: 'kbtools' }, sel('Layer', 'kb-layer', layers, 'layer'), sel('Status', 'kb-status', statuses, 'status'), h('div', {}, h('label', { for: 'kb-q' }, 'Search'), h('input', { class: 'in', id: 'kb-q', type: 'search', value: F.q, oninput: (e) => { F.q = e.target.value; paint(); } }))),
    count,
    h('div', { class: 'kbscroll' }, h('table', { class: 'kbtable' }, h('thead', {}, h('tr', {}, ['Name', 'Layer', 'Status', 'Regions with data centres', 'Ops burden'].map((t) => h('th', {}, t)))), tbody)), detail));
  paint();
  if (S.kbSel) { const r = kb.records.find((x) => x.id === S.kbSel); if (r) showRec(r); }
}

// ---------------------------------------------------------------- about
function viewAbout() {
  const m = main(); const hd = S.health || {};
  const tr = S.result && S.result.decision_trace;
  m.append(h('div', { class: 'about' }, h('h2', {}, 'About'),
    h('h3', {}, 'How a stack is chosen'),
    h('p', {}, 'Hard filters run first: data residency, compliance, deployment model and an explicit cloud preference remove candidates outright, and a fact the knowledge base cannot confirm counts against the candidate. Survivors are scored by weighted rules; the best compatible combination across layers wins. Budget, timeline and priorities are soft: they move scores and the cost verdict, and the budget is never exceeded without saying so.'),
    h('p', {}, 'Every explanation on the result page is generated from those scores and filter reasons. Nothing is written by hand per scenario.'),
    tr && tr.layers ? h('div', {}, h('h4', {}, 'Scoring rules seen in the last run'), h('ul', { class: 'tlist' }, [...new Set(Object.values(tr.layers).flatMap((l) => (l.top || []).flatMap((t) => t.contributions.map((c) => c.key))))].sort().map((k) => h('li', {}, h('code', {}, k)))),
      h('p', { class: 'muted' }, 'Constants: ' + Object.entries(tr.constants || {}).map(([k, v]) => k + ' = ' + v).join(', '))) : h('p', { class: 'muted' }, 'Run a scenario to list the scoring rules and constants it used.'),
    h('h3', {}, 'Determinism'), h('p', {}, 'The same input always produces the same bytes. There is no clock, no randomness and no network call in the recommendation path.'),
    h('h3', {}, 'LLM wording'), h('p', {}, 'The LLM is ' + (hd.llm || 'unknown') + ' in this build. When on, it may only suggest input fields from a description or reword explanations; the chosen stack is identical either way.'),
    h('h3', {}, 'Versions'), h('p', {}, 'Engine ', h('code', {}, hd.engine_version), ', knowledge base ', h('code', {}, hd.kb_version), '.')));
}

boot();
