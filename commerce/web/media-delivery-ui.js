/* Local sample approval uses the existing request/review ledger. */
window.CommerceMediaDeliveryFlow=()=>{
  const ui=window.CommerceUI,e=ui.escape,settings=new Map(),acks=new Set(),keys=new Map();
  const defaults=r=>({source_policy:'allow_stills',audio_policy:'optional',allow_looping:false,sample_duration_ms:Math.min(1500,r.spec.duration_ms)});
  const options=r=>{if(!settings.has(r.id))settings.set(r.id,defaults(r));return settings.get(r.id)};
  const ackKey=r=>JSON.stringify([r.id,r.request_sha256,r.result_sha256,r.spec.delivery_commitment?.sha256]);
  const canApprove=r=>r.delivery?.role!=='sample'||acks.has(ackKey(r));
  const canExecute=r=>r.delivery?.role!=='full'||r.delivery.gate==='ready';
  const button=(label,id,busy)=>ui.button({label,attrs:{'data-media-action':'delivery-open','data-request':id,disabled:busy}});
  function view(r,busy){
    if(!r.spec.format?.endsWith('_video')&&!r.delivery)return '';
    const c=r.spec.delivery_commitment;
    if(!c){
      if(r.assets.length||r.job_id)return '';
      const d=options(r);
      const select=(label,key,values)=>ui.field(label,ui.select({'data-delivery-field':key,value:d[key],options:values.map(([value,label])=>({value,label}))}));
      return `<details class="media-editor"><summary>样片审批与交付承诺</summary><p class="muted">先选好分镜素材，再冻结本次时长、画幅、字幕和来源。样片取完整时间线的开头，通过后再明确启动完整制作。</p><div class="media-metric-fields">${select('画面来源','source_policy',[['allow_stills','允许图片与视频'],['video_only','全部使用视频素材']])}${select('声音要求','audio_policy',[['optional','音轨可选'],['audible_required','需要可听音轨'],['no_audio','不含音轨']])}${ui.field('样片时长（秒）',ui.input({type:'number',min:1,max:Math.min(5,r.spec.duration_ms/1000),step:0.001,value:d.sample_duration_ms/1000,'data-delivery-field':'sample_duration_ms'}))}</div><label class="media-check"><input type="checkbox" data-delivery-field="allow_looping" ${d.allow_looping?'checked':''}>允许短视频素材循环</label><div class="form-actions">${ui.button({label:'保存交付承诺并建立样片',variant:'primary',attrs:{'data-media-action':'delivery-prepare',disabled:busy||r.stale}})}</div></details>`;
    }
    const d=r.delivery,requirement=c.requirements;
    const status=d.role==='sample'?'样片用于核对本次完整制作要求':({ready:'样片已通过 · 可明确启动完整制作',sample_rejected:'样片已退回 · 请返回来源版本调整',sample_required:'等待样片产出并审批'})[d.gate];
    const ack=d.role==='sample'&&r.assets.length&&!r.review?`<label class="media-check"><input type="checkbox" data-delivery-field="ack" ${acks.has(ackKey(r))?'checked':''}>已完整观看本次样片，并确认符合本次交付要求</label>`:'';
    return `<section class="media-review-report" aria-label="样片审批与交付承诺"><h3>${d.role==='sample'?'样片审批':'完整制作交付承诺'}</h3><p>${e('完整成片 '+c.duration_ms/1000+'秒 · '+c.width+'×'+c.height+' · MP4 · 样片为开头 '+requirement.sample_duration_ms/1000+'秒')}</p><p>${e((requirement.source_policy==='video_only'?'全部使用视频素材':'允许图片与视频')+' · '+({optional:'音轨可选',audible_required:'需要可听音轨',no_audio:'不含音轨'})[requirement.audio_policy]+' · '+(requirement.allow_looping?'允许循环':'不循环'))}</p><p role="status">${e(status)}</p><p class="muted">素材、字幕与制作版本已固定；变更时从来源版本重新确认。样片通过仅允许本次本机制作，成片仍须单独审阅。</p>${button(d.role==='sample'?'查看完整制作版本':'查看样片与审阅',d.role==='sample'?d.full_request_id:d.sample_request_id,busy)}${button('返回来源版本调整',d.source_request_id,busy)}${ack}</section>`;
  }
  function input(ev,r){
    const key=ev.target.dataset.deliveryField;if(!key||!r)return false;
    if(key==='ack'){if(ev.target.checked)acks.add(ackKey(r));else acks.delete(ackKey(r));return 'repaint'}
    const d=options(r);d[key]=key==='allow_looping'?ev.target.checked:key==='sample_duration_ms'?Math.round(Number(ev.target.value)*1000):ev.target.value;
    return true;
  }
  async function prepare(api,r,asset_ids,audio_asset_id){
    if(asset_ids.some(x=>!x))throw Error('creative_shot_assets_required');
    const args={request_id:r.id,expected_request_sha256:r.request_sha256,asset_ids,requirements:{...options(r)},...(audio_asset_id?{audio_asset_id}:{})};
    const key=JSON.stringify(args);if(!keys.has(key))keys.set(key,crypto.randomUUID());
    const result=await api('commerce_media_delivery_prepare',{...args,idempotency_key:keys.get(key)});keys.delete(key);return result;
  }
  const reviewArgs=r=>r.delivery?.role==='sample'?{sample_review:{watched:true,matches_commitment:true,commitment_sha256:r.spec.delivery_commitment.sha256}}:{};
  return {view,input,prepare,canApprove,canExecute,reviewArgs};
};
