'use strict';
window.BotManagement = (() => {
 let roster = [], rosterRoom = '', editing = null, deleting = null, secretGeneration = 0;
 const palette = ['sage','sand','rose','blue','slate'];
 const allowed = () => Boolean(state?.can_manage_bots && adminToken === COOKIE_SESSION);
 const command = id => `python scripts/local_runtime.py connect-bot --bot ${id}`;
 function avatar(bot) {
  const color=palette.includes(bot.avatar)?bot.avatar:'sage';
  const node=element('span',`avatar avatar-${color} character-avatar`);
  node.setAttribute('aria-hidden','true');const body=element('span','character-body');body.append(element('span','character-eyes'));node.append(body);return node;
 }
 function button(text, fn, danger=false) { const node=element('button',danger?'danger compact':'secondary compact',text);node.type='button';node.onclick=fn;return node; }
 function render() {
  const can=allowed();$('bot-add').hidden=!can;$('bot-local-only').hidden=can;
  const members=rosterRoom===active?.id&&can?roster:(state?.agents||bots);
  $('bot-cards').replaceChildren();
  for(const bot of members){
   const row=element('section','bot-card');row.dataset.botId=bot.id;
   const info=element('div','bot-card-info'),heading=element('div','bot-card-heading');
   heading.append(avatar(bot),element('h3','',bot.deleted?t('botDeleted'):bot.name));
   info.append(heading,element('p','',bot.deleted?t('botDeleted'):bot.disabled?t('botDisabled'):memberEvidence(bot.id)));
   if(!bot.deleted){info.append(element('code','',bot.id),element('p','',t({'grok-routine':'wakeRoutine','mcp-events':'wakeEvents','poll':'wakePoll'}[bot.wake||wakeMethods[bot.id]]||'botSetupNeeded')));}
   row.append(info);
   if(can&&!bot.deleted){const controls=element('div','bot-row-actions');controls.append(button(t('editBot'),()=>edit(bot)),button(t(bot.disabled?'restoreBot':'disableBot'),()=>changeStatus(bot)),button(t('deleteBot'),()=>remove(bot),true));row.append(controls);}
   $('bot-cards').append(row);
  }
 }
 async function load() {
  const room=active?.id;if(!room)return;
  if(allowed()){const data=await api(roomPath('/bot-management'),COOKIE_SESSION);if(active?.id!==room)return;roster=data.bots;rosterRoom=room;}
  else {await reloadWorkspace();roster=[];rosterRoom='';}
  render();
 }
 async function open(){openDialog('directory-dialog');await load();}
 function edit(bot=null){
  editing=bot;$('bot-editor-form').reset();$('bot-editor-title').textContent=t(bot?'editBot':'addBot');
  $('bot-name').value=bot?.name||'';$('bot-id').value=bot?.id||'';$('bot-id').disabled=Boolean(bot);$('bot-id-field').hidden=Boolean(bot);
  $('bot-kind-field').hidden=Boolean(bot);$('bot-kind').value=bot?.kind||'mailbox';$('bot-wake').value=bot?.wake||wakeMethods[bot?.id]||'poll';$('bot-limit').value=bot?.allowance_limit??20;
  $('bot-create-warning').hidden=Boolean(bot);$('bot-connect-command').hidden=!bot;$('bot-connect-command').textContent=bot?command(bot.id):'';
  $('bot-avatar-options').replaceChildren();
  for(const color of palette){const label=element('label','avatar-option'),radio=element('input');radio.type='radio';radio.name='avatar';radio.value=color;radio.checked=color===(bot?.avatar||'sage');label.append(radio,avatar({avatar:color}),element('span','small',t('avatar_'+color)));$('bot-avatar-options').append(label);}
  $('bot-save').textContent=t(bot?'save':'addBot');openDialog('bot-editor-dialog');$('bot-name').focus();
 }
 async function changeStatus(bot){
  if(!bot.disabled&&!confirm(t('botDisableHint')))return;
  await action(async()=>{await api(roomPath(`/bot-management/${bot.id}/${bot.disabled?'restore':'disable'}`),COOKIE_SESSION,{});await refresh(true);await load();},$('directory-dialog'));
 }
 function remove(bot){deleting=bot;$('bot-delete-form').reset();$('bot-delete-label').textContent=t('botDeleteConfirm').replace('{name}',bot.name);$('bot-delete-submit').disabled=true;openDialog('bot-delete-dialog');$('bot-delete-confirm').focus();}
 $('bot-delete-confirm').oninput=()=>{$('bot-delete-submit').disabled=$('bot-delete-confirm').value!==deleting?.name;};
 $('bot-delete-form').onsubmit=event=>{event.preventDefault();action(async()=>{if(!deleting)return;const bot=deleting;$('bot-delete-submit').disabled=true;try{await api(roomPath(`/bot-management/${bot.id}/delete`),COOKIE_SESSION,{confirm:$('bot-delete-confirm').value});closeDialog('bot-delete-dialog');await refresh(true);await load();}finally{$('bot-delete-submit').disabled=false;}},$('bot-delete-dialog'));};
 $('bot-name').oninput=()=>{if(editing||$('bot-id').dataset.edited)return;$('bot-id').value=$('bot-name').value.toLowerCase().replace(/[^a-z0-9-]+/g,'-').replace(/^[^a-z]+/,'').replace(/-+$/,'').slice(0,40);};
 $('bot-id').oninput=()=>{$('bot-id').dataset.edited='true';};
 $('bot-add').onclick=()=>{delete $('bot-id').dataset.edited;edit();};
 $('bot-editor-form').onsubmit=event=>{
  event.preventDefault();action(async()=>{
   $('bot-save').disabled=true;
   try{
    const values={name:$('bot-name').value,wake:$('bot-wake').value,allowance_limit:Number($('bot-limit').value)};
    values.avatar=document.querySelector('#bot-avatar-options input:checked').value;
    const secretEpoch=secretGeneration;
    const result=await api(roomPath(editing?`/bot-management/${editing.id}/update`:'/bot-management'),COOKIE_SESSION,editing?values:{...values,id:$('bot-id').value,kind:$('bot-kind').value});
    closeDialog('bot-editor-dialog');
    const showToken=Boolean(result.token&&secretEpoch===secretGeneration&&!document.hidden);
    if(showToken){$('bot-created-token').textContent=result.token;$('bot-created-command').textContent=command(result.bot.id);$('bot-copy-status').textContent='';openDialog('bot-token-dialog');}
    await action(async()=>{await refresh(true);await load();},$(showToken?'bot-token-dialog':'directory-dialog'));
    if(result.token&&!showToken)setError(new Error('botTokenCleared'),$('directory-dialog'));
   }finally{$('bot-save').disabled=false;}
  },$('bot-editor-dialog'));
 };
 $('bot-copy-token').onclick=()=>action(async()=>{const value=$('bot-created-token').textContent;if(!value)return;await navigator.clipboard.writeText(value);$('bot-copy-status').textContent=t('tokenCopied');},$('bot-token-dialog'));
 function clearToken(){$('bot-created-token').textContent='';$('bot-created-command').textContent='';$('bot-copy-status').textContent='';}
 $('bot-token-dialog').addEventListener('close',clearToken);
 $('bot-token-dialog').addEventListener('cancel',clearToken);
 function hideToken(){secretGeneration++;clearToken();if($('bot-token-dialog').open)$('bot-token-dialog').close();}
 window.addEventListener('pagehide',hideToken);
 document.addEventListener('visibilitychange',()=>{if(document.hidden)hideToken();});
 return {open,render};
})();
