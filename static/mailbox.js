'use strict';
// The shared roundtable is the only timeline. Filters never change recipients or access.
window.MailboxUI = (() => {
 let roomId='', topicId='', messages=[], generation=0, loading=false, sending=false;
 let botFilter='', tasksOnly=false, presentation='', filterSignature='', request=null;
 const drafts=new Map(), palette=['sage','sand','rose','blue','slate'];
 const actorName=actor=>actor==='user'?t('human'):(state?.agents||[]).find(a=>'bot:'+a.id===actor)?.name||actor.replace(/^bot:/,'');
 const endpoint=suffix=>roomPath('/topics'+suffix);
 const post=(suffix,body)=>api(endpoint(suffix),roomAuth(),body);
 function avatar(actor){
  const ids=(state?.agents||[]).map(a=>'bot:'+a.id).sort();const seed=actor==='user'?4:Math.max(0,ids.indexOf(actor)), color=palette[seed%palette.length];
  const node=element('span','avatar mailbox-avatar avatar-'+color);node.setAttribute('aria-hidden','true');
  if(actor==='user'){node.textContent=t('human').slice(0,1);return node;}
  node.classList.add('character-avatar','character-'+['pebble','capsule','kite'][seed%3]);
  const body=element('span','character-body');body.append(element('span','character-eyes'));node.append(body);return node;
 }
 function reset(){
  if(roomId)drafts.set(roomId,$('body').value);
  roomId=active?.id||'';topicId=state?.roundtable?.id||'';messages=[];generation++;loading=false;
  botFilter='';tasksOnly=false;presentation='';filterSignature='';request=null;
  $('messages').replaceChildren();$('body').value=drafts.get(roomId)||'';
 }
 function notifications(){
  const ids=[...$('body').value.matchAll(/(?:^|\s)@([a-z][a-z0-9-]{1,39})(?=\s|$|[.,!?，。！？])/g)].map(m=>'bot:'+m[1]);
  return [...new Set(ids)];
 }
 function notificationPreview(){
  const selected=notifications();$('notification-preview').textContent=selected.length?
   t('willNotify')+selected.map(actorName).join(language==='zh'?'、':', '):t('silentMessage');
 }
 function sizeComposer(){const field=$('body');field.style.height='auto';field.style.height=Math.min(136,Math.max(24,field.scrollHeight))+'px';}
 function renderFilters(){
  const key=JSON.stringify([language,botFilter,state?.agents.map(a=>[a.id,a.name])]);
  $('task-filter').textContent=t('tasksOnly');$('task-filter').setAttribute('aria-pressed',String(tasksOnly));
  if(key===filterSignature)return;filterSignature=key;
  const focused=document.activeElement?.dataset.botFilter;$('bot-filters').replaceChildren();
  const everyone=element('button','bot-filter',t('wholeTable'));everyone.type='button';everyone.dataset.botFilter='';everyone.setAttribute('aria-pressed',String(!botFilter));everyone.onclick=()=>{botFilter='';render();};$('bot-filters').append(everyone);
  for(const bot of state?.agents||[]){const actor='bot:'+bot.id,button=element('button','bot-filter');button.type='button';button.dataset.botFilter=actor;button.setAttribute('aria-pressed',String(botFilter===actor));button.setAttribute('aria-label',t('filterByBot').replace('{name}',bot.name));button.append(avatar(actor),element('span','',bot.name));button.onclick=()=>{botFilter=botFilter===actor?'':actor;render();};$('bot-filters').append(button);if(focused===actor)button.focus();}
 }
 function messageNode(message,animate){
  const node=element('article','message mailbox-message '+(message.sender==='user'?'human':'bot'));
  node.dataset.messageId=String(message.id);node.dataset.created=String(message.created);node.dataset.actors=JSON.stringify([message.sender,...message.mentions]);node.tabIndex=0;
  const face=avatar(message.sender);node.dataset.avatarColor=palette.find(c=>face.classList.contains('avatar-'+c))||'slate';
  const content=element('div','message-content'),meta=element('div','message-meta'),stamp=new Date(message.created*1000);
  const time=element('time','',stamp.toLocaleTimeString(language==='zh'?'zh-CN':'en',{hour:'2-digit',minute:'2-digit'}));time.dateTime=stamp.toISOString();time.title=stamp.toLocaleString(language==='zh'?'zh-CN':'en');
  meta.append(element('strong','',actorName(message.sender)),time);content.append(meta,element('p','message-body',message.body));node.append(face,content);
  if(animate){node.classList.add('message-arriving');node.addEventListener('animationend',()=>node.classList.remove('message-arriving'),{once:true});}
  return node;
 }
 function renderTimeline(){
  const container=$('messages'),nextPresentation=language+':'+roomId;
  if(presentation!==nextPresentation){presentation=nextPresentation;container.replaceChildren();}
  const known=new Set([...container.querySelectorAll('[data-message-id]')].map(n=>n.dataset.messageId));
  const nearBottom=$('chat').scrollHeight-$('chat').scrollTop-$('chat').clientHeight<140;
  for(const message of messages)if(!known.has(String(message.id)))container.append(messageNode(message,known.size>0));
  window.HandoffUI.syncCards(container,topicId);
  const nodes=[...container.querySelectorAll('[data-message-id],.task-card')].sort((a,b)=>Number(a.dataset.created)-Number(b.dataset.created));
  // Only changed order moves nodes; an idle poll performs no child-list mutations.
  const appended=nodes.some(n=>n.dataset.messageId&&!known.has(n.dataset.messageId));let previous=null;
  for(const node of nodes){const expected=previous?previous.nextElementSibling:container.firstElementChild;if(expected!==node)container.insertBefore(node,expected);previous=node;node.hidden=(tasksOnly&&!node.matches('.task-card'))||Boolean(botFilter&&!JSON.parse(node.dataset.actors||'[]').includes(botFilter));}
  const visible=nodes.some(n=>!n.hidden);let empty=container.querySelector('.timeline-empty');
  if(!visible){if(!empty){empty=element('div','timeline-empty');container.append(empty);}const key=language+':'+Boolean(nodes.length);if(empty.dataset.signature!==key){empty.dataset.signature=key;empty.replaceChildren(element('h2','',nodes.length?t('noFilteredActivity'):t('startRoundtable')),element('p','',nodes.length?t('changeFilter'):t('roundtableEmpty')));}empty.hidden=false;}else if(empty)empty.remove();
  if(known.size&&appended&&nearBottom&&!tasksOnly&&!botFilter)requestAnimationFrame(()=>{$('chat').scrollTop=$('chat').scrollHeight;});
 }
 function render(){
  if(roomId!==(active?.id||''))reset();
  $('room-title').textContent=active?.name||t('roundtableTitle');$('room-subtitle').textContent=t('roundtableSubtitle');
  $('composer-wrap').hidden=!state;$('task-filter').disabled=!state;$('directory').disabled=!state;
  $('send').disabled=!state||sending||Boolean(state?.roundtable?.stopped);$('body').disabled=!state||Boolean(state?.roundtable?.stopped);$('delegate-topic').disabled=!state;
  $('body').placeholder=t('roundtablePlaceholder');$('stop').disabled=!state||Boolean(state?.roundtable?.stopped);
  renderFilters();notificationPreview();sizeComposer();
  if(!state)return;topicId=state.roundtable?.id||topicId;renderTimeline();
 }
 async function fetchTimeline(){
  if(!active||!state||loading)return;loading=true;const room=active.id,seq=++generation;
  try{
   if(!state.roundtable)state.roundtable=await post('/roundtable',{});
   topicId=state.roundtable.id;let after=messages.at(-1)?.id||0;
   while(true){const result=await post('/query',{topic_id:topicId,after});if(room!==active?.id||seq!==generation)return;const known=new Set(messages.map(m=>m.id));messages.push(...result.messages.filter(m=>!known.has(m.id)));after=result.next_cursor;if(result.messages.length<100)break;}
   if(after)await post('/read',{topic_id:topicId,cursor:after});
   if(room===active?.id&&seq===generation)render();
  }finally{if(seq===generation)loading=false;}
 }
 const baseRender=renderState;renderState=function(){baseRender();render();};
 const baseSelect=selectRoom;selectRoom=async function(room){await baseSelect(room);await fetchTimeline();};
 const baseForget=forgetAccess;forgetAccess=function(){baseForget();drafts.clear();reset();render();};$('forget-access').onclick=forgetAccess;
 $('task-filter').onclick=()=>{tasksOnly=!tasksOnly;render();};
 $('delegate-topic').onclick=()=>window.HandoffUI.createDialog(topicId,state?.roundtable?.members);
 $('compose').onsubmit=event=>{event.preventDefault();if(sending||!topicId||!$('body').value.trim())return;const body=$('body').value,current=topicId,room=roomId;
  if(!request||request.body!==body||request.topic!==current)request={id:crypto.randomUUID(),body,topic:current};sending=true;render();
  action(async()=>{try{await post('/messages',{topic_id:current,body,mentions:notifications(),request_id:request.id});drafts.delete(room);if(room===roomId){$('body').value='';request=null;await fetchTimeline();}}finally{sending=false;render();}});
 };
 $('body').addEventListener('input',()=>{drafts.set(roomId,$('body').value);notificationPreview();sizeComposer();
  const query=mentionQuery();mentionList.replaceChildren();mentionIndex=0;mentionMatches=query?(state?.agents||[]).filter(a=>a.id.startsWith(query[1].toLowerCase())):[];mentionList.hidden=!mentionMatches.length;$('body').setAttribute('aria-expanded',String(!mentionList.hidden));
  mentionMatches.forEach((bot,index)=>{const option=element('button','mention-option',bot.name+' @'+bot.id);option.type='button';option.id='mention-option-'+index;option.setAttribute('role','option');option.setAttribute('aria-selected',String(index===0));option.onclick=()=>chooseMention(index);mentionList.append(option);});
 });
 $('stop').onclick=()=>action(async()=>{if(!confirm(t('stopRoundtableConfirm')))return;await post('/stop',{topic_id:topicId});await refresh(true);render();},$('manage-dialog'));
 const settings=$('mailbox-settings'),summary=settings.querySelector('summary');
 function closeSettings(restore=true){if(!settings.open)return;settings.open=false;summary.setAttribute('aria-expanded','false');if(restore)summary.focus();}
 settings.addEventListener('toggle',()=>summary.setAttribute('aria-expanded',String(settings.open)));
 settings.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();closeSettings();}});
 document.addEventListener('click',event=>{if(!settings.contains(event.target))closeSettings();else if(event.target.closest('.sidebar-settings-panel button'))closeSettings(false);});
 settings.querySelectorAll('select').forEach(n=>n.addEventListener('change',()=>closeSettings()));
 const preferred=storage('localStorage','getItem','roundtable-theme')||'system';$('mailbox-theme').value=['system','light','dark'].includes(preferred)?preferred:'system';
 function theme(){const value=$('mailbox-theme').value;document.documentElement.dataset.theme=value==='system'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):value;storage('localStorage','setItem','roundtable-theme',value);}
 $('mailbox-theme').onchange=theme;matchMedia('(prefers-color-scheme: dark)').addEventListener('change',theme);theme();
 let lastRenew=Date.now(),polling=false;
 setInterval(async()=>{if(!active||!state||polling)return;polling=true;try{if(adminToken===COOKIE_SESSION&&Date.now()-lastRenew>240000){await sessionRequest('/api/ui-login/renew');lastRenew=Date.now();}await refresh();await fetchTimeline();}catch(error){if(error.message==='UI session expired')forgetAccess();else setError(error);}finally{polling=false;}},1800);
 render();return {render,refresh:fetchTimeline,currentTopicId:()=>topicId};
})();
