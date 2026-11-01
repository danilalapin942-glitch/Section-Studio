/* Local disk recovery survives server restarts and changing localhost ports. */
(function(root){'use strict';
 function init(api){const $=id=>document.getElementById(id);let debounce=0,deadline=0,busy=false,pending=false,sequence=0,last=null,error=null;
  function message(text,failed=false){$('recoveryState').textContent=text;$('recoveryState').classList.toggle('warning',failed);$('recoveryBadge').textContent=failed?' · ошибка, сохрани JSON':last?' · копия сохранена':StudioNative.available?' · включено':' · сохраняй JSON';$('recoveryBadge').classList.toggle('warning',failed);}
  async function refresh(){if(!StudioNative.available){message('Автовосстановление доступно при запуске Start_Section_Studio.bat. В HTML сохраняй JSON вручную.');$('recoverySave').disabled=true;return;}
   try{const r=await StudioNative.recoveryList(),select=$('recoverySelect'),previous=select.value;select.replaceChildren();for(const item of r.snapshots){const o=document.createElement('option');o.value=item.id;o.textContent=item.name+' · '+new Date(item.savedAt).toLocaleString()+(item.sourceName?' · '+item.sourceName:'');select.append(o);}if(r.snapshots.some(s=>s.id===previous))select.value=previous;$('recoveryRestore').disabled=!r.snapshots.length;
    if(r.warnings.length)message('Есть повреждённые снимки; показаны проверенные копии. Можно восстановить предыдущую.',true);
    else if(!last&&!error)message(r.snapshots.length?'Найдены сохранённые копии. Выбери проект для восстановления.':'Автосохранение включено. Копия появится после открытия или изменения проекта.');
   }catch(e){error=e.message;message('Автовосстановление: '+e.message+' Сохрани JSON вручную.',true);}
  }
  function touch(){sequence++;pending=true;clearTimeout(debounce);debounce=setTimeout(save,1500);if(!deadline)deadline=setTimeout(save,10000);}
  async function save(){clearTimeout(debounce);clearTimeout(deadline);debounce=deadline=0;if(!StudioNative.available)return null;if(busy){pending=true;return null;}const revision=sequence,project=api.getProject();busy=true;pending=false;$('recoverySave').disabled=true;
   try{const errors=SectionCore.validate(project,false);if(errors.length)throw Error(errors[0]);const r=await StudioNative.recoverySave(project);last=r.snapshot;error=null;message('Автосохранено: '+project.name+' · '+new Date(last.savedAt).toLocaleTimeString()+'. Хранятся три последние проверенные копии.');await refresh();return r;}
   catch(e){error=e.message;message('Автосохранение не выполнено: '+e.message+' Сохрани JSON вручную.',true);return null;}
   finally{busy=false;$('recoverySave').disabled=false;if(pending||revision!==sequence){pending=true;clearTimeout(debounce);debounce=setTimeout(save,1500);}}
  }
  async function restore(id){const revision=sequence;if(api.hasChanges()&&!confirm('Восстановить выбранную копию? Текущий проект останется в истории отмены.'))return null;
   try{const r=await StudioNative.recoveryLoad(id);if(revision!==sequence)throw Error('Проект изменился во время загрузки. Повтори восстановление.');api.restore(r.project);api.notice('Восстановлен проект '+r.project.name+'. Нативные проверки нужно выполнить заново.');message('Проект восстановлен из копии от '+new Date(r.snapshot.savedAt).toLocaleString()+'.');return r;}
   catch(e){message('Восстановление не выполнено: '+e.message,true);api.notice(e.message,true);return null;}
  }
  $('recoverySave').onclick=save;$('recoveryRefresh').onclick=refresh;$('recoveryRestore').onclick=()=>restore($('recoverySelect').value);
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&pending&&!busy)save();});
  refresh();return {touch,save,restore,refresh,state:()=>({busy,pending,last,error})};
 }
 root.SectionRecoveryUI={init};
})(globalThis);
