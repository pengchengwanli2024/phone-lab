// Geographic data and scale are independent of either renderer's camera objects.
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
export const altitudeForZoom=zoom=>2.4*2**(-.85*(clamp(Number(zoom)||1,1,9)-1));
export const zoomForAltitude=altitude=>clamp(1+Math.log2(2.4/Math.max(.001,Number(altitude)||2.4))/.85,1,9);
export const longitude=v=>((v+180)%360+360)%360-180;
export const shortLongitude=(from,to)=>from+longitude(to-from);
export function viewBounds(view,aspect=2){
  if(view.zoom<=1.8)return {west:-180,east:180,south:-90,north:90};
  const span=Math.min(359.99,360/2**(view.zoom-1)),height=Math.min(180,span/Math.max(.6,aspect));
  return {west:longitude(view.lng-span/2),east:longitude(view.lng+span/2),south:clamp(view.lat-height/2,-90,89.99),north:clamp(view.lat+height/2,-89.99,90)};
}
export function normalizeRows(rows){
  const found=new Map();
  for(const r of rows||[]){const lat=r.location?.lat,lon=r.location?.lon;
    if(typeof r.id!=='string'||!Number.isFinite(lat)||!Number.isFinite(lon)||Math.abs(lat)>90||Math.abs(lon)>180)continue;
    found.set(r.id,{...r,lat,lng:lon,title:String(r.title||r.callsign||r.name||r.icao24||r.mmsi||r.id)});
  }
  return [...found.values()];
}
export function clusterRows(rows,zoom){
  if(zoom>=4.2)return rows;
  const cell=zoom<2?12:zoom<3?6:3,groups=new Map();
  for(const r of rows){const key=[r.kind,Math.floor((r.lng+180)/cell),Math.floor((r.lat+90)/cell)].join(':');
    if(!groups.has(key))groups.set(key,[]);groups.get(key).push(r);
  }
  return [...groups].map(([key,children])=>children.length===1?children[0]:({id:'cluster:'+key,kind:children[0].kind,cluster:true,children,
    lat:children.reduce((n,r)=>n+r.lat,0)/children.length,lng:children.reduce((n,r)=>n+r.lng,0)/children.length,
    title:({flight:'航空器',vessel:'船舶',event:'情报事件',reference:'地理参考'})[children[0].kind]+' · '+children.length+' 条'}));
}
export function retainedUpdate(previous,rows){
  const signature=JSON.stringify(rows.map(r=>[r.id,r.lat,r.lng,r.title,r.heading,r.category,r.observed_at,r.published,r.record_sha256,r.altitude_m,r.speed_kmh,r.country]));
  return previous?.signature===signature?previous:{signature,rows};
}
export const colorFor=r=>r.kind==='flight'?'#82b5ff':r.kind==='vessel'?'#48dec0':r.kind==='reference'?'#dbe7f4':r.category==='earthquake'?'#ffc65a':'#ff875d';

// resumeAnimation renders its first frame synchronously. Mark the loop running
// before that frame can dispatch another controls/change event.
export function animationGate(resume,pause){
  let running=false;
  return {start(){if(running)return;running=true;try{resume()}catch(error){running=false;throw error}},stop(){if(!running)return;running=false;pause()}};
}
