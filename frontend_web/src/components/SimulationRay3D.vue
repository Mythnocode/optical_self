<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Line2 } from 'three/addons/lines/Line2.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import type { Scene3DPrimitive, SimulationPlot } from '../domain/simulation-results.js';

const props = defineProps<{ plot: SimulationPlot }>();
const host = ref<HTMLDivElement>();
const labels = ref<HTMLCanvasElement>();
const tooltip = ref<{text:string;x:number;y:number} | null>(null);
const emit = defineEmits<{ surfaceSelected: [index:number]; surfaceActivated: [index:number] }>();
const scene = new THREE.Scene();
// Matplotlib's transData maps [-.095,.09] into a square axes viewport.
const camera = new THREE.OrthographicCamera(-.95, .9, .9, -.95, .01, 30);
let renderer: THREE.WebGLRenderer | undefined;
let controls: OrbitControls | undefined;
let observer: ResizeObserver | undefined;
let size = 1;
let opticalZoom = 1;
let dragging = false;
let hoverTimer: ReturnType<typeof setTimeout> | undefined;
let hoverCandidate: ArtistGroup | undefined;
let pointerOrigin: [number,number] | undefined;
let groups: ArtistGroup[] = [];
const lineMaterials: LineMaterial[] = [];
const spriteSizes = new Map<THREE.Sprite, [number, number]>();
interface ArtistGroup {
  data: Scene3DPrimitive;
  objects: THREE.Object3D[];
  points: THREE.Vector3[];
  faces?: THREE.Vector3[][];
  mesh?: THREE.Mesh;
}
function color(rgba: number[]): THREE.Color {
  return new THREE.Color().setRGB(rgba[0], rgba[1], rgba[2], THREE.SRGBColorSpace);
}
function point(row: number[]): THREE.Vector3 {
  const model = props.plot.scene_artists!;
  return new THREE.Vector3(...row.map((value, i) => (value-model.limits[i][0])*model.box_aspect[i]/(model.limits[i][1]-model.limits[i][0])) as [number, number, number]);
}
function depth(p: THREE.Vector3): number {
  return -p.clone().applyMatrix4(camera.matrixWorldInverse).z;
}
function createLine(path: THREE.Vector3[], data: Scene3DPrimitive, rgba = data.color): THREE.Object3D {
  const geometry = new LineGeometry();
  geometry.setPositions(path.flatMap(p => p.toArray()));
  const material = new LineMaterial({color: color(rgba), linewidth: (data.width ?? 1)*100/72,
    opacity: rgba[3], transparent: true, depthTest: false, depthWrite: false,
    resolution: new THREE.Vector2(size, size)});
  lineMaterials.push(material);
  material.dashed = Boolean(data.dash?.length);
  material.userData.dash = data.dash;
  const line = new Line2(geometry, material);
  // Solid optical curves use screen-space widths, including subpixel lines.
  // Dashed paths are split in projected screen coordinates during ordering.
  line.computeLineDistances();
  return line;
}
function createText(data: Scene3DPrimitive): THREE.Sprite {
  const canvas = document.createElement('canvas'), ctx = canvas.getContext('2d')!;
  const font = `${data.weight === 'semibold' || data.weight === 'bold' ? 600 : 400} ${(data.size ?? 9)*100/72}px "Times New Roman", "Microsoft YaHei", serif`;
  ctx.font = font;
  const measured = ctx.measureText(data.text ?? '');
  const ascent = measured.actualBoundingBoxAscent || (data.size ?? 9)*100/72;
  const descent = measured.actualBoundingBoxDescent || 2;
  const w = Math.ceil(measured.width)+4, h = Math.ceil(ascent+descent)+4;
  const ratio = window.devicePixelRatio;
  canvas.width = Math.ceil(w*ratio); canvas.height = Math.ceil(h*ratio);
  ctx.scale(ratio, ratio); ctx.font = font; ctx.fillStyle = `rgba(${data.color.slice(0,3).map(v=>Math.round(v*255)).join(',')},${data.color[3]})`;
  ctx.fillText(data.text ?? '', 2, 2+ascent);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map: texture, depthTest:false, depthWrite:false, transparent:true}));
  sprite.position.copy(point(data.point!));
  const horizontal = data.horizontal === 'right' ? (w-2)/w : data.horizontal === 'center' ? .5 : 2/w;
  const vertical = data.vertical === 'bottom' ? 2/h : data.vertical === 'top' ? (h-2)/h : data.vertical === 'center' ? .5 : (descent+2)/h;
  sprite.center.set(horizontal, vertical);
  spriteSizes.set(sprite, [w,h]);
  return sprite;
}
function disposeScene() {
  clearHover();
  scene.traverse(object => {
    const drawable = object as THREE.Mesh | THREE.Sprite;
    if ('geometry' in drawable) drawable.geometry?.dispose();
    if ('material' in drawable) {
      const materials = Array.isArray(drawable.material) ? drawable.material : [drawable.material];
      for (const material of materials) { if ('map' in material) (material.map as THREE.Texture | null)?.dispose(); material.dispose(); }
    }
  });
  scene.clear(); groups = []; lineMaterials.length = 0; spriteSizes.clear();
}
function rebuild() {
  if (!renderer || !props.plot.scene_artists) return;
  disposeScene(); opticalZoom = 1; updateZoom();
  const model = props.plot.scene_artists;
  const target = new THREE.Vector3(...model.box_aspect.map(v=>v*.5) as [number,number,number]);
  const elevation = model.elevation*Math.PI/180, azimuth = model.azimuth*Math.PI/180;
  camera.up.set(0,0,1);
  camera.position.copy(target).add(new THREE.Vector3(Math.cos(elevation)*Math.cos(azimuth), Math.cos(elevation)*Math.sin(azimuth), Math.sin(elevation)).multiplyScalar(10));
  camera.lookAt(target); camera.updateMatrixWorld(); camera.updateProjectionMatrix();
  controls?.target.copy(target); controls?.update();
  for (const data of model.primitives) {
    if (data.kind === 'text_2d') continue;
    const group: ArtistGroup = {data, objects: [], points: []};
    if (data.kind === 'line' || data.kind === 'line_collection') {
      for (const path of data.paths ?? []) {
        const vertices = path.map(point); group.points.push(...vertices);
        const line = createLine(vertices, data); group.objects.push(line);
      }
    } else if (data.kind === 'polygons') {
      group.faces = (data.faces ?? []).filter(face=>face.length>=3).map(face=>face.map(point));
      group.points = group.faces.flat();
      const geometry = new THREE.BufferGeometry();
      const vertices: number[] = [];
      for (const face of group.faces) for(let i=1;i<face.length-1;i++) vertices.push(...face[0].toArray(), ...face[i].toArray(), ...face[i+1].toArray());
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices,3));
      const material = new THREE.MeshBasicMaterial({color:color(data.color),opacity:data.color[3],transparent:true,
        side:THREE.DoubleSide, depthTest:false, depthWrite:false});
      material.forceSinglePass = true;
      group.mesh = new THREE.Mesh(geometry,material); group.objects.push(group.mesh);
      if ((data.edge_color?.[3] ?? 0)>0) for(const face of group.faces) group.objects.push(createLine([...face,face[0]],data,data.edge_color));
    } else if (data.kind === 'text') group.objects.push(createText(data));
    for(const object of group.objects) scene.add(object);
    groups.push(group);
  }
  resize();
}
function orderArtists() {
  camera.updateMatrixWorld();
  const collections = groups.filter(group=>['polygons','line_collection'].includes(group.data.kind));
  collections.sort((a,b)=>Math.min(...b.points.map(depth))-Math.min(...a.points.map(depth)));
  const zOrders = new Map(collections.map((group,i)=>[group,2.5+i]));
  const ordered = [...groups].sort((a,b)=>(zOrders.get(a)??a.data.z_order)-(zOrders.get(b)??b.data.z_order)||a.data.order-b.data.order);
  for(const [index,group] of ordered.entries()) {
    group.objects.forEach((object,i)=>object.renderOrder=index*10000+i);
    if(group.faces && group.mesh) {
      const faces = [...group.faces].sort((a,b)=>b.reduce((sum,p)=>sum+depth(p),0)/b.length-a.reduce((sum,p)=>sum+depth(p),0)/a.length);
      const vertices: number[]=[];
      for(const face of faces) for(let i=1;i<face.length-1;i++) vertices.push(...face[0].toArray(),...face[i].toArray(),...face[i+1].toArray());
      const attribute = group.mesh.geometry.getAttribute('position') as THREE.BufferAttribute;
      (attribute.array as Float32Array).set(vertices); attribute.needsUpdate=true;
    }
  }
}
function drawLabels() {
  const canvas=labels.value,ctx=canvas?.getContext('2d'); if(!canvas||!ctx)return;
  const ratio=window.devicePixelRatio; canvas.width=Math.round(size*ratio); canvas.height=Math.round(size*ratio); ctx.scale(ratio,ratio);
  canvas.style.width = `${size}px`; canvas.style.height = `${size}px`;
  const texts=[...(props.plot.scene_artists?.primitives.filter(p=>p.kind==='text_2d')??[]),
    {point:[.018,.972],text:props.plot.title ?? '',size:13,weight:'semibold',color:[16/255,24/255,40/255,1],horizontal:'left'},
    {point:[.982,.025],text:props.plot.scale_label ?? '',size:8.5,weight:'normal',color:[102/255,112/255,133/255,1],horizontal:'right'}];
  for(const text of texts) {
    ctx.font=`${text.weight==='semibold'?600:400} ${text.size!*100/72}px "Times New Roman", "Microsoft YaHei", serif`;
    ctx.fillStyle=`rgba(${text.color.slice(0,3).map(v=>Math.round(v*255)).join(',')},${text.color[3]})`;
    ctx.textAlign=text.horizontal==='right'?'right':text.horizontal==='center'?'center':'left';
    ctx.fillText(text.text ?? '',text.point![0]*size,(1-text.point![1])*size);
  }
}
function render() {
  if(!renderer)return;
  const pixelsPerUnit=size*camera.zoom/1.85;
  for(const material of lineMaterials) {
    const dash = material.userData.dash as number[] | undefined;
    if(dash?.length) { material.dashSize=dash[0]*100/72/pixelsPerUnit; material.gapSize=dash[1]*100/72/pixelsPerUnit; }
  }
  for(const [sprite,[w,h]] of spriteSizes) sprite.scale.set(w/pixelsPerUnit,h/pixelsPerUnit,1);
  orderArtists(); renderer.render(scene,camera); drawLabels();
}
function resize() {
  if(!renderer||!host.value)return;
  size=Math.max(1,Math.min(host.value.clientWidth,host.value.clientHeight));
  renderer.setSize(size,size); lineMaterials.forEach(material=>material.resolution.set(size,size)); render();
}
function wheel(event: WheelEvent) {
  if(!event.ctrlKey)return;
  event.preventDefault(); opticalZoom=Math.max(.66,Math.min(1.22,opticalZoom*(event.deltaY<0?1.08:.93))); updateZoom(); render();
}
function updateZoom() {
  // Keep Matplotlib's asymmetric transData centre fixed as its box grows.
  camera.zoom=opticalZoom;
  camera.left=-.925-.025/opticalZoom; camera.right=.925-.025/opticalZoom;
  camera.top=.925-.025/opticalZoom; camera.bottom=-.925-.025/opticalZoom;
  camera.updateProjectionMatrix();
}
function interactive(start: boolean) {
  dragging=start;if(start)clearHover();
  for(const group of groups) for(const object of group.objects) {
    if(group.data.interactive_hide) object.visible=!start;
    if(group.data.kind==='line_collection' && object instanceof Line2) object.material.opacity=start?.22:group.data.color[3];
  }
  render();
}
function clearHover() { if(hoverTimer)clearTimeout(hoverTimer);hoverTimer=undefined;tooltip.value=null;hoverCandidate=undefined; }
function surfaceAt(event: PointerEvent | MouseEvent): ArtistGroup | undefined {
  const rect=renderer!.domElement.getBoundingClientRect(),x=event.clientX-rect.x,y=event.clientY-rect.y;
  let found: ArtistGroup | undefined,closest=7*100/72;
  for(const group of groups) {
    if(!group.data.surface_id)continue;
    const points=group.points.map(p=>p.clone().project(camera)).map(p=>[(p.x+1)*size/2,(1-p.y)*size/2]);
    for(let i=1;i<points.length;i++) {
      const [ax,ay]=points[i-1],[bx,by]=points[i],dx=bx-ax,dy=by-ay;
      const t=Math.max(0,Math.min(1,((x-ax)*dx+(y-ay)*dy)/(dx*dx+dy*dy || 1)));
      const distance=Math.hypot(x-ax-t*dx,y-ay-t*dy);
      if(distance<closest){closest=distance;found=group;}
    }
  }
  return found;
}
function pointerMove(event: MouseEvent) {
  if(dragging || !renderer || !host.value)return;
  const candidate=surfaceAt(event);if(candidate===hoverCandidate)return;clearHover();hoverCandidate=candidate;
  if(!candidate?.data.hover_text)return;
  const bounds=host.value.getBoundingClientRect(),x=Math.min(event.clientX-bounds.x+14,Math.max(0,bounds.width-315)),y=Math.min(event.clientY-bounds.y+16,Math.max(0,bounds.height-105));
  hoverTimer=setTimeout(()=>{tooltip.value={text:candidate.data.hover_text!,x,y};},650);
}
function pointerDown(event: PointerEvent) { pointerOrigin=[event.clientX,event.clientY]; }
function selectSurface(event: MouseEvent,activate=false) {
  if(!renderer || !pointerOrigin || Math.hypot(event.clientX-pointerOrigin[0],event.clientY-pointerOrigin[1])>3)return;
  pointerMove(event);
  const surface=surfaceAt(event);if(!surface?.data.surface_id)return;
  const index=Number(surface.data.surface_id.split(':')[1]);
  if(activate)emit('surfaceActivated',index);else emit('surfaceSelected',index);
}
async function exportPng() {
  if(!renderer||!host.value)return; render();
  const ratio=window.devicePixelRatio,canvas=document.createElement('canvas');
  canvas.width=Math.round(host.value.clientWidth*ratio);canvas.height=Math.round(host.value.clientHeight*ratio);
  const ctx=canvas.getContext('2d')!;ctx.fillStyle='#F8FAFC';ctx.fillRect(0,0,canvas.width,canvas.height);
  const left=(canvas.width-renderer.domElement.width)/2,top=(canvas.height-renderer.domElement.height)/2;
  ctx.drawImage(renderer.domElement,left,top); if(labels.value)ctx.drawImage(labels.value,left,top);
  const dataUrl=canvas.toDataURL('image/png');
  if(window.opticalDesktop)await window.opticalDesktop.savePngFile({suggestedName:'analysis_result.png',dataUrl});
  else {const a=document.createElement('a');a.href=dataUrl;a.download='analysis_result.png';a.click();}
}
defineExpose({exportPng});
onMounted(()=>{
  if(!host.value)return;
  renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});
  renderer.setPixelRatio(window.devicePixelRatio);renderer.setClearColor('#F8FAFC');renderer.outputColorSpace=THREE.SRGBColorSpace;
  renderer.domElement.className='simulation-ray-3d-renderer';host.value.append(renderer.domElement);
  controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=false;controls.enableZoom=false;
  controls.addEventListener('start',()=>interactive(true));controls.addEventListener('end',()=>interactive(false));
  controls.addEventListener('change',render);renderer.domElement.addEventListener('wheel',wheel,{passive:false});
  observer=new ResizeObserver(resize);observer.observe(host.value);rebuild();
});
watch(()=>props.plot,rebuild);
onBeforeUnmount(()=>{observer?.disconnect();controls?.dispose();renderer?.domElement.removeEventListener('wheel',wheel);disposeScene();renderer?.dispose();renderer?.forceContextLoss();renderer=undefined;});
</script>
<template><div ref="host" class="simulation-ray-3d" role="img" aria-label="三维光路。拖动旋转，按住 Ctrl 滚轮缩放。" @pointermove="pointerMove" @pointerup="pointerMove" @pointerleave="clearHover" @pointerdown="pointerDown" @click="selectSurface($event)" @dblclick="selectSurface($event,true)"><canvas ref="labels" class="simulation-ray-3d-labels" /><div v-if="tooltip" class="simulation-surface-tooltip" role="tooltip" :style="{left:`${tooltip.x}px`,top:`${tooltip.y}px`}">{{ tooltip.text }}</div></div></template>
