<script setup lang="ts">
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue';
import { useTeachingStore } from '../stores/teaching.js';
import TeachingPrimitive from './TeachingPrimitive.vue';
import type { TeachingPose } from '../teaching/domain/scene-types.js';
const props = defineProps<{ visible: boolean }>();
const emit = defineEmits<{ inspect: [] }>();
const store = useTeachingStore(), host = ref<HTMLElement>();
const width = ref(1), height = ref(1), zoom = ref(1), offset = ref({x:0,y:0}), hovered = ref<string | null>(null);
const horizontalBar=ref(false),verticalBar=ref(false);
const viewWidth=computed(()=>width.value-(verticalBar.value?12:0)),viewHeight=computed(()=>height.value-(horizontalBar.value?12:0));
let observer: ResizeObserver | undefined, userScaled = false, fitted = false;
let gesture: { pointer: number; x: number; y: number; offset: { x:number; y:number }; component?: string; pose?: TeachingPose; axis?: 'x'|'y' } | undefined;
const data = computed(() => store.canvas2d);
const items = computed(() => data.value?.components.filter(item => store.components.some(c => c.component_id === item.component_id)) ?? []);
function fitScene(): void {
  if (!props.visible || !data.value || width.value < 2 || height.value < 2) return;
  if (data.value.components.length !== store.components.length || data.value.components.some(item => {
    const c=store.components.find(component=>component.component_id===item.component_id);
    return !c || item.x !== c.pose.x_mm*8 || item.y !== -c.pose.y_mm*8;
  })) { fitted=false; return; }
  const [x,y,w,h] = data.value.fit_bounds;
  for (let i=0;i<4;i++) {
    zoom.value = Math.min((viewWidth.value-4)/w,(viewHeight.value-4)/h);
    updateBars();
  }
  offset.value = {x:Math.round(viewWidth.value/2-(x+w/2)*zoom.value),y:Math.round(viewHeight.value/2-(y+h/2)*zoom.value)};
  userScaled = false; fitted = true;
}
watch([() => props.visible,width,height], () => { if (!userScaled || !fitted) fitScene(); });
watch(data, () => { if (!fitted) fitScene(); });
onMounted(() => {
  observer = new ResizeObserver(() => { width.value=host.value!.clientWidth-2; height.value=host.value!.clientHeight-2; });
  observer.observe(host.value!);
});
onBeforeUnmount(() => { observer?.disconnect(); if (gesture?.component) store.cancelDrag(); });
function transform(id: string): string {
  const c=store.components.find(item=>item.component_id===id)!;
  const original=data.value!.components.find(item=>item.component_id===id)!;
  return `translate(${c.pose.x_mm*8},${-c.pose.y_mm*8}) rotate(${original.rotation})`;
}
function start(event: PointerEvent, id?: string): void {
  if (event.button !== 0 || store.busy) return;
  event.preventDefault(); host.value?.focus({preventScroll:true});
  const c = id ? store.components.find(item=>item.component_id===id) : undefined;
  store.selectComponent(id ?? null);
  if (id) store.beginDrag();
  gesture={pointer:event.pointerId,x:event.clientX,y:event.clientY,offset:{...offset.value},component:id,pose:c?{...c.pose}:undefined};
  host.value!.setPointerCapture(event.pointerId);
}
function move(event: PointerEvent): void {
  if (!gesture || gesture.pointer !== event.pointerId) return;
  const dx=event.clientX-gesture.x,dy=event.clientY-gesture.y;
  if (gesture.axis && data.value) {
    const axis=gesture.axis;
    offset.value={...gesture.offset,[axis]:gesture.offset[axis]-(axis==='x'?dx:dy)*(axis==='x'?data.value.scene_bounds[2]/viewWidth.value:data.value.scene_bounds[3]/viewHeight.value)*zoom.value}; clampOffset();
  }
  else if (gesture.component && gesture.pose) store.updatePose(gesture.component,{...gesture.pose,x_mm:gesture.pose.x_mm+dx/zoom.value/8,y_mm:gesture.pose.y_mm-dy/zoom.value/8});
  else { offset.value={x:gesture.offset.x+dx,y:gesture.offset.y+dy}; userScaled=true; }
}
function end(event: PointerEvent): void {
  if (!gesture || gesture.pointer !== event.pointerId) return;
  if (gesture.component) {
    const c=store.components.find(item=>item.component_id===gesture!.component);
    if (c && event.shiftKey) store.updatePose(c.component_id,{...c.pose,x_mm:Math.round(c.pose.x_mm/2.5)*2.5,y_mm:Math.round(c.pose.y_mm/2.5)*2.5});
    void store.endDrag();
  }
  gesture=undefined; host.value?.releasePointerCapture(event.pointerId);
}
function cancel(): void { if (gesture?.component) store.cancelDrag(); gesture=undefined; }
function wheel(event: WheelEvent): void {
  if (!event.deltaY || !host.value) return;
  const next=Math.max(.02,Math.min(16,zoom.value*(event.deltaY<0?1.15:1/1.15)));
  const rect=host.value.getBoundingClientRect(),x=event.clientX-rect.x-1,y=event.clientY-rect.y-1,ratio=next/zoom.value;
  offset.value={x:Math.round(x-(x-offset.value.x)*ratio),y:Math.round(y-(y-offset.value.y)*ratio)}; zoom.value=next; updateBars(); clampOffset(); userScaled=true;
}
function updateBars(): void {
  if (!data.value) return;
  for (let i=0;i<3;i++) { horizontalBar.value=data.value.scene_bounds[2]*zoom.value>viewWidth.value; verticalBar.value=data.value.scene_bounds[3]*zoom.value>viewHeight.value; }
}
function clampOffset(): void {
  if (!data.value) return;
  const [x,y,w,h]=data.value.scene_bounds;
  offset.value={x:Math.round(w*zoom.value<=viewWidth.value?(viewWidth.value-w*zoom.value)/2-x*zoom.value:Math.max(viewWidth.value-(x+w)*zoom.value,Math.min(-x*zoom.value,offset.value.x))),y:Math.round(h*zoom.value<=viewHeight.value?(viewHeight.value-h*zoom.value)/2-y*zoom.value:Math.max(viewHeight.value-(y+h)*zoom.value,Math.min(-y*zoom.value,offset.value.y)))};
}
function thumb(axis:'x'|'y'): Record<string,string> {
  if (!data.value) return {};
  const view=axis==='x'?viewWidth.value:viewHeight.value,start=data.value.scene_bounds[axis==='x'?0:1]*zoom.value,total=data.value.scene_bounds[axis==='x'?2:3]*zoom.value;
  const size=Math.max(axis==='x'?32:36,view*view/total),position=Math.max(0,Math.min(view-size,(-offset.value[axis]-start)/(total-view)*(view-size)));
  return axis==='x'?{left:`${position}px`,width:`${size}px`}:{top:`${position}px`,height:`${size}px`};
}
function scrollStart(event:PointerEvent,axis:'x'|'y'):void {
  if (event.button!==0 || !data.value) return;
  userScaled=true;
  if (!(event.target as HTMLElement).classList.contains('teaching-scroll-thumb')) {
    const rect=(event.currentTarget as HTMLElement).getBoundingClientRect(),position=(axis==='x'?event.clientX-rect.x:event.clientY-rect.y),style=thumb(axis),start=parseFloat(style[axis==='x'?'left':'top']!);
    offset.value={...offset.value,[axis]:offset.value[axis]+(position<start?1:-1)*(axis==='x'?viewWidth.value:viewHeight.value)};clampOffset();return;
  }
  gesture={pointer:event.pointerId,x:event.clientX,y:event.clientY,offset:{...offset.value},axis};host.value!.setPointerCapture(event.pointerId);
}
function poseAt(x:number,y:number):TeachingPose|null {
  if(!host.value || !fitted)return null;
  const r=host.value.getBoundingClientRect();
  return {x_mm:(Math.round(x-r.x)-1-offset.value.x)/zoom.value/8,y_mm:-(Math.round(y-r.y)-1-offset.value.y)/zoom.value/8,z_mm:25,yaw_rad:0,pitch_rad:0,roll_rad:0};
}
defineExpose({ fitScene, poseAt });
</script>
<template>
  <div ref="host" class="teaching-bench-2d" aria-label="二维光学实验台" tabindex="0" @pointerdown="start($event)" @pointermove="move" @pointerup="end" @pointercancel="cancel" @keydown.esc="cancel" @wheel.prevent="wheel">
    <svg v-if="data" :width="viewWidth" :height="viewHeight" :viewBox="`0 0 ${viewWidth} ${viewHeight}`" role="img" aria-label="二维光学台面与器件">
      <g :transform="`translate(${offset.x},${offset.y}) scale(${zoom})`">
        <rect :x="data.board[0]" :y="data.board[1]" :width="data.board[2]" :height="data.board[3]" fill="#D7DCE2" stroke="#98A2B3" stroke-width="1.2" />
        <circle v-for="(hole,index) in data.holes" :key="index" :cx="hole[0]" :cy="hole[1]" r="2.2" fill="#7B8794" />
        <path :d="`M0 0 H${data.board[2]}`" fill="none" stroke="#64748b" stroke-width="1" stroke-dasharray="4 2" />
        <path v-if="store.baseline_enabled" :d="`M${store.baseline_x_mm*8} ${data.board[1]} v${data.board[3]}`" fill="none" stroke="#2563eb" stroke-width="1.4" stroke-dasharray="5.6 2.8" />
        <text x="8" :y="data.board[1]+data.board[3]+16" fill="#475569" font-family="Microsoft YaHei UI" font-size="10.6667">俯视 · 沿导轨（mm）  台面 450 × 300</text>
        <path v-for="(ray,index) in store.preview?.rays.slice(0,80) ?? []" :key="`ray-${index}`" :d="`M${ray.start_teaching_mm[0]*8} ${-ray.start_teaching_mm[1]*8} L${ray.end_teaching_mm[0]*8} ${-ray.end_teaching_mm[1]*8}`" fill="none" :stroke="`rgba(239,68,68,${Math.max(50,Math.min(230,Math.trunc(70+150*ray.power_fraction)))/255})`" :stroke-width="ray.power_fraction>.9?4.2:2.6" stroke-linecap="round" />
        <g v-for="item in items" :key="item.component_id" :transform="transform(item.component_id)" role="button" :aria-label="store.components.find(c=>c.component_id===item.component_id)?.label" tabindex="0" class="teaching-2d-component" @pointerdown.stop="start($event,item.component_id)" @pointerenter="hovered=item.component_id" @pointerleave="hovered=null" @keydown.enter.stop="store.selectComponent(item.component_id)" @dblclick.stop="store.selectComponent(item.component_id);emit('inspect')">
          <TeachingPrimitive v-for="(primitive,index) in (store.selected_component_id===item.component_id?item.selected_primitives:hovered===item.component_id?item.hover_primitives:item.primitives)" :key="index" :primitive="primitive" />
        </g>
      </g>
    </svg>
    <div v-if="horizontalBar" class="teaching-scrollbar horizontal" :style="{width:`${viewWidth}px`}" @pointerdown.stop="scrollStart($event,'x')"><span class="teaching-scroll-thumb" :style="thumb('x')"></span></div>
    <div v-if="verticalBar" class="teaching-scrollbar vertical" :style="{height:`${viewHeight}px`}" @pointerdown.stop="scrollStart($event,'y')"><span class="teaching-scroll-thumb" :style="thumb('y')"></span></div>
    <div v-if="horizontalBar && verticalBar" class="teaching-scroll-corner"></div>
    <span v-else class="canvas-loading">正在加载画布…</span>
  </div>
</template>
