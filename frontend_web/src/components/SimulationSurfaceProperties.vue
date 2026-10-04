<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import SimulationNumber from './SimulationNumber.vue';
import { useSimulationStore } from "../stores/simulation.js";
import { fieldValue, surfaceId, surfaceName, type SurfaceField } from "../domain/simulation-project.js";
import { surfaceRegistry, surfaceSpec, editorValues, parameters, parameterValue } from '../domain/surface-registry.js';
const props = withDefaults(defineProps<{ initialTab?: number }>(), { initialTab: 0 });
const emit = defineEmits<{ close: [] }>();
const simulation = useSimulationStore();
const surface = computed(() => simulation.project.surfaces[simulation.selectedIndex]);
const spec = computed(() => surfaceSpec(surface.value));
const tab = ref(props.initialTab);
const common: Array<{ field: SurfaceField; label: string; unit?: string; min?: number }> = [
  { field: "radius", label: "曲率半径 R", unit: "mm", min: -1e9 }, { field: "thickness", label: "厚度", unit: "mm", min: 0 },
  { field: "material", label: "材料 / 后介质" }, { field: "aperture", label: "半口径", unit: "mm", min: .000001 },
];
function value(event: Event): string { return (event.target as HTMLInputElement).value; }
function number(field: SurfaceField): number { return Number(fieldValue(surface.value, field)); }
const applied = ref(false);
const body = ref<HTMLElement>();
const scrollbar = ref({ top: 0, height: 0, thumbTop: 0, thumbHeight: 0, visible: false });
let bodyObserver: ResizeObserver | undefined;
function measureScrollbar(): void {
  const area = body.value; if (!area) return;
  const height = area.clientHeight, thumbHeight = Math.max(24, height * height / area.scrollHeight);
  scrollbar.value = { top: area.offsetTop, height, thumbHeight,
    thumbTop: area.scrollTop * (height - thumbHeight) / Math.max(1, area.scrollHeight - height), visible: area.scrollHeight > height + 1 };
}
watch(body, element => {
  bodyObserver?.disconnect();
  if (element) { bodyObserver = new ResizeObserver(measureScrollbar); bodyObserver.observe(element); }
  void nextTick(measureScrollbar);
});
watch([tab, spec], () => { void nextTick(measureScrollbar); });
onBeforeUnmount(() => bodyObserver?.disconnect());
let dragStart: { y: number; scroll: number } | undefined;
function scrollStart(event: PointerEvent): void {
  dragStart = { y: event.clientY, scroll: body.value?.scrollTop ?? 0 };
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
}
function scrollMove(event: PointerEvent): void {
  if (!dragStart || !body.value) return;
  body.value.scrollTop = dragStart.scroll + (event.clientY - dragStart.y) * (body.value.scrollHeight - body.value.clientHeight) / Math.max(1, scrollbar.value.height - scrollbar.value.thumbHeight);
}
function appliedState(): void {
  applied.value = true;
  // Qt rebuilds the property page after auto-apply, returning its scroll area to the top.
  void nextTick(() => { if (body.value) body.value.scrollTop = 0; measureScrollbar(); });
}
function preparePropertyDefaults(): void {
  const params = parameters(surface.value);
  params._aperture_type ??= apertureType.value;
  params._clear_aperture_mm ??= editorValues(surface.value).semi_aperture_mm * 2;
}
function change(field: SurfaceField, value: number | string): void {
  preparePropertyDefaults(); if (simulation.change(field, String(value))) appliedState();
}
function property(key: string, value: string | boolean): void {
  preparePropertyDefaults(); simulation.changeProperty(key, value); if (!simulation.error) appliedState();
}
function step(direction: number): void {
  const next = simulation.project.surfaces[simulation.selectedIndex + direction]; if (next) simulation.selectedId = surfaceId(next);
}
const apertureType = computed(() => parameters(surface.value)._aperture_type ?? ({ circular: '圆形通光孔径', rectangular: '矩形孔径', elliptical: '椭圆孔径', user: '用户孔径' } as Record<string,string>)[String(surface.value.aperture_type)] ?? '圆形通光孔径');
const feature = computed(() => {
  const preferred: Record<string,string[]> = {
    cylindrical: ['cylinder_axis_deg'], grating: ['groove_density_lpm','diffraction_order','grating_mode'],
    coordinate_break: ['decenter_x_mm','tilt_x_deg','tilt_y_deg'], mirror: ['mirror_mode','reflectivity','design_incidence_deg'],
    stop: ['stop_role','aperture_shape'], detector: ['pixel_pitch_um','pixels_x','pixels_y'], aspheric: ['a4','a6','a8'],
    binary_diffractive: ['diffraction_order','phase_a2','phase_a4'], user_defined: ['plugin_id'],
  };
  return (preferred[surface.value.surface_type] ?? []).slice(0,3).map(key => {
    const parameter = spec.value.parameters.find(item => item.key === key)!;
    const current = parameterValue(surface.value, parameter);
    const text = parameter.kind === 'float' ? Number(current).toFixed(2) : String(current);
    if (key === 'diffraction_order') return `m=${text}`;
    const prefix = key.startsWith('decenter_') || key.startsWith('tilt_') || key.startsWith('pixels_') ? `${parameter.label}=` : '';
    return `${prefix}${text}${parameter.unit ? ' '+parameter.unit : ''}`;
  }).join(' · ') || (surface.value.surface_type === 'user_defined' ? '' : '—');
});
function selectionContext(): string {
  return `${spec.value.name}｜材料 ${editorValues(surface.value).material}｜半口径 ${editorValues(surface.value).semi_aperture_mm.toFixed(2)} mm｜${feature.value}`;
}
// The original helper label refreshes on selection/reopening, while auto-apply changes only the badge.
const contextText = ref(selectionContext());
watch(() => simulation.selectedId, () => { applied.value = false; if (surface.value) contextText.value = selectionContext(); });
</script>

<template>
  <div v-if="surface" class="simulation-properties-dialog" role="dialog" aria-label="表面属性" aria-modal="false" @keydown.esc="emit('close')">
    <div class="simulation-properties-header"><strong :class="{ applied }"><template v-if="applied">S{{ surface.index + 1 }} 已自动应用</template><template v-else>S{{ surface.index + 1 }}｜{{ surface.metadata.group_id }}｜{{ surfaceName(surface) }}</template></strong><span>{{ contextText }}</span><button aria-label="关闭表面属性" @click="emit('close')">×</button></div>
    <div class="simulation-properties-tabs" role="tablist"><button v-for="(title, index) in ['公共参数', '面形与孔径', `${spec.name}参数`, '制造与备注']" :key="index" role="tab" :aria-selected="tab === index" :class="{ active: tab === index }" @click="tab = index">{{ title }}</button></div>
    <div ref="body" :key="`${simulation.selectedId}-${tab}-${surface.surface_type}`" class="simulation-properties-body" :class="{ 'surface-dynamic-body': tab === 2, 'surface-profile-body': tab === 1, 'surface-scroll-body': tab === 0 || tab === 3 || (tab === 2 && spec.parameters.length >= 5) }" role="tabpanel" @scroll="measureScrollbar">
      <template v-if="tab === 0">
        <label class="simulation-property-field"><span>元件组</span><input :value="surface.metadata.group_id" placeholder="例如 L1、G1、CB1" @change="property('group_id', value($event))" /></label>
        <label class="simulation-property-field"><span>表面名称</span><input :value="surfaceName(surface)" @change="change('name', value($event))" /></label>
        <label class="simulation-property-field"><span>表面类型</span><select :value="surface.surface_type" @change="property('surface_type', value($event))"><option v-for="type in surfaceRegistry" :key="type.key" :value="type.key">{{ type.name }}</option></select></label>
        <label v-for="column in common" :key="column.field" class="simulation-property-field"><span>{{ column.label }}</span>
          <SimulationNumber v-if="column.unit" class="simulation-property-number" spin-buttons :label="column.label" :model-value="number(column.field)" :unit="column.unit" :min="column.min" :max="1e9" :decimals="8" :disabled="spec.disabled_common_fields.includes(column.field)" @update:model-value="change(column.field, $event)" />
          <input v-else :value="fieldValue(surface, column.field)" list="optical-materials" :disabled="spec.disabled_common_fields.includes(column.field)" @change="change(column.field, value($event))" />
        </label>
        <datalist id="optical-materials"><option>AIR</option><option>N-BK7</option><option>N-SF11</option><option>F_SILICA</option><option>MIRROR</option><option>自定义</option></datalist>
      </template>
      <template v-else-if="tab === 1">
        <label class="simulation-property-field"><span>圆锥系数 k</span><SimulationNumber class="simulation-property-number" spin-buttons label="圆锥系数 k" :model-value="number('conic')" :min="-1e9" :max="1e9" :decimals="9" @update:model-value="change('conic', $event)" /></label>
        <label class="simulation-property-field"><span>孔径类型</span><select :value="apertureType" @change="property('aperture_type', value($event))"><option>圆形通光孔径</option><option>矩形孔径</option><option>椭圆孔径</option><option>用户孔径</option></select></label>
        <label class="simulation-property-field"><span>有效通光直径</span><SimulationNumber class="simulation-property-number" spin-buttons label="有效通光直径" :model-value="Number(parameters(surface)._clear_aperture_mm ?? editorValues(surface).semi_aperture_mm * 2)" unit="mm" :min=".000001" :max="2e9" :decimals="8" @update:model-value="property('clear_diameter', String($event))" /></label>
      </template>
      <template v-else-if="tab === 2">
        <div class="surface-dynamic-fields" :style="{ '--field-count': spec.parameters.length }">
          <label v-for="parameter in spec.parameters" :key="parameter.key" class="simulation-property-field"><span>{{ parameter.label }}</span>
            <SimulationNumber v-if="['float','int'].includes(parameter.kind)" class="simulation-property-number" spin-buttons :class="{ 'surface-integer-number': parameter.kind === 'int' }" :label="parameter.label" :model-value="Number(parameterValue(surface, parameter))" :unit="parameter.unit" :min="parameter.minimum" :max="parameter.maximum" :integer="parameter.kind === 'int'" :decimals="Math.max(8, parameter.decimals)" @update:model-value="property(parameter.key, String($event))" />
            <select v-else-if="parameter.kind === 'choice'" :value="parameterValue(surface, parameter)" @change="property(parameter.key, value($event))"><option v-for="choice in parameter.choices" :key="choice">{{ choice }}</option></select>
            <span v-else-if="parameter.kind === 'bool'" class="simulation-property-checkbox"><input type="checkbox" :checked="Boolean(parameterValue(surface, parameter))" @change="property(parameter.key, ($event.target as HTMLInputElement).checked)" />启用</span>
            <input v-else :value="parameterValue(surface, parameter)" @change="property(parameter.key, value($event))" />
            <small v-if="parameter.helper">{{ parameter.helper }}</small>
          </label>
          <p v-if="!spec.parameters.length" class="simulation-property-empty">该表面类型没有额外专用参数；使用公共参数与面形参数即可。</p>
        </div>
      </template>
      <template v-else>
        <label class="simulation-property-field"><span>镀膜</span><input :value="surface.metadata.coating_preset" list="optical-coatings" @change="property('coating_preset', value($event))" /></label>
        <datalist id="optical-coatings"><option>无</option><option>增透膜</option><option>高反膜</option><option>金属膜</option><option>自定义镀膜</option></datalist>
        <label class="simulation-property-field"><span>表面粗糙度</span><SimulationNumber class="simulation-property-number" spin-buttons label="表面粗糙度" :model-value="Number(surface.roughness_rms_nm ?? 0)" unit="nm RMS" :min="0" :max="1e9" :decimals="8" @update:model-value="property('roughness_rms_nm', String($event))" /></label>
        <label class="simulation-property-field"><span>机械直径</span><SimulationNumber class="simulation-property-number" spin-buttons label="机械直径" :model-value="surface.mechanical_diameter_mm ?? 0" unit="mm" :min=".0001" :max="1e9" :decimals="8" @update:model-value="property('mechanical_diameter_mm', String($event))" /></label>
        <label class="simulation-property-field"><span>启用状态</span><span class="simulation-property-checkbox"><input type="checkbox" :checked="surface.enabled" @change="property('enabled', ($event.target as HTMLInputElement).checked)" />参与追迹和正式计算</span></label>
        <label class="simulation-property-field"><span>备注</span><input :value="surface.metadata.note" placeholder="元件型号、装配位置或制造备注" @change="property('note', value($event))" /></label>
      </template>
    </div>
    <div v-if="scrollbar.visible" class="surface-property-scrollbar" aria-hidden="true" :style="{ top: `${scrollbar.top}px`, height: `${scrollbar.height}px` }">
      <div class="surface-property-scroll-thumb" :style="{ top: `${scrollbar.thumbTop}px`, height: `${scrollbar.thumbHeight}px` }" @pointerdown.prevent="scrollStart" @pointermove="scrollMove" @pointerup="dragStart = undefined" @pointercancel="dragStart = undefined" />
    </div>
    <div class="simulation-properties-footer"><button :disabled="simulation.selectedIndex <= 0" @click="step(-1)">‹ 上一面</button><button :disabled="simulation.selectedIndex >= simulation.project.surfaces.length - 1" @click="step(1)">› 下一面</button></div>
  </div>
</template>
