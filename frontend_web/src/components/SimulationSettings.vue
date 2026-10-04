<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import SimulationNumber from "./SimulationNumber.vue";
import { clone } from "../domain/simulation-project.js";
import { useSimulationStore } from "../stores/simulation.js";
const emit = defineEmits<{ close: [] }>();
const simulation = useSimulationStore(), draft = ref(clone(simulation.project.analysis_settings));
const dialog = ref<HTMLDialogElement>();
const previousFocus = document.activeElement as HTMLElement | null;
onMounted(() => { dialog.value?.showModal(); });
onBeforeUnmount(() => { dialog.value?.close(); previousFocus?.focus(); });
const choices = [
  { key: 'calc_precision', label: '计算精度', items: [['preview', '预览'], ['standard', '标准'], ['high', '高精度']] },
  { key: 'calc_grid_size', label: '接收面网格', items: [65, 129, 257, 513, 1025].map(n => [n, `${n}×${n}`]) },
  { key: 'calc_layout_pupil', label: '光路采样', items: [7, 9, 13, 17].map(n => [n, `${n}×${n}`]) },
  { key: 'calc_pupil', label: '分析光瞳', items: [17, 33, 49, 65].map(n => [n, `${n}×${n}`]) },
  { key: 'calc_propagation', label: '传播方法', items: [['angular_spectrum', '普通角谱'], ['band_limited_angular_spectrum', '带限角谱'], ['scaled_angular_spectrum', '缩放角谱'], ['scaled_fresnel', '缩放 Fresnel'], ['issc', 'ISSC'], ['fresnel', 'Fresnel']] },
];
const analyses = [['raytrace', '光路'], ['spot', '点列图'], ['psf', '点扩散函数 PSF'], ['coupling', '耦合效率'], ['mtf', 'MTF'], ['power_audit', '能量检查']];
const checkboxes = [
  ['calc_high_precision_coupling', '完整复场耦合'], ['calc_only_visible_results', '只计算当前结果'],
  ['calc_sampling_convergence', '检查采样收敛'], ['calc_save_large_arrays', '保存完整数组'], ['incident_intensity_only', '端面匹配只显示入射光光强'],
  ['alignment_enabled', '光纤对准'], ['alignment_include_dz', '包含轴向对准'],
];
const alignment = [
  { key: 'alignment_max_offset_um', label: '最大横向偏移', min: 0, max: 1e6 },
  { key: 'alignment_max_axial_offset_um', label: '最大轴向偏移', min: 0, max: 1e6 },
  { key: 'alignment_max_tilt_urad', label: '最大倾角', min: 0, max: 1e7 },
  { key: 'alignment_max_iterations', label: '最大迭代次数', min: 1, max: 1e6, integer: true },
  { key: 'alignment_max_function_evaluations', label: '最大函数求值次数', min: 1, max: 1e6, integer: true },
  { key: 'alignment_timeout_seconds', label: '对准超时', min: 1, max: 1e6 },
];
function setChoice(key: string, event: Event) {
  const value = (event.target as HTMLSelectElement).value;
  draft.value[key] = ['calc_grid_size', 'calc_layout_pupil', 'calc_pupil'].includes(key) ? Number(value) : value;
}
function selectAnalysis(key: string, event: Event) {
  const selected = new Set(draft.value.requested_analyses);
  if ((event.target as HTMLInputElement).checked) selected.add(key); else selected.delete(key);
  draft.value.requested_analyses = analyses.map(([key]) => key).filter(key => selected.has(key));
}
function apply() { simulation.applySettings(draft.value); emit('close'); }
</script>
<template>
  <dialog ref="dialog" class="simulation-settings-dialog" aria-label="计算设置" @cancel.prevent="emit('close')">
    <header class="simulation-settings-title">计算设置<button aria-label="取消计算设置" @click="emit('close')">×</button></header>
    <div class="simulation-settings-scroll">
      <div class="simulation-settings-form">
        <label v-for="choice in choices" :key="choice.key">{{ choice.label }}<select :aria-label="choice.label" :value="draft[choice.key]" @change="setChoice(choice.key, $event)"><option v-for="item in choice.items" :key="String(item[0])" :value="item[0]">{{ item[1] }}</option></select></label>
        <label>零填充<SimulationNumber label="零填充" :model-value="draft.calc_zero_padding" :min="1" :max="16" integer @update:model-value="draft.calc_zero_padding = $event" /></label>
        <label>计算窗口<SimulationNumber label="计算窗口" :model-value="draft.calc_output_extent_mm" :min=".001" :max="1000" @update:model-value="draft.calc_output_extent_mm = $event" /></label>
        <label class="simulation-settings-check"><span></span><span><input v-model="draft.calc_auto_expand_output" type="checkbox" />自动扩展计算窗口</span></label>
        <label v-for="(analysis, index) in analyses" :key="analysis[0]" class="simulation-settings-check"><span>{{ index === 0 ? '计算内容' : '' }}</span><span><input type="checkbox" :checked="draft.requested_analyses.includes(analysis[0])" @change="selectAnalysis(analysis[0], $event)" />{{ analysis[1] }}</span></label>
        <label v-for="box in checkboxes" :key="box[0]" class="simulation-settings-check"><span></span><span><input type="checkbox" :checked="Boolean(draft[box[0]])" @change="draft[box[0]] = ($event.target as HTMLInputElement).checked" />{{ box[1] }}</span></label>
        <label v-for="field in alignment" :key="field.key">{{ field.label }}<SimulationNumber :label="field.label" :model-value="Number(draft[field.key])" :min="field.min" :max="field.max" :integer="field.integer" @update:model-value="draft[field.key] = $event" /></label>
      </div>
    </div>
    <footer><button @click="apply">Close</button></footer>
  </dialog>
</template>
