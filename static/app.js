'use strict';
const $ = (id) => document.getElementById(id);
let active = null;
let busy = false;
async function api(path, token, body) {
  const response = await fetch(path, {method: body ? 'POST' : 'GET', headers: {'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}
async function action(fn) {
  try { $('error').textContent = ''; await fn(); }
  catch (error) { $('error').textContent = error.message; }
}
function credentials() {
  if (!active) throw new Error('请先连接房间');
  return active;
}
async function refresh() {
  if (!active || busy) return;
  busy = true;
  const current = active;
  try {
    const data = await api(`/api/rooms/${encodeURIComponent(current.id)}`, current.token);
    if (current !== active) return;
    $('messages').replaceChildren();
    for (const message of data.messages) {
      const article = document.createElement('article');
      const label = document.createElement('strong');
      label.textContent = `${message.sender} · ${message.source}`;
      const content = document.createElement('p');
      content.textContent = message.body;
      article.append(label, content);
      $('messages').append(article);
    }
    const run = data.runs.at(-1);
    $('status').textContent = run ? `${run.status} · ${run.turn}/${run.budget}` : '已连接 · 等待议题';
    const selected = new Set([...$('targets').selectedOptions].map(o => o.value));
    $('targets').replaceChildren(...data.agents.map(agent => {
      const option = document.createElement('option');
      option.value = agent.id; option.textContent = `${agent.id} · ${agent.kind}`;
      option.selected = selected.has(agent.id); return option;
    }));
  } finally { busy = false; }
}
$('create').onclick = () => action(async () => {
  const room = await api('/api/rooms', $('admin').value, {name: $('name').value});
  $('admin').value = ''; $('room').value = room.id; $('token').value = room.token;
  active = room; await refresh();
});
$('connect').onclick = () => action(async () => {
  active = {id: $('room').value.trim(), token: $('token').value.trim()}; await refresh();
});
$('compose').onsubmit = event => { event.preventDefault(); action(async () => {
  const room = credentials();
  await api(`/api/rooms/${encodeURIComponent(room.id)}/runs`, room.token, {body: $('body').value, targets: [...$('targets').selectedOptions].map(o => o.value), budget: Number($('budget').value), request_id: crypto.randomUUID()});
  $('body').value = ''; await refresh();
}); };
$('stop').onclick = () => action(async () => {
  const room = credentials(); await api(`/api/rooms/${encodeURIComponent(room.id)}/stop`, room.token, {}); await refresh();
});
setInterval(() => action(refresh), 1000);
