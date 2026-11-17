/* Dependency-free, shared SVG packing viewer. Coordinates remain in centimetres. */
window.CommerceShippingViewer = (() => {
  const NS='http://www.w3.org/2000/svg',EPS=1e-8,DEFAULT={yaw:40,pitch:30,zoom:1};
  const COLORS=['var(--ui-color-action-primary)','var(--ui-color-success)','var(--ui-color-warning)','var(--ui-color-text)'];
  const FACES=[
    {name:'x-',axis:0,sign:-1,ids:[0,3,7,4]}, {name:'x+',axis:0,sign:1,ids:[1,5,6,2]},
    {name:'y-',axis:1,sign:-1,ids:[0,4,5,1]}, {name:'y+',axis:1,sign:1,ids:[3,2,6,7]},
    {name:'z-',axis:2,sign:-1,ids:[0,1,2,3]}, {name:'z+',axis:2,sign:1,ids:[4,7,6,5]}
  ];
  const EDGES=[[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]];
  let sequence=0;
  const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
  const wrap=n=>((n%360)+360)%360;
  const finite=n=>typeof n==='number'&&Number.isFinite(n);
  const vertices=([x,y,z],[l,w,h])=>[[x,y,z],[x+l,y,z],[x+l,y+w,z],[x,y+w,z],[x,y,z+h],[x+l,y,z+h],[x+l,y+w,z+h],[x,y+w,z+h]];
  const dimensions=a=>Array.isArray(a)&&a.length===3&&a.every(n=>finite(n)&&n>0);
  const position=a=>Array.isArray(a)&&a.length===3&&a.every(n=>finite(n)&&n>=0);

  // A face-centre sort is wrong for mixed-size cuboids whose depth ranges overlap.
  // Build an axis-aligned BSP once per packing/filter change. Its split polygons
  // can be traversed back-to-front from any camera, including below the carton.
  function partition(face,axis,value) {
    const back=[],front=[],v=face.vertices;
    for(let i=0;i<v.length;i++){
      const a=v[i],b=v[(i+1)%v.length],da=a[axis]-value,db=b[axis]-value;
      if(da<=EPS)back.push(a);if(da>=-EPS)front.push(a);
      if((da>EPS&&db<-EPS)||(da<-EPS&&db>EPS)){
        const t=da/(da-db),p=a.map((n,j)=>n+(b[j]-n)*t);p[axis]=value;back.push(p);front.push(p);
      }
    }
    return [back,front];
  }
  function bsp(faces) {
    if(!faces.length)return null;
    let plane=faces[0],best=Infinity;
    for(let sample=0;sample<Math.min(9,faces.length);sample++){
      const candidate=faces[Math.floor(sample*faces.length/Math.min(9,faces.length))],axis=candidate.axis,value=candidate.vertices[0][axis];
      let below=0,above=0,split=0;
      for(const face of faces){const ds=face.vertices.map(v=>v[axis]-value),min=Math.min(...ds),max=Math.max(...ds);if(min<-EPS)below++;if(max>EPS)above++;if(min<-EPS&&max>EPS)split++;}
      const score=Math.abs(below-above)+split*3;if(score<best){best=score;plane=candidate;}
    }
    const axis=plane.axis,value=plane.vertices[0][axis],back=[],front=[],coplanar=[];
    for(const face of faces){
      const ds=face.vertices.map(v=>v[axis]-value),min=Math.min(...ds),max=Math.max(...ds);
      if(min>=-EPS&&max<=EPS)coplanar.push(face);
      else if(max<=EPS)back.push(face);
      else if(min>=-EPS)front.push(face);
      else {const [a,b]=partition(face,axis,value);if(a.length>=3)back.push({...face,vertices:a});if(b.length>=3)front.push({...face,vertices:b});}
    }
    return {axis,coplanar,back:bsp(back),front:bsp(front)};
  }
  function ordered(tree,direction,visit){
    if(!tree)return;
    const positive=direction[tree.axis]>=0;
    ordered(positive?tree.back:tree.front,direction,visit);
    for(const face of tree.coplanar)if(face.sign*direction[face.axis]>EPS)visit(face);
    ordered(positive?tree.front:tree.back,direction,visit);
  }

  function create({element,box=null,count,layer='all',palette=null,initialState={},onChange=()=>{},label='可旋转的商品三维装箱图'}={}) {
    if(!element?.ownerDocument)throw new TypeError('装箱查看器需要一个 SVG 元素');
    const document=element.ownerDocument,view=document.defaultView||window;
    const camera={...DEFAULT},pointers=new Map(),listeners=[],descriptionId=`shipping-viewer-description-${++sequence}`;
    let currentBox=box,currentPalette=palette,limit=count,currentLayer=String(layer),tree=null,visibleCount=0,totalCount=0,destroyed=false,frame=null;
    const originalAttributes=new Map(['tabindex','role','aria-label','aria-describedby','aria-keyshortcuts'].map(name=>[name,element.getAttribute(name)]));
    const node=(name,attrs={},text)=>{const n=document.createElementNS(NS,name);for(const [key,value]of Object.entries(attrs))n.setAttribute(key,value);if(text!==undefined)n.textContent=text;return n;};
    const getState=()=>({...camera,visibleCount,totalCount});
    const notify=()=>{if(!destroyed)onChange(getState());};
    const color=sku=>{
      const supplied=typeof currentPalette==='function'?currentPalette(sku):currentPalette?.get?.(sku)??currentPalette?.[sku];
      if(typeof supplied==='string'&&supplied)return supplied;
      let hash=0;for(const char of String(sku))hash=(Math.imul(hash,31)+char.codePointAt(0))>>>0;return COLORS[hash%COLORS.length];
    };
    function rebuild(){
      const items=Array.isArray(currentBox?.items)?currentBox.items:[];totalCount=items.length;
      const n=limit==null?totalCount:clamp(Math.floor(Number(limit)||0),0,totalCount),faces=[];visibleCount=0;
      if(dimensions(currentBox?.inner_cm))for(let index=0;index<n;index++){
        const item=items[index];if(currentLayer!=='all'&&String(item.position_cm?.[2])!==currentLayer)continue;
        if(!position(item.position_cm)||!dimensions(item.orientation_cm))continue;
        visibleCount++;const v=vertices(item.position_cm,item.orientation_cm),sku=String(item.sku??'');
        for(const face of FACES)faces.push({...face,index,sku,vertices:face.ids.map(i=>v[i])});
      }
      tree=bsp(faces);
    }
    function render(){
      if(destroyed)return;if(frame!==null){view.cancelAnimationFrame?.(frame);frame=null;}
      const rect=element.getBoundingClientRect(),w=rect.width>0?rect.width:600,h=rect.height>0?rect.height:w<480?260:340;
      element.setAttribute('viewBox',`0 0 ${w} ${h}`);
      const title=node('title',{},`${currentBox?.carton_name||'装箱示意'}：已显示 ${visibleCount} / ${totalCount} 件`);
      const description=node('desc',{id:descriptionId},'拖动旋转，滚轮或双指缩放；键盘方向键旋转，加减键缩放，Home 重置。依据估算坐标绘制；现场复核缓冲、承重和稳定性。');
      const behind=node('g',{'aria-hidden':'true'}),goods=node('g',{'aria-hidden':'true'}),ahead=node('g',{'aria-hidden':'true'});
      element.replaceChildren(title,description,behind,goods,ahead);
      if(!dimensions(currentBox?.inner_cm))return;
      const size=currentBox.inner_cm,center=size.map(n=>n/2),outer=vertices([0,0,0],size),yaw=camera.yaw*Math.PI/180,pitch=camera.pitch*Math.PI/180;
      const cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch),direction=[sy*cp,cy*cp,sp];
      const project0=p=>{const [x,y,z]=p.map((n,i)=>n-center[i]);return [x*cy-y*sy,(x*sy+y*cy)*sp-z*cp];};
      const corners=outer.map(project0),xs=corners.map(p=>p[0]),ys=corners.map(p=>p[1]);
      const scale=Math.min(Math.max(1,w-40)/Math.max(EPS,Math.max(...xs)-Math.min(...xs)),Math.max(1,h-40)/Math.max(EPS,Math.max(...ys)-Math.min(...ys)))*camera.zoom;
      const project=p=>{const q=project0(p);return [q[0]*scale+w/2,q[1]*scale+h/2];};
      ordered(tree,direction,face=>{
        const fill=`color-mix(in srgb,${color(face.sku)} ${[64,76,90][face.axis]}%,var(--ui-color-surface))`;
        const polygon=node('polygon',{points:face.vertices.map(project).map(p=>p.map(n=>Number(n.toFixed(3))).join(',')).join(' '),fill,stroke:'var(--ui-color-surface)','stroke-width':.8,'stroke-linejoin':'round','data-shipping-item':face.index,'data-shipping-sku':face.sku,'data-shipping-face':face.name});
        polygon.appendChild(node('title',{},`${face.sku} · 装入 ${face.index+1}`));goods.appendChild(polygon);
      });
      for(const [a,b]of EDGES){
        const front=FACES.some(f=>f.ids.includes(a)&&f.ids.includes(b)&&f.sign*direction[f.axis]>EPS),p=project(outer[a]),q=project(outer[b]);
        const line=node('line',{x1:p[0],y1:p[1],x2:q[0],y2:q[1],stroke:'var(--ui-color-text)','stroke-opacity':front?.55:.22,'stroke-width':1,'vector-effect':'non-scaling-stroke'});
        if(!front)line.setAttribute('stroke-dasharray','4 4');(front?ahead:behind).appendChild(line);
      }
    }
    function schedule(){if(destroyed||frame!==null)return;if(view.requestAnimationFrame)frame=view.requestAnimationFrame(()=>{frame=null;render();});else render();}
    function setState(next={}){
      if(destroyed)return;
      if(finite(next.yaw))camera.yaw=wrap(next.yaw);
      if(finite(next.pitch))camera.pitch=wrap(next.pitch+180)-180;
      if(finite(next.zoom))camera.zoom=clamp(next.zoom,.25,4);
      schedule();notify();
    }
    const rotateBy=(yaw=0,pitch=0)=>setState({yaw:camera.yaw+yaw,pitch:camera.pitch+pitch});
    const zoomBy=ratio=>setState({zoom:camera.zoom*ratio});
    function setFilter(next={}){
      if(destroyed)return;if('count'in next)limit=next.count;if('layer'in next)currentLayer=String(next.layer??'all');rebuild();schedule();notify();
    }
    function setBox(next,options={}){
      if(destroyed)return;currentBox=next;if('palette'in options)currentPalette=options.palette;setFilter(options);
    }
    function listen(type,handler,options){element.addEventListener(type,handler,options);listeners.push([type,handler,options]);}
    const location=event=>({x:event.clientX,y:event.clientY});
    const distance=()=>{const [a,b]=pointers.values();return a&&b?Math.hypot(a.x-b.x,a.y-b.y):0;};
    function release(event){
      pointers.delete(event.pointerId);
      if(element.hasPointerCapture?.(event.pointerId))element.releasePointerCapture(event.pointerId);
      if(!pointers.size)element.removeAttribute('data-shipping-dragging');
    }
    listen('pointerdown',event=>{
      if(event.button!==0||pointers.size>=2)return;
      event.preventDefault();element.focus({preventScroll:true});pointers.set(event.pointerId,location(event));element.setPointerCapture?.(event.pointerId);element.setAttribute('data-shipping-dragging','true');
    });
    listen('pointermove',event=>{
      const previous=pointers.get(event.pointerId);if(!previous)return;event.preventDefault();
      const before=distance();pointers.set(event.pointerId,location(event));
      if(pointers.size===2){const after=distance();if(before>0&&after>0)zoomBy(after/before);}
      else rotateBy((event.clientX-previous.x)*.5,(event.clientY-previous.y)*.5);
    });
    for(const type of ['pointerup','pointercancel','lostpointercapture'])listen(type,release);
    listen('wheel',event=>{
      if(!finite(event.deltaY))return;event.preventDefault();
      const unit=event.deltaMode===1?16:event.deltaMode===2?(element.getBoundingClientRect().height||340):1;
      zoomBy(Math.exp(clamp(-event.deltaY*unit*.0015,-20,20)));
    },{passive:false});
    listen('keydown',event=>{
      if(event.ctrlKey||event.metaKey||event.altKey)return;
      const amount=event.shiftKey?30:10,actions={ArrowLeft:()=>rotateBy(-amount,0),ArrowRight:()=>rotateBy(amount,0),ArrowUp:()=>rotateBy(0,amount),ArrowDown:()=>rotateBy(0,-amount),'+':()=>zoomBy(1.2),'=':()=>zoomBy(1.2),'-':()=>zoomBy(1/1.2),'_':()=>zoomBy(1/1.2),Home:()=>setState(DEFAULT)};
      if(actions[event.key]){event.preventDefault();actions[event.key]();}
    });
    element.classList.add('shipping-viewer');element.setAttribute('tabindex','0');element.setAttribute('role','img');element.setAttribute('aria-label',label);element.setAttribute('aria-describedby',descriptionId);element.setAttribute('aria-keyshortcuts','ArrowLeft ArrowRight ArrowUp ArrowDown + - Home');
    const Observer=view.ResizeObserver,observer=Observer?new Observer(schedule):null;
    if(observer)observer.observe(element);else view.addEventListener('resize',schedule);
    for(const key of ['yaw','pitch','zoom'])if(finite(initialState[key]))camera[key]=key==='zoom'?clamp(initialState[key],.25,4):key==='yaw'?wrap(initialState[key]):wrap(initialState[key]+180)-180;
    rebuild();render();notify();
    return {getState,setState,setBox,setFilter,rotateBy,zoomIn:()=>zoomBy(1.2),zoomOut:()=>zoomBy(1/1.2),reset:()=>setState(DEFAULT),render,destroy(){
      if(destroyed)return;destroyed=true;
      for(const [type,handler,options]of listeners)element.removeEventListener(type,handler,options);
      for(const pointerId of pointers.keys())if(element.hasPointerCapture?.(pointerId))element.releasePointerCapture(pointerId);
      pointers.clear();element.removeAttribute('data-shipping-dragging');observer?.disconnect();if(!observer)view.removeEventListener('resize',schedule);
      if(frame!==null)view.cancelAnimationFrame?.(frame);frame=null;element.classList.remove('shipping-viewer');
      for(const [name,value]of originalAttributes)if(value===null)element.removeAttribute(name);else element.setAttribute(name,value);
    }};
  }
  return {create};
})();
