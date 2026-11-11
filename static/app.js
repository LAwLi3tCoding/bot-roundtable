'use strict';
const $ = id => document.getElementById(id);
function storage(kind, method, ...args) { try { return window[kind][method](...args); } catch { return null; } }
let language = storage('localStorage','getItem','roundtable-language') || (navigator.language.startsWith('zh') ? 'zh' : 'en');
if (!I18N[language]) language = 'en';
const t = key => I18N[language][key] || key;
let adminToken = '', active = null, rooms = [], bots = [], state = null, refreshing = false, refreshGeneration = 0;
const roomTokens = new Map();
let connectionEvidence = [], wakeMethods = {};
function memberEvidence(id){const item=connectionEvidence.find(m=>m.id===id);if(!item?.last_activity)return language==='zh'?'还没连上':'Not connected yet';const minutes=Math.floor((Date.now()/1000-item.last_activity)/60);return minutes<2?(language==='zh'?'在线':'Online'):(language==='zh'?`${minutes} 分钟前活跃`:`Active ${minutes} min ago`);}
function eventWake(id, bot){const wake=(bot&&bot.wake)||wakeMethods[id];const member=connectionEvidence.find(m=>m.id===id);return wake==='mcp-events'||member?.kind==='dot'||bot?.kind==='dot';}
function subscriptionStatus(id, bot){if(!eventWake(id, bot))return null;const state=connectionEvidence.find(m=>m.id===id)?.subscription_state;if(state==='valid')return {missing:false, text:t('subscriptionValid')};if(state==='missing'||state==='expired')return {missing:true, text:t('subscriptionExpired')};return null;}
function renderSubscriptionBanner(){const banner=$('subscription-banner');if(!banner)return;if(!active||!state){banner.hidden=true;banner.textContent='';return;}const missing=connectionEvidence.filter(member=>subscriptionStatus(member.id, member)?.missing);banner.hidden=!missing.length;banner.textContent=missing.length?t('subscriptionMissing'):'';}

const credentialKey = 'roundtable-access-v1';
const COOKIE_SESSION = 'cookie-session';
const canStoreCredentials = location.hostname === '127.0.0.1';
let authGeneration = 0, temporarySession = false;
let sessionQueue = Promise.resolve();
function sessionRequest(path, body={}) {
 const operation=sessionQueue.catch(()=>{}).then(()=>fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).then(async response=>{const data=await response.json();if(!response.ok)throw new Error(data.error||'needConnection');return data;});
 sessionQueue=operation;return operation;
}
function clearStoredCredentials() {
 for (const kind of ['sessionStorage','localStorage']) storage(kind,'removeItem',credentialKey);
}
function saveAccess() {
 clearStoredCredentials();
 if(active)storage('localStorage','setItem','roundtable-last-room',active.id);
}
function forgetAccess() {
 void sessionRequest('/api/ui-login/revoke').catch(()=>{});
 temporarySession=false;$('remember-access').disabled=true;
 authGeneration++; refreshGeneration++; refreshing=false;
 clearStoredCredentials(); adminToken='';roomTokens.clear();
 active=null;state=null;rooms=[];bots=[];wakeMethods={};
 $('admin').value='';$('token').value='';$('room').value='';$('remember-access').checked=false;

 for(const dialog of document.querySelectorAll('dialog[open]'))dialog.close();
 renderNavigation();renderState();
}
async function restoreAccess() {
 const epoch=authGeneration;
 clearStoredCredentials();
 try {
  await sessionRequest('/api/ui-login/renew');
  const [listed,known]=await Promise.all([api('/api/rooms',''),api('/api/bots','')]);
  if(epoch!==authGeneration)return;
  adminToken=COOKIE_SESSION;temporarySession=true;rooms=listed;bots=known;
  $('remember-access').disabled=true;renderNavigation();
  const last=storage('localStorage','getItem','roundtable-last-room');
  if(rooms.length)await selectRoom(rooms.find(r=>r.id===last)||rooms[0]);
 } catch { /* A fresh browser needs an explicit local login-code launch. */ }
}
async function startAccess() {
 const fragment=new URLSearchParams(location.hash.slice(1));
 if(!fragment.has('roundtable-login'))return restoreAccess();
 const code=fragment.get('roundtable-login');
 history.replaceState(null,'',location.pathname+location.search);
 forgetAccess();const epoch=authGeneration;
 try{
  if(!canStoreCredentials)throw new Error('needConnection');
  await sessionRequest('/api/ui-login/exchange',{code,cookie:true});
  if(epoch!==authGeneration)return;
  const [listed,known]=await Promise.all([api('/api/rooms',COOKIE_SESSION),api('/api/bots',COOKIE_SESSION)]);
  if(epoch!==authGeneration)return;
  adminToken=COOKIE_SESSION;temporarySession=true;rooms=listed;bots=known;
  $('remember-access').disabled=true;$('remember-access').checked=false;
  saveAccess();renderNavigation();if(rooms.length)await selectRoom(rooms.find(r=>r.id===storage('localStorage','getItem','roundtable-last-room'))||rooms[0]);
 }catch(error){if(epoch===authGeneration){forgetAccess();setError(error);}}
}
function element(tag, className, value) { const node = document.createElement(tag); if (className) node.className = className; if (value !== undefined) node.textContent = value; return node; }
function setError(error, dialog) {
 const target=(dialog||document.querySelector('dialog[open]'))?.querySelector('.dialog-error')||$('error');
 const fallback=language==='zh'?({400:'请检查填写的内容。',403:'当前会话不能执行此操作，请从「打开圆桌」重新进入。',409:'内容已变化，请刷新后再试。'}):({400:'Check the entered values.',403:'Open the roundtable again to continue.',409:'This changed. Refresh and try again.'});
 target.textContent=I18N[language].errors[error.message]||I18N[language][error.message]||fallback[error.status]||t('requestFailed');
 clearTimeout(target.errorTimer);if(error.message!=='networkError')target.errorTimer=setTimeout(()=>target.textContent='',6000);
}
async function action(fn, dialog) { $('error').textContent = ''; if(dialog) dialog.querySelectorAll('.dialog-error').forEach(n => n.textContent = ''); try { await fn(); } catch (error) { setError(error, dialog); } }
async function api(path, token, body) {
 const epoch=authGeneration;
 let response; try { response = await fetch(path, {method: body !== undefined ? 'POST' : 'GET', headers: {...(token && token!==COOKIE_SESSION?{'Authorization': `Bearer ${token}`} : {}), 'Content-Type': 'application/json'}, body: body !== undefined ? JSON.stringify(body) : undefined}); } catch { throw new Error('networkError'); }
 const data = await response.json(); if(response.ok&&$('error').textContent===t('networkError'))$('error').textContent=''; if(epoch!==authGeneration)throw new Error('needConnection'); if (!response.ok) { if(data.error==='UI session expired'){forgetAccess();} const error = new Error(data.error || 'requestFailed'); error.status = response.status; throw error; } return data;
}
function roomPath(suffix = '') { if (!active) throw new Error('needConnection'); return `/api/rooms/${active.id}${suffix}`; }
function roomAuth() { if (!active) throw new Error('needConnection'); return adminToken || roomTokens.get(active.id); }
function openDialog(id) { $(id).querySelectorAll('.dialog-error').forEach(n => n.textContent = ''); $(id).showModal(); }
function closeDialog(id) { $(id).close(); }
function translate() {
 document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en'; $('language').value = language;
 document.querySelectorAll('[data-i18n]').forEach(n => n.textContent = t(n.dataset.i18n));
 document.querySelectorAll('[data-i18n-placeholder]').forEach(n => n.placeholder = t(n.dataset.i18nPlaceholder));
 document.querySelectorAll('.close').forEach(n => n.setAttribute('aria-label', t('close'))); document.querySelectorAll('[data-i18n-label]').forEach(n => { n.setAttribute('aria-label', t(n.dataset.i18nLabel)); n.title=t(n.dataset.i18nLabel); });
 renderNavigation(); renderState(); renderDirectory();
 if ($('manage-dialog').open) renderManage();

 if ($('mcp-dialog').open) renderMCP();
}
function renderNavigation() { $('bot-count').textContent=state?.agents.length||bots.length; }
async function reloadWorkspace() { [rooms,bots] = await Promise.all([api('/api/rooms',adminToken),api('/api/bots',adminToken)]); renderNavigation(); }
async function selectRoom(room) { mentionList.hidden = true; active = room; saveAccess(); state = null; connectionEvidence=[];wakeMethods={}; renderNavigation(); await refresh(true); }
async function refresh(force = false) {
 if (!active || (refreshing && !force)) return;
 const current = active; const generation = ++refreshGeneration; refreshing = true;
 try { const data = await api(`/api/rooms/${current.id}`, adminToken || roomTokens.get(current.id)); if (active !== current || generation !== refreshGeneration) return; const evidence=await api(`/api/rooms/${current.id}/connections`,adminToken||roomTokens.get(current.id));if(active!==current||generation!==refreshGeneration)return;connectionEvidence=evidence.members;wakeMethods=evidence.wake_methods||{};state=data;active.name=data.room.name;rooms=rooms.map(r=>r.id===current.id?{...r,...data.room}:r); renderState(); renderNavigation(); }
 finally { if (generation === refreshGeneration) refreshing = false; }
}
function renderState() {
 const connected=Boolean(active&&state);
 $('login-guide').hidden=connected;
 $('composer-wrap').hidden=!connected;
 $('manage').disabled=!connected;
 if(!connected){$('messages').replaceChildren();}$('task-filter').disabled=!connected;$('delegate-topic').disabled=!connected;
 window.HandoffUI?.render();
 renderSubscriptionBanner();
}
function wakeLabel(id){const method=wakeMethods[id];const zh={'grok-routine':'推送到 Webhook','mcp-events':'订阅事件','poll':'Bot 自己定时来看'};const en={'grok-routine':'Push to webhook','mcp-events':'Subscribe to events','poll':'Bot checks on a schedule'};return (language==='zh'?zh:en)[method]||(language==='zh'?'通知方式尚未配置':'Notifications not configured');}
function renderDirectory() {
 if(window.BotManagement){window.BotManagement.render();return;}
 $('bot-cards').replaceChildren(); for(const bot of bots){const card=element('div','bot-card');card.append(element('div','avatar',bot.name.slice(0,1)),element('h3','',bot.name),element('span','status-pill',memberEvidence(bot.id)),element('p','muted',bot.description||t('registerHint')),element('code','',bot.id),element('p','member-evidence',wakeLabel(bot.id)));const sub=subscriptionStatus(bot.id, bot);if(sub)card.append(element('p',sub.missing?'subscription-missing muted':'muted',sub.text));$('bot-cards').append(card);}
}
function renderManage() {
 if(!state)return;$('edit-name').value=state.room.name;
 $('manage-members').replaceChildren();for(const agent of state.agents){const row=element('div','manage-member');const identity=element('div');const minutes=Math.max(1,Math.ceil(((agent.allowance_reset||Date.now()/1000+3600)-Date.now()/1000)/60));identity.append(element('strong','',agent.name),element('small','muted',memberEvidence(agent.id)),element('small','muted',language==='zh'?`剩余 ${agent.allowance} 次，用完后 ${minutes} 分钟恢复`:`${agent.allowance} left; renews in ${minutes} minutes`));const number=element('input');number.type='number';number.min='0';number.max='20';number.value=agent.allowance_limit??20;number.setAttribute('aria-label',`${agent.name} ${t('allowance')}`);const grant=element('button','secondary compact',t('grant'));grant.type='button';grant.onclick=()=>action(async()=>{await api(roomPath('/grant'),roomAuth(),{id:agent.id,allowance:Number(number.value)});await refresh(true);renderManage();},$('manage-dialog'));row.append(identity,number,grant);$('manage-members').append(row);}
}
function renderMCP(){void action(refreshConnections,$('mcp-dialog'));const config={mcpServers:{roundtable:{command:'/absolute/path/to/.venv/bin/python',args:['/absolute/path/to/bot-roundtable/mcp_bridge.py'],env:{ROUNDTABLE_URL:location.origin,ROUNDTABLE_ROOM:active?.id||'ROOM_ID',ROUNDTABLE_AGENT:'REGISTERED_BOT_ID',ROUNDTABLE_TOKEN:'ROOM_SCOPED_AGENT_TOKEN'}}}};$('mcp-config').textContent=t('managedCLI')+'\n.venv/bin/python scripts/local_runtime.py client --operation doctor\n.venv/bin/python scripts/local_runtime.py client --operation probe\n\n'+t('manualMCP')+'\n'+JSON.stringify(config,null,2);}
$('advanced-access').onclick=()=>openDialog('access-dialog');
$('language').onchange=()=>{language=$('language').value;storage('localStorage','setItem','roundtable-language',language);translate();};

document.querySelectorAll('.close').forEach(button=>button.onclick=()=>button.closest('dialog').close());
$('access-form').onsubmit=event=>{event.preventDefault();action(async()=>{const epoch=++authGeneration;const candidate=$('admin').value;const [listed,known]=await Promise.all([api('/api/rooms',candidate),api('/api/bots',candidate)]);if(epoch!==authGeneration)return;roomTokens.clear();temporarySession=/^ui_[A-Za-z0-9_-]{43}$/.test(candidate);$('remember-access').disabled=true;if(temporarySession)$('remember-access').checked=false;adminToken=candidate;$('admin').value='';rooms=listed;bots=known;saveAccess();closeDialog('access-dialog');renderNavigation();if(rooms.length)await selectRoom(rooms[0]);},$('access-dialog'));};
$('room-connect').onclick=()=>action(async()=>{const id=$('room').value.trim();if(!/^[a-f0-9]{24}$/.test(id))throw new Error('Invalid room or agent credential');const epoch=++authGeneration;const token=$('token').value.trim();if(/^ui_[A-Za-z0-9_-]{43}$/.test(token))throw new Error('Invalid room or agent credential');const data=await api(`/api/rooms/${id}`,token);if(epoch!==authGeneration)return;adminToken='';temporarySession=false;$('remember-access').disabled=true;roomTokens.clear();roomTokens.set(id,token);rooms=[data.room];bots=[];$('token').value='';saveAccess();closeDialog('access-dialog');await selectRoom(data.room);},$('access-dialog'));
const mentionList = element('div', 'mention-list');
mentionList.id = 'mention-list'; mentionList.setAttribute('role', 'listbox'); mentionList.hidden = true;
$('composer-wrap').prepend(mentionList);
$('body').setAttribute('aria-controls', 'mention-list');
let mentionMatches = [], mentionIndex = 0;
function mentionQuery() { return $('body').value.slice(0, $('body').selectionStart).match(/(?:^|\s)@([a-z0-9-]*)$/i); }
function chooseMention(index) {
 const query = mentionQuery(), member = mentionMatches[index]; if (!query || !member) return;
 const input = $('body'), end = input.selectionStart, start = end - query[1].length - 1;
 input.setRangeText('@' + member.id + ' ', start, end, 'end');
 mentionList.hidden = true; input.setAttribute('aria-expanded','false'); input.focus();input.dispatchEvent(new Event('input',{bubbles:true}));
}
$('body').addEventListener('keydown', event => {
 if(mentionList.hidden)return;
 if(['ArrowDown','ArrowUp'].includes(event.key)) { event.preventDefault(); mentionIndex = (mentionIndex + (event.key === 'ArrowDown' ? 1 : -1) + mentionMatches.length) % mentionMatches.length; [...mentionList.children].forEach((n,i)=>n.setAttribute('aria-selected',String(i===mentionIndex))); $('body').setAttribute('aria-activedescendant','mention-option-'+mentionIndex); }
 else if(event.key === 'Enter' || event.key === 'Tab') {event.preventDefault(); chooseMention(mentionIndex);}
 else if(event.key === 'Escape') {event.preventDefault();mentionList.hidden=true;}
});
// Enter sends; Cmd/Ctrl/Shift+Enter add a line. Runs after the mention handler,
// so Enter that picks a mention never sends. IME composition never sends.
$('body').addEventListener('keydown', event => {
 if(event.key !== 'Enter' || event.defaultPrevented || event.isComposing || event.keyCode === 229) return;
 const input = $('body');
 if(event.metaKey || event.ctrlKey) { event.preventDefault(); input.setRangeText('\n', input.selectionStart, input.selectionEnd, 'end'); input.dispatchEvent(new Event('input',{bubbles:true})); return; }
 if(event.shiftKey || event.altKey) return;
 event.preventDefault();
 if(input.value.trim() && !$('send').disabled) $('compose').requestSubmit();
});
$('directory').onclick=()=>action(async()=>{if(window.BotManagement)return window.BotManagement.open();await reloadWorkspace();renderDirectory();openDialog('directory-dialog');});
$('manage').onclick=()=>action(()=>{if(!active)throw new Error('needConnection');renderManage();openDialog('manage-dialog');});
$('settings-form').onsubmit=event=>{event.preventDefault();action(async()=>{await api(roomPath('/settings'),roomAuth(),{name:$('edit-name').value});await refresh(true);renderManage();},$('manage-dialog'));};
$('mcp-open').onclick=()=>{renderMCP();openDialog('mcp-dialog');};
$('forget-access').onclick=forgetAccess;
$('remember-access').onchange=saveAccess;
$('remember-access').disabled=true;
window.addEventListener('hashchange',()=>{if(new URLSearchParams(location.hash.slice(1)).has('roundtable-login'))void startAccess();});
translate();void startAccess();

async function refreshConnections(){
 const results=$('connection-results');results.replaceChildren();
 if(!active){results.textContent=t('needConnection');return;}
 const room=active.id;const data=await api(roomPath('/connections'),roomAuth());
 if(active?.id!==room)return;
 for(const member of data.members){const row=element('p','small');row.append(element('strong','',member.name+' · '),element('span','',member.observed?`${t('connectionObserved')} ${new Date(member.observed*1000).toLocaleString()}`:t('connectionUnseen')));const sub=subscriptionStatus(member.id, member);if(sub)row.append(element('span',sub.missing?'subscription-missing':'',' · '+sub.text));results.append(row);}
}
$('connection-refresh').onclick=()=>action(refreshConnections,$('mcp-dialog'));
