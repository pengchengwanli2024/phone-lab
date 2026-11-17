/* Shared selected-file transport. An explicit retry resumes the same local receipt. */
;(function(target){
  const base64=bytes=>{let text='';for(const byte of bytes)text+=String.fromCharCode(byte);return btoa(text)};
  target.CommerceMaterialUpload={create({api,onProgress=()=>{},shouldContinue=()=>true}){
    let request=null,disposed=false;
    const check=req=>{if(req.cancelled)throw Error('copilot_upload_cancelled');if(disposed||!shouldContinue())throw Error('copilot_upload_scope_changed')};
    const progress=(req,status,received=0)=>{req.status=status;if(!disposed)onProgress({status,received,total:req.size,id:req.id,cancellable:!!req.id&&!req.finishing&&['uploading','unconfirmed'].includes(status)})};
    async function upload({thread,selected,caps}){
      const {filename,mime_type,bytes}=selected,large=bytes.length>(caps.max_file_bytes||65536);
      if(!bytes.length||bytes.length>(caps.chunked_upload_available?caps.max_chunked_file_bytes:caps.max_file_bytes||65536))throw Error('copilot_material_size_or_encoding');
      if(caps.chunked_upload_available){const preflight=await api('commerce_copilot_material_preflight',{filename,mime_type,size_bytes:bytes.length});if(!preflight.allowed)throw Error('copilot_material_extraction_unavailable')}
      let content,digest;
      if(large){if(!crypto.subtle)throw Error('copilot_material_hash_unavailable');digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),byte=>byte.toString(16).padStart(2,'0')).join('')}
      else content=base64(bytes);
      const fingerprint=JSON.stringify({thread:thread.id,scope:thread.context_sha256,filename,mime_type,content:digest||content});
      if(request?.fingerprint!==fingerprint){if(request?.id&&!request.cancelled)throw Error('copilot_upload_pending_selection');request={fingerprint,key:crypto.randomUUID(),size:bytes.length,bound:{thread_id:thread.id,context_sha256:thread.context_sha256},id:null,cancelled:false}}
      const req=request;check(req);
      try{
        let item;
        if(!large){progress(req,'saving');item=await api('commerce_copilot_material_upload',{...req.bound,filename,mime_type,content_base64:content,idempotency_key:req.key})}
        else{
          const receipt=await api('commerce_copilot_material_upload_begin',{...req.bound,filename,mime_type,size_bytes:bytes.length,content_sha256:digest,idempotency_key:req.key});
          req.id=receipt.id;check(req);
          if(!['uploading','completed'].includes(receipt.status))throw Error('copilot_upload_not_active');
          const size=receipt.chunk_bytes,index=receipt.next_index;
          if(!Number.isInteger(size)||size<1||size>49152||!Number.isInteger(index)||index<0||index>Math.ceil(bytes.length/size))throw Error('copilot_upload_invalid_receipt');
          if(receipt.status!=='completed')for(let i=index;i*size<bytes.length;i++){
            check(req);progress(req,'uploading',i*size);
            await api('commerce_copilot_material_upload_chunk',{...req.bound,upload_id:req.id,index:i,content_base64:base64(bytes.subarray(i*size,Math.min(bytes.length,(i+1)*size)))});
          }
          check(req);req.finishing=true;progress(req,'finishing',bytes.length);
          item=await api('commerce_copilot_material_upload_finish',{...req.bound,upload_id:req.id});
        }
        progress(req,'completed',bytes.length);if(request===req)request=null;return item;
      }catch(error){if((error.code||error.message)==='copilot_upload_expired'&&request===req)request=null;progress(req,req.cancelConfirmed?'cancelled':'unconfirmed');if(req.cancelConfirmed)throw Error('copilot_upload_cancelled');throw error}
    }
    return {upload,async cancel(){const req=request;if(!req?.id||req.finishing||!['uploading','unconfirmed'].includes(req.status))throw Error('copilot_upload_not_cancellable');req.cancelled=true;try{const result=await api('commerce_copilot_material_upload_cancel',{...req.bound,upload_id:req.id});req.cancelConfirmed=true;if(request===req)request=null;progress(req,'cancelled');return result;}catch(error){progress(req,'unconfirmed');throw error}},dispose(){disposed=true}};
  }};
})(typeof window==='undefined'?globalThis:window);
