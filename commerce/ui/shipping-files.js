/* Files remain in the user-selected client. No arbitrary path or URL bridge. */
window.CommerceShippingFiles = (() => {
  const kinds={rates:500000,items:200000,cartons:200000};
  const mimeFor={csv:'text/csv',json:'application/json',html:'text/html'};
  function validateFile(file){
    if(!file||typeof file.filename!=='string'||file.filename.length>200||!file.filename||/[\\/\x00-\x1f\x7f]/.test(file.filename)||typeof file.content!=='string')throw Error('shipping_invalid_file');
    const ext=file.filename.split('.').pop().toLowerCase(),mime=String(file.mime_type||'').split(';')[0].toLowerCase();
    if(!mimeFor[ext]||mime!==mimeFor[ext]||new TextEncoder().encode(file.content).length>8000000)throw Error('shipping_invalid_file');
    return file;
  }
  async function readCsv(file,{kind}={}){
    const limit=kinds[kind];if(!limit)throw Error('shipping_invalid_file_kind');
    if(!file||typeof file.name!=='string'||!/^.+\.csv$/i.test(file.name))throw Error('请选择 UTF-8 编码的 CSV 文件。');
    if(!Number.isFinite(file.size)||file.size<=0||file.size>limit)throw Error(`CSV文件须为1至${limit/1000}KB。`);
    let content;try{content=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(await file.arrayBuffer());}catch{throw Error('文件不是有效的 UTF-8 CSV，请转换编码后重新选择。');}
    if(content.includes('\0'))throw Error('文件不是有效的 UTF-8 CSV，请转换编码后重新选择。');
    return {content,filename:file.name,bytes:file.size};
  }
  function validateOperation(op,args){
    if(op==='download'){validateFile(args?.file);return;}
    if(op!=='pick-csv'||!args||Object.keys(args).some(key=>key!=='kind')||!Object.hasOwn(kinds,args.kind))throw Error('shipping_invalid_file_operation');
  }
  function pickCsv(args){
    try{validateOperation('pick-csv',args);}catch(error){return Promise.reject(error);}
    return new Promise((resolve,reject)=>{
      const input=document.createElement('input');input.type='file';input.accept='.csv,text/csv';input.multiple=false;input.hidden=true;
      let settled=false;
      const cleanup=()=>{clearTimeout(timer);input.removeEventListener('change',change);input.removeEventListener('cancel',cancel);input.remove();};
      const finish=(error,value)=>{if(settled)return;settled=true;cleanup();error?reject(error):resolve(value);};
      const cancel=()=>finish(null,{status:'cancelled'});
      const change=async()=>{const selected=input.files?.[0];if(!selected){cancel();return;}try{const value=await readCsv(selected,args);finish(null,{status:'selected',...value});}catch(error){finish(error);}};
      const timer=setTimeout(()=>finish(Error('shipping_file_selection_unknown')),120000);
      input.addEventListener('change',change);input.addEventListener('cancel',cancel);document.body.appendChild(input);
      try{input.click();}catch(error){finish(error);}
    });
  }
  async function saveFile(input,nativeSave){
    const file=validateFile(input),url=URL.createObjectURL(new Blob([file.content],{type:file.mime_type}));
    if(nativeSave){
      try{
        const receipt=await nativeSave({url,name:file.filename,mediaType:file.mime_type});
        if(!receipt||!['saved','requested','cancelled'].includes(receipt.status)||(receipt.status==='saved'&&(typeof receipt.path!=='string'||!receipt.path)))throw Error('shipping_invalid_file_receipt');
        return {...receipt,filename:file.filename};
      }finally{URL.revokeObjectURL(url);}
    }
    const link=document.createElement('a');link.href=url;link.download=file.filename;link.rel='noopener';
    try{document.body.appendChild(link);link.click();}finally{link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);}
    return {status:'requested',filename:file.filename};
  }
  function createClient({target=window,nonce,timeoutMs=120000}={}){
    const pending=new Map();let disposed=false;
    const receive=event=>{
      const message=event.data;if(event.source!==target.parent||message?.type!=='commerce:shipping-file-result'||message.nonce!==nonce)return;
      const entry=pending.get(message.id);if(!entry)return;clearTimeout(entry.timer);pending.delete(message.id);message.error?entry.reject(Error(message.error)):entry.resolve(message.result);
    };
    target.addEventListener('message',receive);
    return {
      request(op,args){
        if(disposed)return Promise.reject(Error('shipping_file_view_closed'));
        try{validateOperation(op,args);}catch(error){return Promise.reject(error);}
        if(target.parent===target)return op==='pick-csv'?pickCsv(args):saveFile(args.file);
        const id=target.crypto.randomUUID();return new Promise((resolve,reject)=>{
          const timer=setTimeout(()=>{pending.delete(id);reject(Error(op==='pick-csv'?'shipping_file_selection_unknown':'request_outcome_unknown'));},timeoutMs);pending.set(id,{resolve,reject,timer});
          target.parent.postMessage({type:'commerce:shipping-file',nonce,id,op,args},'*');
        });
      },
      dispose(){disposed=true;target.removeEventListener('message',receive);for(const entry of pending.values()){clearTimeout(entry.timer);entry.reject(Error('shipping_file_view_closed'));}pending.clear();}
    };
  }
  async function handleRequest(event,{source,nonce,perform,alive=()=>true}={}){
    const message=event.data;if(event.source!==source||message?.type!=='commerce:shipping-file'||message.nonce!==nonce)return false;
    if(typeof message.id!=='string'||!/^[a-zA-Z0-9_-]{1,100}$/.test(message.id))return true;
    try{
      validateOperation(message.op,message.args);
      const result=await perform(message.op,message.args);if(alive())source.postMessage({type:'commerce:shipping-file-result',nonce,id:message.id,result},'*');
    }catch(error){if(alive())source.postMessage({type:'commerce:shipping-file-result',nonce,id:message.id,error:error.message||'shipping_file_failed'},'*');}
    return true;
  }
  return {readCsv,pickCsv,saveFile,createClient,handleRequest};
})();
