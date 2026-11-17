export interface PreparedOrderSupport {
  context:{schema:'commerce-order-support-context-v1';scope:{demo:boolean;platform:string;store_id:string;market:string};order:{id:string;order_id:string;source_sha256:string;record_sha256:string;import_batch_id:string|null};context_sha256:string};
  sources:unknown[];external_execution_allowed:false;
}
export interface OrderSupportRequest {id:string;prepared:PreparedOrderSupport}
