const labels = { todo: 'To do', doing: 'In progress', done: 'Done' };

async function api(path, options = {}) {
  const res = await fetch(`/api${path}`, { headers: { 'Content-Type': 'application/json' }, ...options });
  if (!res.ok && res.status !== 204) throw new Error(`${res.status} ${await res.text()}`);
  return res.status === 204 ? null : res.json();
}

function taskItem(task) {
  const li = document.createElement('li');
  const title = document.createElement('span');
  title.className = 'title';
  title.textContent = task.title;
  const actions = document.createElement('div');
  actions.className = 'actions';
  for (const status of Object.keys(labels)) {
    if (status === task.status) continue;
    const b = document.createElement('button');
    b.textContent = `→ ${labels[status]}`;
    b.onclick = () => api(`/tasks/${task.id}`, { method: 'PATCH', body: JSON.stringify({ status }) }).then(load);
    actions.append(b);
  }
  const del = document.createElement('button');
  del.className = 'delete';
  del.textContent = 'Delete';
  del.onclick = () => api(`/tasks/${task.id}`, { method: 'DELETE' }).then(load);
  actions.append(del);
  li.append(title, actions);
  return li;
}

async function load() {
  const tasks = await api('/tasks');
  for (const col of document.querySelectorAll('.column')) {
    const mine = tasks.filter(t => t.status === col.dataset.status);
    col.querySelector('ul').replaceChildren(...mine.map(taskItem));
    col.querySelector('.count').textContent = `(${mine.length})`;
  }
}

async function loadInfo() {
  const footer = document.getElementById('info');
  try {
    const i = await api('/info');
    footer.innerHTML = `Served by backend pod <b>${i.pod}</b> · app version <b>${i.version}</b> · database <b class="ok">${i.database}</b>`;
  } catch (e) {
    footer.textContent = `Backend not reachable: ${e.message}`;
  }
}

document.getElementById('new-task').addEventListener('submit', async (e) => {
  e.preventDefault();
  const input = document.getElementById('title');
  await api('/tasks', { method: 'POST', body: JSON.stringify({ title: input.value }) });
  input.value = '';
  load();
});

load();
loadInfo();
setInterval(loadInfo, 3000);
