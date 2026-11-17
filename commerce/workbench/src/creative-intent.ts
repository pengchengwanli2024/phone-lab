/** Product-to-content links retain their own identity, outside generic record IDs. */
export interface CreativeIntent { id:string;case_id:string;source_sha256:string;project_id?:string }
const validId=(value:string|null)=>!!value&&/^[a-zA-Z0-9_-]{1,160}$/.test(value);
export function readCreativeIntent(params:URLSearchParams):CreativeIntent|null {
  const caseId=params.get('creative_case_id'),source=params.get('creative_source'),project=params.get('creative_project_id'),id=params.get('creative_intent_id');
  if(!validId(caseId)||!source||!/^[a-f0-9]{64}$/.test(source)||project&&!validId(project)||id&&!validId(id))return null;
  return {id:id||crypto.randomUUID(),case_id:caseId!,source_sha256:source,...(project?{project_id:project}:{})};
}
export function writeCreativeIntent(url:URL,intent:CreativeIntent|null){
  for(const key of ['creative_case_id','creative_source','creative_project_id','creative_intent_id'])url.searchParams.delete(key);
  if(intent){url.searchParams.set('creative_case_id',intent.case_id);url.searchParams.set('creative_source',intent.source_sha256);url.searchParams.set('creative_intent_id',intent.id);if(intent.project_id)url.searchParams.set('creative_project_id',intent.project_id);}
}
