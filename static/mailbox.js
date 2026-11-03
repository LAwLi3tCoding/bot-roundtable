'use strict';
// The shared roundtable is the only timeline. Filters never change recipients or access.
window.MailboxUI = (() => {
 let roomId='', topicId='', messages=[], generation=0, loading=false, sending=false;
 let botFilter='', tasksOnly=false, presentation='', filterSignature='', request=null;
 const drafts=new Map(), palette=['sage','sand','rose','blue','slate'];
 const actorName=actor=>{if(actor==='user')return t('human');const agent=(state?.agents||[]).find(a=>'bot:'+a.id===actor);return agent?.deleted?t('botDeleted'):agent?.name||actor.replace(/^bot:/,'');};
 const endpoint=suffix=>roomPath('/topics'+suffix);
 const post=(suffix,body)=>api(endpoint(suffix),roomAuth(),body);
 function avatar(actor){
  const preset=(state?.agents||[]).find(a=>'bot:'+a.id===actor)?.avatar;
  const seed=actor==='user'?4:palette.includes(preset)?palette.indexOf(preset):[...actor].reduce((sum,char)=>sum+char.charCodeAt(0),0)%palette.length,color=palette[seed];
  const node=element('span','avatar mailbox-avatar avatar-'+(palette.includes(preset)?preset:color));node.setAttribute('aria-hidden','true');
  if(actor==='user'){node.textContent=t('human').slice(0,1);return node;}
  node.classList.add('character-avatar','character-'+['pebble','capsule','kite'][seed%3]);
  const body=element('span','character-body');body.append(element('span','character-eyes'));node.append(body);return node;
 }
 function saveFilters(){if(roomId)storage('localStorage','setItem','roundtable-filter:'+roomId,JSON.stringify({bot:botFilter,tasks:tasksOnly}));}
 function changeFilter(){saveFilters();render();requestAnimationFrame(()=>{$('chat').scrollTop=0;});}
 function reset(){
  if(roomId)drafts.set(roomId,$('body').value);
  roomId=active?.id||'';topicId=state?.roundtable?.id||'';messages=[];generation++;loading=false;
  botFilter='';tasksOnly=false;presentation='';filterSignature='';request=null;
  try{const saved=JSON.parse(storage('localStorage','getItem','roundtable-filter:'+roomId)||'null');if(saved&&typeof saved.bot==='string'&&/^(bot:[a-z][a-z0-9-]{1,39})?$/.test(saved.bot)){botFilter=saved.bot;tasksOnly=saved.tasks===true;}}catch{}
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
  const key=JSON.stringify([language,botFilter,state?.agents.map(a=>[a.id,a.name,a.deleted])]);
  $('task-filter').textContent=t('tasksOnly');$('task-filter').setAttribute('aria-pressed',String(tasksOnly));
  if(key===filterSignature)return;filterSignature=key;
  const select=$('bot-filter');select.replaceChildren();
  const everyone=element('option','',t('wholeTable'));everyone.value='';select.append(everyone);
  for(const bot of state?.agents||[]){const option=element('option','',actorName('bot:'+bot.id));option.value='bot:'+bot.id;select.append(option);}
  if(botFilter&&![...select.options].some(option=>option.value===botFilter)){const missing=element('option','',actorName(botFilter));missing.value=botFilter;select.append(missing);}
  select.value=botFilter;select.disabled=!state;
 }
 function updateMessage(node,message){
  const signature=JSON.stringify([language,actorName(message.sender),state?.agents.find(a=>'bot:'+a.id===message.sender)?.avatar,message.body]);
  if(node.dataset.messageSignature===signature)return;node.dataset.messageSignature=signature;
  const face=avatar(message.sender);node.dataset.avatarColor=palette.find(c=>face.classList.contains('avatar-'+c))||'slate';
  const old=node.querySelector(':scope > .avatar');if(old)old.replaceWith(face);else node.prepend(face);
  const meta=node.querySelector('.message-meta'),stamp=new Date(message.created*1000),time=meta.querySelector('time');
  meta.querySelector('strong').textContent=actorName(message.sender);
  time.textContent=stamp.toLocaleTimeString(language==='zh'?'zh-CN':'en',{hour:'2-digit',minute:'2-digit'});time.dateTime=stamp.toISOString();time.title=stamp.toLocaleString(language==='zh'?'zh-CN':'en');
  node.querySelector('.message-body').textContent=message.body;
 }
 function messageNode(message,animate){
  const node=element('article','message mailbox-message '+(message.sender==='user'?'human':'bot'));
  node.dataset.messageId=String(message.id);node.dataset.created=String(message.created);node.dataset.actors=JSON.stringify([message.sender]);node.dataset.timelineId='message:'+message.id;node.tabIndex=0;
  const content=element('div','message-content'),meta=element('div','message-meta');
  meta.append(element('strong'),element('time'));content.append(meta,element('p','message-body'));node.append(content);updateMessage(node,message);
  if(animate){node.classList.add('message-arriving');node.addEventListener('animationend',()=>node.classList.remove('message-arriving'),{once:true});}
  return node;
 }
 function renderTimeline(){
  const container=$('messages'),nextPresentation=roomId;
  if(presentation!==nextPresentation){presentation=nextPresentation;container.replaceChildren();}
  const existing=new Map([...container.children].map(n=>[n.dataset.timelineId,n])),known=new Set(existing.keys());
  const nearBottom=$('chat').scrollHeight-$('chat').scrollTop-$('chat').clientHeight<140;
  for(const message of messages){const node=existing.get('message:'+message.id);if(node)updateMessage(node,message);else container.append(messageNode(message,known.size>0));}
  window.HandoffUI.syncCards(container,topicId,messageNode,updateMessage);
  const nodes=[...container.children].filter(n=>n.dataset.timelineId).sort((a,b)=>Number(a.dataset.created)-Number(b.dataset.created)||a.dataset.timelineId.localeCompare(b.dataset.timelineId));
  // Only changed order moves nodes; an idle poll performs no child-list mutations.
  let previous=null;
  for(const node of nodes){const expected=previous?previous.nextElementSibling:container.firstElementChild;if(expected!==node)container.insertBefore(node,expected);previous=node;node.hidden=(tasksOnly&&!node.dataset.taskEntry)||Boolean(botFilter&&!JSON.parse(node.dataset.actors||'[]').includes(botFilter));}
  const visible=nodes.filter(n=>!n.hidden),appended=visible.some(n=>!known.has(n.dataset.timelineId));let empty=container.querySelector('.timeline-empty');
  $('filter-summary').textContent=t('filterCount').replace('{count}',visible.length);
  if(!visible.length){if(!empty){empty=element('div','timeline-empty');container.append(empty);}const key=language+':'+Boolean(nodes.length);if(empty.dataset.signature!==key){empty.dataset.signature=key;empty.replaceChildren(element('h2','',nodes.length?t('noFilteredActivity'):t('startRoundtable')),element('p','',nodes.length?t('changeFilter'):t('roundtableEmpty')));}empty.hidden=false;}else if(empty)empty.remove();
  if(appended&&nearBottom)requestAnimationFrame(()=>{$('chat').scrollTop=$('chat').scrollHeight;});
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
   await window.HandoffUI.loadTimeline(topicId);
   if(room===active?.id&&seq===generation)render();
  }finally{if(seq===generation)loading=false;}
 }
 const baseRender=renderState;renderState=function(){baseRender();render();};
 const baseSelect=selectRoom;selectRoom=async function(room){await baseSelect(room);await fetchTimeline();};
 const baseForget=forgetAccess;forgetAccess=function(){baseForget();drafts.clear();reset();render();$('poll-error').hidden=true;};$('forget-access').onclick=forgetAccess;
 $('bot-filter').onchange=()=>{botFilter=$('bot-filter').value;changeFilter();};
 $('task-filter').onclick=()=>{tasksOnly=!tasksOnly;changeFilter();};
 $('delegate-topic').onclick=()=>window.HandoffUI.createDialog(topicId,state?.roundtable?.members);
 $('compose').onsubmit=event=>{event.preventDefault();if(sending||!topicId||!$('body').value.trim())return;const body=$('body').value,current=topicId,room=roomId;
  if(!request||request.body!==body||request.topic!==current)request={id:crypto.randomUUID(),body,topic:current};sending=true;render();
  action(async()=>{try{await post('/messages',{topic_id:current,body,mentions:notifications(),request_id:request.id});drafts.delete(room);if(room===roomId){$('body').value='';request=null;await fetchTimeline();}}finally{sending=false;render();}});
 };
 $('body').addEventListener('input',()=>{drafts.set(roomId,$('body').value);notificationPreview();sizeComposer();
  const query=mentionQuery();mentionList.replaceChildren();mentionIndex=0;mentionMatches=query?(state?.agents||[]).filter(a=>!a.disabled&&!a.deleted&&a.id.startsWith(query[1].toLowerCase())):[];mentionList.hidden=!mentionMatches.length;$('body').setAttribute('aria-expanded',String(!mentionList.hidden));
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
 setInterval(async()=>{if(!active||!state||polling)return;polling=true;try{if(adminToken===COOKIE_SESSION&&Date.now()-lastRenew>240000){await sessionRequest('/api/ui-login/renew');lastRenew=Date.now();}await refresh();await fetchTimeline();$('poll-error').hidden=true;}catch(error){if(error.message==='UI session expired'){forgetAccess();$('poll-error').hidden=true;}else $('poll-error').hidden=false;}finally{polling=false;}},1800);
 render();return {render,refresh:fetchTimeline,currentTopicId:()=>topicId};
})();
