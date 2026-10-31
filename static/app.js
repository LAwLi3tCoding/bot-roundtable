'use strict';
const $ = id => document.getElementById(id);
let language = localStorage.getItem('roundtable-language') || (navigator.language.startsWith('zh') ? 'zh' : 'en');
if (!I18N[language]) language = 'en';
const t = key => I18N[language][key] || key;
let adminToken = '', active = null, rooms = [], bots = [], state = null, selected = new Set(), threadId = '', refreshing = false, refreshGeneration = 0, leadContext = null;
const roomTokens = new Map();
const roomPreviews = new Map();
function element(tag, className, value) { const node = document.createElement(tag); if (className) node.className = className; if (value !== undefined) node.textContent = value; return node; }
function setError(error, dialog) { const target = dialog?.querySelector('.dialog-error') || $('error'); target.textContent = I18N[language].errors[error.message] || (I18N[language][error.message] ? t(error.message) : `${t('requestFailed')} ${error.status ? `(${error.status})` : ''}`); }
async function action(fn, dialog) { $('error').textContent = ''; if(dialog) dialog.querySelectorAll('.dialog-error').forEach(n => n.textContent = ''); try { await fn(); } catch (error) { setError(error, dialog); } }
async function api(path, token, body) {
 let response; try { response = await fetch(path, {method: body !== undefined ? 'POST' : 'GET', headers: {'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json'}, body: body !== undefined ? JSON.stringify(body) : undefined}); } catch { throw new Error('networkError'); }
 const data = await response.json(); if (!response.ok) { const error = new Error(data.error || 'requestFailed'); error.status = response.status; throw error; } return data;
}
function roomPath(suffix = '') { if (!active) throw new Error('needConnection'); return `/api/rooms/${active.id}${suffix}`; }
function roomAuth() { if (!active) throw new Error('needConnection'); return adminToken || roomTokens.get(active.id); }
function requireAdmin() { if (!adminToken) throw new Error('needAdmin'); }
function openDialog(id) { $(id).querySelectorAll('.dialog-error').forEach(n => n.textContent = ''); $(id).showModal(); }
function closeDialog(id) { $(id).close(); }
function sourceLabel(source) { const base = source.replace(/-error$/, ''); return t(`source_${['human','demo','mcp','mailbox','grok','dot'].includes(base) ? base : 'other'}`) + (source.endsWith('-error') ? ` · ${t('run_failed')}` : ''); }
function translate() {
 document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en'; $('language').value = language;
 document.querySelectorAll('[data-i18n]').forEach(n => n.textContent = t(n.dataset.i18n));
 document.querySelectorAll('[data-i18n-placeholder]').forEach(n => n.placeholder = t(n.dataset.i18nPlaceholder));
 document.querySelectorAll('.close').forEach(n => n.setAttribute('aria-label', t('close'))); document.querySelectorAll('[data-i18n-label]').forEach(n => { n.setAttribute('aria-label', t(n.dataset.i18nLabel)); n.title=t(n.dataset.i18nLabel); });
 $('budget').title = t('budgetNotice'); renderNavigation(); renderState(); renderDirectory();
 if ($('manage-dialog').open) renderManage();
 if ($('create-dialog').open) renderCreate();
 if ($('mcp-dialog').open) renderMCP();
}
function renderNavigation() {
 $('access').textContent = adminToken ? t('ownerScope') : active ? t('roomOnly') : t('connect'); $('bot-count').textContent = bots.length;
 const navSignature=JSON.stringify([language,rooms,active?.id,$('room-search').value,[...roomPreviews]]);
 if($('room-list').dataset.signature===navSignature)return;
 $('room-list').dataset.signature=navSignature;
 const focusedRoom=document.activeElement?.dataset.roomId;
 $('room-list').replaceChildren();
 if (!rooms.length) $('room-list').append(element('p', 'nav-empty', t('noRooms')));
 const query = $('room-search').value.trim().toLocaleLowerCase();
 const matches = rooms.filter(room => room.name.toLocaleLowerCase().includes(query));
 if (rooms.length && !matches.length) $('room-list').append(element('p','nav-empty',t('noMatches')));
 for (const room of matches) {
  const button=element('button','room-nav'+(active?.id===room.id?' active':''));
  button.dataset.roomId=room.id;
  button.setAttribute('aria-current',active?.id===room.id?'page':'false');
  const avatar=element('span','avatar room-avatar',room.name.slice(0,1).toLocaleUpperCase());
  const content=element('span','room-nav-content'); const title=element('span','room-nav-title');
  title.append(element('span','room-nav-name',room.name)); const preview=roomPreviews.get(room.id);
  if(preview) title.append(element('time','',new Date(preview.created*1000).toLocaleTimeString(language==='zh'?'zh-CN':'en-US',{hour:'2-digit',minute:'2-digit'})));
  content.append(title,element('span','room-preview',preview?.body||t('roomPreview')));button.append(avatar,content);
  button.onclick=()=>action(()=>selectRoom(room));$('room-list').append(button);if(focusedRoom===room.id)button.focus();
 }
 $('access').textContent = adminToken ? t('ownerScope') : active ? t('roomOnly') : t('connect'); $('bot-count').textContent = bots.length;
}
async function reloadWorkspace() { requireAdmin(); [rooms,bots] = await Promise.all([api('/api/rooms',adminToken),api('/api/bots',adminToken)]); renderNavigation(); }
async function selectRoom(room) { active = room; state = null; threadId = ''; selected = new Set(); document.querySelector('.app-shell').classList.add('chat-open'); renderNavigation(); await refresh(true); }
async function refresh(force = false) {
 if (!active || (refreshing && !force)) return;
 const current = active; const generation = ++refreshGeneration; refreshing = true;
 try { const data = await api(`/api/rooms/${current.id}`, adminToken || roomTokens.get(current.id)); if (active !== current || generation !== refreshGeneration) return; const first = !state; state = data; if(data.messages.length) roomPreviews.set(current.id,data.messages.at(-1)); active.name = data.room.name; active.lead = data.room.lead; rooms = rooms.map(r => r.id === current.id ? {...r,...data.room} : r); if (first) selected = new Set(data.agents.map(a => a.id)); else selected = new Set([...selected].filter(id => data.agents.some(a => a.id === id))); renderState(); renderNavigation(); }
 finally { if (generation === refreshGeneration) refreshing = false; }
}
function renderState() {
 const connected = Boolean(active && state); $('welcome').hidden = connected; $('thread-bar').hidden = !connected; $('composer-wrap').classList.toggle('inactive', !connected);
 $('manage').disabled = !connected; $('options-open').disabled = !connected; $('stop').hidden = true; $('send').disabled = !connected; $('stop').disabled = !connected;
 if (!connected) { $('room-title').textContent = t('welcomeTitle'); $('room-subtitle').textContent = t('welcomeSub'); $('status').textContent = t('disconnected'); $('messages').replaceChildren(); $('participants').replaceChildren(); $('member-list').replaceChildren(); $('participant-count').textContent='0'; window.HandoffUI?.render(); return; }
 $('room-title').textContent = state.room.name; $('room-subtitle').textContent = `${state.agents.length} ${t('participants')} · ${state.room.lead ? t('leadBadge') : t('noneLead')}`;
 const currentRun = state.runs.at(-1); const running = currentRun?.status === 'running';
 const displayRun = state.runs.find(r => r.id === threadId) || currentRun; $('status').textContent = displayRun ? `${t('run_' + displayRun.status)} · ${displayRun.turn}/${displayRun.budget}` : t('idle'); $('status').classList.toggle('running', running);
 $('send').disabled = running; $('send').hidden = running; $('stop').disabled = !running; $('stop').hidden = !running; $('body').disabled = running; $('budget').disabled = running;
 const selector = $('thread-select');
 const threadSignature=JSON.stringify([language,state.runs.map(run=>[run.id,run.status])]);
 if(selector.dataset.signature!==threadSignature){selector.dataset.signature=threadSignature;selector.replaceChildren(); const latestOption = element('option','',t('latest')); latestOption.value=''; selector.append(latestOption);
 state.runs.forEach((run,index) => { const option = element('option','',`${t('history')} ${index+1} · ${t('run_' + run.status)}`); option.value=run.id; selector.append(option); });} selector.value = threadId;
 const shownRun = threadId || currentRun?.id; const messages = state.messages.filter(m => m.run === shownRun);
 const wasNearBottom = $('chat').scrollHeight - $('chat').scrollTop - $('chat').clientHeight < 140;
 const signature = JSON.stringify([language,shownRun,messages]);
 if ($('messages').dataset.signature !== signature) {
  $('messages').dataset.signature=signature; $('messages').replaceChildren();
  if (!messages.length) $('messages').append(element('div','empty-thread',t('noMessages')));
  for (const message of messages) {
   const senderId=message.sender.startsWith('bot:')?message.sender.slice(4):message.sender; const agent = state.agents.find(a => a.id === senderId); const human = message.sender === 'user' && message.source === 'human'; const article = element('article', 'message ' + (human ? 'human' : 'bot'));
   const avatar = element('div','avatar' + (message.sender === state.room.lead ? ' lead-avatar' : ''), human ? '↗' : '◈');
   const content = element('div','message-content'); const meta = element('div','message-meta'); meta.append(element('strong','', human ? t('human') : agent?.name || message.sender), element('span','source',sourceLabel(message.source)));
   if (message.sender === state.room.lead) meta.append(element('span','lead-badge',t('lead')));
   const time = element('time','',new Date(message.created*1000).toLocaleTimeString(language === 'zh' ? 'zh-CN' : 'en-US',{hour:'2-digit',minute:'2-digit'})); meta.append(time);
   content.append(meta,element('p','message-body',message.body)); article.append(avatar,content); $('messages').append(article);
  }
  if (wasNearBottom || !threadId) requestAnimationFrame(() => { $('chat').scrollTop = $('chat').scrollHeight; });
 }
 const focusedAgent=document.activeElement?.dataset.agentId;
 const participantSignature=JSON.stringify([language,state.agents,[...selected],running,state.room.lead]);
 const updateParticipants=$('participants').dataset.signature!==participantSignature;
 if(updateParticipants){$('participants').dataset.signature=participantSignature;$('participants').replaceChildren();} $('participants').title=t('targetHint'); $('member-list').replaceChildren(); $('participant-count').textContent=state.agents.length;
 for (const agent of state.agents) {
  const chip=element('button','participant-chip'+(selected.has(agent.id)?' selected':''),agent.name); chip.type='button'; chip.dataset.agentId=agent.id; chip.setAttribute('aria-pressed',String(selected.has(agent.id))); chip.disabled=running; if(agent.id===state.room.lead) chip.append(element('span','',` · ${t('lead')}`)); chip.onclick=()=>{if(selected.has(agent.id))selected.delete(agent.id);else selected.add(agent.id);renderState();}; if(updateParticipants){$('participants').append(chip);if(focusedAgent===agent.id)chip.focus();}
  const row=element('div','member'); row.append(element('div','avatar small-avatar','◈')); const info=element('div','member-info'); info.append(element('strong','',agent.name),element('span','',agent.kind==='demo'?t('ready'):t('waiting'))); row.append(info); if(agent.id===state.room.lead) row.append(element('span','lead-badge',t('lead'))); $('member-list').append(row);
 }
 if(!state.agents.length)$('member-list').append(element('p','muted',t('noBots')));
 window.HandoffUI?.render();
 $('lead-note').textContent=state.room.lead ? `${t('lead')}: ${state.agents.find(a=>a.id===state.room.lead)?.name||state.room.lead}` : '';
}
function renderCreate() {
 $('create-bots').replaceChildren(); for(const bot of bots){const label=element('label','check-row');const input=element('input');input.type='checkbox';input.value=bot.id;input.checked=bot.kind==='demo';label.append(input,element('span','',bot.name),element('small','muted',bot.kind==='demo'?t('demo'):t('waiting')));$('create-bots').append(label);}
}
function showCreate() { if(!adminToken){openDialog('access-dialog');return;} $('name').value=t('defaultRoom');renderCreate();openDialog('create-dialog'); }
function renderDirectory() {
 $('bot-cards').replaceChildren(); for(const bot of bots){const card=element('div','bot-card');card.append(element('div','avatar','◈'),element('h3','',bot.name),element('span','status-pill',bot.kind==='demo'?t('ready'):t('waiting')),element('p','muted',bot.description||t('registerHint')),element('code','',bot.id));$('bot-cards').append(card);}
}
function showSecrets(data) { $('secrets').textContent=JSON.stringify(data,null,2);$('copy-secrets').textContent=t('copy');openDialog('secret-dialog'); }
function renderManage() {
 if(!state)return;$('edit-name').value=state.room.name;$('lead-select').replaceChildren();const none=element('option','',t('noneLead'));none.value='';$('lead-select').append(none);
 for(const agent of state.agents){const option=element('option','',agent.name);option.value=agent.id;$('lead-select').append(option);}$('lead-select').value=state.room.lead;
 $('manage-members').replaceChildren();for(const agent of state.agents){const row=element('div','manage-member');const identity=element('div');identity.append(element('strong','',agent.name),element('small','muted',agent.id));const number=element('input');number.type='number';number.min='0';number.max='20';number.value=agent.allowance;number.setAttribute('aria-label',`${agent.name} ${t('allowance')}`);const grant=element('button','secondary compact',t('grant'));grant.type='button';grant.onclick=()=>action(async()=>{await api(roomPath('/grant'),roomAuth(),{id:agent.id,allowance:Number(number.value)});await refresh(true);renderManage();},$('manage-dialog'));const remove=element('button','danger compact',t('remove'));remove.type='button';remove.onclick=()=>action(async()=>{if(!confirm(t('deleteConfirm')))return;await api(roomPath('/remove'),roomAuth(),{id:agent.id});await refresh(true);renderManage();},$('manage-dialog'));row.append(identity,number,grant,remove);$('manage-members').append(row);}
 $('join-select').replaceChildren();for(const bot of bots.filter(b=>!state.agents.some(a=>a.id===b.id))){const option=element('option','',bot.name);option.value=bot.id;$('join-select').append(option);}$('join-form').querySelector('button').disabled=!$('join-select').options.length;
}
function renderMCP(){void action(refreshConnections,$('mcp-dialog'));const config={mcpServers:{roundtable:{command:'/absolute/path/to/.venv/bin/python',args:['/absolute/path/to/bot-roundtable/mcp_bridge.py'],env:{ROUNDTABLE_URL:'http://127.0.0.1:8765',ROUNDTABLE_ROOM:active?.id||'ROOM_ID',ROUNDTABLE_AGENT:'REGISTERED_BOT_ID',ROUNDTABLE_TOKEN:'ROOM_SCOPED_AGENT_TOKEN'}}}};$('mcp-config').textContent=JSON.stringify(config,null,2);}
function showBotForm(leadRoom=null){requireAdmin();leadContext=leadRoom;$('bot-form').reset();$('bot-dialog-title').textContent=t(leadRoom?'createLead':'registerBot');openDialog('bot-dialog');}
$('language').onchange=()=>{language=$('language').value;localStorage.setItem('roundtable-language',language);translate();};
$('menu').onclick=()=>{document.querySelector('.app-shell').classList.remove('chat-open'); $('room-search').focus();};
$('room-search').oninput=renderNavigation;
$('options-open').onclick=()=>openDialog('options-dialog');
document.querySelectorAll('.close').forEach(button=>button.onclick=()=>button.closest('dialog').close());
$('secret-dialog').addEventListener('close',()=>{$('secrets').textContent='';});
$('access').onclick=()=>openDialog('access-dialog');$('new-room').onclick=showCreate;$('hero-create').onclick=showCreate;
$('access-form').onsubmit=event=>{event.preventDefault();action(async()=>{const candidate=$('admin').value;const listed=await api('/api/rooms',candidate);adminToken=candidate;$('admin').value='';rooms=listed;bots=await api('/api/bots',adminToken);closeDialog('access-dialog');renderNavigation();if(rooms.length)await selectRoom(rooms[0]);},$('access-dialog'));};
$('room-connect').onclick=()=>action(async()=>{const id=$('room').value.trim();if(!/^[a-f0-9]{24}$/.test(id))throw new Error('Invalid room or agent credential');const token=$('token').value.trim();const data=await api(`/api/rooms/${id}`,token);adminToken='';roomTokens.set(id,token);rooms=[data.room];bots=[];$('token').value='';closeDialog('access-dialog');await selectRoom(data.room);},$('access-dialog'));
$('create-form').onsubmit=event=>{event.preventDefault();action(async()=>{requireAdmin();const chosen=[...document.querySelectorAll('#create-bots input:checked')].map(n=>n.value);const room=await api('/api/rooms',adminToken,{name:$('name').value,bots:chosen});roomTokens.set(room.id,room.token);closeDialog('create-dialog');await reloadWorkspace();await selectRoom(room);showSecrets({room_id:room.id,room_token:room.token,agents:room.agent_tokens});},$('create-dialog'));};
$('compose').onsubmit=event=>{event.preventDefault();action(async()=>{if(!$('budget').checkValidity()){openDialog('options-dialog');$('budget').focus();$('budget').reportValidity();return;}if(!selected.size)throw new Error('emptySelection');await api(roomPath('/runs'),roomAuth(),{body:$('body').value,targets:state.agents.filter(a=>selected.has(a.id)).map(a=>a.id),budget:Number($('budget').value),request_id:crypto.randomUUID()});$('body').value='';threadId='';await refresh(true);});};
$('stop').onclick=()=>action(async()=>{await api(roomPath('/stop'),roomAuth(),{});await refresh(true);});
$('thread-select').onchange=()=>{threadId=$('thread-select').value;renderState();};$('latest').onclick=()=>{threadId='';renderState();};
$('directory').onclick=()=>action(async()=>{requireAdmin();await reloadWorkspace();renderDirectory();openDialog('directory-dialog');});
$('register').onclick=()=>action(()=>showBotForm(),$('directory-dialog'));
$('bot-form').onsubmit=event=>{event.preventDefault();action(async()=>{requireAdmin();const bot=await api('/api/bots',adminToken,{id:$('bot-id').value,name:$('bot-name').value,kind:$('bot-kind').value,description:$('bot-description').value});closeDialog('bot-dialog');await reloadWorkspace();renderDirectory();if(leadContext){const room=leadContext;const credential=await api(`/api/rooms/${room.id}/join`,adminToken,{id:bot.id});await api(`/api/rooms/${room.id}/settings`,adminToken,{name:room.name,lead:bot.id});await refresh(true);renderManage();showSecrets({room_id:room.id,agent:credential});leadContext=null;}},$('bot-dialog'));};
$('manage').onclick=()=>action(()=>{if(!active)throw new Error('needConnection');renderManage();openDialog('manage-dialog');});
$('settings-form').onsubmit=event=>{event.preventDefault();action(async()=>{await api(roomPath('/settings'),roomAuth(),{name:$('edit-name').value,lead:$('lead-select').value});await refresh(true);renderManage();},$('manage-dialog'));};
$('create-lead').onclick=()=>action(()=>showBotForm({...active}),$('manage-dialog'));
$('join-form').onsubmit=event=>{event.preventDefault();action(async()=>{const credential=await api(roomPath('/join'),roomAuth(),{id:$('join-select').value});await refresh(true);selected.add(credential.id);renderManage();showSecrets({room_id:active.id,agent:credential});},$('manage-dialog'));};
$('copy-secrets').onclick=()=>action(async()=>{await navigator.clipboard.writeText($('secrets').textContent);$('copy-secrets').textContent=t('copied');});
$('mcp-open').onclick=()=>{renderMCP();openDialog('mcp-dialog');};
translate();setInterval(()=>refresh().catch(error=>setError(error)),1200);

async function refreshConnections(){
 const results=$('connection-results');results.replaceChildren();
 if(!active){results.textContent=t('needConnection');return;}
 const room=active.id;const data=await api(roomPath('/connections'),roomAuth());
 if(active?.id!==room)return;
 for(const member of data.members){const row=element('p','small');row.append(element('strong','',member.name+' · '),element('span','',member.observed?`${t('connectionObserved')} ${new Date(member.observed*1000).toLocaleString()}`:t('connectionUnseen')));results.append(row);}
}
$('connection-refresh').onclick=()=>action(refreshConnections,$('mcp-dialog'));
