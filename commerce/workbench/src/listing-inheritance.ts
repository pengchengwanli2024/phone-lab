import type {ListingTarget} from './listing-observation';
export type ListingFields={sku:string;title:string;description:string;category_id:string;price:string|number;currency:string;quantity:number|null;image_refs:string[]};
export type ListingFieldOverrides=Partial<ListingFields>;
export interface InheritedListing {target:ListingTarget;revision:number;source_sha256:string;payload:{fields:ListingFields};base_fields?:ListingFields;base_sha256?:string;field_overrides?:ListingFieldOverrides}
export function supportsInheritance(data:InheritedListing):boolean{return !!data.base_fields&&!!data.base_sha256&&data.field_overrides!==undefined;}
export function listingOverrides(data:InheritedListing):ListingFieldOverrides{return structuredClone(supportsInheritance(data)?data.field_overrides!:data.payload.fields);}
export function rebaseListingFields<T extends {fields:ListingFields}>(payload:T,data:InheritedListing,overrides:ListingFieldOverrides):T{return supportsInheritance(data)?{...payload,fields:{...data.base_fields!,...overrides}}:payload;}
export function listingSaveArguments<T extends {fields:ListingFields}>(data:InheritedListing,payload:T,overrides:ListingFieldOverrides){return {...data.target,payload,expected_revision:data.revision,expected_source_sha256:data.source_sha256,...(supportsInheritance(data)?{field_overrides:structuredClone(overrides),expected_base_sha256:data.base_sha256}:{})};}
/** Any actual field edit is a store override; metadata edits leave inheritance alone. */
export function changedListingOverrides(previous:ListingFields,next:ListingFields,overrides:ListingFieldOverrides):ListingFieldOverrides{
 const result={...overrides};
 for(const key of Object.keys(next)as (keyof ListingFields)[])if(JSON.stringify(previous[key])!==JSON.stringify(next[key]))Object.assign(result,{[key]:next[key]});
 return result;
}
