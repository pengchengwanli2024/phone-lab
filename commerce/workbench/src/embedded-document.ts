const documents = new Map<string, Promise<string>>();

/** The artifact is trusted build output, never user/model HTML. No network load. */
export function embeddedDocument(packed: string): Promise<string> {
  const existing=documents.get(packed);
  if(existing)return existing;
  const pending=decode(packed).catch(error=>{documents.delete(packed);throw error;});
  documents.set(packed,pending);
  return pending;
}

async function decode(packed: string) {
  if(typeof DecompressionStream!=='function')throw Error('embedded_document_unsupported');
  if(packed.startsWith('inline:')){
    const id='commerce-embedded-'+packed.slice(7);
    // The shell can paint while the HTML parser is still receiving inert data.
    if(document.readyState==='loading'){
      await new Promise<void>(resolve=>document.addEventListener('DOMContentLoaded',()=>resolve(),{once:true}));
    }
    const payload=document.getElementById(id)?.textContent?.trim();
    if(!payload)throw Error('embedded_document_missing');
    packed=payload;
  }
  const binary=atob(packed),bytes=new Uint8Array(binary.length);
  for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);
  const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Response(stream).text();
}
