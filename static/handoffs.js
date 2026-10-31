'use strict';
// Same task IDs and event model as native MCP. All remote text stays inert textContent.
window.HandoffUI = (() => {
 let mode='discussion', roomId='', taskId='', assignmentId='', snapshot=null, cursor=0, events=[], generation=0, busy=false, listSignature='', detailSignature='';
 const name = actor => actor==='user'?t('human'):actor==='system'?t('taskSystem'):state?.agents.find(a=>a.id===actor.replace(/^bot:/,''))?.name||actor.replace(/^bot:/,'');
 const status = value => t('task_'+value);
 const stamp = value => new Date(value*1000).toLocaleTimeString(language==='zh'?'zh-CN':'en-US',{hour:'2-digit',minute:'2-digit'});
 const safeText = (tag,cls,value) => element(tag,cls,value);
 const endpoint = suffix => roomPath('/tasks'+suffix);
 const post = (suffix,body) => api(endpoint(suffix),roomAuth(),body);
 function reset(){
  taskId='';assignmentId='';snapshot=null;cursor=0;events=[];generation++;busy=false;listSignature='';detailSignature='';$('task-note').value='';
  for(const id of ['task-header','assignment-switch','handoff-instruction','handoff-events'])$(id).replaceChildren();
  $('cancel-task').disabled=true;$('retry-task').hidden=true;$('task-more').hidden=true;
  $('task-note').disabled=true;$('task-note-form').querySelector('button').disabled=true;
 }
 const stillViewing=(room,task)=>active?.id===room&&taskId===task;
 function setMode(value){mode=value;generation++;busy=false;renderState();}
 async function openTask(id){reset();taskId=id;mode='tasks';render();await fetchTask(true);}
 async function fetchTask(force=false){
  if(!taskId||!active||(busy&&!force))return;
  const seq=++generation,currentRoom=active.id,currentTask=taskId;busy=true;
  try{
   const data=await post('/query',{task_id:currentTask,after:cursor});
   if(seq!==generation||active?.id!==currentRoom||taskId!==currentTask)return;
   snapshot=data;const known=new Set(events.map(e=>e.id));events.push(...data.events.filter(e=>!known.has(e.id)));cursor=data.cursor;renderDetail();
  }catch(error){if(seq===generation)setError(error);}
  finally{if(seq===generation)busy=false;}
 }
 function render(){
  if(roomId!==(active?.id||'')){roomId=active?.id||'';reset();}
  const connected=Boolean(active&&state),show=connected&&mode==='tasks';
  $('discussion-view').classList.toggle('selected',!show);$('task-view').classList.toggle('selected',show);
  $('task-view').textContent=t('taskTab')+(state?.tasks?.length?` (${state.tasks.length})`:'');
  $('new-task').disabled=!connected;
  $('handoffs-view').hidden=!show;$('messages').hidden=show;$('composer-wrap').hidden=show;$('thread-bar').hidden=show||!connected;
  if(show)$('welcome').hidden=true;
  if(!show)return;
  $('status').textContent=t('taskTab');$('status').classList.remove('running');
  $('task-list').hidden=Boolean(taskId);$('task-thread').hidden=!taskId;
  if(taskId){renderDetail();void fetchTask();return;}
  const signature=JSON.stringify([language,state.tasks]);if(listSignature===signature)return;listSignature=signature;
  $('task-list').replaceChildren();
  if(!state.tasks?.length){const empty=safeText('div','empty-thread',t('noTasks'));$('task-list').append(empty);return;}
  for(const item of state.tasks){
   const task=item.task,card=safeText('button','task-card');card.type='button';card.dataset.taskId=task.id;
   const top=safeText('span','task-card-meta');top.append(safeText('span','avatar small-avatar',task.origin==='user'?'↗':'◈'),safeText('span','',name(task.origin)),safeText('span','task-status',status(task.status)),safeText('time','',stamp(task.created)));
   card.append(top,safeText('strong','task-card-title',task.title),safeText('span','task-card-context',task.context.slice(0,220)));
   const handoffs=safeText('span','task-card-workers');for(const a of item.assignments)handoffs.append(safeText('span','handoff-mini',`${name(a.worker)} · ${status(a.status)}`));
   card.append(handoffs,safeText('span','task-card-id',task.id));card.onclick=()=>action(()=>openTask(task.id));$('task-list').append(card);
  }
 }
 function renderDetail(){
  if(!snapshot){$('task-header').textContent=t('taskLoading');return;}
  const signature=JSON.stringify([language,snapshot.task,snapshot.budget,snapshot.assignments,events,assignmentId]);if(signature===detailSignature){$('status').textContent=status(snapshot.task.status);$('status').classList.toggle('running',snapshot.task.status==='running');return;}detailSignature=signature;
  const task=snapshot.task;$('status').textContent=status(task.status);$('status').classList.toggle('running',task.status==='running');$('task-note').disabled=false;$('task-note-form').querySelector('button').disabled=false;
  $('task-header').replaceChildren(safeText('h2','',task.title),safeText('p','task-meta',`${name(task.origin)} → ${t('taskFanIn')} · ${status(task.status)} · ${task.id}`));
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
 function createDialog(){
  if(!active||!state)throw new Error('needConnection');
  $('task-create-form').reset();$('task-workers').replaceChildren();
  for(const agent of state.agents){const row=safeText('label','task-worker-row');const check=document.createElement('input');check.type='checkbox';check.value=agent.id;check.checked=true;const title=safeText('span','',name(agent.id));const input=document.createElement('textarea');input.rows=2;input.maxLength=4000;input.placeholder=t('workerInstruction');input.setAttribute('aria-label',`${name(agent.id)} ${t('workerInstruction')}`);input.dataset.worker=agent.id;row.append(check,title,input);$('task-workers').append(row);}
  openDialog('task-create-dialog');
 }
 $('discussion-view').onclick=()=>setMode('discussion');$('task-view').onclick=()=>setMode('tasks');
 $('new-task').onclick=()=>action(createDialog);
 $('task-back').onclick=()=>{reset();render();};$('task-more').onclick=()=>action(()=>fetchTask(true));
 $('task-create-dialog').querySelector('.close').onclick=()=>closeDialog('task-create-dialog');
 $('task-create-form').onsubmit=event=>{event.preventDefault();if($('create-task').disabled)return;$('create-task').disabled=true;action(async()=>{
  const room=active.id;
  const assignments=[...$('task-workers').querySelectorAll('input:checked')].map(input=>({worker:input.value,instruction:input.closest('label').querySelector('textarea').value}));
  const result=await post('',{title:$('task-title').value,context:$('task-context').value,assignments,budget:Number($('task-budget').value),request_id:crypto.randomUUID()});
  closeDialog('task-create-dialog');if(active?.id!==room)return;await refresh(true);if(active?.id===room)await openTask(result.task_id);
 },$('task-create-dialog')).finally(()=>{$('create-task').disabled=false;});};
 $('task-note-form').onsubmit=event=>{event.preventDefault();if(!snapshot)return;action(async()=>{
  const room=active.id,task=taskId,draft=$('task-note').value;
  await post('/context',{task_id:task,assignment_id:assignmentId,body:draft,request_id:crypto.randomUUID()});
  if(!stillViewing(room,task))return;if($('task-note').value===draft)$('task-note').value='';await fetchTask(true);
 });};
 async function mutate(operation){
  if(!snapshot)return;const room=active.id,task=taskId;
  await post('/'+operation,{task_id:task,assignment_id:assignmentId,request_id:crypto.randomUUID()});
  if(!stillViewing(room,task))return;await refresh(true);if(stillViewing(room,task))await fetchTask(true);
 }
 $('cancel-task').onclick=()=>action(()=>mutate('cancel'));
 $('retry-task').onclick=()=>action(()=>mutate('retry'));
 render();return {render,openTask};
})();
