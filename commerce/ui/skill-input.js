/* Controlled task fields over the original skill input; unknown keys round-trip. */
window.CommerceSkillInput=(ui)=>{
 const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
 function read(raw){let value;try{value=JSON.parse(raw)}catch{return null}if(!object(value)||('goal'in value&&typeof value.goal!=='string')||('scope'in value&&!object(value.scope))||('facts'in value&&(!Array.isArray(value.facts)||value.facts.some(r=>!object(r)||['id','text','source_ref','label'].some(k=>k in r&&typeof r[k]!=='string')))))return null;const scope=value.scope||{};if(['marketplace','currency'].some(k=>k in scope&&typeof scope[k]!=='string'))return null;if('period'in scope&&typeof scope.period!=='string'&&(!object(scope.period)||['start','end'].some(k=>k in scope.period&&typeof scope.period[k]!=='string')))return null;return value}
 function write(raw,path,value){
  const data=read(raw);if(!data)throw Error('invalid_json');
  if(path==='goal')data.goal=value;
  else if(/^scope\.(marketplace|currency|period)$/.test(path)){data.scope=data.scope||{};data.scope[path.split('.')[1]]=value}
  else if(/^scope\.period\.(start|end)$/.test(path)){data.scope=data.scope||{};if(data.scope.period!==undefined&&!object(data.scope.period))throw Error('invalid_json');data.scope.period=data.scope.period||{};data.scope.period[path.split('.')[2]]=value}
  else {const m=/^facts\.(\d+)\.(id|text|source_ref|label)$/.exec(path);if(!m||!data.facts?.[Number(m[1])])throw Error('invalid_json');if(m[2]==='label'&&!['provided','synthetic','estimate','unknown'].includes(value))throw Error('invalid_json');data.facts[Number(m[1])][m[2]]=value}
  return JSON.stringify(data,null,2);
 }
 function add(raw){const data=read(raw);if(!data)throw Error('invalid_json');const rows=data.facts||[],ids=new Set(rows.map(r=>r.id));let n=1;while(ids.has('F'+n))n++;data.facts=[...rows,{id:'F'+n,text:'',source_ref:'',label:'unknown'}];return JSON.stringify(data,null,2)}
 function remove(raw,index){const data=read(raw);if(!data||!Number.isInteger(index)||!data.facts?.[index])throw Error('invalid_json');data.facts=data.facts.filter((_,i)=>i!==index);return JSON.stringify(data,null,2)}
 function view(raw){
  const data=read(raw);if(!data)return ui.alert('当前JSON不能转为任务表单，请在高级JSON中核对；原输入已保留。','danger');
  const scope=data.scope||{},period=scope.period===undefined?{}:scope.period,field=(label,key,value,area=false)=>ui.field(label,area?`<textarea class="ui-control" data-skill-field="${ui.escape(key)}" rows="3">${ui.escape(value??'')}</textarea>`:ui.input({'data-skill-field':key,value:value??''}));
  return `<section aria-label="技能任务表单"><div class="skills-task-fields">${field('本次任务目标','goal',data.goal,true)}${field('站点或市场','scope.marketplace',scope.marketplace)}${field('金额币种','scope.currency',scope.currency)}${typeof period==='string'?field('数据期间','scope.period',period):field('期间开始','scope.period.start',period.start)+field('期间结束','scope.period.end',period.end)}</div><h4>本次任务依据</h4>${(data.facts||[]).map((r,i)=>`<section class="skills-task-fact"><header><strong>${ui.escape(r.id||'未指定ID')}</strong>${ui.button({label:'移除此条依据',attrs:{'data-skills-action':'input-remove-fact','data-fact':i}})}</header>${field('商品或业务事实','facts.'+i+'.text',r.text,true)}<div class="skills-task-fields">${field('依据ID','facts.'+i+'.id',r.id)}${field('原始来源或记录位置','facts.'+i+'.source_ref',r.source_ref)}${ui.field('资料性质',ui.select({'data-skill-field':'facts.'+i+'.label',value:r.label||'unknown',options:[{value:'unknown',label:'未知 / 待核对'},{value:'provided',label:'调用者提供'},{value:'synthetic',label:'合成示例'},{value:'estimate',label:'估算'}]}))}</div></section>`).join('')||ui.empty('尚无任务依据。填写事实与原始来源，未知内容保持待核对。')}${ui.button({label:'添加一条依据',attrs:{'data-skills-action':'input-add-fact'}})}</section>`;
 }
 return Object.freeze({read,write,add,remove,view});
};
