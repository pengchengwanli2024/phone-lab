import type {OpsAlert} from './types';

export type AlertEvidence=OpsAlert&{platform?:string;market?:string;warehouse?:string;order_id?:string|null;observed_at?:string;source_sha256?:string;source?:string;rules?:{max_age_minutes?:number;dispatch_warning_hours?:number}};
export interface AlertEvidenceRow {alert:AlertEvidence;live:boolean}

// This is a transient UI selection, never a new alert or business state.
export function alertEvidenceKey(row:AlertEvidenceRow,demo:boolean,storeScope:string):string {
  return JSON.stringify([demo,storeScope,row.live,row.alert]);
}
export function selectedAlertEvidence(rows:AlertEvidenceRow[],selection:string,demo:boolean,storeScope:string):AlertEvidenceRow|null {
  return rows.find(row=>alertEvidenceKey(row,demo,storeScope)===selection)||null;
}
