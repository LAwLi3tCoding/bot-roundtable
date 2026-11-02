'use strict';
// Topic data is always fetched through the current authenticated room boundary.
window.MailboxUI = (() => {
 const words = {
  en:{all:'All',newChat:'New chat',bots:'Bots',groups:'Group chats',workspace:'Workspace',empty:'Start a conversation',hint:'Choose a bot for a direct message, or bring a few together.',noTopics:'No conversations yet',newGroup:'New conversation',title:'Conversation name',members:'To',create:'Start conversation',cancel:'Cancel',you:'You',join:'Send a message to join this conversation. Members can see its full history.',allHint:'Every conversation in your workspace. Open one to join in.',message:'Message',budget:'Bot reply budget',stop:'Stop replies',stopped:'Replies stopped',theme:'Appearance',light:'Light',dark:'Dark',system:'System',history:'Earlier messages',read:'Read',waiting:'No messages yet',sending:'Sending…',retry:'Could not send. Your draft is saved; try again.',options:'Conversation details',membersHint:'Messages go to all members. Bots are notified within the reply budget; @ narrows who should reply.',scope:'Conversation',allCount:'conversations',profile:'Avatar',initial:'Initials',color:'Color',save:'Save',avatarHint:'Stored on this browser only. No remote images are loaded.'},
  zh:{all:'全部',newChat:'新话题',bots:'成员',groups:'群聊',workspace:'工作区',empty:'开始一段对话',hint:'点选成员私聊，或邀请几位成员一起聊。',noTopics:'还没有对话',newGroup:'新建话题',title:'话题名称',members:'收件人',create:'开始对话',cancel:'取消',you:'你',join:'发送消息后，你将加入此话题，并可查看完整历史。',allHint:'工作区内的所有对话。打开话题即可插话。',message:'发送消息',budget:'Bot 回复预算',stop:'停止回复',stopped:'已停止回复',theme:'外观',light:'浅色',dark:'深色',system:'跟随系统',history:'更早的消息',read:'已读',waiting:'还没有消息',sending:'发送中…',retry:'未能发送，草稿已保留，请重试。',options:'话题详情',membersHint:'消息投递给所有成员，Bot 在回复预算内收到通知；@ 可缩小希望回复的范围。',scope:'话题',allCount:'个话题',profile:'头像',initial:'字母',color:'颜色',save:'保存',avatarHint:'只保存在此浏览器，不加载外部图片。'}
 };
 const w = k => words[language==='zh'?'zh':'en'][k];
 let navSignature='', topicId='', topics=[], messages=[], roomId='', generation=0, loading=false, sending=false, creating=false, taskMode=false, allMode=true, signature='', request=null;
 const drafts = new Map();
 let avatarSettings={};try{avatarSettings=JSON.parse(storage('localStorage','getItem','roundtable-avatars')||'{}');}catch{}
 const palette=['sage','sand','rose','blue','slate'];
 const label = actor => actor==='user'?w('you'):(state?.agents||bots).find(a=>'bot:'+a.id===actor)?.name||actor.replace(/^bot:/,'');
 function avatar(actor, small=false) {
  const settings=avatarSettings[actor]||{}, name=label(actor);
  const seed=[...actor].reduce((sum,c)=>sum+c.charCodeAt(0),0);
  const color=palette.includes(settings.color)?settings.color:palette[seed%palette.length];
  const n=element('span','avatar mailbox-avatar '+(small?'small-avatar ':'')+'avatar-'+color);
  n.setAttribute('aria-hidden','true');
  if(actor==='user'||settings.character==='initials'||(!settings.character&&typeof settings.initial==='string')) {
   n.textContent=typeof settings.initial==='string'?settings.initial.slice(0,2):name.slice(0,2).toLocaleUpperCase();
  } else {
   const shapes=['pebble','capsule','kite'];
   const shape=shapes.includes(settings.character)?settings.character:shapes[seed%shapes.length];
   n.classList.add('character-avatar','character-'+shape);
   const body=element('span','character-body');
   body.append(element('span','character-eyes'),element('span','character-mouth'));
   n.append(body);
  }
  return n;
 }
 function stack(members){const n=element('span','avatar-stack');members.filter(m=>m!=='user').slice(0,3).forEach(m=>n.append(avatar(m)));return n;}
 function topic(){return topics.find(x=>x.id===topicId);}
 function title(item){return item.members.length===2&&item.members.includes('user')?label(item.members.find(m=>m!=='user')):item.title;}
 const endpoint = suffix => roomPath('/topics'+suffix);
 const post = (suffix,data) => api(endpoint(suffix),roomAuth(),data);
 function rememberDraft(){if(topicId)drafts.set(roomId+':'+topicId,$('body').value);}
 function reset(){rememberDraft();roomId=active?.id||'';topicId='';topics=[];messages=[];generation++;signature='';request=null;loading=false;allMode=true;taskMode=false;}
 function row(item){const button=element('button','mailbox-row'+(topicId===item.id?' selected':''));button.type='button';button.dataset.topicId=item.id;button.setAttribute('aria-label',title(item));button.title=title(item);button.setAttribute('aria-current',topicId===item.id?'page':'false');button.append(stack(item.members));const info=element('span','mailbox-row-copy');const top=element('span','mailbox-row-title');top.append(element('strong','',title(item)));if(item.last_message)top.append(element('time','',new Date(item.last_message.created*1000).toLocaleTimeString(language==='zh'?'zh-CN':'en',{hour:'2-digit',minute:'2-digit'})));info.append(top,element('span','mailbox-preview',item.last_message?`${label(item.last_message.sender)}: ${item.last_message.body}`:w('waiting')));button.append(info);if(item.unread)button.append(element('span','unread',String(item.unread)));button.onclick=()=>action(()=>open(item.id));return button;}
 function navigation(){
  $('mailbox-all').textContent=w('all');$('mailbox-all').classList.toggle('selected',allMode);$('mailbox-new').textContent=w('newChat');$('mailbox-theme').setAttribute('aria-label',w('theme'));$('mailbox-theme').options[0].textContent=w('system');$('mailbox-theme').options[1].textContent=w('light');$('mailbox-theme').options[2].textContent=w('dark');
  const navKey=JSON.stringify([language,topicId,allMode,topics,state?.agents,$('room-search').value,avatarSettings]);if(navSignature===navKey)return;navSignature=navKey;const focused=document.activeElement?.closest('.mailbox-row');const focusedTopic=focused?.dataset.topicId,focusedBot=focused?.dataset.botId;$('mailbox-list').replaceChildren();const query=$('room-search').value.toLocaleLowerCase();const members=(state?.agents||[]).filter(a=>a.name.toLocaleLowerCase().includes(query));
  $('mailbox-list').append(element('h2','mailbox-section',w('bots')));
  for(const bot of members){const direct=topics.find(x=>x.members.length===2&&x.members.includes('user')&&x.members.includes('bot:'+bot.id));if(direct){$('mailbox-list').append(row(direct));continue;}const button=element('button','mailbox-row');button.type='button';button.dataset.botId=bot.id;button.setAttribute('aria-label',bot.name);button.title=bot.name;button.append(avatar('bot:'+bot.id));const info=element('span','mailbox-row-copy');info.append(element('strong','',bot.name),element('span','mailbox-preview',w('waiting')));button.append(info);button.onclick=()=>action(()=>directChat(bot));$('mailbox-list').append(button);}
  const groups=topics.filter(x=>!(x.members.length===2&&x.members.includes('user'))&&title(x).toLocaleLowerCase().includes(query));$('mailbox-list').append(element('h2','mailbox-section',w('groups')));groups.forEach(item=>$('mailbox-list').append(row(item)));
  $('mailbox-new').disabled=!state;$('mailbox-all').disabled=!state;for(const n of $('mailbox-list').querySelectorAll('.mailbox-row'))if((focusedTopic&&n.dataset.topicId===focusedTopic)||(focusedBot&&n.dataset.botId===focusedBot))n.focus();
 }
 function render(){
  if(roomId!==(active?.id||''))reset();navigation();if(!state||taskMode)return;
  $('welcome').hidden=true;$('thread-bar').hidden=true;$('handoffs-view').hidden=true;$('messages').hidden=false;$('discussion-view').textContent=w('scope');$('discussion-view').classList.add('selected');$('task-view').classList.remove('selected');
  const item=topic();$('composer-wrap').hidden=!item;$('options-open').disabled=!item;$('send').disabled=!item||sending;$('stop').hidden=!item||Boolean(item.stopped);$('stop').disabled=!item;$('stop').textContent=w('stop');$('body').placeholder=item?`${w('message')} ${title(item)}`:w('message');
  $('room-title').textContent=item?title(item):w('all');$('room-subtitle').textContent=item?item.members.map(label).join(' · '):`${active.name} · ${topics.length} ${w('allCount')}`;$('status').textContent=item?(item.stopped?w('stopped'):`${item.used} / ${item.budget}`):'';
  const headerAvatar=document.querySelector('.topbar > .avatar');headerAvatar.replaceChildren();headerAvatar.className='avatar mailbox-heading-avatar';if(item)headerAvatar.append(stack(item.members));else headerAvatar.textContent='◎';
  $('mailbox-join').hidden=!item||item.members.includes('user');$('mailbox-join').textContent=w('join');
  const next=JSON.stringify([language,topicId,allMode,topicId?messages:topics,avatarSettings]);if(signature===next)return;signature=next;
  const existingIds=new Set([...$('messages').querySelectorAll('[data-message-id]')].map(n=>n.dataset.messageId));
  const nearBottom=$('chat').scrollHeight-$('chat').scrollTop-$('chat').clientHeight<140;$('messages').replaceChildren();
  if(!item){const intro=element('div','mailbox-overview-heading');intro.append(element('h2','',w('all')),element('p','',w('allHint')));$('messages').append(intro);if(!topics.length){const empty=element('div','mailbox-empty');empty.append(element('h2','',w('empty')),element('p','',w('hint')));$('messages').append(empty);}topics.forEach(x=>$('messages').append(row(x)));return;}
  if(!messages.length){const empty=element('div','mailbox-empty');empty.append(stack(item.members),element('h2','',title(item)),element('p','',w('membersHint')));$('messages').append(empty);}
  for(const message of messages){const human=message.sender==='user';const article=element('article','message mailbox-message '+(human?'human':'bot'));article.dataset.messageId=message.id;if(!existingIds.has(String(message.id)))article.classList.add('message-arriving');article.append(avatar(message.sender));const content=element('div','message-content');const meta=element('div','message-meta');meta.append(element('strong','',label(message.sender)),element('time','',new Date(message.created*1000).toLocaleTimeString(language==='zh'?'zh-CN':'en',{hour:'2-digit',minute:'2-digit'})));content.append(meta,element('p','message-body',message.body));if(message.mentions.length)content.append(element('small','mailbox-recipients',message.mentions.map(m=>'@'+label(m)).join(' ')));article.append(content);$('messages').append(article);}
  if(nearBottom)requestAnimationFrame(()=>{$('chat').scrollTop=$('chat').scrollHeight;});
 }
 async function fetchTopics(){if(!active||loading)return;const current=active.id,seq=++generation;loading=true;try{const listed=await api(endpoint(''),roomAuth());if(current!==active?.id||seq!==generation)return;topics=listed;if(topicId){const result=await post('/query',{topic_id:topicId,after:0});if(current!==active?.id||seq!==generation)return;messages=result.messages;let cursor=result.next_cursor;while(result.messages.length===100&&cursor){const more=await post('/query',{topic_id:topicId,after:cursor});if(current!==active?.id||seq!==generation)return;messages.push(...more.messages);cursor=more.next_cursor;if(more.messages.length<100)break;}if(!taskMode&&topic()?.members.includes('user')&&messages.length){await post('/read',{topic_id:topicId,cursor:messages.at(-1).id});const item=topic();if(item)item.unread=0;}}render();}finally{if(seq===generation)loading=false;}}
 async function open(id){rememberDraft();generation++;loading=false;topicId=id;allMode=false;taskMode=false;request=null;messages=[];signature='';$('body').value=drafts.get(roomId+':'+id)||'';mentionList.hidden=true;document.querySelector('.app-shell').classList.add('chat-open');storage('localStorage','setItem','roundtable-last-topic:'+roomId,id);render();await fetchTopics();$('chat').scrollTop=$('chat').scrollHeight;}
 async function directChat(bot){if(creating)return;creating=true;try{const existing=topics.find(x=>x.members.length===2&&x.members.includes('user')&&x.members.includes('bot:'+bot.id));if(existing)return await open(existing.id);const item=await post('',{members:['user','bot:'+bot.id],title:bot.name,request_id:crypto.randomUUID(),budget:4});topics.unshift({...item,unread:0,last_message:null});await open(item.id);}finally{creating=false;}}
 function showCreate(){if(!state)return;$('mailbox-create-form').reset();$('mailbox-members').replaceChildren();for(const bot of state.agents){const row=element('label','check-row');const checkbox=element('input');checkbox.type='checkbox';checkbox.value='bot:'+bot.id;row.append(checkbox,avatar('bot:'+bot.id),element('span','',bot.name));$('mailbox-members').append(row);}for(const n of document.querySelectorAll('[data-mailbox-label]'))n.textContent=w(n.dataset.mailboxLabel);openDialog('mailbox-dialog');}
 function details(){const item=topic();if(!item)return;$('mailbox-details-members').replaceChildren();item.members.forEach(m=>{const r=element('div','member');r.append(avatar(m),element('span','',label(m)));const edit=element('button','subtle',w('profile'));edit.onclick=()=>editAvatar(m);r.append(edit);$('mailbox-details-members').append(r);});for(const n of document.querySelectorAll('[data-mailbox-label]'))n.textContent=w(n.dataset.mailboxLabel);$('mailbox-detail-budget').textContent=`${w('budget')}: ${item.used} / ${item.budget}`;openDialog('mailbox-details');}
 function editAvatar(actor){$('mailbox-avatar-actor').value=actor;$('mailbox-avatar-initial').value=avatarSettings[actor]?.initial||label(actor).slice(0,2);$('mailbox-avatar-color').value=avatarSettings[actor]?.color||'sage';$('mailbox-avatar-character').value=avatarSettings[actor]?.character||'auto';openDialog('mailbox-avatar-dialog');}
 const originalRender=renderState;renderState=function(){const retained=[...$('messages').childNodes];originalRender();if(!taskMode&&state)$('messages').replaceChildren(...retained);render();};
 const originalNavigation=renderNavigation;renderNavigation=function(){originalNavigation();navigation();};
 const originalSelect=selectRoom;selectRoom=async function(room){await originalSelect(room);reset();await fetchTopics();const previous=storage('localStorage','getItem','roundtable-last-topic:'+room.id);if(topics.some(x=>x.id===previous))await open(previous);};
 const originalTask=window.HandoffUI.openTask;window.HandoffUI.openTask=async function(id){taskMode=true;await originalTask(id);};
 const previousForget=forgetAccess;forgetAccess=function(){previousForget();drafts.clear();reset();render();};$('forget-access').onclick=forgetAccess;
 $('room-search').oninput=navigation;$('room-search').placeholder=language==='zh'?'搜索对话':'Search conversations';
 $('mailbox-new').onclick=showCreate;$('mailbox-all').onclick=()=>{rememberDraft();generation++;loading=false;topicId='';allMode=true;taskMode=false;signature='';storage('localStorage','removeItem','roundtable-last-topic:'+roomId);document.querySelector('.app-shell').classList.add('chat-open');render();};
 $('discussion-view').addEventListener('click',()=>{taskMode=false;signature='';render();});$('task-view').addEventListener('click',()=>{taskMode=true;window.HandoffUI.render();});$('new-task').addEventListener('click',()=>{taskMode=true;window.HandoffUI.render();});
 $('options-open').onclick=details;
 $('mailbox-create-form').onsubmit=event=>{event.preventDefault();if(creating)return;const members=[...document.querySelectorAll('#mailbox-members input:checked')].map(n=>n.value);if(!members.length){$('mailbox-dialog').querySelector('.dialog-error').textContent=w('hint');return;}creating=true;$('mailbox-create-submit').disabled=true;action(async()=>{try{const item=await post('',{members:['user',...members],title:$('mailbox-title').value.trim()||members.map(label).join(', '),budget:Number($('mailbox-budget').value),request_id:crypto.randomUUID()});topics.unshift({...item,unread:0,last_message:null});closeDialog('mailbox-dialog');await open(item.id);}finally{creating=false;$('mailbox-create-submit').disabled=false;}},$('mailbox-dialog'));};
 $('compose').onsubmit=event=>{event.preventDefault();if(sending||!topicId||!$('body').value.trim())return;const body=$('body').value,current=topicId,currentRoom=roomId;let mentions=[...new Set([...body.matchAll(/(?:^|\s)@([a-z][a-z0-9-]{1,39})(?=\s|$|[.,!?])/g)].map(m=>'bot:'+m[1]))];if(!mentions.length)mentions=(topic()?.members||[]).filter(m=>m.startsWith('bot:'));if(!request||request.body!==body||request.topic!==current)request={id:crypto.randomUUID(),body,topic:current};sending=true;render();action(async()=>{try{await post('/messages',{topic_id:current,body,mentions,request_id:request.id,join:true});drafts.delete(currentRoom+':'+current);if(topicId===current&&roomId===currentRoom){$('body').value='';request=null;await fetchTopics();}}finally{sending=false;render();}});};
 $('body').addEventListener('input',()=>{rememberDraft();$('body').style.height='auto';$('body').style.height=Math.min(130,$('body').scrollHeight)+'px';});
 $('body').removeEventListener('input',updateMentions);$('body').addEventListener('input',()=>{const query=mentionQuery();mentionList.replaceChildren();mentionIndex=0;const members=topic()?.members||[];mentionMatches=query?(state?.agents||[]).filter(a=>members.includes('bot:'+a.id)&&a.id.startsWith(query[1].toLowerCase())):[];mentionList.hidden=!mentionMatches.length;$('body').setAttribute('aria-expanded',String(!mentionList.hidden));mentionMatches.forEach((member,index)=>{const option=element('button','mention-option',member.name+' @'+member.id);option.type='button';option.id='mention-option-'+index;option.setAttribute('role','option');option.setAttribute('aria-selected',String(index===0));option.onclick=()=>chooseMention(index);mentionList.append(option);});});
 $('stop').onclick=()=>action(async()=>{if(!topicId)return;await post('/stop',{topic_id:topicId});await fetchTopics();});
 $('mailbox-avatar-form').onsubmit=e=>{e.preventDefault();avatarSettings[$('mailbox-avatar-actor').value]={initial:$('mailbox-avatar-initial').value.slice(0,2),color:$('mailbox-avatar-color').value,character:$('mailbox-avatar-character').value};storage('localStorage','setItem','roundtable-avatars',JSON.stringify(avatarSettings));closeDialog('mailbox-avatar-dialog');signature='';render();details();};
 // Desktop layout preference; keyboard and pointer resizing share one clamp.
 const shell=document.querySelector('.app-shell'), resize=$('mailbox-resize');
 let sidebarWidth=Number(storage('localStorage','getItem','roundtable-sidebar-width'))||280;
 function setSidebarWidth(width) {
  sidebarWidth=Math.max(240,Math.min(400,width));
  shell.style.setProperty('--mailbox-sidebar-width',sidebarWidth+'px');
  resize.setAttribute('aria-valuenow',String(sidebarWidth));
  storage('localStorage','setItem','roundtable-sidebar-width',String(sidebarWidth));
 }
 setSidebarWidth(sidebarWidth);
 $('mailbox-collapse').onclick=()=>{
  const compact=shell.classList.toggle('sidebar-compact');
  $('mailbox-collapse').setAttribute('aria-expanded',String(!compact));
 };
 resize.addEventListener('keydown',event=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  event.preventDefault();
  setSidebarWidth(event.key==='Home'?240:event.key==='End'?400:sidebarWidth+(event.key==='ArrowLeft'?-10:10));
 });
 resize.addEventListener('pointerdown',event=>{
  if(event.button!==0)return;
  resize.setPointerCapture(event.pointerId);
 });
 resize.addEventListener('pointermove',event=>{
  if(resize.hasPointerCapture(event.pointerId))setSidebarWidth(event.clientX-shell.getBoundingClientRect().left);
 });
 resize.addEventListener('pointerup',event=>{
  if(resize.hasPointerCapture(event.pointerId))resize.releasePointerCapture(event.pointerId);
 });
 const preferred=storage('localStorage','getItem','roundtable-theme')||'system';$('mailbox-theme').value=['system','light','dark'].includes(preferred)?preferred:'system';function theme(){const value=$('mailbox-theme').value;document.documentElement.dataset.theme=value==='system'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):value;storage('localStorage','setItem','roundtable-theme',value);}$('mailbox-theme').onchange=theme;matchMedia('(prefers-color-scheme: dark)').addEventListener('change',theme);theme();
 document.querySelectorAll('[data-mailbox-close]').forEach(n=>n.onclick=()=>n.closest('dialog').close());
 setInterval(()=>{if(active&&state)fetchTopics().catch(e=>setError(e));},1800);render();return {render,refresh:fetchTopics};
})();
