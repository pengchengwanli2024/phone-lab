import {EarthRenderer} from './globe.js';
import {PlaneRenderer} from './flat.js';
import {normalizeRows,retainedUpdate,viewBounds} from './model.mjs';
import countries from './countries.generated.json';
import './style.css';

window.CommerceGeoMap=({onPick,onView,isActive})=>{
  const ui=window.CommerceUI,stage=document.createElement('div');stage.className='intel-geo-stage';stage.id='intel-geo-stage';
  stage.dataset.instance=crypto.randomUUID();stage.dataset.engine='globe.gl / MapLibre + deck.gl';stage.dataset.mode='globe';stage.dataset.rendering='false';
  let mode='globe',view={lng:30,lat:18,zoom:1.6},active=false,selected=null,retained=null,host=null,high=true,cruise=false,disposed=false;
  const drivers={},slots={},lifetimes={},failures=new Map(),reduced=matchMedia('(prefers-reduced-motion: reduce)'),safe=text=>String(text??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const button=(label,action,attrs={})=>ui.button({label,variant:'quiet',attrs:{'data-geo-action':action,...attrs}});
  stage.innerHTML=`<div class="intel-geo-render intel-geo-earth" id="intel-geo-earth"></div><div class="intel-geo-render intel-geo-plane" id="intel-geo-plane" hidden></div>
    <div class="intel-geo-toolbar" role="group" aria-label="地图渲染视图">${button('3D 地球','globe',{'aria-pressed':true})}${button('2D 地图','flat',{'aria-pressed':false})}${button('2D＋3D','tilt',{'aria-pressed':false})}<span class="intel-geo-toolbar-divider"></span>${button('巡航','cruise',{'aria-pressed':false,title:'缓慢旋转地球；操作地图时暂停'})}${button('清晰','quality',{'aria-pressed':true,title:'切换清晰或流畅画质'})}</div>
    <div class="intel-geo-compass" aria-hidden="true">N<span></span></div><div class="intel-geo-tooltip" hidden></div>
    <div class="intel-geo-loading" role="status">正在准备三维地球…</div><div class="intel-geo-error" role="alert" hidden></div><div class="intel-geo-retry" hidden>${button('重新启动地图','retry')}</div>
    <div class="intel-geo-caption"><span id="intel-geo-hint">拖动旋转 · 滚轮缩放 · 选点查看</span><small>NASA / Natural Earth · 静态地球纹理</small></div>`;
  slots.globe=stage.querySelector('#intel-geo-earth');slots.flat=stage.querySelector('#intel-geo-plane');
  const loading=stage.querySelector('.intel-geo-loading'),error=stage.querySelector('.intel-geo-error'),tooltip=stage.querySelector('.intel-geo-tooltip');
  let frameRaf=0,lastFrame=0,frameTimes=[],frames=0,rendering=false;
  function monitor(now){if(!active||!rendering)return;const elapsed=now-lastFrame;lastFrame=now;if(elapsed>0&&elapsed<100)frameTimes.push(elapsed);if(frameTimes.length>180)frameTimes.shift();frames++;
    if(frames%30===0&&frameTimes.length){const sorted=[...frameTimes].sort((a,b)=>a-b);stage.dataset.frameP95=sorted[Math.floor(sorted.length*.95)].toFixed(2);stage.dataset.fps=(1000/(frameTimes.reduce((a,b)=>a+b,0)/frameTimes.length)).toFixed(1);stage.dataset.frames=String(frames)}
    frameRaf=requestAnimationFrame(monitor);
  }
  function frameState(value){if(rendering===value)return;rendering=value;stage.dataset.rendering=String(value);cancelAnimationFrame(frameRaf);if(value&&active){lastFrame=performance.now();frameRaf=requestAnimationFrame(monitor)}}
  function hint(){loading.textContent=mode==='globe'?'正在准备三维地球…':'正在准备二维地图…';stage.querySelector('#intel-geo-hint').textContent=mode==='globe'?'拖动旋转 · 滚轮缩放 · 选点查看':'拖动平移 · 滚轮缩放 · 右键倾斜'}
  function announce(text){stage.querySelector('.intel-geo-retry').hidden=false;error.hidden=false;error.textContent=text;stage.dataset.error=text}
  function fail(key,text,state='failed'){
    failures.set(key,{text,state});slots[key].dataset.ready='false';drivers[key]?.setActive(false);
    if((mode==='globe'?'globe':'flat')!==key)return;
    loading.hidden=true;tooltip.hidden=true;stage.dataset.ready=state;host?.classList.remove('has-webgl');frameState(false);announce(text);
  }
  function ready(){stage.querySelector('.intel-geo-retry').hidden=true;loading.hidden=true;error.hidden=true;delete stage.dataset.error;stage.dataset.ready='true';host?.classList.add('has-webgl')}
  function hover(row,x,y){if(!row){tooltip.hidden=true;return;}tooltip.innerHTML=`<strong>${safe(row.title)}</strong>${row.observed_at?`<small>观测 ${safe(new Date(row.observed_at*1000).toLocaleTimeString('zh-CN',{hour12:false}))}</small>`:''}`;tooltip.style.left=Math.min(stage.clientWidth-190,Math.max(8,x+12))+'px';tooltip.style.top=Math.max(58,Math.min(stage.clientHeight-76,y+8))+'px';tooltip.hidden=false}
  function report(next){view={...view,...next};stage.dataset.view=JSON.stringify(view);const zoom=host?.parentElement?.querySelector('#intel-map-zoom');if(zoom)zoom.textContent=Math.round(2**(view.zoom-1)*100)+'%';if(active&&stage.isConnected)onView?.(viewBounds(view,stage.clientWidth/Math.max(1,stage.clientHeight)),view)}
  function picked(row){if(row.cluster){focus({location:{lon:row.lng,lat:row.lat}},Math.min(6,view.zoom+1.4));return;}selected=row.id;drivers[mode==='globe'?'globe':'flat']?.update(retained?.rows||[],selected);onPick?.(row)}
  const callbacks={onReady:ready,onPick:picked,onHover:hover,onView:report,onFrameState:frameState,onFrame:()=>{
    const now=performance.now(),elapsed=now-lastFrame;lastFrame=now;if(elapsed>0&&elapsed<100){frameTimes.push(elapsed);if(frameTimes.length>180)frameTimes.shift()}if(frameTimes.length){stage.dataset.frameP95=[...frameTimes].sort((a,b)=>a-b)[Math.floor(frameTimes.length*.95)].toFixed(2)}
  },onInteraction:()=>{if(cruise){cruise=false;drivers.globe?.setCruise(false);stage.querySelector('[data-geo-action="cruise"]').setAttribute('aria-pressed','false')}}};
  function ensure(){const key=mode==='globe'?'globe':'flat';if(failures.has(key)){const f=failures.get(key);fail(key,f.text,f.state);return null;}if(drivers[key])return drivers[key];loading.hidden=false;stage.dataset.ready='loading';host?.classList.remove('has-webgl');
    try{
      const token={};lifetimes[key]=token;const valid=()=>!disposed&&lifetimes[key]===token;
      const scoped=Object.fromEntries(Object.entries(callbacks).map(([name,fn])=>[name,(...args)=>{if(valid()&&!failures.has(key)&&(mode==='globe'?'globe':'flat')===key)return fn(...args)}]));
      scoped.onReady=()=>{if(!valid()||failures.has(key))return;slots[key].dataset.ready='true';if((mode==='globe'?'globe':'flat')===key)ready()};
      scoped.onError=text=>{if(valid())fail(key,text)};
      scoped.onContextLost=event=>{event.preventDefault?.();if(valid())fail(key,'地图图形上下文中断，已保留基础地图。可重新启动或切换视图。','lost')};
      drivers[key]=key==='globe'?new EarthRenderer(slots[key],countries.features,scoped):new PlaneRenderer(slots[key],countries.features,scoped,view);
      if(failures.has(key)){drivers[key].setActive(false);return null;}
      drivers[key].setView({...view,pitch:mode==='tilt'?45:0},0);drivers[key].setActive(active);drivers[key].setQuality(high);drivers[key].update(retained?.rows||[],selected);report(drivers[key].getView());resize();return drivers[key];
    }
    catch(failure){fail(key,'此环境暂不能启动该图形视图，已保留基础地图。可切换其它视图重试。');console.warn('Intelligence renderer initialization failed:',failure?.message||'renderer_error');return null}
  }
  function resize(){if(!active||!stage.isConnected||!stage.clientWidth||!stage.clientHeight)return;const driver=drivers[mode==='globe'?'globe':'flat'];driver?.resize(stage.clientWidth,stage.clientHeight)}
  const observer=new ResizeObserver(resize);observer.observe(stage);
  function switchMode(next){if(!['globe','flat','tilt'].includes(next))return;const previous=drivers[mode==='globe'?'globe':'flat'];if(previous)view={...view,...previous.getView()};previous?.setActive(false);if(cruise){cruise=false;drivers.globe?.setCruise(false);stage.querySelector('[data-geo-action="cruise"]').setAttribute('aria-pressed','false')}mode=next;error.hidden=true;stage.querySelector('.intel-geo-retry').hidden=true;stage.querySelector('[data-geo-action="cruise"]').disabled=mode!=='globe';
    slots.globe.hidden=mode!=='globe';slots.flat.hidden=mode==='globe';tooltip.hidden=true;hint();
    for(const el of stage.querySelectorAll('[data-geo-action]'))if(['globe','flat','tilt'].includes(el.dataset.geoAction))el.setAttribute('aria-pressed',String(el.dataset.geoAction===mode));
    stage.dataset.mode=mode;const driver=ensure();if(driver&&slots[mode==='globe'?'globe':'flat'].dataset.ready==='true')ready();driver?.setActive(active);driver?.setView({...view,pitch:mode==='tilt'?45:0},reduced.matches?0:650);driver?.update(retained?.rows||[],selected);
  }
  function focus(row,zoom=4.4){if(!row?.location)return;callbacks.onInteraction();view={...view,lng:row.location.lon,lat:row.location.lat,zoom};ensure()?.setView({...view,pitch:mode==='tilt'?45:0},reduced.matches?0:1100)}
  stage.addEventListener('click',event=>{const action=event.target.closest('[data-geo-action]')?.dataset.geoAction;if(!action)return;
    if(action==='retry'){const key=mode==='globe'?'globe':'flat';lifetimes[key]=null;drivers[key]?.dispose();delete drivers[key];failures.delete(key);slots[key].replaceChildren();ensure();}
    else if(['globe','flat','tilt'].includes(action))switchMode(action);
    else if(action==='cruise'){cruise=!cruise;drivers.globe?.setCruise(cruise);stage.querySelector('[data-geo-action="cruise"]').setAttribute('aria-pressed',String(cruise))}
    else if(action==='quality'){high=!high;for(const driver of Object.values(drivers))driver.setQuality(high);const el=stage.querySelector('[data-geo-action="quality"]');el.setAttribute('aria-pressed',String(high));el.textContent=high?'清晰':'流畅'}
  });
  stage.tabIndex=0;stage.setAttribute('role','application');stage.setAttribute('aria-label','全球交互地图，方向键移动，加减缩放，Home复位');
  stage.addEventListener('keydown',event=>{if(event.target.closest('button,input,select'))return;view={...view,...drivers[mode==='globe'?'globe':'flat']?.getView()};let next={...view};const step=24/2**(view.zoom-1);
    if(event.key==='ArrowLeft')next.lng-=step;else if(event.key==='ArrowRight')next.lng+=step;else if(event.key==='ArrowUp')next.lat=Math.min(85,next.lat+step);else if(event.key==='ArrowDown')next.lat=Math.max(-85,next.lat-step);else if(['+','='].includes(event.key))next.zoom=Math.min(8,next.zoom+.5);else if(event.key==='-')next.zoom=Math.max(1,next.zoom-.5);else if(event.key==='Home')next={lng:30,lat:18,zoom:1.6};else return;
    event.preventDefault();callbacks.onInteraction();view=next;ensure()?.setView({...view,pitch:mode==='tilt'?45:0},reduced.matches?0:250);
  });
  const visibility=()=>{const visible=active&&!document.hidden;drivers[mode==='globe'?'globe':'flat']?.setActive(visible)};
  document.addEventListener('visibilitychange',visibility);
  function dispose(){if(disposed)return;disposed=true;observer.disconnect();document.removeEventListener('visibilitychange',visibility);cancelAnimationFrame(frameRaf);for(const driver of Object.values(drivers))driver.dispose();stage.remove()}
  window.addEventListener('pagehide',dispose,{once:true});
  return {
    beforePaint(){if(stage.isConnected)stage.remove()},
    mount(nextHost,rows,selection){
      host=nextHost;active=!!host&&(!isActive||isActive());
      if(!active){for(const driver of Object.values(drivers))driver.setActive(false);frameState(false);return;}
      if(stage.parentElement!==host)host.prepend(stage);host.classList.toggle('has-webgl',stage.dataset.ready==='true');
      const next=retainedUpdate(retained,normalizeRows(rows)),changed=next!==retained||selection!==selected;retained=next;selected=selection;
      const driver=ensure();driver?.setActive(!document.hidden);if(changed)driver?.update(retained.rows,selected);resize();
    },
    active:()=>active&&!['failed','lost'].includes(stage.dataset.ready),zoomPercent:()=>Math.round(2**((drivers[mode==='globe'?'globe':'flat']?.getView().zoom??view.zoom)-1)*100),bounds:()=>viewBounds(view,stage.clientWidth/Math.max(1,stage.clientHeight)),focus,
    reset(){callbacks.onInteraction();view={lng:30,lat:18,zoom:1.6};ensure()?.setView(view,reduced.matches?0:900)},
    zoomBy(factor){callbacks.onInteraction();view={...view,zoom:Math.max(1,Math.min(8,view.zoom+Math.log2(factor)))};ensure()?.setView(view,reduced.matches?0:250)},
    box(box){callbacks.onInteraction();if(box.w>=720){view={lng:30,lat:18,zoom:1.6};ensure()?.setView(view,reduced.matches?0:900);return;}const zoom=1+Math.log2(720/box.w);focus({location:{lon:(box.x+box.w/2)/2-180,lat:90-(box.y+box.h/2)/2}},zoom)},dispose
  };
};
