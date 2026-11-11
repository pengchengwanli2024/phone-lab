/* Commerce UI: dependency-free shared renderers for browser and Harness. */
window.CommerceUI = (() => {
  'use strict';
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const permitted=/^(class|id|type|title|role|name|value|placeholder|maxlength|min|max|step|autocomplete|disabled|readonly|required|checked|aria-[a-z-]+|data-[a-z0-9-]+)$/;
  function attributes(values={}){
    return Object.entries(values).filter(([key,value])=>permitted.test(key)&&value!==undefined&&value!==null&&(value!==false||key.startsWith('aria-')||key.startsWith('data-'))).map(([key,value])=>value===true&&['disabled','readonly','required','checked'].includes(key)?key:`${key}="${escape(value)}"`).join(' ');
  }
  // Compatibility adapter for pre-existing local templates. DOM parsing decodes
  // escaped values; the attribute allowlist removes event handlers and URLs.
  function legacyAttributes(source=''){
    const template=document.createElement('template');template.innerHTML=`<button ${source}></button>`;
    const button=template.content.firstElementChild;
    return button?Object.fromEntries([...button.attributes].filter(a=>permitted.test(a.name)).map(a=>[a.name,a.value])):{};
  }
  function button({label,variant='secondary',action,attrs={}}){
    const kind=['primary','secondary','danger','quiet'].includes(variant)?variant:'secondary';
    return `<button ${attributes({type:'button',...attrs,class:`ui-button ${kind==='primary'?'primary':''} ${kind==='danger'?'ui-danger':''} ${kind==='quiet'?'link-btn':''} ${attrs.class||''}`,'data-action':action})}>${escape(label)}</button>`;
  }
  function badge(label,tone='warning'){
    const kind=['blue','gray','success','warning','danger'].includes(tone)?tone:'warning';
    return `<span class="badge ui-badge ${kind}" data-ui-tone="${kind}">${escape(label)}</span>`;
  }
  function input({value='',type='text',...attrs}={}){
    const kind=['text','password','search','number','email','url','date','checkbox'].includes(type)?type:'text';
    return `<input ${attributes({...attrs,type:kind,value,class:`ui-control ${attrs.class||''}`})}>`;
  }
  function select({options=[],value='',...attrs}={}){
    return `<select ${attributes({...attrs,class:`ui-control ${attrs.class||''}`})}>${options.map(option=>`<option value="${escape(option.value)}" ${String(option.value)===String(value)?'selected':''}>${escape(option.label)}</option>`).join('')}</select>`;
  }
  const field=(label,control)=>`<label class="ui-field">${escape(label)}${control}</label>`;
  const empty=(message='暂无记录')=>`<div class="empty ui-empty" role="status">${escape(message)}</div>`;
  const alert=(message,tone='info')=>`<div class="alert ui-alert ${tone==='danger'?'error':''}" role="${tone==='danger'?'alert':'status'}">${escape(message)}</div>`;
  function card({title='',content='',attrs={}}){
    return `<section ${attributes({...attrs,class:`card ui-card ${attrs.class||''}`})}>${title?`<h2>${escape(title)}</h2>`:''}${content}</section>`;
  }
  function table(headers,rows,emptyText='没有匹配的数据。未授权店铺时真实数据为空。'){
    return `<div class="table-wrap ui-table"><table class="data-table"><thead><tr>${headers.map(h=>`<th scope="col">${escape(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>${rows.length?'':empty(emptyText)}</div>`;
  }
  function tabs(items,value){
    return `<nav class="tabs ui-tabs" aria-label="电商模块">${Object.entries(items).map(([key,name])=>`<button type="button" class="tab ${value===key?'active':''}" data-tab="${escape(key)}" aria-current="${value===key?'page':'false'}">${escape(name)}</button>`).join('')}</nav>`;
  }
  function modal({title,body,actions=''}){
    return `<div class="overlay"><section class="dialog ui-dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title"><div class="dialog-head"><h2 id="dialog-title">${escape(title)}</h2>${button({label:'×',action:'close',attrs:{'aria-label':'关闭'}})}</div>${body}<div class="dialog-actions">${actions||button({label:'关闭',action:'close'})}</div></section></div>`;
  }
  const icon=(name='grid')=>{const paths={grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',chat:'<path d="M3 4h18v13H9l-6 4z"/><path d="M8 9h8M8 13h5"/>',store:'<path d="M4 10v11h16V10M3 3h18l1 7H2zM9 21v-7h6v7"/>',cart:'<path d="M2 3h3l3 13h11l3-10H6"/><circle cx="9" cy="21" r="1"/><circle cx="19" cy="21" r="1"/>',clock:'<circle cx="12" cy="12" r="10"/><path d="M12 5v7l5 3"/>',box:'<path d="m12 2 10 5v11l-10 5-10-5V7zM2 7l10 5 10-5M12 12v11M7 4l10 6v5"/>',bolt:'<path d="m14 1-12 13h9l-1 9 12-14h-9z"/>',book:'<path d="M2 3h8l2 2 2-2h8v17h-8l-2 2-2-2H2zM12 5v17"/>',code:'<path d="m8 4-7 8 7 8m8-16 7 8-7 8M14 2l-4 20"/>',link:'<path d="m9 15 6-6M8 6l2-2a5 5 0 0 1 7 7l-2 2M16 18l-2 2a5 5 0 0 1-7-7l2-2"/>',info:'<circle cx="12" cy="12" r="10"/><path d="M12 11v6m0-11v1"/>',gear:'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 1v3m0 16v3M1 12h3m16 0h3"/>',headset:'<path d="M3 14v-3a9 9 0 0 1 18 0v3M3 12h4v7H3zM17 12h4v7h-4zM17 20l-5 2"/>',doc:'<path d="M5 2h10l5 5v15H5zM15 2v6h5M9 12h7M9 16h7"/>',spark:'<path d="m12 1 3 8 8 3-8 3-3 8-3-8-8-3 8-3z"/>'};return `<svg class="icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${paths[name]||paths.grid}</svg>`};
  const systemScheme=window.matchMedia('(prefers-color-scheme: dark)');
  let theme='system';
  const getTheme=()=>({preference:theme,resolved:theme==='system'?(systemScheme.matches?'dark':'light'):theme});
  function applyTheme(value){
    if(!['light','dark','system'].includes(value))throw Error('invalid_ui_theme');
    theme=value;const current=getTheme();document.documentElement.dataset.theme=value;
    document.documentElement.dataset.resolvedTheme=current.resolved;
    window.dispatchEvent(new CustomEvent('commerce:themechange',{detail:current}));
    return current;
  }
  systemScheme.addEventListener('change',()=>{if(theme==='system')applyTheme('system')});
  applyTheme('system');
  return Object.freeze({version:'1.1.2',applyTheme,getTheme,icon,escape,attributes,legacyAttributes,button,badge,input,select,field,empty,alert,card,table,tabs,modal});
})();
