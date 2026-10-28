(function(root){'use strict';
const config=root.SectionStudioLocalConfig;
async function call(path,data){
 if(!config)throw new Error('Запусти Start_Section_Studio.bat для подключения OpenVSP.');
 let response;try{response=await fetch('/api/'+path,{method:data?'POST':'GET',headers:{'X-Section-Studio':config.token,...(data?{'Content-Type':'application/json'}:{})},...(data?{body:JSON.stringify(data)}:{})});}catch{throw new Error('Локальное подключение остановлено. Запусти Start_Section_Studio.bat и оставь окно запуска открытым.');}
 let result;try{result=await response.json();}catch{throw new Error('Некорректный ответ локальной программы.');}
 if(!response.ok||result.error)throw new Error(result.error||'OpenVSP не выполнил подготовку.');return result;
}
root.StudioNative={available:!!config,status:()=>call('status'),configure:executable=>call('configure',{executable}),pick:()=>call('pick',{}),prepare:data=>call('prepare',data),audit:data=>call('audit',data),verifyRepair:data=>call('verify-repair',data),auditTri:data=>call('machline-tri',data)};
})(globalThis);
