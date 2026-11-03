'use strict';
// Same task IDs and event model as native MCP. All remote text stays inert textContent.
window.HandoffUI = (() => {
 let createTopicId='',timelineRoom='',timelineGeneration=0;
 const timelineTasks=new Map();
 const actorId=value=>['user','system'].includes(value)?value:'bot:'+value.replace(/^bot:/,'');
 const detailDialog=document.createElement('dialog');detailDialog.id='task-detail-dialog';detailDialog.className='wide-dialog';detailDialog.setAttribute('aria-labelledby','task-header');document.body.append(detailDialog);detailDialog.append($('handoffs-view'));$('handoffs-view').hidden=false;$('task-list').hidden=true;
 const dialogError=element('p','dialog-error');dialogError.setAttribute('role','alert');detailDialog.append(dialogError);
 detailDialog.addEventListener('close',()=>{taskId='';generation++;busy=false;});
 let roomId='', taskId='', assignmentId='', snapshot=null, cursor=0, events=[], generation=0, busy=false, detailSignature='';
 const name = actor => {if(actor==='user')return t('human');if(actor==='system')return t('taskSystem');const agent=state?.agents.find(a=>a.id===actor.replace(/^bot:/,''));return agent?.deleted?t('botDeleted'):agent?.name||actor.replace(/^bot:/,'');};
 const status = value => t('task_'+value);
 const stamp = value => new Date(value*1000).toLocaleTimeString(language==='zh'?'zh-CN':'en-US',{hour:'2-digit',minute:'2-digit'});
 const safeText = (tag,cls,value) => element(tag,cls,value);
 const endpoint = suffix => roomPath('/tasks'+suffix);
 const post = (suffix,body) => api(endpoint(suffix),roomAuth(),body);
 function reset(){
  taskId='';assignmentId='';snapshot=null;cursor=0;events=[];generation++;busy=false;detailSignature='';$('task-note').value='';
  for(const id of ['task-list','task-header','assignment-switch','handoff-instruction','handoff-events'])$(id).replaceChildren();
  $('cancel-task').disabled=true;$('retry-task').hidden=true;$('task-more').hidden=true;
  $('task-note').disabled=true;$('task-note-form').querySelector('button').disabled=true;
 }
 const stillViewing=(room,task)=>active?.id===room&&taskId===task;
 async function openTask(id){reset();taskId=id;$('task-thread').hidden=false;openDialog('task-detail-dialog');renderDetail();await fetchTask(true);}
 async function fetchTask(force=false){
  if(!taskId||!active||(busy&&!force))return;
  const seq=++generation,currentRoom=active.id,currentTask=taskId;busy=true;
  try{
   const data=await post('/query',{task_id:currentTask,after:cursor});
   if(seq!==generation||active?.id!==currentRoom||taskId!==currentTask)return;
   snapshot=data;const known=new Set(events.map(e=>e.id));events.push(...data.events.filter(e=>!known.has(e.id)));cursor=data.cursor;renderDetail();
  }catch(error){if(seq===generation)setError(error,detailDialog);}
  finally{if(seq===generation)busy=false;}
 }
 function render(){
  if(roomId!==(active?.id||'')){roomId=active?.id||'';reset();detailDialog.close();}
  if(taskId&&detailDialog.open){renderDetail();void fetchTask();}
 }
 function topicTasks(topicId){return (state?.tasks||[]).filter(item=>item.task.topic_id===topicId);}
 function topicHasTasks(topicId){return topicTasks(topicId).length>0;}
 async function loadTimeline(topicId){
  const currentRoom=active?.id;if(!currentRoom)return;
  if(timelineRoom!==currentRoom){timelineRoom=currentRoom;timelineGeneration++;timelineTasks.clear();}
  const seq=timelineGeneration;
  // Lists contain only previews; fetch the existing scoped, paginated event API.
  for(const item of topicTasks(topicId)){
   const id=item.task.id,version=JSON.stringify(item),cached=timelineTasks.get(id);
   if(cached?.version===version)continue;
   const entry=cached||{events:[],cursor:0,snapshot:null,version:''};
   let more=true;
   while(more){
    const data=await post('/query',{task_id:id,after:entry.cursor});
    if(active?.id!==currentRoom||seq!==timelineGeneration)return;
    const known=new Set(entry.events.map(event=>event.id));entry.events.push(...data.events.filter(event=>!known.has(event.id)));
    entry.cursor=data.cursor;entry.snapshot=data;more=data.has_more;
   }
   entry.version=version;timelineTasks.set(id,entry);
  }
 }
 function syncCards(container,topicId,messageNode,updateMessage){
  if(timelineRoom!==(active?.id||'')){timelineRoom=active?.id||'';timelineGeneration++;timelineTasks.clear();}
  const items=topicTasks(topicId),ids=new Set(items.map(item=>item.task.id)),nodes=new Map([...container.children].map(node=>[node.dataset.timelineId,node]));
  for(const old of container.querySelectorAll('[data-task-entry]'))if(!ids.has(old.dataset.taskEntry))old.remove();
  for(const item of items){
   const task=item.task,cached=timelineTasks.get(task.id),snapshot=cached?.snapshot;
   const actors=[...new Set([actorId(task.origin),...item.assignments.map(a=>actorId(a.worker))])];
   let article=nodes.get('task:'+task.id);
   if(!article){article=messageNode({id:'task:'+task.id,sender:actorId(task.origin),created:task.created,body:''},false);article.classList.remove('mailbox-message');article.classList.add('task-message');delete article.dataset.messageId;article.dataset.timelineId='task:'+task.id;article.dataset.taskEntry=task.id;const bubble=element('div','task-bubble');bubble.append(article.querySelector('.message-body'));article.querySelector('.message-content').append(bubble);container.append(article);nodes.set(article.dataset.timelineId,article);}
   article.dataset.actors=JSON.stringify(actors);
   updateMessage(article,{sender:actorId(task.origin),created:task.created,body:t('taskAssigned')+(language==='zh'?'：':': ')+(snapshot?.task.context||task.context||task.title)});
   let card=article.querySelector('.task-card');if(!card){card=safeText('button','task-card');card.type='button';card.dataset.taskId=task.id;card.onclick=()=>action(()=>openTask(task.id),detailDialog);article.querySelector('.task-bubble').append(card);}
   card.dataset.created=String(task.created);card.dataset.actors=JSON.stringify(actors);
   const signature=JSON.stringify([language,item,snapshot?.task.context,actors.map(name)]);
   if(card.dataset.signature!==signature){
    card.dataset.signature=signature;
    const displayStatus=task.status==='running'&&item.assignments.every(a=>a.status==='queued')?'queued':task.status;
    const top=safeText('span','task-card-meta');top.append(safeText('span','task-status',status(displayStatus)));
    const workers=safeText('span','task-card-workers');for(const a of item.assignments)workers.append(safeText('span','handoff-mini',item.assignments.length===1?name(a.worker):`${name(a.worker)} · ${status(a.status)}`));
    card.replaceChildren(top,safeText('strong','task-card-title',task.title),workers);
    card.setAttribute('aria-label',`${task.title} · ${item.assignments.map(a=>name(a.worker)).join(', ')} · ${status(displayStatus)}`);
   }
   for(const event of cached?.events||[]){
    if(!['claimed','progress','completed','failed','context'].includes(event.kind))continue;
    const id='event:'+event.id;let reply=nodes.get(id);
    const assignment=snapshot.assignments.find(a=>a.id===event.assignment);
    const body=event.kind==='claimed'?t('taskReceipt').replace('{origin}',name(task.origin)).replace('{instruction}',assignment?.instruction||task.title):event.body;
    if(!reply){reply=messageNode({id,sender:actorId(event.actor),created:event.created,body},false);reply.classList.remove('mailbox-message');reply.classList.add('task-reply');delete reply.dataset.messageId;reply.dataset.timelineId=id;reply.dataset.taskEntry=task.id;reply.dataset.eventId=String(event.id);reply.dataset.actors=JSON.stringify(actors);
    const label=safeText('span','task-reply-label');reply.querySelector('.message-content').prepend(label);container.append(reply);nodes.set(id,reply);}
    updateMessage(reply,{sender:actorId(event.actor),created:event.created,body});reply.dataset.actors=JSON.stringify(actors);
    const label=reply.querySelector('.task-reply-label'),text=t('taskReply').replace('{title}',task.title);if(label.textContent!==text)label.textContent=text;
   }
  }
 }
 function renderDetail(){
  if(!snapshot){$('task-header').textContent=t('taskLoading');return;}
  const signature=JSON.stringify([language,snapshot.task,snapshot.budget,snapshot.assignments,events,assignmentId,state?.agents.map(a=>[a.id,a.name,a.deleted])]);if(signature===detailSignature)return;detailSignature=signature;
  const task=snapshot.task;$('task-note').disabled=false;$('task-note-form').querySelector('button').disabled=false;
  $('task-header').replaceChildren(safeText('h2','',task.title),safeText('p','task-meta',`${name(task.origin)} · ${status(task.status)}`));
  const budget=snapshot.budget;$('task-header').append(safeText('p','muted small',`${t('taskBudget')}: ${budget.used}/${budget.limit}`));
  $('assignment-switch').replaceChildren();const overview=safeText('button',!assignmentId?'selected':'',t('taskOverview'));overview.type='button';overview.onclick=()=>{assignmentId='';renderDetail();};$('assignment-switch').append(overview);
  for(const a of snapshot.assignments){const button=safeText('button',assignmentId===a.id?'selected':'',`${name(a.worker)} · ${status(a.status)}`);button.type='button';button.dataset.assignmentId=a.id;button.onclick=()=>{assignmentId=a.id;renderDetail();};$('assignment-switch').append(button);}
  const assignment=snapshot.assignments.find(a=>a.id===assignmentId);
  $('handoff-instruction').replaceChildren(safeText('div','task-route',assignment?`${name(task.origin)} → ${name(assignment.worker)}`:t('taskSharedContext')),safeText('p','',assignment?assignment.instruction:task.context));
  $('handoff-events').replaceChildren();
  for(const event of events.filter(e=>assignmentId?(!e.assignment||e.assignment===assignmentId):true)){
   const article=safeText('article','handoff-event'+(event.actor==='user'?' human':''));article.dataset.eventId=event.id;
   article.append(safeText('div','message-meta',`${name(event.actor)} · ${t('event_'+event.kind)} · ${stamp(event.created)}`));
   if(event.body)article.append(safeText('p','message-body',event.body));$('handoff-events').append(article);
  }
  for(const a of snapshot.assignments.filter(a=>!assignmentId||a.id===assignmentId)){
   if(a.status==='completed'||a.status==='failed'){
    const result=safeText('section','handoff-result');result.append(safeText('strong','',`${name(a.worker)} · ${status(a.status)}`),safeText('p','',a.result));
    for(const artifact of a.artifacts){result.append(safeText('h3','',artifact.name),safeText('pre','',artifact.text));}$('handoff-events').append(result);
   }
  }
  $('task-more').hidden=!snapshot.has_more;
  $('cancel-task').disabled=!['running','failed'].includes(task.status);$('retry-task').hidden=assignment?.status!=='failed'||!['running','failed'].includes(task.status);
 }
 function syncWorkers(){const count=$('task-workers').querySelectorAll('input:checked').length;$('create-task').disabled=count===0;$('task-budget').value=Math.max(1,count);$('task-budget').min=Math.max(1,count);}
 function createDialog(topicId='',members=null){
  createTopicId=topicId||state?.roundtable?.id||'';
  if(!active||!state)throw new Error('needConnection');
  $('task-create-form').reset();$('task-workers').replaceChildren();
  for(const agent of state.agents.filter(agent=>!agent.disabled&&!agent.deleted&&(!members||members.includes('bot:'+agent.id)))){const row=safeText('label','task-worker-row');const check=document.createElement('input');check.type='checkbox';check.value=agent.id;check.checked=false;check.onchange=syncWorkers;const title=safeText('span','',name(agent.id));const input=document.createElement('textarea');input.rows=2;input.maxLength=4000;input.placeholder=t('workerInstruction');input.setAttribute('aria-label',`${name(agent.id)} ${t('workerInstruction')}`);input.dataset.worker=agent.id;row.append(check,title,input);$('task-workers').append(row);}
  syncWorkers();openDialog('task-create-dialog');
 }
 $('task-back').onclick=()=>detailDialog.close();$('task-more').onclick=()=>action(()=>fetchTask(true));
 $('task-create-dialog').querySelector('.close').onclick=()=>closeDialog('task-create-dialog');
 $('task-create-form').onsubmit=event=>{event.preventDefault();if($('create-task').disabled)return;$('create-task').disabled=true;action(async()=>{
  const room=active.id;
  const assignments=[...$('task-workers').querySelectorAll('input:checked')].map(input=>({worker:input.value,instruction:input.closest('label').querySelector('textarea').value}));
  await post('',{title:$('task-title').value,context:$('task-context').value,assignments,budget:Number($('task-budget').value),...(createTopicId?{topic_id:createTopicId}:{}),request_id:crypto.randomUUID()});
  closeDialog('task-create-dialog');if(active?.id!==room)return;await refresh(true);if(active?.id===room){await window.MailboxUI?.refresh();window.MailboxUI?.render();}
 },$('task-create-dialog')).finally(()=>{$('create-task').disabled=false;});};
 $('task-note-form').onsubmit=event=>{event.preventDefault();if(!snapshot)return;action(async()=>{
  const room=active.id,task=taskId,draft=$('task-note').value;
  await post('/context',{task_id:task,assignment_id:assignmentId,body:draft,request_id:crypto.randomUUID()});
  if(!stillViewing(room,task))return;if($('task-note').value===draft)$('task-note').value='';await fetchTask(true);
 },detailDialog);};
 async function mutate(operation){
  if(!snapshot)return;const room=active.id,task=taskId;
  await post('/'+operation,{task_id:task,assignment_id:assignmentId,request_id:crypto.randomUUID()});
  if(!stillViewing(room,task))return;await refresh(true);if(stillViewing(room,task))await fetchTask(true);
 }
 $('cancel-task').onclick=()=>action(()=>mutate('cancel'),detailDialog);
 $('retry-task').onclick=()=>action(()=>mutate('retry'),detailDialog);
 render();return {render,openTask,createDialog,syncCards,loadTimeline,topicHasTasks};
})();
