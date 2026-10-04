<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue';
import { heatmapPixels, type SimulationPlot } from '../domain/simulation-results.js';
const props = defineProps<{ plot: SimulationPlot; smoothHeatmap?: boolean }>();
const canvas = ref<HTMLCanvasElement>();
let observer: ResizeObserver | undefined;
let imageCanvas: HTMLCanvasElement | undefined;
type Bounds = [number, number];
let view: { x: Bounds; y: Bounds } | undefined;
let axes: { box: { x: number; y: number; w: number; h: number }; x: Bounds; y: Bounds } | undefined;
let pan: { pointer: number; x: number; y: number; ranges: { x: Bounds; y: Bounds } } | undefined;
const emit = defineEmits<{ surfaceSelected: [index: number]; surfaceActivated: [index: number] }>();
const colors: Record<string,[string,number,number]> = { chief:['#B42318',1.45,.92], marginal:['#D92D20',1,.76], regular:['#F04438',.85,.58], failed:['#7A271A',1.05,.95] };
const font = '"Microsoft YaHei UI", sans-serif', serif = '"Times New Roman", "Microsoft YaHei", serif';
function draw() {
  const target=canvas.value; if(!target) return;
  const {width,height}=target.getBoundingClientRect(); if(!width || !height) return;
  const dpr=window.devicePixelRatio || 1; target.width=Math.round(width*dpr); target.height=Math.round(height*dpr);
  const ctx=target.getContext('2d')!; ctx.scale(dpr,dpr);
  ctx.fillStyle=['heatmap','beam_match','heatmap_pair'].includes(props.plot.kind) ? 'white' : '#F8FAFC'; ctx.fillRect(0,0,width,height);
  if(props.plot.kind==='heatmap' || props.plot.kind==='beam_match') drawHeatmap(ctx,width,height);
  else if(props.plot.kind==='scatter' || props.plot.kind==='raytrace_section' || props.plot.kind==='raytrace') drawAxes(ctx,width,height);
}
function line(ctx:CanvasRenderingContext2D, points:number[][], color:string, width:number, alpha=1) {
  if(!points.length) return; ctx.beginPath(); points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y)); ctx.strokeStyle=color; ctx.lineWidth=width; ctx.globalAlpha=alpha; ctx.stroke(); ctx.globalAlpha=1;
}
function text(ctx:CanvasRenderingContext2D, value:string, x:number,y:number,size=16, family=font,bold=false) {
  ctx.fillStyle='#111827'; ctx.font=`${bold?'700 ':''}${size}px ${family}`; ctx.textAlign='center'; ctx.textBaseline='middle'; ctx.fillText(value,x,y);
}
function fitted(x:number,y:number,w:number,h:number,ratio:number) { const fw=Math.min(Math.floor(w),Math.round(h*ratio)), fh=Math.min(Math.floor(h),Math.round(w/ratio)); return {x:x+Math.floor((w-fw)/2),y:y+Math.floor((h-fh)/2),w:fw,h:fh}; }
function drawHeatmap(ctx:CanvasRenderingContext2D,w:number,h:number) {
  const p=props.plot, beam=p.kind==='beam_match';
  if(!imageCanvas) { const image=heatmapPixels(p); imageCanvas=document.createElement('canvas'); imageCanvas.width=image.width; imageCanvas.height=image.height; imageCanvas.getContext('2d')!.putImageData(image,0,0); }
  const spanX=Math.abs((p.x?.at(-1)??imageCanvas.width)-(p.x?.[0]??0)),spanY=Math.abs((p.y?.at(-1)??imageCanvas.height)-(p.y?.[0]??0));
  const box=fitted(beam?70:52,beam?64:14,w-(beam?94:76),h-(beam?106:56), spanX/spanY || 1);
  ctx.imageSmoothingEnabled=!!props.smoothHeatmap; ctx.drawImage(imageCanvas,box.x,box.y,box.w,box.h); ctx.strokeStyle='#111827';ctx.lineWidth=1;ctx.strokeRect(box.x+.5,box.y+.5,box.w-1,box.h-1);
  if(beam) {
    for(const path of p.contour_paths??[])line(ctx,path.map(([x,y])=>[box.x+x*box.w,box.y+box.h-1-y*box.h]),'#ef4444',1.5);
    Object.values(p.x_profiles??{}).forEach((values,j)=>{const max=Math.max(1e-20,...values.map(Math.abs)); line(ctx,values.map((v,i)=>[box.x+i/Math.max(1,values.length-1)*box.w,51-v/max*44]),j?'#ef4444':'#2563eb',1.35);});
    Object.values(p.y_profiles??{}).forEach((values,j)=>{const max=Math.max(1e-20,...values.map(Math.abs)); line(ctx,values.map((v,i)=>[box.x+box.w+35+v/max*46,box.y+box.h-1-i/Math.max(1,values.length-1)*box.h]),j?'#ef4444':'#2563eb',1.35);});
    const profiles=Object.keys(p.x_profiles??{});if(profiles.length){const lw=Math.min(220,Math.max(150,Math.floor(box.w/3))),lx=box.x+10,ly=box.y+10;ctx.fillStyle='rgba(255,255,255,.8784)';ctx.fillRect(lx,ly,lw,10+18*profiles.length);ctx.strokeStyle='#94a3b8';ctx.strokeRect(lx,ly,lw,10+18*profiles.length); profiles.forEach((profile,i)=>{line(ctx,[[lx+8,ly+9+18*i],[lx+28,ly+9+18*i]],i?'#ef4444':'#2563eb',2);ctx.font=`16.6667px ${font}`;ctx.fillStyle='#111827';ctx.textBaseline='middle';ctx.textAlign='left';ctx.fillText(profile,lx+36,ly+9+18*i);});}
  }
  text(ctx,p.x_label??'x',beam?box.x+box.w/2:52+(w-76)/2,(beam?box.y+box.h-1:h-43)+20,16.6667);
  ctx.save();ctx.translate(box.x-(beam?12:18),beam?box.y+(box.h-1)/2:14+(h-57)/2);ctx.rotate(-Math.PI/2);text(ctx,p.y_label??'y',0,0,16.6667);ctx.restore();
}
function range(values:number[],padding=.05):[number,number] { let lo=Infinity,hi=-Infinity;for(const v of values)if(Number.isFinite(v)){lo=Math.min(lo,v);hi=Math.max(hi,v);}if(!Number.isFinite(lo))return[-.5,.5];if(lo===hi){const span=Math.abs(lo)*.05 || .05;lo-=span;hi+=span;}const pad=(hi-lo)*padding;return[lo-pad,hi+pad]; }
function ticks(r:[number,number],count:number) { const raw=(r[1]-r[0])/count, power=10**Math.floor(Math.log10(raw)),step=([1,2,2.5,5,10].find(v=>v>=raw/power)??10)*power;const start=Math.ceil(r[0]/step)*step;return Array.from({length:Math.max(0,Math.floor((r[1]-start)/step+1e-8)+1)},(_,i)=>Number((start+i*step).toPrecision(12))); }
function drawAxes(ctx:CanvasRenderingContext2D,w:number,h:number) {
  const p=props.plot,ray=p.kind!=='scatter';let xr:[number,number],yr:[number,number];
  let box={x:w*(ray?.155:.15),y:h*.14,w:w*(ray?.805:.815),h:h*(ray?.64:.62)};
  if(ray){const rays=p.rays??[],z=rays.flatMap(r=>r.z),t=rays.flatMap(r=>r.t??r.y??[]);for(const s of p.surfaces??[]){z.push(s.z);t.push(s.t_min,s.t_max);}xr=range(z,0);const pad=.08*Math.max(xr[1]-xr[0],1);xr=[xr[0]-pad,xr[1]+pad];const ymax=Math.max(1e-6,...t.map(Math.abs));yr=[-1.16*ymax,1.16*ymax];}
  else {xr=range(p.x??[]);yr=range(p.y??[]);if((p.airy_radius_um??0)>0){xr=range([...(p.x??[]),-p.airy_radius_um!,p.airy_radius_um!]);yr=range([...(p.y??[]),-p.airy_radius_um!,p.airy_radius_um!]);}if(p.equal_aspect || p.airy_radius_um){const ratio=(xr[1]-xr[0])/(yr[1]-yr[0]);box=fitted(box.x,box.y,box.w,box.h,ratio);}}
  if(view) { xr=view.x; yr=view.y; }
  axes={box,x:xr,y:yr};
  const x=(v:number)=>box.x+(v-xr[0])/(xr[1]-xr[0])*box.w,y=(v:number)=>box.y+box.h-(v-yr[0])/(yr[1]-yr[0])*box.h;
  ctx.fillStyle='white';ctx.fillRect(box.x,box.y,box.w,box.h);
  const xt=ticks(xr,9),yt=ticks(yr,9);
  for(const tick of xt){line(ctx,[[x(tick),box.y],[x(tick),box.y+box.h]],'#CBD5E1',.65*100/72,.48);line(ctx,[[x(tick),box.y+box.h],[x(tick),box.y+box.h+7]],'#111827',1.3*100/72);text(ctx,String(tick),x(tick),box.y+box.h+18,11*100/72,serif);}
  for(const tick of yt){line(ctx,[[box.x,y(tick)],[box.x+box.w,y(tick)]],'#CBD5E1',.65*100/72,.48);line(ctx,[[box.x-7,y(tick)],[box.x,y(tick)]],'#111827',1.3*100/72);text(ctx,String(tick),box.x-19,y(tick),11*100/72,serif);}
  ctx.save();ctx.beginPath();ctx.rect(box.x,box.y,box.w,box.h);ctx.clip();
  if(ray){const m=p.section_artists;if(m){m.surface_segments.forEach((s,i)=>line(ctx,s.map(([a,b])=>[x(a),y(b)]),m.surface_colors[i],m.surface_widths[i]*100/72,.88));m.rim_segments.forEach(s=>line(ctx,s.map(([a,b])=>[x(a),y(b)]),'#075985',.55*100/72,.42));Object.entries(m.grouped_rays).forEach(([role,rays])=>{const [color,width,alpha]=colors[role]??colors.regular;if(role==='failed')ctx.setLineDash([5,3]);rays.forEach(s=>line(ctx,s.map(([a,b])=>[x(a),y(b)]),color,width*100/72,alpha));ctx.setLineDash([]);});}
    line(ctx,[[box.x,y(0)],[box.x+box.w,y(0)]],'#475467',.75*100/72,.55);
    for(const item of p.objects??[]){if(item.visible===false)continue;const cy=item.center_y??item.center_x??0;
      if(item.kind==='fiber'){const radius=Math.max(item.radius??0,.02);ctx.beginPath();ctx.ellipse(x(item.z),y(cy),(x(item.z+Math.max(radius*.35,.02))-x(item.z))/2,Math.abs(y(cy+radius)-y(cy)),0,0,2*Math.PI);ctx.strokeStyle='#06B6D4';ctx.lineWidth=1.4*100/72;ctx.stroke();ctx.setLineDash([5,3]);line(ctx,[[x(item.z),box.y],[x(item.z),box.y+box.h]],'#1D4ED8',1.05*100/72,.8);ctx.setLineDash([]);}
      else if(['detector','image'].includes(item.kind)){const height=Math.max(item.height??0,2*(item.radius??0),.08),width=Math.max((item.width??0)*.04,.02);ctx.globalAlpha=.28;ctx.fillStyle='#12B76A';ctx.fillRect(x(item.z-width/2),y(cy+height/2),x(item.z+width/2)-x(item.z-width/2),y(cy-height/2)-y(cy+height/2));ctx.strokeStyle='#05603A';ctx.lineWidth=1.2*100/72;ctx.strokeRect(x(item.z-width/2),y(cy+height/2),x(item.z+width/2)-x(item.z-width/2),y(cy-height/2)-y(cy+height/2));ctx.globalAlpha=1;}}
  }else{ctx.fillStyle='#155EEF';ctx.strokeStyle='#155EEF';ctx.globalAlpha=.72;ctx.lineWidth=100/72;(p.x??[]).forEach((v,i)=>{if(!Number.isFinite(v)||!Number.isFinite(p.y?.[i]))return;ctx.beginPath();ctx.arc(x(v),y(p.y![i]),2*100/72,0,2*Math.PI);ctx.fill();ctx.stroke();});ctx.globalAlpha=1;if(p.airy_radius_um){ctx.beginPath();ctx.ellipse(x(0),y(0),Math.abs(x(p.airy_radius_um)-x(0)),Math.abs(y(p.airy_radius_um)-y(0)),0,0,2*Math.PI);ctx.setLineDash([5,3]);ctx.stroke();ctx.setLineDash([]);}}
  ctx.restore();ctx.strokeStyle='#111827';ctx.lineWidth=1.35*100/72;ctx.strokeRect(box.x,box.y,box.w,box.h);
  text(ctx,p.title??'',box.x+box.w/2,box.y-19,16*100/72,serif,true);text(ctx,p.x_label??'',box.x+box.w/2,box.y+box.h+39,13*100/72,serif);
  ctx.save();ctx.translate(box.x-42,box.y+box.h/2);ctx.rotate(-Math.PI/2);text(ctx,p.y_label??'',0,0,13*100/72,serif);ctx.restore();
  if(ray && p.section_artists?.scale_visible){ctx.font=`${11*100/72}px ${font}`;ctx.fillStyle='#B45309';ctx.textAlign='right';ctx.textBaseline='bottom';ctx.fillText(p.scale_label??'',box.x+box.w*.99,box.y+box.h*.985);}
}
function local(event: MouseEvent) { const rect=canvas.value!.getBoundingClientRect(); return [event.clientX-rect.x,event.clientY-rect.y]; }
function inside(x: number,y: number) { const box=axes?.box;return box && x>=box.x && x<=box.x+box.w && y>=box.y && y<=box.y+box.h; }
function wheel(event: WheelEvent) {
  if(!event.ctrlKey || ['heatmap','beam_match'].includes(props.plot.kind) || !axes)return;
  const [px,py]=local(event);if(!inside(px,py))return;event.preventDefault();
  const {box,x,y}=axes,dx=x[0]+(px-box.x)/box.w*(x[1]-x[0]),dy=y[1]-(py-box.y)/box.h*(y[1]-y[0]);
  const factor=event.deltaY<0?1/1.18:1.18;
  view={x:[dx-(dx-x[0])*factor,dx+(x[1]-dx)*factor],y:[dy-(dy-y[0])*factor,dy+(y[1]-dy)*factor]};draw();
}
function pointerDown(event: PointerEvent) {
  if(event.button!==1 || !axes || ['heatmap','beam_match'].includes(props.plot.kind))return;
  const [x,y]=local(event);if(!inside(x,y))return;event.preventDefault();
  pan={pointer:event.pointerId,x,y,ranges:{x:[...axes.x],y:[...axes.y]}};canvas.value!.setPointerCapture(event.pointerId);
}
function pointerMove(event: PointerEvent) {
  if(!pan || !axes)return;const [x,y]=local(event),{box}=axes;
  const dx=(x-pan.x)/box.w*(pan.ranges.x[1]-pan.ranges.x[0]),dy=-(y-pan.y)/box.h*(pan.ranges.y[1]-pan.ranges.y[0]);
  view={x:[pan.ranges.x[0]-dx,pan.ranges.x[1]-dx],y:[pan.ranges.y[0]-dy,pan.ranges.y[1]-dy]};draw();
}
function pointerUp(event: PointerEvent) { if(pan?.pointer!==event.pointerId)return;pan=undefined;if(canvas.value?.hasPointerCapture(event.pointerId))canvas.value.releasePointerCapture(event.pointerId); }
function selectSurface(event: MouseEvent, activate=false) {
  if(!['raytrace','raytrace_section'].includes(props.plot.kind) || !axes)return;
  const [px,py]=local(event);if(!inside(px,py))return;const {box,x}=axes,z=x[0]+(px-box.x)/box.w*(x[1]-x[0]);
  const nearest=[...(props.plot.surfaces??[])].sort((a,b)=>Math.abs(a.z-z)-Math.abs(b.z-z))[0];
  if(nearest && Math.abs(nearest.z-z)<=Math.max(.012*(x[1]-x[0]),.05) && nearest.surface_index!==undefined) {
    if(activate)emit('surfaceActivated',nearest.surface_index);else emit('surfaceSelected',nearest.surface_index);
  }
}
async function exportPng() {
  const original=canvas.value;if(!original)return;
  const exportCanvas=document.createElement('canvas'),scale=220/100;
  const {width,height}=original.getBoundingClientRect();
  exportCanvas.width=Math.round(width*scale);exportCanvas.height=Math.round(height*scale);
  const ctx=exportCanvas.getContext('2d')!;ctx.scale(scale,scale);
  ctx.fillStyle=['heatmap','beam_match'].includes(props.plot.kind)?'white':'#F8FAFC';ctx.fillRect(0,0,width,height);
  if(['heatmap','beam_match'].includes(props.plot.kind))drawHeatmap(ctx,width,height);else drawAxes(ctx,width,height);
  const dataUrl=exportCanvas.toDataURL('image/png');
  if(window.opticalDesktop) await window.opticalDesktop.savePngFile({suggestedName:'analysis_result.png',dataUrl});
  else {const a=document.createElement('a');a.href=dataUrl;a.download='analysis_result.png';a.click();}
}
defineExpose({exportPng});
watch(()=>props.plot,()=>{imageCanvas=undefined;view=undefined;axes=undefined;pan=undefined;draw();},{flush:'post'});
onMounted(()=>{observer=new ResizeObserver(draw);if(canvas.value){observer.observe(canvas.value);canvas.value.addEventListener('wheel',wheel,{passive:false});}draw();});
onBeforeUnmount(()=>{observer?.disconnect();canvas.value?.removeEventListener('wheel',wheel);});
</script>
<template><canvas ref="canvas" class="simulation-result-canvas" role="img" :aria-label="plot.title || '仿真结果图'" @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="pointerUp" @auxclick.middle.prevent @click="selectSurface($event)" @dblclick="selectSurface($event,true)" /></template>
