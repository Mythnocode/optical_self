<script setup lang="ts">
import { computed, ref, nextTick, watch, onMounted, onBeforeUnmount } from 'vue';
import { useTeachingStore } from '../stores/teaching.js';
import { COMPONENT_CATALOG, type ComponentKind } from '../teaching/domain/component-catalog.js';
import manifest from '../teaching/domain/equipment.json';
import TeachingNumber from './TeachingNumber.vue';

const emit = defineEmits<{ close: []; status: [message: string]; drop: [kind: ComponentKind, x: number, y: number] }>();
const store = useTeachingStore();
const search = ref(''), presetKind = ref(''), presetIndex = ref(0), customWavelength = ref(780);
const lastAddedId = ref<string | null>(null);
const scroll = ref<HTMLElement>(), scrollHeight = ref(0), contentHeight = ref(0), scrollTop = ref(0);
let resizeObserver: ResizeObserver | undefined;
let thumbDrag: {pointer:number; y:number; top:number} | undefined;
let equipmentDrag: {pointer:number; x:number; y:number; kind:ComponentKind; moved:boolean} | undefined;
let ignoreClick=false;
function startEquipment(event:PointerEvent,kind:ComponentKind):void {
  if(event.button!==0 || store.busy)return;
  ignoreClick=false;
  equipmentDrag={pointer:event.pointerId,x:event.clientX,y:event.clientY,kind,moved:false};
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
}
function moveEquipment(event:PointerEvent):void {
  if(equipmentDrag?.pointer===event.pointerId && Math.abs(event.clientX-equipmentDrag.x)+Math.abs(event.clientY-equipmentDrag.y)>=8) equipmentDrag.moved=true;
}
function endEquipment(event:PointerEvent):void {
  if(equipmentDrag?.pointer!==event.pointerId)return;
  if(equipmentDrag.moved) {ignoreClick=true; emit('drop',equipmentDrag.kind,event.clientX,event.clientY);}
  equipmentDrag=undefined;(event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId);
}
function cancelEquipment():void { equipmentDrag=undefined;ignoreClick=false; }
function recordDroppedId(id:string):void {lastAddedId.value=id;}
function resetAddedId():void {lastAddedId.value=null;}
defineExpose({recordDroppedId,resetAddedId});
const thumbHeight = computed(() => Math.max(32, Math.floor(scrollHeight.value * scrollHeight.value / contentHeight.value)));
const thumbTop = computed(() => scrollTop.value / (contentHeight.value - scrollHeight.value) * (scrollHeight.value - thumbHeight.value));
function measureScroll(): void { if (scroll.value) { scrollHeight.value=scroll.value.clientHeight; contentHeight.value=scroll.value.scrollHeight; scrollTop.value=scroll.value.scrollTop; } }
watch([search,presetKind],async()=>{await nextTick(); measureScroll();});
onMounted(()=>{resizeObserver=new ResizeObserver(measureScroll); if(scroll.value)resizeObserver.observe(scroll.value); measureScroll();});
onBeforeUnmount(()=>resizeObserver?.disconnect());
function startThumb(event: PointerEvent): void {
  if (event.button !== 0 || !scroll.value) return;
  const track=event.currentTarget as HTMLElement;
  if (!(event.target as HTMLElement).classList.contains('teaching-equipment-thumb')) {
    scroll.value.scrollTop += (event.clientY-track.getBoundingClientRect().y < thumbTop.value ? -1 : 1) * scrollHeight.value;
    return;
  }
  thumbDrag={pointer:event.pointerId,y:event.clientY,top:scroll.value.scrollTop};track.setPointerCapture(event.pointerId);
}
function moveThumb(event: PointerEvent): void {
  if (thumbDrag?.pointer===event.pointerId && scroll.value) scroll.value.scrollTop=thumbDrag.top+(event.clientY-thumbDrag.y)*(contentHeight.value-scrollHeight.value)/(scrollHeight.value-thumbHeight.value);
}
function endThumb(event: PointerEvent): void { thumbDrag=undefined; (event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId); }
type Preset = { title: string; values: { label: string; params: Record<string, number> | null }[] };
const presets = manifest.presets as unknown as Record<string, Preset>;
const preset = computed(() => presets[presetKind.value]);
const groups = manifest.groups as { title: string; kinds: ComponentKind[] }[];
function matches(kind: ComponentKind): boolean {
  const needle = search.value.trim().toLowerCase();
  return !needle || COMPONENT_CATALOG[kind].label.toLowerCase().includes(needle) || kind.includes(needle);
}
async function add(kind: ComponentKind, event: MouseEvent): Promise<void> {
  if(ignoreClick && event.detail>0){ignoreClick=false;return;}
  ignoreClick=false;
  if (!await store.addComponent(kind)) return;
  lastAddedId.value = store.selected_component_id;
  presetKind.value = kind; presetIndex.value = 0; customWavelength.value = 780;
  emit('status', `已添加 ${COMPONENT_CATALOG[kind].label}`);
}
async function applyPreset(): Promise<void> {
  const target = store.components.find(item => item.component_id === (lastAddedId.value ?? store.selected_component_id));
  const choice = preset.value?.values[presetIndex.value];
  if (!target || !choice) return;
  const params = choice.params ?? (presetKind.value === 'laser' ? { wavelength_nm: customWavelength.value } : null);
  if (params && await store.updateParams(target.component_id, params)) emit('status', '已应用工程规格');
}
</script>

<template>
  <aside class="teaching-equipment-window" :class="{ 'has-preset': !!preset, 'laser-preset': presetKind === 'laser' }" aria-label="器材库" @keydown.esc="emit('close')">
    <div class="teaching-equipment-title"><span>器材库</span><button aria-label="关闭器材库" type="button" @click="emit('close')">×</button></div>
    <input v-model="search" class="teaching-equipment-search" aria-label="搜索器材" placeholder="搜索器材…" />
    <p class="teaching-equipment-hint">拖到台上放置，或点击添加</p>
    <template v-if="preset">
      <strong class="teaching-equipment-preset-title">{{ preset.title }}</strong>
      <select v-model="presetIndex" :aria-label="preset.title" :disabled="store.busy"><option v-for="(choice, index) in preset.values" :key="choice.label" :value="index">{{ choice.label }}</option></select>
      <TeachingNumber v-if="presetKind === 'laser'" v-model="customWavelength" label="自定义波长" :min="0.01" :max="30000" :decimals="3" suffix=" nm" :disabled="store.busy" />
      <button class="teaching-equipment-apply" type="button" :disabled="store.busy" @click="applyPreset">应用当前规格</button>
    </template>
    <div class="teaching-equipment-scroll-wrap"><div ref="scroll" class="teaching-equipment-scroll" @scroll="measureScroll"><div class="teaching-equipment-catalog">
      <template v-for="group in groups" :key="group.title">
        <strong class="teaching-equipment-group">{{ group.title }}</strong>
        <template v-for="kind in group.kinds" :key="kind"><button v-if="matches(kind)" :data-kind="kind" class="teaching-equipment-item" type="button" :disabled="store.busy" @pointerdown="startEquipment($event,kind)" @pointermove="moveEquipment" @pointerup="endEquipment" @pointercancel="cancelEquipment" @click="add(kind,$event)">{{ COMPONENT_CATALOG[kind].label }}</button></template>
      </template>
    </div></div><div v-if="contentHeight > scrollHeight" class="teaching-equipment-track" @pointerdown.prevent="startThumb" @pointermove="moveThumb" @pointerup="endThumb" @pointercancel="endThumb"><span class="teaching-equipment-thumb" :style="{top:`${thumbTop}px`,height:`${thumbHeight}px`}"></span></div></div>
  </aside>
</template>
