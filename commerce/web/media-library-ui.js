/* Read-only index over original local media. No copies, model calls or approvals. */
window.CommerceMediaLibrary=({api,repaint,isActive=()=>true,onProduct,synthetic=false})=>{
 const ui=window.CommerceUI,e=ui.escape,id=crypto.randomUUID(),LIMIT=20,MAX=8*1024*1024,CHUNK=48*1024;
 const kindNames={all:'全部素材',product_image:'产品原图',competitor_image:'竞品原图',supplier_image:'货源原图',generated_image:'AI生成图片',video:'视频',reference_image:'参考图片',audio:'音频',document:'文档与图文材料',other:'其他素材'};
 const storageNames={registered_local_file:'已登记本地文件 · 读取时核对',missing_local_file:'本地文件缺失',missing_or_invalid_local_file:'本地文件缺失或登记不符',link_only:'仅有来源链接 · 未保存本地文件',source_archived:'原来源已归档'};
 const s={query:'',appliedQuery:'',storeRef:'all',kind:'all',items:[],stores:[],total:null,offset:0,next:null,loading:false,error:'',issues:[],listGeneration:0,mediaGeneration:0,media:null,hidden:false,disposed:false};
 const urls=new Set(),timers=new Map();
 const active=()=>!s.disposed&&!s.hidden&&isActive();
 const paint=()=>{if(!active())return;const prior=document.activeElement,focusId=prior?.id,restore=!!focusId&&own(prior),start=prior?.selectionStart,end=prior?.selectionEnd;repaint();if(restore&&!prior.isConnected&&document.activeElement===document.body){const current=document.getElementById?.(focusId);if(current&&!current.disabled){current.focus({preventScroll:true});if(start!=null&&current.setSelectionRange)current.setSelectionRange(start,end)}}};
 const controlId=(action,rowId='')=>'media-library-'+id+'-'+action+(rowId?'-'+String(rowId).replace(/[^a-zA-Z0-9_-]/g,'-'):'');
 const button=(label,action,attrs={})=>ui.button({label,attrs:{id:controlId(action,attrs['data-media-id']),'data-media-library-action':action,...attrs}});
 const integer=v=>Number.isSafeInteger(v)&&v>=0;
 const sha=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
 const rowById=value=>s.items.find(row=>row.id===value);
 const scope=()=>JSON.stringify([synthetic,s.appliedQuery,s.storeRef,s.kind,s.offset]);
 function release(url){if(!url)return;clearTimeout(timers.get(url));timers.delete(url);if(urls.delete(url))URL.revokeObjectURL(url)}
 function closeMedia(){++s.mediaGeneration;for(const url of [...urls])release(url);s.media=null}
 function fileSize(value){return !integer(value)?'大小未知':value<1024?value+' B':value<1024*1024?(value/1024).toFixed(1)+' KB':(value/1024/1024).toFixed(2)+' MB'}
 function dimensions(row){return Number.isFinite(row.width)&&row.width>0&&Number.isFinite(row.height)&&row.height>0?row.width+' × '+row.height+' px':'尺寸未知'}
 function storeLabel(identity){return identity?.kind==='research_candidate'?'调研候选 · 未绑定店铺':identity?.kind==='store'?(identity.label||'店铺名称待核对'):'未知店铺 / 未绑定'}
 function sourceLabel(row){return row.origin==='product_evidence'?(row.source_kind==='supplier'?'货源证据':row.source_kind==='competitor'?'竞品证据':'商品证据'):'原创意项目'}
 function reviewLabel(row){return row.kind==='generated_image'||row.role==='generated'||String(row.asset_kind).startsWith('generated')?'AI生成 · 当前用途未审核':'当前用途待审核'}
 function canRead(row){
  if(row?.preview?.available!==true||!integer(row.size)||row.size<1||row.size>MAX||!sha(row.sha256))return false;
  const p=row.preview,args=p.arguments;
  if(!args||typeof args!=='object'||Array.isArray(args))return false;
  if(p.tool==='commerce_creative_asset_read')return row.origin==='creative'&&typeof args.project_id==='string'&&!!args.project_id&&typeof args.asset_id==='string'&&!!args.asset_id&&args.project_id===row.project_id&&args.asset_id===row.asset_id&&args.offset==='0'&&Object.keys(args).every(k=>['project_id','asset_id','offset'].includes(k));
  if(p.tool==='commerce_product_evidence_image')return row.origin==='product_evidence'&&typeof args.case_id==='string'&&!!args.case_id&&typeof args.entry_id==='string'&&!!args.entry_id&&args.case_id===row.case_id&&args.entry_id===row.entry_id&&args.expected_entry_sha256===row.entry_sha256&&sha(args.expected_entry_sha256)&&args.index===row.image_index&&integer(args.index)&&args.index<=11&&args.offset===0&&Object.keys(args).every(k=>['case_id','entry_id','expected_entry_sha256','index','offset'].includes(k));
  return false;
 }
 function unavailable(row){return row.size>MAX?'文件超过8 MB，请在原项目处理。':row.preview?.available!==true?(storageNames[row.storage_status]||'本地文件暂不可读。'):!integer(row.size)||row.size<1||!sha(row.sha256)?'大小或SHA登记不完整，暂不读取。':'读取范围尚未核对，暂不读取。'}
 function previewable(row){if(['video','audio'].includes(row.kind))return false;return row.kind!=='other'||Number.isFinite(row.width)&&row.width>0&&Number.isFinite(row.height)&&row.height>0}
 function matchesStore(row,filter){const x=row.store_identity;if(filter==='all')return true;if(filter==='unassigned')return x?.kind==='unassigned';if(filter==='research_candidates')return x?.kind==='research_candidate';return filter===x?.account_id||filter===x?.connection_id}
 function validList(result,request){return result&&result.synthetic===synthetic&&Array.isArray(result.items)&&result.items.length<=LIMIT&&integer(result.total)&&result.offset===request.offset&&result.limit===LIMIT&&result.items.length===Math.min(LIMIT,Math.max(0,result.total-request.offset))&&result.next_offset===(request.offset+result.items.length<result.total?request.offset+result.items.length:null)&&new Set(result.items.map(row=>row.id)).size===result.items.length&&result.items.every(row=>row&&typeof row.id==='string'&&row.synthetic===synthetic&&matchesStore(row,request.store_ref)&&(request.kind==='all'||row.kind===request.kind))&&Array.isArray(result.stores)&&result.store_facets_complete===true}
 async function load(offset=0){
  if(!active())return;closeMedia();s.appliedQuery=s.query.trim().slice(0,200);s.offset=offset;s.loading=true;s.error='';s.items=[];s.total=null;s.next=null;s.issues=[];
  const generation=++s.listGeneration,key=scope(),request={synthetic,query:s.appliedQuery,store_ref:s.storeRef,kind:s.kind,limit:LIMIT,offset};paint();
  try{const result=await api('commerce_media_library_list',request);if(!active()||generation!==s.listGeneration||key!==scope())return;if(!validList(result,request))throw Error('media_scope_invalid');s.items=result.items;s.stores=result.stores;s.total=result.total;s.next=result.next_offset;s.issues=Array.isArray(result.issues)?result.issues:[]}
  catch{if(active()&&generation===s.listGeneration&&key===scope()){s.error='本地素材索引暂不可读，请刷新后核对。';s.items=[];s.total=null;s.next=null}}
  finally{if(active()&&generation===s.listGeneration&&key===scope()){s.loading=false;paint()}}
 }
 async function enter(){if(s.disposed)return;s.hidden=false;await load(s.offset)}
 function requestCurrent(generation,key,row){return active()&&generation===s.mediaGeneration&&key===scope()&&rowById(row.id)===row}
 function packetBytes(packet,row,offset,firstMime){
  if(!packet||packet.size!==row.size||packet.sha256!==row.sha256||typeof packet.mime!=='string'||packet.mime.length>100||/[\r\n]/.test(packet.mime)||firstMime&&packet.mime!==firstMime||typeof packet.content_base64!=='string'||packet.content_base64.length>65536||packet.content_base64.length%4||!/^[A-Za-z0-9+/]*={0,2}$/.test(packet.content_base64))throw Error('media_packet_invalid');
  const raw=atob(packet.content_base64),bytes=Uint8Array.from(raw,c=>c.charCodeAt(0));
  if(bytes.length!==Math.min(CHUNK,row.size-offset))throw Error('media_size_changed');
  const next=offset+bytes.length;
  if(row.preview.tool==='commerce_creative_asset_read'){
   if(packet.next_offset!==String(next)||typeof packet.done!=='boolean'||packet.done!==(next===row.size))throw Error('media_offset_invalid');
  }else if(packet.status!=='archived'||packet.next_offset!==(next===row.size?null:next))throw Error('media_offset_invalid');
  return bytes;
 }
 function imageType(bytes,mime){
  const prefix=(...values)=>values.every((v,i)=>bytes[i]===v);
  if(prefix(137,80,78,71,13,10,26,10))return 'image/png';
  if(prefix(255,216,255))return 'image/jpeg';
  if(prefix(82,73,70,70)&&[87,69,66,80].every((v,i)=>bytes[8+i]===v))return 'image/webp';
  if(prefix(71,73,70,56)&&(bytes[4]===55||bytes[4]===57)&&bytes[5]===97)return 'image/gif';
  return null;
 }
 function filename(row,mime){const extensions={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp','image/gif':'.gif','application/json':'.json','text/plain':'.txt','text/csv':'.csv','video/mp4':'.mp4','video/webm':'.webm','audio/wav':'.wav'},type=mime.split(';')[0].trim().toLowerCase(),base=String(row.display_name||row.asset_id||'local-media').replace(/[\\/<>:"|?*\u0000-\u001f]/g,'-').replace(/^\.+/,'').slice(0,100)||'local-media';const ext=extensions[type]||'.bin';return base.toLowerCase().endsWith(ext)?base:base+ext}
 async function read(row,mode){
  if(!active()||!canRead(row)||s.media?.id===row.id&&s.media.phase==='loading')return;
  closeMedia();const generation=s.mediaGeneration,key=scope();s.media={id:row.id,label:row.display_name||kindNames[row.kind]||'本地素材',phase:'loading',mode,received:0,total:row.size};paint();document.querySelector?.(`[data-media-library-id="${id}"] .media-library-preview`)?.focus({preventScroll:false});
  try{
   if(!crypto.subtle?.digest)throw Error('media_hash_unavailable');
   let offset=0,mime='',parts=[];
   while(offset<row.size){
    if(!requestCurrent(generation,key,row))return;
    const args={...row.preview.arguments,offset:row.preview.tool==='commerce_creative_asset_read'?String(offset):offset},packet=await api(row.preview.tool,args);
    if(!requestCurrent(generation,key,row))return;
    const bytes=packetBytes(packet,row,offset,mime);mime=mime||packet.mime;parts.push(bytes);offset+=bytes.length;s.media.received=offset;paint();
   }
   const bytes=new Uint8Array(row.size);let position=0;for(const part of parts){bytes.set(part,position);position+=part.length}parts=[];
   const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');
   if(!requestCurrent(generation,key,row))return;if(digest!==row.sha256)throw Error('media_hash_mismatch');
   if(mode==='download'){
    const url=URL.createObjectURL(new Blob([bytes],{type:'application/octet-stream'}));urls.add(url);
    if(!requestCurrent(generation,key,row)){release(url);return}
    const link=document.createElement('a');link.href=url;link.download=filename(row,mime);document.body.append(link);link.click();link.remove();if(!requestCurrent(generation,key,row)){release(url);return}timers.set(url,setTimeout(()=>release(url),5000));
    s.media={id:row.id,label:s.media.label,phase:'downloaded',mode,total:row.size,mime};
   }else{
    const imageMime=imageType(bytes,mime),type=mime.split(';')[0].trim().toLowerCase();
    if(imageMime){const url=URL.createObjectURL(new Blob([bytes],{type:imageMime}));urls.add(url);s.media={id:row.id,label:s.media.label,phase:'ready',mode,url,total:row.size,mime:imageMime}}
    else if(['application/json','text/plain','text/csv','text/html'].includes(type)){const text=new TextDecoder('utf-8').decode(bytes);s.media={id:row.id,label:s.media.label,phase:'ready',mode,text:text.slice(0,100000),textTruncated:text.length>100000,total:row.size,mime}}
    else{s.media={id:row.id,label:s.media.label,phase:'unsupported',mode,total:row.size,mime}}
   }
  }catch{if(requestCurrent(generation,key,row)){closeMedia();s.media={id:row.id,label:row.display_name||'所选素材',phase:'failed',mode,error:'素材读取或SHA核对未通过，未展示或下载文件。请回原项目核对登记与本地文件。'}}}
  finally{if(active()&&key===scope())paint()}
 }
 function mediaView(){const m=s.media;if(!m)return '';return `<section id="${e(controlId('preview-panel'))}" class="card media-library-preview" tabindex="-1" aria-live="polite" aria-label="所选素材预览"><div class="media-library-heading"><h3>${e(m.label)}</h3>${button('关闭预览 / 回执','close')}</div>${m.phase==='loading'?`<p role="status">正在${m.mode==='download'?'核对下载文件':'读取所选素材'}… ${e(fileSize(m.received))} / ${e(fileSize(m.total))}</p>`:m.phase==='failed'?ui.alert(m.error,'danger'):m.phase==='downloaded'?ui.alert('文件SHA已核对，并已请求浏览器下载；请核对本机下载结果。'):m.phase==='unsupported'?ui.empty('文件SHA已核对；此格式不提供内嵌预览，请下载或在原项目查看。'):m.url?`<img src="${e(m.url)}" alt="${e(m.label)} · 本地素材预览">`:`<p class="muted">以下为本地文件原文；HTML标签仅作为文字展示。${m.textTruncated?'仅预览前100000字符，完整内容请下载核对。':''}</p><pre class="media-library-text">${e(m.text)}</pre>`}${['ready','downloaded','unsupported'].includes(m.phase)?'<p class="muted">文件SHA核对通过只确认当前字节与登记相符，不代表内容审核、商用权或发布批准。</p>':''}</section>`}
 function rowView(row){const identity=row.store_identity,readable=canRead(row),loading=s.media?.id===row.id&&s.media.phase==='loading';return `<article class="media-library-item"><div class="media-library-heading"><h3>${e(row.display_name||kindNames[row.kind]||'未命名素材')}</h3>${ui.badge(kindNames[row.kind]||'其他素材','gray')}</div><p class="media-library-product">${e(row.product_name||row.project_name||'商品名称待核对')}</p><p class="muted">${e(storeLabel(identity))} · ${e(identity?.platform||'平台未知')} / ${e(identity?.market||'市场未知')}<br>SKU ${e(row.sku||'未知')} · 商品编号 ${e(row.product_id||'未知')}</p><p>${ui.badge(reviewLabel(row),'gray')}${row.review_status==='local_review_recorded'?` ${ui.badge('原请求有本地审阅记录','gray')}`:''}</p><dl class="media-library-facts"><div><dt>来源</dt><dd>${e(sourceLabel(row))}${row.source_label?' · '+e(row.source_label):''}</dd></div><div><dt>本地状态</dt><dd>${e(storageNames[row.storage_status]||'状态待核对')}</dd></div><div><dt>尺寸 / 大小</dt><dd>${e(dimensions(row))} · ${e(fileSize(row.size))}${row.rendition==='thumbnail'?' · 已标记缩略图':''}${Number.isFinite(row.duration_seconds)&&row.duration_seconds>0?' · '+e(row.duration_seconds)+'秒':''}</dd></div><div><dt>来源记录</dt><dd>${e(row.source_url||row.source_reference||'来源未登记')}</dd></div><div><dt>原项目 / 证据</dt><dd>${e(row.project_name||row.project_id||row.entry_id||'未关联')}${row.entry_revision?' · 来源v'+e(row.entry_revision):''}</dd></div><div><dt>SHA-256</dt><dd class="media-library-sha">${e(sha(row.sha256)?row.sha256:'未登记')}</dd></div></dl><div class="media-library-actions">${button('预览图片 / 原文','preview',{'data-media-id':row.id,disabled:!readable||!previewable(row)||loading})}${button('下载本地文件','download',{'data-media-id':row.id,disabled:!readable||loading})}${row.product_readable===true&&row.case_id&&typeof onProduct==='function'?button('查看原商品','product',{'data-media-id':row.id}):''}</div>${!readable?`<p class="muted">${e(unavailable(row))}</p>`:!previewable(row)?'<p class="muted">视频、音频等格式请下载或在原项目处理，当前页面不播放。</p>':''}${identity?.kind==='store'&&identity.active===false?'<p class="muted">该素材属于已保存的非当前店铺；原商品入口不可用时，不会切换店铺。</p>':''}${row.review_status==='local_review_recorded'?'<p class="muted">原请求审阅仅适用于原请求，当前用途和发布仍待核对。</p>':''}</article>`}
 function storeOptions(){const values=[{value:'all',label:'全部本地素材'},{value:'unassigned',label:'未知店铺 / 未绑定'},{value:'research_candidates',label:'调研候选 · 未绑定店铺'}],seen=new Set(values.map(v=>v.value));for(const item of s.stores){if(typeof item.store_ref!=='string'||seen.has(item.store_ref))continue;seen.add(item.store_ref);values.push({value:item.store_ref,label:(item.label||'店铺名称待核对')+(item.active===true?' · 当前活跃':item.kind==='store'?' · 非当前店铺':'')})}if(!seen.has(s.storeRef))values.push({value:s.storeRef,label:'所选店铺 · 当前条件无素材选项'});return values}
 function view(){if(s.disposed||s.hidden)return '';const known=s.items.filter(row=>row.store_identity?.kind==='store'),research=s.items.filter(row=>row.store_identity?.kind==='research_candidate'),unknown=s.items.filter(row=>!['store','research_candidate'].includes(row.store_identity?.kind));return `<section class="media-library" data-media-library-id="${e(id)}" aria-busy="${s.loading}" aria-label="本地素材库"><header><h2>本地素材库</h2><p class="muted">按原店铺、商品和来源索引已登记素材。${synthetic?'当前为合成资料。':'当前为真实资料。'}仅显式点击读取本地文件，不自动访问远端来源。</p></header><form data-media-library-search><div class="media-library-controls">${ui.field('搜索商品、SKU或素材',ui.input({id:'media-library-query-'+id,type:'search',value:s.query,maxlength:200,placeholder:'输入名称、SKU或来源'}))}${ui.field('准确店铺归属',ui.select({id:'media-library-store-'+id,value:s.storeRef,options:storeOptions()}))}${ui.field('素材类型',ui.select({id:'media-library-kind-'+id,value:s.kind,options:Object.entries(kindNames).map(([value,label])=>({value,label}))}))}${button('搜索','search',{disabled:s.loading})}${button('刷新索引','refresh',{disabled:s.loading})}</div></form><p class="muted">AI生成素材默认当前用途未审核，文件名不能证明通过。原请求审阅不等于商用或发布批准；预览与下载上限为8 MB。</p>${s.error?ui.alert(s.error,'danger'):''}${s.loading?ui.empty('正在读取本地素材索引…'):''}${s.issues.length?ui.alert('部分来源完整性未能读取，当前列表可能不完整；请回原商品核对。'):''}${mediaView()}${[['已归属店铺素材',known],['调研候选素材',research],['未知店铺 / 未绑定素材',unknown]].filter(([,rows])=>rows.length).map(([title,rows])=>`<section class="media-library-group"><h3>${title}</h3><div class="media-library-grid">${rows.map(rowView).join('')}</div></section>`).join('')}${!s.loading&&!s.error&&s.total===0?ui.empty('当前筛选没有已登记的本地素材。'):''}<div class="media-library-pagination">${button('上一页','prev',{disabled:s.loading||s.offset===0})}<span>${s.total===null?'素材总数待核对':s.total===0?'共0项':!s.items.length?'共'+s.total+'项 · 当前页无记录':`${s.offset+1}–${s.offset+s.items.length} / 共${s.total}项`}</span>${button('下一页','next',{disabled:s.loading||s.next===null})}</div></section>`}
 const own=target=>target?.closest?.(`[data-media-library-id="${id}"]`);
 const submit=event=>{if(active()&&own(event.target)&&event.target.matches?.('[data-media-library-search]')){event.preventDefault();load(0)}};
 const input=event=>{if(active()&&event.target.id==='media-library-query-'+id)s.query=event.target.value.slice(0,200)};
 const change=event=>{if(!active())return;if(event.target.id==='media-library-store-'+id){const value=event.target.value;if(!storeOptions().some(v=>v.value===value))return;s.storeRef=value;load(0)}else if(event.target.id==='media-library-kind-'+id&&Object.hasOwn(kindNames,event.target.value)){s.kind=event.target.value;load(0)}};
 const click=event=>{if(!active())return;const b=event.target.closest?.('[data-media-library-action]');if(!b||!own(b)||b.disabled)return;event.preventDefault();const action=b.dataset.mediaLibraryAction,row=rowById(b.dataset.mediaId);if(action==='search'||action==='refresh')return load(0);if(action==='prev')return load(Math.max(0,s.offset-LIMIT));if(action==='next'&&s.next!==null)return load(s.next);if(action==='close'){const m=s.media;closeMedia();paint();if(m)document.getElementById?.(controlId(m.mode==='download'?'download':'preview',m.id))?.focus({preventScroll:true});return}if(action==='product'&&row?.product_readable===true&&row.case_id&&typeof onProduct==='function'){closeMedia();onProduct(row.case_id);return}if((action==='preview'||action==='download')&&row&&(action==='download'||previewable(row)))return read(row,action)};
 const listeners={submit,input,change,click};for(const [name,handler]of Object.entries(listeners))document.addEventListener(name,handler);
 function hide(){s.hidden=true;++s.listGeneration;closeMedia();s.loading=false;s.items=[];s.total=null;s.next=null}
 function dispose(){if(s.disposed)return;hide();s.disposed=true;for(const [name,handler]of Object.entries(listeners))document.removeEventListener(name,handler)}
 return {enter,view,hide,dispose};
};
