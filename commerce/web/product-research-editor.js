/* Current-product research revisions. Historical artifacts and task snapshots stay immutable. */
(() => {
  'use strict';
  const clone = value => JSON.parse(JSON.stringify(value));
  const signature = value => JSON.stringify(value);
  const editableParts = ['original','zh','reviewed','kind','source_url','locator'];
  const commonParts = ['language','source_url','captured_at','raw_excerpt','evidence_note','category_rules_url','category_rules_checked'];
  function editableRecord(record) {
    if (!record || typeof record !== 'object' || Array.isArray(record)) throw Error('invalid_research_record');
    if (Object.hasOwn(record,'fields') && (!record.fields || typeof record.fields !== 'object' || Array.isArray(record.fields))) throw Error('invalid_research_record');
    if (record.fields && Object.values(record.fields).some(row=>!row || typeof row !== 'object' || Array.isArray(row))) throw Error('invalid_research_field');
    const result=clone(record);
    // research.validate permits an omitted fields container in a sparse HOLD.
    if (!Object.hasOwn(result,'fields')) result.fields={};
    return result;
  }
  function createDraft(snapshot, selectedTask, spec, key) {
    if (!snapshot?.case?.id || !snapshot.source_sha256) throw Error('workspace_research_context_unavailable');
    if (selectedTask || snapshot.research_context?.selected_explicitly) throw Error('workspace_research_snapshot_read_only');
    const artifact = snapshot.artifacts?.research;
    if (artifact && !artifact.intact) throw Error('workspace_artifact_changed');
    const sourceRecord = artifact ? artifact.payload?.record : {...spec.record,market:snapshot.case.scope.market || ''};
    const record = editableRecord(sourceRecord);
    return {caseId:snapshot.case.id,name:snapshot.name,scope:clone(snapshot.case.scope),source:snapshot.source_sha256,artifactId:artifact?.id || '',base:clone(sourceRecord),record,spec:clone(spec),key,dirty:false,version:0,request:null,unknown:false};
  }
  function changed(draft, key) {
    if (draft.request || draft.unknown) throw Error('workspace_research_save_pending');
    draft.key = key; draft.version++; draft.dirty = signature(draft.record) !== signature(draft.base);
  }
  function editField(draft, field, part, value, key) {
    if (!draft.spec.fields.some(row => row.key === field) || !editableParts.includes(part)) throw Error('invalid_research_field');
    if (draft.request || draft.unknown) throw Error('workspace_research_save_pending');
    const row = draft.record.fields[field] ||= {original:'',zh:'',reviewed:false,kind:'source_statement',source_url:'',locator:''};
    if (part === 'reviewed' && value && (!row.original?.trim() || !row.zh?.trim())) throw Error('workspace_research_review_requires_text');
    if (row[part] === value) return;
    row[part] = value;
    if (part !== 'reviewed') row.reviewed = false;
    changed(draft,key);
  }
  function editCommon(draft, part, value, key) {
    if (!commonParts.includes(part)) throw Error('invalid_research_field');
    if (draft.request || draft.unknown) throw Error('workspace_research_save_pending');
    if (draft.record[part] === value) return;
    draft.record[part] = value;
    if (['language','source_url','captured_at','raw_excerpt'].includes(part)) for (const row of Object.values(draft.record.fields)) row.reviewed = false;
    changed(draft,key);
  }
  function manualRevision(draft, field, key) {
    if (!draft.spec.fields.some(row => row.key === field)) throw Error('invalid_research_field');
    if (draft.request || draft.unknown) throw Error('workspace_research_save_pending');
    const row = draft.record.fields[field];
    if (!row?.translation) return;
    delete row.translation; row.reviewed = false; changed(draft,key);
  }
  function saveArguments(draft) {
    return {case_id:draft.caseId,record:clone(draft.record),expected_source_sha256:draft.source,expected_artifact_id:draft.artifactId,idempotency_key:draft.key};
  }
  function validateReceipt(receipt, args) {
    if (receipt?.schema !== 'workspace-research-save-v1' || receipt.case_id !== args.case_id || !receipt.artifact_id || !/^[a-f0-9]{64}$/.test(receipt.artifact_sha256 || '') || !/^[a-f0-9]{64}$/.test(receipt.source_sha256 || '') || receipt.previous_source_sha256 !== args.expected_source_sha256 || receipt.previous_artifact_id !== args.expected_artifact_id || receipt.external_execution_allowed !== false || receipt.publication_ready !== false) throw Error('workspace_research_receipt_invalid');
    return receipt;
  }
  function matchesReadback(snapshot, receipt) {
    const artifact = snapshot?.artifacts?.research;
    return snapshot?.case?.id === receipt.case_id && snapshot.source_sha256 === receipt.source_sha256 && artifact?.id === receipt.artifact_id && artifact.sha256 === receipt.artifact_sha256 && artifact.intact === true;
  }
  function rebase(draft, snapshot, keepLocal, key, currentSpec=draft.spec) {
    const next = createDraft(snapshot,'',keepLocal?draft.spec:currentSpec,key);
    if (keepLocal) { next.record = clone(draft.record); next.dirty = signature(next.record) !== signature(next.base); }
    return next;
  }
  const errors = {
    workspace_research_snapshot_read_only:'当前是明确选择的研究快照，只读。请返回商品当前研究后补充新版本。',
    workspace_artifact_changed:'原资料完整性异常，不能以此保存新版本。请核对原来源。',
    workspace_source_changed:'商品依据已变化。输入已保留，请读取并核对当前保存版本。',
    workspace_research_conflict:'研究资料已有新版本。输入已保留，请核对后再保存。',
    workspace_research_scope_mismatch:'研究平台或市场与当前商品范围不匹配，未保存；原输入保留。',
    workspace_research_idempotency_conflict:'原保存标识对应的请求不同。请先核对原保存结果，不会自动另发。',
    workspace_research_receipt_invalid:'保存回执未能安全核对。输入已保留，请显式重试同一保存以查询原结果。',
    workspace_research_review_requires_text:'先填写原文和中文，再明确记录校对。',
    unknown_tool:'当前后台尚未加载受保护研究保存，请更新后台后重新读取保存能力。输入已保留。',
  };
  function explain(error) { const code=error?.code || error?.message; return errors[code] || (String(code).startsWith('invalid_')?'输入格式未通过校验，请核对当前字段与来源。':'保存结果尚未确认。输入和原请求已保留，不会自动重发。'); }
  function Editor({api,ui,getCurrent,showDialog,closeDialog,onDirty=()=>{},onSaved=()=>{}}) {
    const esc=ui.escape, uuid=()=>crypto.randomUUID();
    let state=null,sequence=0,dialogGeneration=0;
    const button=(label,action,primary=false,disabled=false)=>ui.button({label,variant:primary?'primary':'secondary',attrs:{type:'button','data-pre-action':action,disabled}});
    const field=(label,control)=>ui.field(label,control);
    const text=(id,value,rows=3,maxlength=16000,extra='')=>`<textarea class="ui-control" id="${id}" rows="${rows}" maxlength="${maxlength}" ${extra}>${esc(value || '')}</textarea>`;
    function current(s=state) {const context=getCurrent();return !!s && state===s && context?.data?.case?.id===s.draft?.caseId && !context.taskId && !context.data.research_context?.selected_explicitly;}
    function dirty() {onDirty(!!state && (!!state.busy || !!state.draft?.dirty || !!state.draft?.unknown));}
    function reportInput() {
      if (!state) return;
      state.check=null;state.latest=null;state.error='';
      const status=document.getElementById('pre-save-state');if(status)status.textContent=state.draft.dirty?'有未保存修改':'当前输入未修改';
      const check=document.getElementById('pre-check-state');if(check)check.textContent='输入已变化，请重新核对缺项。';
      const review=document.getElementById('pre-reviewed'),row=state.draft.record.fields[state.field];
      if(review){review.checked=!!row?.reviewed;review.disabled=state.busy||!row?.original?.trim()||!row?.zh?.trim();}
      dirty();
    }
    function render(focusId='') {
      if (!state) return;
      const prior=document.querySelector('.dialog'),scroll=prior?.scrollTop || 0,active=document.activeElement;
      const remembered=active?.id,selection=active?.selectionStart;
      const s=state,d=s.draft,locked=!!s.busy || !!d?.unknown;
      let body='';
      if (!d) body=`<p role="status">${s.error?esc(s.error):'正在读取当前商品的研究字段与保存能力…'}</p>`;
      else {
        const definition=d.spec.fields.find(row=>row.key===s.field),value=d.record.fields[s.field] || {},issues=s.check?.issues || [];
        body=`<div class="pre-editor"><p><strong>${esc(d.name || d.caseId)}</strong> · SKU ${esc(d.scope.sku || '待核对')} · ${esc(d.record.platform)} · ${esc(d.record.market)}</p><p class="pw-meta">修改会追加当前商品研究版本，保留原记录。填写与人工校对不等于来源或事实已核实。</p>${s.error?ui.alert(esc(s.error),'warning'):''}${!s.capable?ui.alert('当前后台尚未确认原子版本保护，暂不能保存；可以保留输入并重新读取保存能力。','warning'):''}<p id="pre-save-state" role="status">${d.unknown?'原保存结果待确认；编辑已暂停，避免重复保存。':s.busy?'正在处理，请保留当前页面…':d.dirty?'有未保存修改':'当前输入未修改'}</p>`;
        if(s.confirmClose)body+=`<section class="pw-section"><p>当前输入尚未保存。继续编辑，或明确放弃本次输入后离开。</p><div class="pw-form-actions">${button('继续编辑','keep-editing',true)}${button('放弃本次输入','discard')}</div></section>`;
        if(s.latest){
          const latest=s.latest.artifacts?.research?.payload?.record;
          body+=`<section class="pw-section"><h3>核对当前保存版本</h3><p>原研究 ${esc(d.artifactId || '无')} → 当前 ${esc(s.latest.artifacts?.research?.id || '无')}。本地输入尚未覆盖。</p><details><summary>对照原基线、当前保存与本地输入</summary><h4>原编辑基线</h4><pre class="pw-source-text">${esc(JSON.stringify(d.base,null,2))}</pre><h4>当前保存</h4><pre class="pw-source-text">${esc(JSON.stringify(latest || null,null,2))}</pre><h4>本地输入</h4><pre class="pw-source-text">${esc(JSON.stringify(d.record,null,2))}</pre></details><label class="review-check">${ui.input({type:'checkbox',id:'pre-rebase-confirm',checked:!!s.rebaseConfirmed,disabled:locked})}我已对照当前保存版本与本地输入</label><div class="pw-form-actions">${button('采用当前保存版本','adopt-latest',false,locked||!s.rebaseConfirmed)}${button('保留本地输入并采用此基线','rebase-local',false,locked||!s.rebaseConfirmed)}</div></section>`;
        }
        body+=`${field('补充字段',ui.select({id:'pre-field-select','data-pre-select':'field',value:s.field,disabled:locked,options:d.spec.fields.map(row=>({value:row.key,label:row.label+(row.required?' · 必填':' · 可选')}))}))}<div class="pw-input-grid">${field('原文或明确的缺失说明',text('pre-original',value.original,5,6000,`data-pre-field="original" ${locked?'disabled':''}`))}${field(definition?.translatable?'中文对照':'中文说明（非必需译文）',text('pre-zh',value.zh,5,12000,`data-pre-field="zh" ${locked?'disabled':''}`))}</div><div class="pw-input-grid">${field('陈述类型',ui.select({id:'pre-kind','data-pre-field':'kind',value:value.kind||'source_statement',disabled:locked,options:[{value:'source_statement',label:'来源中的陈述'},{value:'inference',label:'推断'},{value:'conflict',label:'存在冲突'},{value:'unverified',label:'待核实'}]}))}${field('原文位置或证据索引',ui.input({id:'pre-locator','data-pre-field':'locator',value:value.locator||'',maxlength:500,disabled:locked}))}</div>${field('本字段来源链接（留空沿用公共来源）',ui.input({id:'pre-field-source','data-pre-field':'source_url',value:value.source_url||'',maxlength:2000,disabled:locked}))}`;
        if(definition?.translatable)body+=`<label class="review-check">${ui.input({type:'checkbox',id:'pre-reviewed','data-pre-field':'reviewed',checked:!!value.reviewed,disabled:locked||!value.original?.trim()||!value.zh?.trim()})}我已对照原文校对这段中文</label>`;
        if(value.translation)body+=`<details><summary>原译文依据</summary><pre class="pw-source-text">${esc(JSON.stringify(value.translation,null,2))}</pre><p>若原文已改变，旧译文依据会继续保留并提示不匹配。明确开始人工修订后，新版本不再沿用旧译文元数据；原版本仍保留。</p>${button('开始人工修订此字段','manual-revision',false,locked)}</details>`;
        body+=`<details ${s.sourcesOpen?'open':''} data-pre-sources><summary>来源、时间与采集范围</summary><p>平台 ${esc(d.record.platform)} · 市场 ${esc(d.record.market)}；绑定当前商品，不自动更改来源范围。</p><div class="pw-input-grid">${field('原文语言',ui.input({id:'pre-language','data-pre-common':'language',value:d.record.language||'',disabled:locked,maxlength:16000}))}${field('实际采集时间（带时区）',ui.input({id:'pre-captured-at','data-pre-common':'captured_at',value:d.record.captured_at||'',disabled:locked,maxlength:16000,placeholder:'填写实际时间，例如 2026-11-17T10:00:00+08:00'}))}</div>${field('公共来源 HTTP(S) 链接',ui.input({id:'pre-source-url','data-pre-common':'source_url',value:d.record.source_url||'',disabled:locked,maxlength:16000}))}${field('支持结论的原文摘录',text('pre-excerpt',d.record.raw_excerpt,4,16000,`data-pre-common="raw_excerpt" ${locked?'disabled':''}`))}${field('证据与限制说明',text('pre-evidence',d.record.evidence_note,2,16000,`data-pre-common="evidence_note" ${locked?'disabled':''}`))}`;
        if(d.record.platform!=='research')body+=`${field('平台/站点/类目规则来源',ui.input({id:'pre-rules-url','data-pre-common':'category_rules_url',value:d.record.category_rules_url||'',disabled:locked,maxlength:16000}))}<label class="review-check">${ui.input({type:'checkbox',id:'pre-rules-checked','data-pre-common':'category_rules_checked',checked:!!d.record.category_rules_checked,disabled:locked})}已按实际站点与类目核对当前必填属性并记录依据</label>`;
        body+=`</details><section class="pw-section"><h3>当前输入的具体缺项</h3><p id="pre-check-state" role="status">${s.check?(issues.length?`${issues.length} 项需补充或核对。`:'本次格式与完整性检查未发现缺项；仍非事实核实。'):'尚未按当前输入核对。'}</p>${issues.length?`<ul>${issues.map((issue,index)=>`<li>${ui.button({label:issue.message,variant:'quiet',attrs:{type:'button','data-pre-action':'focus-issue','data-pre-issue':index,disabled:!!s.busy}})}</li>`).join('')}</ul>`:''}</section><details><summary>高级：研究 JSON 导入与导出</summary><p>JSON只编辑当前表单，保存仍使用同一版本保护。岗位交接中的原批量导入入口继续保留。</p>${button('下载当前研究JSON','export',false,locked)}${field('导入同商品研究JSON',`<input class="ui-control" id="pre-import" type="file" accept=".json,application/json" ${locked?'disabled':''}>`)}</details></div>`;
      }
      const actions=d?`${button('核对当前输入','check',false,locked)}${button('保存研究资料','save',true,locked||!s.capable)}${d.unknown?button('显式重试同一保存','retry',false,!!s.busy):''}${button('读取当前保存版本','latest',false,!!s.busy)}${!s.capable?button('重新读取保存能力','capability',false,!!s.busy):''}${button('关闭','close',false,!!s.busy)}`:button('关闭','close');
      showDialog('补充当前商品研究资料',body,actions);
      const modal=document.querySelector('.dialog');if(modal)modal.scrollTop=scroll;
      const focus=document.getElementById(focusId || remembered || 'pre-field-select');
      if(focus&&!focus.disabled){focus.focus({preventScroll:!focusId});if(focusId)focus.scrollIntoView?.({block:'nearest',inline:'nearest'});if(selection!=null&&focus.setSelectionRange&&focus.type!=='number')focus.setSelectionRange(selection,selection);}
    }
    async function capability(s=state){
      try{const result=await api('commerce_workspace_research_capabilities',{});if(state!==s)return;s.capable=result?.schema==='workspace-research-save-v1'&&result.save_tool==='commerce_workspace_research_save'&&result.atomic_source_and_head===true&&result.idempotent_receipt===true&&result.external_execution_allowed===false;if(!s.capable)s.error='后台未确认原子版本保护，不能保存。';}
      catch(error){if(state===s){s.capable=false;s.error=explain(error);}}
    }
    async function check(s=state){
      if(!s?.draft||s.busy||s.draft.unknown)return false;
      const version=s.draft.version,record=clone(s.draft.record),token=++sequence;
      s.busy=true;s.error='';dirty();render();
      try{const result=await api('commerce_collection_check',{record});if(state!==s||sequence!==token||version!==s.draft.version)return false;s.check=result;return true;}
      catch(error){if(state===s)s.error=explain(error);return false;}
      finally{if(state===s&&sequence===token){s.busy=false;dirty();render();}}
    }
    async function save(retry=false){
      const s=state;if(!s?.draft||s.busy||!s.capable||!current(s))return;
      if(!retry&&s.draft.unknown)return;
      if(!retry&&!await check(s))return;
      if(state!==s||!current(s))return;
      const args=retry?s.draft.request:saveArguments(s.draft);
      if(!args)return;
      s.draft.request=clone(args);s.busy=true;s.error='';dirty();render();
      let receipt;
      try{
        receipt=validateReceipt(await api('commerce_workspace_research_save',clone(args)),args);
        s.receipt=receipt;s.draft.unknown=false;
        const readback=await api('commerce_workspace_get',{case_id:s.draft.caseId});
        if(state!==s)return;
        if(!matchesReadback(readback,receipt)){s.latest=readback;s.error='本次保存回执已取得，但当前商品已有后续更新。输入已保留，请核对当前版本。';s.draft.request=null;return;}
        if(!current(s)){s.error='原商品保存已读回，但当前页面范围已变化。没有替换其他商品。';s.draft.request=null;return;}
        state=null;dirty();closeDialog();onSaved(readback,receipt);
      }catch(error){
        if(state!==s)return;
        const code=error?.code||error?.message;
        s.error=explain(error);
        const definitive=code==='unknown_tool'||code==='workspace_source_changed'||code==='workspace_research_conflict'||code==='workspace_artifact_changed'||code==='workspace_research_scope_mismatch'||code==='workspace_research_idempotency_conflict'||String(code).startsWith('invalid_');
        s.draft.unknown=!definitive;
        if(definitive)s.draft.request=null;
        if(code==='unknown_tool')s.capable=false;
        if(receipt)s.error='本次保存回执已取得，保存后的读取尚未确认。输入与原请求保留，请显式重试同一保存。';
      }finally{if(state===s){s.busy=false;dirty();render();}}
    }
    async function latest(){
      const s=state;if(!s?.draft||s.busy)return;
      s.busy=true;s.error='';dirty();render();
      try{const value=await api('commerce_workspace_get',{case_id:s.draft.caseId});if(state!==s)return;if(value.case?.id!==s.draft.caseId||value.artifacts?.research&&!value.artifacts.research.intact)throw Error('workspace_artifact_changed');const spec=await api('commerce_collection_template',{platform:value.artifacts?.research?.payload?.record?.platform||value.case.scope.platform});if(state!==s)return;s.latest=value;s.latestSpec=spec;s.rebaseConfirmed=false;}
      catch(error){if(state===s)s.error=explain(error);}
      finally{if(state===s){s.busy=false;dirty();render();}}
    }
    function close(discard=false){
      if(!state)return true;
      if(state.busy||state.draft?.unknown){state.error='原保存仍在处理或结果待确认，请先核对同一请求。';render();return false;}
      if(state.draft?.dirty&&!discard){state.confirmClose=true;render();return false;}
      const next=state.leave;state=null;sequence++;dialogGeneration++;dirty();closeDialog();next?.();return true;
    }
    async function open(snapshot,taskId=''){
      if(state){render();return;}
      const s={draft:null,busy:true,error:'',capable:false,field:'',check:null,latest:null,sourcesOpen:false,generation:++dialogGeneration};state=s;dirty();render();
      try{
        if(taskId||snapshot.research_context?.selected_explicitly)throw Error('workspace_research_snapshot_read_only');
        const platform=snapshot.artifacts?.research?.payload?.record?.platform||snapshot.case.scope.platform;
        const [spec]=await Promise.all([api('commerce_collection_template',{platform}),capability(s)]);
        if(state!==s)return;
        s.draft=createDraft(snapshot,taskId,spec,uuid());s.field=spec.fields.find(row=>row.required)?.key||spec.fields[0]?.key||'';
      }catch(error){if(state===s)s.error=explain(error);}
      finally{if(state===s){s.busy=false;dirty();render();}}
      if(state===s&&s.draft)await check(s);
    }
    async function action(name,target){
      const s=state;if(!s)return;
      if(name==='close'){close();return;}
      if(name==='keep-editing'){s.confirmClose=false;s.leave=null;render('pre-field-select');return;}
      if(name==='discard'){close(true);return;}
      if(!s.draft||s.busy)return;
      if(name==='retry'){await save(true);return;}
      if(name==='latest'){await latest();return;}
      if(name==='capability'){s.busy=true;render();await capability(s);if(state===s){s.busy=false;render();}return;}
      if(s.draft.unknown)return;
      if(name==='check'){await check();return;}
      if(name==='save'){await save();return;}
      if(name==='manual-revision'){manualRevision(s.draft,s.field,uuid());reportInput();render('pre-original');return;}
      if(name==='adopt-latest'||name==='rebase-local'){
        if(!s.latest||!s.rebaseConfirmed)return;
        s.draft=rebase(s.draft,s.latest,name==='rebase-local',uuid(),s.latestSpec||s.draft.spec);s.generation=++dialogGeneration;s.latest=null;s.check=null;s.error='';dirty();render();return;
      }
      if(name==='focus-issue'){
        const issue=s.check?.issues?.[Number(target?.dataset.preIssue)];if(!issue)return;
        if(s.draft.spec.fields.some(row=>row.key===issue.field)){s.field=issue.field;render('pre-original');}
        else{s.sourcesOpen=true;render(({captured_at:'pre-captured-at',source_url:'pre-source-url',raw_excerpt:'pre-excerpt',language:'pre-language',category_rules_checked:'pre-rules-checked'})[issue.field]||'pre-field-select');}return;
      }
      if(name==='export'){
        const document={case_id:s.draft.caseId,kind:'research',payload:{sku:s.draft.scope.sku,row_key:s.draft.scope.row_key,record:clone(s.draft.record)}};
        const url=URL.createObjectURL(new Blob([JSON.stringify(document,null,2)],{type:'application/json'})),link=window.document.createElement('a');link.href=url;link.download='product-research-draft.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      }
    }
    function owns(target){return !!state&&!!target?.closest?.('.dialog')&&!!document.querySelector('.dialog .pre-editor');}
    document.addEventListener('click',event=>{
      if(!state||!event.target?.closest?.('.dialog'))return;
      const control=event.target.closest('[data-pre-action]'),dismiss=event.target.closest('[data-action="close"]');
      if(control||dismiss){event.preventDefault();event.stopImmediatePropagation();Promise.resolve(action(control?.dataset.preAction||'close',control)).catch(error=>{if(state){state.error=explain(error);render();}});}
    },true);
    const input=event=>{
      if(!owns(event.target))return;
      event.stopImmediatePropagation();const s=state,target=event.target;
      if(!s?.draft||s.busy)return;
      try{
        if(target.dataset.preField){editField(s.draft,s.field,target.dataset.preField,target.type==='checkbox'?target.checked:target.value,uuid());reportInput();}
        if(target.dataset.preCommon){editCommon(s.draft,target.dataset.preCommon,target.type==='checkbox'?target.checked:target.value,uuid());reportInput();}
        if(target.id==='pre-field-select'){s.field=target.value;render('pre-field-select');}
        if(target.id==='pre-rebase-confirm'){s.rebaseConfirmed=target.checked;render('pre-rebase-confirm');}
      }catch(error){s.error=explain(error);render();}
    };
    document.addEventListener('input',input,true);
    document.addEventListener('change',event=>{
      if(!owns(event.target))return;
      input(event);
      if(event.target.id!=='pre-import')return;
      const s=state,file=event.target.files?.[0];if(!s?.draft||!file||s.busy||s.draft.unknown)return;
      const draft=s.draft,version=draft.version,generation=s.generation,caseId=draft.caseId;
      const importCurrent=()=>state===s&&s.draft===draft&&s.generation===generation&&draft.caseId===caseId&&current(s)&&draft.version===version&&!draft.request&&!draft.unknown&&!s.busy;
      Promise.resolve().then(async()=>{
        if(file.size>120000)throw Error('invalid_research_record');
        const value=JSON.parse(await file.text());if(!importCurrent())return;
        if(value.case_id!==caseId||value.kind!=='research'||value.payload?.sku!==draft.scope.sku||value.payload?.row_key!==draft.scope.row_key)throw Error('workspace_research_scope_mismatch');
        const record=value.payload.record;
        if(record?.platform!==draft.record.platform||record?.market!==draft.record.market)throw Error('workspace_research_scope_mismatch');
        await api('commerce_collection_check',{record});if(!importCurrent())return;
        draft.record=editableRecord(record);changed(draft,uuid());reportInput();render();
      }).catch(error=>{if(importCurrent()){s.error=explain(error);render();}});
    },true);
    document.addEventListener('toggle',event=>{if(owns(event.target)&&event.target.hasAttribute('data-pre-sources'))state.sourcesOpen=event.target.open;},true);
    document.addEventListener('keydown',event=>{if(state&&event.target?.closest?.('.dialog')&&event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();close();}},true);
    return {open,action,requestLeave(callback){if(!state)return true;state.leave=callback;close();return false;},hasPendingChanges:()=>!!state&&(!!state.busy||!!state.draft?.dirty||!!state.draft?.unknown),hasActiveMutation:()=>!!state&&(!!state.draft?.request||!!state.draft?.unknown),isOpen:()=>!!state};
  }
  Editor.model=Object.freeze({createDraft,editField,editCommon,manualRevision,saveArguments,validateReceipt,matchesReadback,rebase});
  window.CommerceProductResearchEditor=Editor;
})();
