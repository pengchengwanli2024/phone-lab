const documents = new Map<string, Promise<string>>();

function completeBlock(id: string): Promise<void> {
  const complete = () => document.readyState !== 'loading' || !!document.getElementById(id + '-complete');
  if (complete()) return Promise.resolve();
  return new Promise<void>(resolve => {
    let observer: MutationObserver | undefined;
    const check = () => {
      if (!complete()) return;
      observer?.disconnect();
      document.removeEventListener?.('DOMContentLoaded', check);
      resolve();
    };
    document.addEventListener('DOMContentLoaded', check, { once: true });
    if (typeof MutationObserver === 'function' && document.documentElement) {
      observer = new MutationObserver(check);
      observer.observe(document.documentElement, { childList: true, subtree: true });
    }
    // Close the race between the initial check and subscribing to parser work.
    check();
  });
}

/** The artifact is trusted build output, never user/model HTML. No network load. */
export function embeddedDocument(packed: string): Promise<string> {
  const existing=documents.get(packed);
  if(existing)return existing;
  const pending=decode(packed).catch(error=>{documents.delete(packed);throw error;});
  documents.set(packed,pending);
  return pending;
}

/** Browsers fetch the packed document on demand; a host that only got the HTML keeps it inline. */
async function fetchPayload(identifier:string):Promise<string>{
  const response=await fetch('/workspace/document/'+encodeURIComponent(identifier),{credentials:'same-origin',headers:{accept:'text/plain'}});
  if(!response.ok)throw Error('embedded_document_unavailable');
  const payload=(await response.text()).trim();
  // The endpoint returns base64 of one gzip stream; anything else is not our artifact.
  if(!payload||!/^[A-Za-z0-9+/]+={0,2}$/.test(payload))throw Error('embedded_document_invalid');
  return payload;
}

async function decode(packed: string) {
  if(typeof DecompressionStream!=='function')throw Error('embedded_document_unsupported');
  if(packed.startsWith('inline:')){
    const identifier=packed.slice(7),id='commerce-embedded-'+identifier;
    // New artifacts release each complete block independently. Older artifacts
    // without completion markers retain the DOMContentLoaded fallback.
    await completeBlock(id);
    const payload=document.getElementById(id)?.textContent?.trim()||await fetchPayload(identifier);
    if(!payload)throw Error('embedded_document_missing');
    packed=payload;
  }
  const binary=atob(packed),bytes=new Uint8Array(binary.length);
  for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);
  const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Response(stream).text();
}
