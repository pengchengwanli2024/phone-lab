import Globe from 'globe.gl';
import * as THREE from 'three';
import earth from 'three-globe/example/img/earth-day.jpg';
import {altitudeForZoom,zoomForAltitude,shortLongitude,colorFor,clusterRows,animationGate} from './model.mjs';

// Persistent globe.gl / Three.js renderer, using the same public graphics stack
// studied in World Monitor. No application state or model calls live here.
export class EarthRenderer {
  constructor(host,countries,callbacks){
    this.host=host;this.callbacks=callbacks;this.rows=[];this.selected=null;this.sequence=0;this.active=false;this.meshes=[];
    this.globe=new Globe(host,{animateIn:false,rendererConfig:{antialias:true,alpha:true,powerPreference:'high-performance'}})
      .globeImageUrl(earth).backgroundColor('#040a15').showAtmosphere(true)
      .atmosphereColor('#76aaff').atmosphereAltitude(.15).showGraticules(true);
    this.globe.pauseAnimation();this.animation=animationGate(()=>this.globe.resumeAnimation(),()=>this.globe.pauseAnimation());
    this.globe.renderer().setPixelRatio(Math.min(devicePixelRatio||1,1.5));this.globe.postProcessingComposer().setPixelRatio(Math.min(devicePixelRatio||1,1.5));
    const material=this.globe.globeMaterial();material.shininess=8;material.emissive=new THREE.Color('#0a2140');material.emissiveIntensity=.25;
    const controls=this.globe.controls();controls.enablePan=false;controls.enableDamping=true;controls.dampingFactor=.075;controls.autoRotate=false;controls.rotateSpeed=.65;controls.zoomSpeed=1.1;controls.minDistance=108;controls.maxDistance=520;
    this.start=()=>{this.cancelFlight();this.wake();callbacks.onInteraction?.()};
    this.change=()=>{this.wake();this.refreshScale();clearTimeout(this.settled);this.settled=setTimeout(()=>this.publish(),140)};
    this.end=()=>{this.publish();this.scheduleSleep()};
    controls.addEventListener('start',this.start);controls.addEventListener('change',this.change);controls.addEventListener('end',this.end);
    this.canvas=this.globe.renderer().domElement;
    this.down=event=>{this.pointer={x:event.clientX,y:event.clientY};this.start()};
    this.move=event=>{this.hoverEvent={clientX:event.clientX,clientY:event.clientY};if(!this.hoverFrame)this.hoverFrame=requestAnimationFrame(()=>{this.hoverFrame=0;this.pick(this.hoverEvent,false)})};
    this.click=event=>{if(this.pointer&&Math.hypot(event.clientX-this.pointer.x,event.clientY-this.pointer.y)<6)this.pick(event,true)};
    this.wheel=()=>this.wake();
    this.canvas.addEventListener('pointerdown',this.down);this.canvas.addEventListener('pointermove',this.move);this.canvas.addEventListener('click',this.click);this.canvas.addEventListener('wheel',this.wheel,{passive:true});
    this.canvas.addEventListener('webglcontextlost',callbacks.onContextLost);
    const coordinates=[];
    for(const feature of countries){const polygons=feature.geometry.type==='Polygon'?[feature.geometry.coordinates]:feature.geometry.coordinates;
      for(const polygon of polygons)for(const ring of polygon)for(let i=1;i<ring.length;i++){
        if(Math.abs(ring[i][0]-ring[i-1][0])>180)continue;
        for(const p of [ring[i-1],ring[i]]){const v=this.globe.getCoords(p[1],p[0],.001);coordinates.push(v.x,v.y,v.z)}
      }
    }
    const borderGeo=new THREE.BufferGeometry();borderGeo.setAttribute('position',new THREE.Float32BufferAttribute(coordinates,3));
    this.borders=new THREE.LineSegments(borderGeo,new THREE.LineBasicMaterial({color:'#8eb5d0',transparent:true,opacity:.24}));this.globe.scene().add(this.borders);
    const starPositions=[];let seed=73;const random=()=>{seed=(seed*16807)%2147483647;return seed/2147483647};
    for(let i=0;i<1300;i++){const y=random()*2-1,angle=random()*Math.PI*2,r=1300;starPositions.push(Math.sqrt(1-y*y)*Math.cos(angle)*r,y*r,Math.sqrt(1-y*y)*Math.sin(angle)*r)}
    const starsGeo=new THREE.BufferGeometry();starsGeo.setAttribute('position',new THREE.Float32BufferAttribute(starPositions,3));
    this.stars=new THREE.Points(starsGeo,new THREE.PointsMaterial({color:'#c5d9ff',size:1.1,transparent:true,opacity:.6,sizeAttenuation:true}));this.globe.scene().add(this.stars);
    this.countries=countries.filter(c=>c.properties.zh);
    this.globe.onGlobeReady(()=>{callbacks.onReady?.();this.wake()});
  }
  getView(){const p=this.globe.pointOfView();return {lat:p.lat,lng:p.lng,zoom:zoomForAltitude(p.altitude)}}
  publish(){if(this.active)this.callbacks.onView?.(this.getView())}
  wake(){if(!this.active)return;this.animation.start();this.callbacks.onFrameState?.(true);clearTimeout(this.sleep);this.scheduleSleep()}
  scheduleSleep(){clearTimeout(this.sleep);if(this.cruise)return;this.sleep=setTimeout(()=>{if(this.active){this.animation.stop();this.callbacks.onFrameState?.(false)}},1800)}
  setActive(active){if(this.active===active)return;this.active=active;if(active)this.wake();else{this.cancelFlight();clearTimeout(this.sleep);this.animation.stop();this.callbacks.onFrameState?.(false)}}
  resize(width,height){if(this.width===width&&this.height===height)return;this.width=width;this.height=height;this.globe.width(width).height(height);const camera=this.globe.camera();camera.aspect=width/height;camera.fov=2*Math.atan(Math.tan(50*Math.PI/360)/Math.min(1,camera.aspect))*180/Math.PI;camera.updateProjectionMatrix();this.wake()}
  cancelFlight(){this.sequence++;cancelAnimationFrame(this.flight)}
  setView(view,duration=0){
    this.cancelFlight();const generation=this.sequence,start=this.getView(),target={...view,lng:shortLongitude(start.lng,view.lng)},began=performance.now();
    const animate=now=>{if(generation!==this.sequence)return;const progress=duration?Math.min(1,(now-began)/duration):1,ease=1-(1-progress)**3;
      this.globe.pointOfView({lat:start.lat+(target.lat-start.lat)*ease,lng:start.lng+(target.lng-start.lng)*ease,altitude:altitudeForZoom(start.zoom+(target.zoom-start.zoom)*ease)},0);
      this.refreshScale();if(progress<1)this.flight=requestAnimationFrame(animate);else{this.publish();this.scheduleSleep()}
    };this.wake();animate(began);
  }
  setCruise(value){this.cruise=value;this.globe.controls().autoRotate=value;this.wake()}
  setQuality(high){const ratio=Math.min(devicePixelRatio||1,high?1.75:1);this.globe.renderer().setPixelRatio(ratio);this.globe.postProcessingComposer().setPixelRatio(ratio);for(const mesh of this.meshes)if(mesh.material.uniforms?.pixelRatio)mesh.material.uniforms.pixelRatio.value=ratio;this.wake()}
  refreshScale(){const zoom=this.getView().zoom,level=zoom<2?0:zoom<3?1:zoom<4.2?2:3;
    if(this.level!==level){this.level=level;this.draw()}
  }
  update(rows,selected){this.rows=rows;this.selected=selected;this.draw();this.wake()}
  draw(){
    for(const mesh of this.meshes){this.globe.scene().remove(mesh);mesh.geometry.dispose();mesh.material.map?.dispose();mesh.material.uniforms?.atlas?.value.dispose();mesh.material.dispose()}
    this.meshes=[];const shown=clusterRows(this.rows,this.getView().zoom);
    const positions=[],norths=[],colors=[],sizes=[],types=[],headings=[],color=new THREE.Color();
    for(const r of shown){const pos=this.globe.getCoords(r.lat,r.lng,.014),near=this.globe.getCoords(Math.min(89.999,r.lat+.01),r.lng,.014);
      positions.push(pos.x,pos.y,pos.z);norths.push(near.x-pos.x,near.y-pos.y,near.z-pos.z);
      color.set(r.id===this.selected?'#ffffff':colorFor(r));colors.push(color.r,color.g,color.b);
      sizes.push((r.cluster?22:r.kind==='flight'?15:r.kind==='vessel'?13:r.kind==='reference'?10:8)*(r.id===this.selected?1.3:1));
      types.push(r.cluster?0:['flight','vessel'].includes(r.kind)&&Number.isFinite(r.heading)?1:r.kind==='reference'?2:0);headings.push((r.heading||0)*Math.PI/180);
    }
    if(shown.length){const geometry=new THREE.BufferGeometry();for(const [key,values,count]of [['position',positions,3],['aNorth',norths,3],['aColor',colors,3],['aSize',sizes,1],['aType',types,1],['aHeading',headings,1]])geometry.setAttribute(key,new THREE.Float32BufferAttribute(values,count));
      const material=new THREE.ShaderMaterial({transparent:true,depthWrite:false,uniforms:{pixelRatio:{value:this.globe.renderer().getPixelRatio()}},
        vertexShader:`attribute vec3 aColor; attribute vec3 aNorth; attribute float aSize; attribute float aType; attribute float aHeading; uniform float pixelRatio; varying vec3 vColor; varying float vType; varying float vAngle;
          void main(){vec4 centre=projectionMatrix*modelViewMatrix*vec4(position,1.0);vec4 north=projectionMatrix*modelViewMatrix*vec4(position+aNorth*100.0,1.0);vec2 direction=north.xy/north.w-centre.xy/centre.w;
          vAngle=atan(direction.x,direction.y)+aHeading;vColor=aColor;vType=aType;gl_Position=centre;gl_PointSize=aSize*pixelRatio;}`,
        fragmentShader:`precision highp float;varying vec3 vColor;varying float vType;varying float vAngle;void main(){vec2 p=vec2(gl_PointCoord.x-.5,.5-gl_PointCoord.y);float alpha=1.0;
          if(vType<.5){alpha=1.0-smoothstep(.40,.49,length(p));}else if(vType<1.5){float c=cos(vAngle),s=sin(vAngle);p=mat2(c,-s,s,c)*p;if(p.y>.46-abs(p.x)*2.3||p.y<-.40||abs(p.x)>.36||(p.y<-.12&&abs(p.x)<(-.12-p.y)*.9))discard;}else{if(abs(p.x)+abs(p.y)>.43)discard;}
          if(alpha<.02)discard;gl_FragColor=vec4(vColor,alpha*.96);}`});
      const mesh=new THREE.Points(geometry,material);mesh.userData.rows=shown;this.globe.scene().add(mesh);this.meshes.push(mesh);
    }
    const labels=shown.filter(r=>r.cluster).map(r=>({...r,text:String(r.children.length),color:'#f7fbff'}));
    this.drawLabels([...this.countries.filter(c=>c.properties.area>(this.getView().zoom<2?8:this.getView().zoom<3?1:this.getView().zoom<4 ? .1 : 0)).map(c=>({lat:c.properties.lat,lng:c.properties.lng,text:c.properties.zh})),...labels]);
    this.host.dataset.rendered=String(shown.length);this.host.dataset.observations=String(this.rows.length);
  }
  drawLabels(labels){
    if(!labels.length)return;
    const canvas=document.createElement('canvas');canvas.width=1024;canvas.height=2**Math.ceil(Math.log2(Math.max(64,Math.ceil(labels.length/8)*40)));
    const ctx=canvas.getContext('2d');ctx.textAlign='center';ctx.textBaseline='middle';ctx.font='500 24px "PingFang SC", "Microsoft YaHei", sans-serif';
    const positions=[],rects=[],sizes=[],aspects=[];
    labels.forEach((row,i)=>{const x=i%8*128,y=Math.floor(i/8)*40,width=Math.max(32,Math.min(126,ctx.measureText(row.text).width+8)),p=this.globe.getCoords(row.lat,row.lng,.026);
      ctx.strokeStyle='#06101be0';ctx.lineWidth=4;ctx.strokeText(row.text,x+64,y+20,120);ctx.fillStyle=row.cluster?'#fff':'#c5d8e8';ctx.fillText(row.text,x+64,y+20,120);
      positions.push(p.x,p.y,p.z);rects.push((x+64-width/2)/1024,1-(y+36)/canvas.height,width/1024,32/canvas.height);sizes.push(width/2);aspects.push(width/32);
    });
    const geometry=new THREE.BufferGeometry();for(const [key,values,count]of [['position',positions,3],['aRect',rects,4],['aSize',sizes,1],['aAspect',aspects,1]])geometry.setAttribute(key,new THREE.Float32BufferAttribute(values,count));
    const atlas=new THREE.CanvasTexture(canvas);atlas.colorSpace=THREE.SRGBColorSpace;
    const material=new THREE.ShaderMaterial({transparent:true,depthWrite:false,uniforms:{atlas:{value:atlas},pixelRatio:{value:this.globe.renderer().getPixelRatio()}},
      vertexShader:`attribute vec4 aRect;attribute float aSize;attribute float aAspect;uniform float pixelRatio;varying vec4 vRect;varying float vAspect;void main(){vRect=aRect;vAspect=aAspect;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);gl_PointSize=aSize*pixelRatio;}`,
      fragmentShader:`uniform sampler2D atlas;varying vec4 vRect;varying float vAspect;void main(){vec2 p=vec2(gl_PointCoord.x,1.0-gl_PointCoord.y);p.y=(p.y-.5)*vAspect+.5;if(p.y<0.0||p.y>1.0)discard;vec4 c=texture2D(atlas,vRect.xy+p*vRect.zw);if(c.a<.05)discard;gl_FragColor=c;}`});
    const mesh=new THREE.Points(geometry,material);mesh.renderOrder=2;this.globe.scene().add(mesh);this.meshes.push(mesh);
  }
  pick(event,select){if(!this.active)return;const box=this.canvas.getBoundingClientRect();
    let row=null,best=Infinity;const camera=this.globe.camera(),point=new THREE.Vector3();
    for(const r of this.meshes[0]?.userData.rows||[]){const p=this.globe.getCoords(r.lat,r.lng,.014);point.set(p.x,p.y,p.z);if(point.dot(camera.position.clone().sub(point))<=0)continue;point.project(camera);
      const x=(point.x+1)*box.width/2,y=(1-point.y)*box.height/2,distance=Math.hypot(event.clientX-box.left-x,event.clientY-box.top-y);
      if(distance<(r.cluster?15:11)&&distance<best){row=r;best=distance;}
    }this.canvas.style.cursor=row?'pointer':'grab';
    if(select&&row)this.callbacks.onPick?.(row);else if(!select)this.callbacks.onHover?.(row,event.clientX-box.left,event.clientY-box.top);
  }
  dispose(){this.setActive(false);clearTimeout(this.settled);cancelAnimationFrame(this.hoverFrame);this.canvas.removeEventListener('pointerdown',this.down);this.canvas.removeEventListener('pointermove',this.move);this.canvas.removeEventListener('click',this.click);this.canvas.removeEventListener('wheel',this.wheel);this.canvas.removeEventListener('webglcontextlost',this.callbacks.onContextLost);
    for(const mesh of [...this.meshes,this.borders,this.stars]){this.globe.scene().remove(mesh);mesh.geometry.dispose();mesh.material.map?.dispose();mesh.material.uniforms?.atlas?.value.dispose();mesh.material.dispose()}
    this.globe._destructor();this.host.replaceChildren();
  }
}
