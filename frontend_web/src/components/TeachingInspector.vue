<script setup lang="ts">
import { computed, ref, watch, nextTick, onUpdated } from 'vue';
import { useTeachingStore } from '../stores/teaching.js';
import { COMPONENT_CATALOG } from '../teaching/domain/component-catalog.js';
import labels from '../teaching/domain/parameter-labels.json';
import TeachingNumber from './TeachingNumber.vue';
import laserPresets from '../teaching/domain/laser-presets.json';
import unitWidths from '../teaching/domain/unit-widths.json';
import type { TeachingPose } from '../teaching/domain/scene-types.js';

const emit = defineEmits<{ close: []; publish: [] }>();
const props=defineProps<{visible:boolean}>();
const store = useTeachingStore(), expanded = ref(false);
const selected = computed(() => store.selectedComponent);
const hint=ref<HTMLElement>(),client=ref<HTMLElement>(),windowHeight=ref(467),hintHeight=ref<number>();
const scrollPosition=ref(0),scrollRange=ref(0),scrollViewport=ref(0);
const thumbHeight=computed(()=>Math.max(20,Math.floor(scrollViewport.value*scrollViewport.value/Math.max(1,scrollViewport.value+scrollRange.value))));
const thumbTop=computed(()=>scrollRange.value?Math.floor(scrollPosition.value*(scrollViewport.value-thumbHeight.value)/scrollRange.value):0);
function refreshScroll():void{if(client.value){scrollPosition.value=client.value.scrollTop;scrollRange.value=client.value.scrollHeight-client.value.clientHeight;scrollViewport.value=client.value.clientHeight;}}
onUpdated(refreshScroll);
function scrollbarKey(event:KeyboardEvent):void{
  const distance={ArrowUp:-20,ArrowDown:20,PageUp:-scrollViewport.value,PageDown:scrollViewport.value,Home:-Infinity,End:Infinity}[event.key];
  if(distance===undefined || !client.value)return;
  event.preventDefault();client.value.scrollTop=distance===-Infinity?0:distance===Infinity?scrollRange.value:client.value.scrollTop+distance;
}
function scrollbarPointer(event:PointerEvent):void{
  if(!client.value)return;
  const target=event.currentTarget as HTMLElement,position=event.clientY-target.getBoundingClientRect().top;
  if(!(event.target as HTMLElement).classList.contains('teaching-inspector-scroll-thumb')){client.value.scrollTop+=position<thumbTop.value?-scrollViewport.value:scrollViewport.value;return;}
  event.preventDefault();target.setPointerCapture(event.pointerId);
  const start=event.clientY,initial=client.value.scrollTop;
  const move=(next:PointerEvent)=>{if(client.value)client.value.scrollTop=initial+(next.clientY-start)*scrollRange.value/Math.max(1,scrollViewport.value-thumbHeight.value);};
  const finish=()=>{target.removeEventListener('pointermove',move);target.removeEventListener('pointerup',finish);target.removeEventListener('pointercancel',finish);};
  target.addEventListener('pointermove',move);target.addEventListener('pointerup',finish);target.addEventListener('pointercancel',finish);
}
let fitted=false;
async function toggleDetails():Promise<void>{
  const scrollTop=client.value?.scrollTop??0;
  expanded.value=!expanded.value;
  await nextTick();
  if(client.value)client.value.scrollTop=scrollTop;
}
watch(()=>JSON.stringify([store.sceneSnapshot().scene_id,store.selected_component_id,Object.keys(selected.value?.params??{})]),()=>{
  expanded.value=false;windowHeight.value=selected.value?467:320;fitted=false;
  if(client.value)client.value.scrollTop=0;
});
watch(()=>[props.visible,store.inspectionCurrent,store.selected_component_id,store.setupWarnings.join('\n')],async()=>{
  if(!props.visible || !store.inspectionCurrent)return;
  hintHeight.value=undefined;
  await nextTick();
  if(!props.visible || !store.inspectionCurrent)return;
  hintHeight.value=hint.value?Math.round(hint.value.getBoundingClientRect().height):undefined;
  if(!fitted){windowHeight.value=selected.value?Math.min(720,467+(hintHeight.value?hintHeight.value+7:0)):320;fitted=true;}
},{immediate:true,flush:'post'});
const poses = [
  { key: 'x_mm', label: 'X', unit: 'mm', min: -1000, max: 1000, decimals: 2, caption: 26 },
  { key: 'y_mm', label: 'Y', unit: 'mm', min: -1000, max: 1000, decimals: 2, caption: 26 },
  { key: 'z_mm', label: 'Z', unit: 'mm', min: 0, max: 1000, decimals: 2, caption: 26 },
  { key: 'yaw_rad', label: '绕Z', unit: '°', min: -360, max: 360, decimals: 1, caption: 28 },
  { key: 'pitch_rad', label: '绕Y', unit: '°', min: -89.99, max: 89.99, decimals: 1, caption: 28 },
  { key: 'roll_rad', label: '绕光轴', unit: '°', min: -360, max: 360, decimals: 1, caption: 51 },
] as const;
function poseValue(key: keyof TeachingPose): number { const value = selected.value?.pose[key] ?? 0; return key.endsWith('_rad') ? value * 180 / Math.PI : value; }
function setPose(key: keyof TeachingPose, value: number): void {
  const component = selected.value; if (!component) return;
  const native = key.endsWith('_rad') ? value * Math.PI / 180 : value;
  if (Math.abs(native - component.pose[key]) < 1e-12) return;
  void store.updatePose(component.component_id, { ...component.pose, [key]: native });
}
const optional = new Set(['radius1_mm', 'radius2_mm', 'clear_aperture_mm', 'aperture_radius_mm']);
// Qt stretches the first ratio row to 45 px in these two-row parameter grids.
const ratioGridKinds = new Set(['pbs', 'splitter', 'beam_sampler']);
const parameters = computed(() => {
  const item = selected.value; if (!item) return [];
  const specs = ((labels as Record<string, string[][]>)[item.kind] ?? []).filter(([key]) => !['focal_mm', 'active_area_mm'].includes(key!)).map(([key, label, unit]) => ({ key: key!, label: label!, unit: unit ?? '' }));
  for (const [key, value] of Object.entries(item.params)) if (!specs.some(spec => spec.key === key) && !['focal_mm', 'active_area_mm'].includes(key) && typeof value !== 'boolean') specs.push({ key, label: key, unit: '' });
  return specs.map(spec => ({ ...spec, optional: optional.has(spec.key), numeric: !optional.has(spec.key) && (typeof item.params[spec.key] === 'number' || !!spec.unit), value: item.params[spec.key], decimals: spec.key.includes('wavelength') ? 1 : 2 }));
});
function parameterText(parameter: typeof parameters.value[number]): string {
  if (parameter.optional) return !Number(parameter.value) ? '' : String(parameter.value);
  return parameter.numeric ? Number(parameter.value ?? 0).toFixed(parameter.decimals) : String(parameter.value ?? '');
}
async function setParameter(parameter: typeof parameters.value[number], event: Event): Promise<void> {
  if (!selected.value) return;
  const input = event.target as HTMLInputElement, text = input.value.trim();
  const value = parameter.optional ? (['', '未设', '-', 'none', 'None'].includes(text) ? 0 : Number(text)) : parameter.numeric ? Number(Number(text).toFixed(parameter.decimals)) : text;
  if (typeof value === 'number' && (!Number.isFinite(value) || (!parameter.optional && (value < -1e6 || value > 1e6)))) { input.value = parameterText(parameter); return; }
  if (value === parameter.value || (typeof value === 'number' && value === Number(parameter.value))) return;
  await store.updateParams(selected.value.component_id, { [parameter.key]: value });
}
</script>
<template>
  <div class="teaching-inspector-window" :style="{'--inspector-height':`${windowHeight}px`}" :class="{ 'teaching-inspector-empty': !selected, 'teaching-inspector-expanded': expanded, 'teaching-inspector-with-hint':store.setupWarnings.length>0 }" role="dialog" aria-label="当前对象" :aria-busy="store.busy || !store.inspectionCurrent" @keydown.esc="emit('close')">
    <button class="teaching-inspector-close" aria-label="关闭属性" @click="emit('close')">×</button>
    <div ref="client" class="teaching-inspector-client" @scroll="refreshScroll">
      <template v-if="selected">
        <section class="teaching-inspector-head">
          <strong class="teaching-inspector-title">当前对象</strong>
          <div class="teaching-inspector-object">{{ selected.label }}<br />{{ COMPONENT_CATALOG[selected.kind].label }}</div>
          <label class="teaching-inspector-check"><input type="checkbox" :checked="selected.enabled" :disabled="store.busy" @change="store.setEnabled(selected.component_id, ($event.target as HTMLInputElement).checked)" />启用</label>
          <p v-if="store.setupWarnings.length" ref="hint" :style="hintHeight?{height:`${hintHeight}px`}:undefined" class="teaching-inspector-hint">{{ store.setupWarnings.slice(0, 3).join('\n') }}</p>
        </section>
        <section class="teaching-inspector-pose">
          <strong class="teaching-inspector-title">位置与朝向</strong>
          <div class="teaching-pose-grid">
            <label v-for="(field, index) in poses" :key="field.key" class="teaching-pose-field" :style="{ '--caption-width': `${field.caption}px`, '--field-index': index % 3 }">
              <span>{{ field.label }}</span><TeachingNumber :label="`${field.label}（${field.unit}）`" :model-value="poseValue(field.key)" :min="field.min" :max="field.max" :decimals="field.decimals" :disabled="store.busy" @update:model-value="setPose(field.key, $event)" /><span class="teaching-inspector-unit" :class="{ 'angle-unit': field.unit === '°' }">{{ field.unit }}</span>
            </label>
          </div>
        </section>
        <button class="teaching-inspector-more" :aria-expanded="expanded" @click="toggleDetails"><span>{{ expanded ? '⌄' : '›' }}</span>{{ expanded ? '收起参数' : '更多参数' }}</button>
        <div v-if="expanded" class="teaching-inspector-details">
          <section v-if="parameters.length" class="teaching-inspector-parameters">
            <strong class="teaching-inspector-title">光学参数</strong>
            <div class="teaching-parameter-grid">
              <label v-for="parameter in parameters" :key="parameter.key" :class="{ 'text-parameter': !parameter.numeric && !parameter.unit, 'unitless-parameter': !parameter.unit && !(parameter.key === 'split_ratio' && ratioGridKinds.has(selected.kind)) }">
                <span>{{ parameter.label }}</span><TeachingNumber v-if="parameter.numeric" :label="parameter.label" :model-value="Number(parameter.value ?? 0)" :min="-1e6" :max="1e6" :decimals="parameter.decimals" :disabled="store.busy" @update:model-value="store.updateParams(selected.component_id, { [parameter.key]: $event })" /><input v-else type="text" :aria-label="parameter.label" :placeholder="parameter.optional ? '未设' : undefined" :value="parameterText(parameter)" step="1" :disabled="store.busy" @blur="setParameter(parameter, $event)" @keydown.enter="($event.target as HTMLInputElement).blur()" /><span :class="{ 'teaching-inspector-unit': parameter.unit }" :style="parameter.unit ? {width:`${(unitWidths as Record<string,number>)[parameter.unit] ?? 34}px`} : undefined">{{ parameter.unit }}</span>
              </label>
            </div>
            <select v-if="selected.kind === 'laser'" aria-label="工业常用激光器规格" class="teaching-laser-preset" :disabled="store.busy" @change="store.updateParams(selected.component_id, laserPresets[Number(($event.target as HTMLSelectElement).value)]!.params)"><option value="" disabled selected>选择工业常用激光器规格…</option><option v-for="(preset, index) in laserPresets" :key="preset.label" :value="index">{{ preset.label }}</option></select>
          </section>
          <section class="teaching-inspector-baseline"><strong class="teaching-inspector-title">基准线</strong><button @click="store.setBaseline(true, selected.pose.x_mm)">设置当前对象为基准位置</button><label class="teaching-inspector-check"><input type="checkbox" :checked="store.baseline_enabled" :disabled="store.busy" @change="store.setBaseline(($event.target as HTMLInputElement).checked)" />显示基准线</label></section>
        </div>
        <section class="teaching-inspector-next"><strong class="teaching-inspector-title">下一步</strong><button @click="emit('publish')">同步到仿真</button></section>
      </template>
      <p v-else class="teaching-inspector-empty-message">未选择对象<br /><br />先点击画布中的器件，再点右侧“属性”按钮，<br />这里显示它的坐标和参数。</p>
    </div>
    <div v-if="scrollRange>0" class="teaching-inspector-scrollbar" role="scrollbar" aria-label="属性滚动条" aria-orientation="vertical" :aria-valuemin="0" :aria-valuemax="scrollRange" :aria-valuenow="scrollPosition" tabindex="0" @pointerdown="scrollbarPointer" @keydown="scrollbarKey"><span class="teaching-inspector-scroll-thumb" :style="{height:`${thumbHeight}px`,top:`${thumbTop}px`}"></span></div>
  </div>
</template>
