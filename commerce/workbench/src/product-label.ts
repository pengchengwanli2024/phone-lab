import '../../web/product-identity.js';
import {api} from './api';
interface ProductIdentity {id?:string;name?:string;platform?:string;market?:string;scope?:Record<string,unknown>}
declare global {interface Window {CommerceProductIdentity:{label:(item:ProductIdentity,peers?:ProductIdentity[])=>string;meta:(item:ProductIdentity)=>string;merge:<T extends ProductIdentity>(items:T[],records:ProductIdentity[])=>T[]}}}
export const productLabel=(item:ProductIdentity,peers:ProductIdentity[]=[])=>window.CommerceProductIdentity.label(item,peers);

export async function enrichProductChoices<T extends ProductIdentity>(items:T[]):Promise<T[]> {try{const value=await api<{cases:ProductIdentity[]}>('commerce_agent_cases');return window.CommerceProductIdentity.merge(items,value.cases);}catch{return items;}}
