export {};
type ShippingFile = {filename:string;mime_type:string;content:string};
type ShippingFileReceipt = {status:'saved'|'requested'|'cancelled'|'selected';filename?:string;path?:string;content?:string;bytes?:number};
type ShippingFileArgs = {file:ShippingFile}|{kind:'rates'|'items'|'cartons'};
type ShippingFileOperation = 'download'|'pick-csv';
interface ShippingFileClient {request(op:ShippingFileOperation,args:ShippingFileArgs):Promise<ShippingFileReceipt>;dispose():void;}
declare global {
  interface Window {
    CommerceShippingFiles: {
      readCsv(file:File,options:{kind:'rates'|'items'|'cartons'}):Promise<{content:string;filename:string;bytes:number}>;
      createClient(options:{target:Window;nonce:string;timeoutMs?:number}):ShippingFileClient;
      saveFile(file:ShippingFile):Promise<ShippingFileReceipt>;
      handleRequest(event:MessageEvent,options:{source:Window|null;nonce:string;perform:(op:ShippingFileOperation,args:ShippingFileArgs)=>Promise<ShippingFileReceipt>;alive?:()=>boolean}):Promise<boolean>;
    };
  }
}
