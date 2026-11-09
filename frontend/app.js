// DevOps Shack Command Center — frontend logic (no framework, no build step).
const STATUS = { todo: 'To do', doing: 'In progress', review: 'In review', done: 'Done' };
const PRIORITY_ORDER = ['low', 'medium', 'high', 'critical'];
const COLORS = { todo: 'var(--todo)', doing: 'var(--doing)', review: 'var(--review)', done: 'var(--done)',
  critical: 'var(--critical)', high: 'var(--high)', medium: 'var(--medium)', low: 'var(--low)' };
const ICONS = { created: '➕', moved: '➡️', deleted: '🗑️', priority: '🏷️', chaos: '⚡', setup: '🚀' };

let tasks = [];
let lastPod = null;
const podHits = {};

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function api(path, options = {}) {
  const res = await fetch(`/api${path}`, { headers: { 'Content-Type': 'application/json' }, ...options });
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) throw new Error(body?.error || `HTTP ${res.status}`);
  return body;
}

// ---------- toasts, counters, confetti ----------
function toast(message, kind = '') {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = message;
  $('#toasts').append(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 300); }, 3800);
}

function animateCount(el, to) {
  const from = Number(el.dataset.value || 0);
  el.dataset.value = to;
  const start = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - start) / 700);
    el.textContent = Math.round(from + (to - from) * (1 - Math.pow(1 - t, 3)));
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function confetti() {
  const canvas = $('#confetti');
  const ctx = canvas.getContext('2d');
  canvas.width = innerWidth; canvas.height = innerHeight;
  const colors = ['#ff4d00', '#ff8a3d', '#2ee59d', '#4cc9f0', '#ffd23f', '#ffffff'];
  const parts = Array.from({ length: 160 }, () => ({
    x: innerWidth / 2, y: innerHeight / 3, vx: (Math.random() - 0.5) * 16, vy: Math.random() * -14 - 4,
    s: Math.random() * 7 + 4, c: colors[(Math.random() * colors.length) | 0], r: Math.random() * 6, life: 0,
  }));
  const tick = () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    let alive = false;
    for (const p of parts) {
      p.life++; p.vy += 0.38; p.x += p.vx; p.y += p.vy; p.r += 0.1;
      if (p.y < canvas.height + 20 && p.life < 160) alive = true;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r); ctx.fillStyle = p.c;
      ctx.fillRect(-p.s / 2, -p.s / 2, p.s, p.s * 0.6); ctx.restore();
    }
    if (alive) requestAnimationFrame(tick); else ctx.clearRect(0, 0, canvas.width, canvas.height);
  };
  tick();
}

// ---------- board ----------
function initials(name) {
  return name.split(/\s+/).map((p) => p[0]).join('').slice(0, 2).toUpperCase() || '?';
}

function taskCard(t) {
  const el = document.createElement('div');
  el.className = 'task';
  el.draggable = true;
  el.dataset.id = t.id;
  el.dataset.priority = t.priority;
  el.innerHTML = `
    <div class="task-title">${esc(t.title)}</div>
    <div class="task-meta">
      <span class="chip prio ${t.priority}" title="Click to change priority">${t.priority}</span>
      <span class="chip">#${esc(t.tag)}</span>
      <button class="task-del" title="Delete task">✕</button>
      <span class="avatar" title="${esc(t.assignee)}">${esc(initials(t.assignee))}</span>
    </div>`;
  el.addEventListener('dragstart', (e) => { el.classList.add('dragging'); e.dataTransfer.setData('text/plain', t.id); });
  el.addEventListener('dragend', () => el.classList.remove('dragging'));
  el.querySelector('.prio').onclick = () => {
    const next = PRIORITY_ORDER[(PRIORITY_ORDER.indexOf(t.priority) + 1) % PRIORITY_ORDER.length];
    updateTask(t.id, { priority: next }, `Priority set to ${next}`);
  };
  el.querySelector('.task-del').onclick = async () => {
    try { await api(`/tasks/${t.id}`, { method: 'DELETE' }); toast('Task deleted'); refreshAll(); }
    catch (e) { toast(e.message, 'err'); }
  };
  return el;
}

function renderBoard() {
  const q = $('#search').value.trim().toLowerCase();
  const prio = $('#filter-priority').value;
  const visible = tasks.filter((t) => (!prio || t.priority === prio) &&
    (!q || `${t.title} ${t.assignee} ${t.tag}`.toLowerCase().includes(q)));
  for (const col of document.querySelectorAll('.column')) {
    const mine = visible.filter((t) => t.status === col.dataset.status)
      .sort((a, b) => PRIORITY_ORDER.indexOf(b.priority) - PRIORITY_ORDER.indexOf(a.priority));
    col.querySelector('.col-body').replaceChildren(...mine.map(taskCard));
    col.querySelector('.col-count').textContent = mine.length;
  }
}

async function updateTask(id, change, message) {
  try {
    const updated = await api(`/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(change) });
    if (change.status === 'done') { confetti(); toast(`🎉 "${updated.title}" is done!`, 'ok'); }
    else toast(message || 'Task updated', 'ok');
    refreshAll();
  } catch (e) { toast(e.message, 'err'); }
}

for (const col of document.querySelectorAll('.column')) {
  col.addEventListener('dragover', (e) => { e.preventDefault(); col.classList.add('drag-over'); });
  col.addEventListener('dragleave', () => col.classList.remove('drag-over'));
  col.addEventListener('drop', (e) => {
    e.preventDefault(); col.classList.remove('drag-over');
    const id = Number(e.dataTransfer.getData('text/plain'));
    const task = tasks.find((t) => t.id === id);
    if (task && task.status !== col.dataset.status) {
      updateTask(id, { status: col.dataset.status }, `Moved to ${STATUS[col.dataset.status]}`);
    }
  });
}

// ---------- dashboard ----------
function renderBars(container, rows) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  container.innerHTML = rows.map((r) => `
    <div class="bar-row"><span class="bar-label">${esc(r.label)}</span>
      <div class="bar-track"><div class="bar-fill" style="--c:${r.color || 'var(--brand)'}" data-w="${(r.value / max) * 100}"></div></div>
      <span class="bar-num">${r.value}</span></div>`).join('');
  requestAnimationFrame(() => container.querySelectorAll('.bar-fill').forEach((b) => { b.style.width = `${b.dataset.w}%`; }));
}

function renderDonut(byStatus, completion) {
  const total = Object.values(byStatus).reduce((a, b) => a + b, 0) || 1;
  const r = 50; const c = 2 * Math.PI * r;
  let offset = 0;
  $('#donut').innerHTML = `<circle cx="60" cy="60" r="${r}" stroke="var(--panel-2)"></circle>` +
    Object.entries(byStatus).map(([s, v]) => {
      const len = (v / total) * c;
      const seg = `<circle cx="60" cy="60" r="${r}" stroke="${COLORS[s]}" stroke-dasharray="${len} ${c - len}" stroke-dashoffset="${-offset}"></circle>`;
      offset += len;
      return seg;
    }).join('');
  $('#donut-num').textContent = `${completion}%`;
  $('#donut-legend').innerHTML = Object.entries(byStatus).map(([s, v]) => `<span style="--c:${COLORS[s]}">${STATUS[s]} ${v}</span>`).join('');
}

async function loadStats() {
  const s = await api('/stats');
  animateCount($('#kpi-total'), s.total);
  animateCount($('#kpi-doing'), s.by_status.doing + s.by_status.review);
  animateCount($('#kpi-done'), s.by_status.done);
  animateCount($('#kpi-completion'), s.completion);
  $('#kpi-progress').style.width = `${s.completion}%`;
  renderDonut(s.by_status, s.completion);
  renderBars($('#priority-bars'), [...PRIORITY_ORDER].reverse().map((p) => ({ label: p, value: s.by_priority[p], color: COLORS[p] })));
  renderBars($('#assignee-bars'), s.by_assignee.map((a) => ({ label: a.name, value: a.count })));
}

// ---------- platform ----------
function fmtUptime(sec) {
  const h = Math.floor(sec / 3600); const m = Math.floor((sec % 3600) / 60); const s = sec % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m ${s}s` : `${s}s`;
}

async function loadInfo() {
  try {
    const i = await api('/info');
    $('#live-pill').className = 'live-pill ok';
    $('#live-text').textContent = `Live · ${i.version}`;
    $('#kpi-pod').textContent = i.pod;
    $('#p-pod').textContent = i.pod;
    if (i.pod !== lastPod) {
      $('#p-pod').classList.remove('flash'); void $('#p-pod').offsetWidth; $('#p-pod').classList.add('flash');
      lastPod = i.pod;
    }
    $('#p-version').textContent = i.version;
    $('#p-env').textContent = i.environment;
    $('#p-ns').textContent = i.namespace;
    $('#p-node').textContent = i.node;
    $('#p-uptime').textContent = fmtUptime(i.uptime_seconds);
    $('#p-python').textContent = i.python;
    $('#p-db').textContent = i.database;
    $('#p-latency').textContent = i.db_latency_ms != null ? `${i.db_latency_ms} ms` : '—';
    $('#chaos-state').textContent = i.chaos_enabled ? 'Chaos Lab enabled' : 'Chaos Lab disabled';
    $('#chaos-state').className = `badge ${i.chaos_enabled ? 'on' : 'off'}`;
    podHits[i.pod] = (podHits[i.pod] || 0) + 1;
    renderBars($('#traffic-bars'), Object.entries(podHits).map(([pod, n]) => ({ label: pod.split('-').slice(-2).join('-'), value: n })));
    const line = document.createElement('div');
    line.textContent = `${new Date().toLocaleTimeString()}  GET /api/info → ${i.pod}  (db ${i.db_latency_ms ?? '–'} ms)`;
    $('#ticker').prepend(line);
    while ($('#ticker').children.length > 7) $('#ticker').lastChild.remove();
  } catch (e) {
    $('#live-pill').className = 'live-pill bad';
    $('#live-text').textContent = 'Backend unreachable';
    const line = document.createElement('div');
    line.textContent = `${new Date().toLocaleTimeString()}  GET /api/info → error (${e.message})`;
    $('#ticker').prepend(line);
  }
}

document.querySelectorAll('[data-chaos]').forEach((btn) => {
  btn.onclick = async () => {
    const action = btn.dataset.chaos;
    if (action === 'crash' && !confirm('Crash the pod that answers this request? OpenShift will restart it.')) return;
    btn.disabled = true;
    try {
      const r = await api(`/chaos/${action}`, { method: 'POST' });
      toast(`⚡ ${r.message} (pod ${r.pod})`, 'ok');
    } catch (e) { toast(e.message, 'err'); }
    setTimeout(() => { btn.disabled = false; refreshAll(); }, 1500);
  };
});

// ---------- activity ----------
function timeAgo(iso) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

async function loadActivity() {
  const items = await api('/activity');
  $('#timeline').innerHTML = items.map((a) => `
    <li><span class="t-icon">${ICONS[a.action] || '•'}</span>
      <div><div class="t-detail">${esc(a.detail)}</div><div class="t-pod">handled by ${esc(a.pod)}</div></div>
      <span class="t-time">${timeAgo(a.created_at)}</span></li>`).join('');
}

// ---------- wiring ----------
async function loadTasks() { tasks = await api('/tasks'); renderBoard(); }

async function refreshAll() {
  try { await Promise.all([loadTasks(), loadStats(), loadActivity()]); }
  catch (e) { toast(`Could not load data: ${e.message}`, 'err'); }
}

document.querySelectorAll('.tab').forEach((tab) => {
  tab.onclick = () => {
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t === tab));
    document.querySelectorAll('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${tab.dataset.view}`));
    if (tab.dataset.view === 'dashboard') loadStats();
  };
});

$('#search').oninput = renderBoard;
$('#filter-priority').onchange = renderBoard;
$('#open-create').onclick = () => { $('#modal').classList.add('open'); $('#create-form').elements.title.focus(); };
$('#close-create').onclick = () => $('#modal').classList.remove('open');
$('#modal').onclick = (e) => { if (e.target.id === 'modal') $('#modal').classList.remove('open'); };
$('#create-form').onsubmit = async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  try {
    const t = await api('/tasks', { method: 'POST', body: JSON.stringify(data) });
    toast(`Task "${t.title}" created`, 'ok');
    e.target.reset();
    $('#modal').classList.remove('open');
    refreshAll();
  } catch (err) { toast(err.message, 'err'); }
};
$('#theme-toggle').onclick = () => {
  const root = document.documentElement;
  root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
};

refreshAll();
loadInfo();
setInterval(loadInfo, 2000);
setInterval(refreshAll, 10000);
