import * as maplibregl from 'maplibre-gl';
import workerSource from 'maplibre-gl/dist/maplibre-gl-worker.mjs?inline-worker';
import {MapLibreOverlay} from '@deck.gl/maplibre';
import {ScatterplotLayer,IconLayer,TextLayer} from '@deck.gl/layers';
import {clusterRows,colorFor} from './model.mjs';
import 'maplibre-gl/dist/maplibre-gl.css';

// An inline classic worker avoids module-worker fetches in opaque srcdoc.
const workerUrl=URL.createObjectURL(new Blob([workerSource],{type:'text/javascript'}))+'#.cjs';
window.addEventListener('pagehide',()=>URL.revokeObjectURL(workerUrl.split('#')[0]),{once:true});
maplibregl.setWorkerUrl(workerUrl);
maplibregl.setWorkerCount(2);
const rgb=hex=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16));
const arrow=document.createElement('canvas');arrow.width=32;arrow.height=32;
const arrowPaint=arrow.getContext('2d');arrowPaint.fillStyle='#fff';arrowPaint.beginPath();for(const [i,p]of [[16,1],[29,29],[16,22],[3,29]].entries())arrowPaint[i?'lineTo':'moveTo'](...p);arrowPaint.closePath();arrowPaint.fill();
export class PlaneRenderer {
  constructor(host,countries,callbacks,view){
    this.host=host;this.callbacks=callbacks;this.rows=[];this.countries=countries;this.active=false;
    this.map=new maplibregl.Map({container:host,locale:{'Map.Title':'全球交互地图'},attributionControl:false,center:[view.lng,view.lat],zoom:view.zoom,
      renderWorldCopies:false,maxZoom:8,minZoom:.8,dragRotate:true,touchPitch:true,canvasContextAttributes:{antialias:true,powerPreference:'high-performance'},
      style:{version:8,sources:{countries:{type:'geojson',data:{type:'FeatureCollection',features:countries}}},layers:[
        {id:'ocean',type:'background',paint:{'background-color':'#071222'}},
        {id:'land',type:'fill',source:'countries',paint:{'fill-color':'#20364b','fill-opacity':1}},
        {id:'borders',type:'line',source:'countries',paint:{'line-color':'#64829b','line-width':.65,'line-opacity':.65}}
      ]}});
    this.overlay=new MapLibreOverlay({interleaved:true,layers:[],pickingRadius:8,useDevicePixels:Math.min(devicePixelRatio||1,1.5),
      onClick:info=>{if(info.object)callbacks.onPick?.(info.object)},onHover:info=>callbacks.onHover?.(info.object,info.x,info.y),
      onError:error=>{console.warn('Geographic layer:',error?.message);callbacks.onError?.('地图图层暂不可用，可切换地球或重试。')}});
    this.map.addControl(this.overlay);
    this.map.on('load',()=>{this.ready=true;this.draw();callbacks.onReady?.()});
    this.map.on('movestart',event=>{if(event.originalEvent)callbacks.onInteraction?.()});
    this.map.on('moveend',()=>{this.draw();if(this.active)callbacks.onView?.(this.getView())});
    this.map.on('render',()=>callbacks.onFrame?.());
    this.map.on('webglcontextlost',callbacks.onContextLost);
    this.map.on('error',()=>{if(!this.ready)callbacks.onError?.('二维地图暂不可用，可使用三维地球。')});
  }
  getView(){const c=this.map.getCenter();return {lng:c.lng,lat:c.lat,zoom:this.map.getZoom(),bearing:this.map.getBearing(),pitch:this.map.getPitch()}}
  setView(view,duration=0){this.map.flyTo({center:[view.lng,view.lat],zoom:view.zoom,bearing:view.bearing||0,pitch:view.pitch||0,duration,essential:false})}
  resize(){this.map.resize()}
  setActive(active){this.active=active;if(!active)this.map.stop();else this.resize()}
  setCruise(){}
  setQuality(high){this.overlay.setProps({useDevicePixels:Math.min(devicePixelRatio||1,high?1.75:1)})}
  update(rows,selected){this.rows=rows;this.selected=selected;this.draw()}
  draw(){if(!this.ready)return;
    const shown=clusterRows(this.rows,this.map.getZoom()),arrows=shown.filter(r=>!r.cluster&&['flight','vessel'].includes(r.kind)&&Number.isFinite(r.heading)),dots=shown.filter(r=>r.cluster||!['flight','vessel'].includes(r.kind)||!Number.isFinite(r.heading));
    const common={pickable:true,getPosition:r=>[r.lng,r.lat]},getColor=r=>rgb(r.id===this.selected?'#ffffff':colorFor(r));
    this.overlay.setProps({layers:[
      new ScatterplotLayer({...common,id:'intel-observations',data:dots,getFillColor:getColor,getRadius:r=>r.cluster?Math.min(14,5+Math.log2(r.children.length)*1.2):4,radiusUnits:'pixels',radiusMinPixels:3,stroked:true,getLineColor:[240,248,255,160],lineWidthUnits:'pixels',getLineWidth:.65}),
      new IconLayer({...common,id:'intel-transport',data:arrows,iconAtlas:arrow,iconMapping:{arrow:{x:0,y:0,width:32,height:32,mask:true}},getIcon:()=> 'arrow',getColor,getSize:14,getAngle:r=>-(r.heading||0),billboard:false}),
      new TextLayer({id:'intel-cluster-labels',data:shown.filter(r=>r.cluster),getPosition:r=>[r.lng,r.lat],getText:r=>String(r.children.length),getSize:11,getColor:[255,255,255],fontFamily:'PingFang SC, Microsoft YaHei, sans-serif',fontWeight:600,characterSet:'auto',pickable:false}),
      new TextLayer({id:'intel-country-labels',data:this.countries.filter(c=>c.properties.area>(this.map.getZoom()<2?5:this.map.getZoom()<3?1:this.map.getZoom()<4 ? .1 : 0)),getPosition:c=>[c.properties.lng,c.properties.lat],getText:c=>c.properties.zh,getSize:11,getColor:[166,192,213,210],fontFamily:'PingFang SC, Microsoft YaHei, sans-serif',characterSet:'auto',pickable:false})
    ]});
    this.host.dataset.rendered=String(shown.length);this.host.dataset.observations=String(this.rows.length);
  }
  dispose(){this.map.stop();this.map.removeControl(this.overlay);this.map.remove();this.host.replaceChildren()}
}
