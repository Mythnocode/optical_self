<script setup lang="ts">
import { editorValues } from '../domain/surface-registry.js';
import { computed, ref, watch } from "vue";
import { useRouter } from 'vue-router';
import MaterialDialog from './MaterialDialog.vue';
import { useMaterialsStore } from '../stores/materials.js';
import { airNames, type MaterialRecord } from '../domain/materials.js';
import SimulationNumber from "./SimulationNumber.vue";
import { useSimulationStore } from "../stores/simulation.js";
import { surfaceName } from "../domain/simulation-project.js";
const simulation = useSimulationStore();
const materials=useMaterialsStore(),router=useRouter(),materialDetail=ref<MaterialRecord|null>(null),selectedMaterial=ref('');
watch(()=>materials.data.used,()=>{selectedMaterial.value='';});
const sourceMore = ref(false), fiberMore = ref(false);
const fileInput = ref<HTMLInputElement>();
const categories = [{ key: 'source', title: '光源' }, { key: 'materials', title: '材料' }, { key: 'fiber', title: '光纤' }, { key: 'detector', title: '探测器' }, { key: 'environment', title: '环境' }, { key: 'field', title: '视场' }];
type Field = { path: string; label: string; unit?: string; min: number; max: number; factor?: number; integer?: boolean };
const sourceCommon: Field[] = [
  { path: 'ui.source_waist_um', label: '束腰半径 ω₀', unit: 'μm', min: .01, max: 1e6 },
  { path: 'ui.source_position_mm', label: '束腰位置', unit: 'mm', min: -1e6, max: 1e6 },
  { path: 'ui.source_m2', label: '光束质量 M²', min: 1, max: 100 },
];
const sourceAxes: Field[] = [
  { path: 'source.waist_x_mm', label: '束腰半径 ωₓ', unit: 'μm', min: .01, max: 1e6, factor: 1000 },
  { path: 'source.waist_position_x_mm', label: '束腰位置 zₓ', unit: 'mm', min: -1e6, max: 1e6 },
  { path: 'source.waist_y_mm', label: '束腰半径 ωᵧ', unit: 'μm', min: .01, max: 1e6, factor: 1000 },
  { path: 'source.waist_position_y_mm', label: '束腰位置 zᵧ', unit: 'mm', min: -1e6, max: 1e6 },
  { path: 'source.beam_quality_m2_x', label: 'M²ₓ', min: 1, max: 100 }, { path: 'source.beam_quality_m2_y', label: 'M²ᵧ', min: 1, max: 100 },
];
const guided: Field[] = [
  { path: 'receiver.core_diameter_um', label: '芯径', unit: 'μm', min: .1, max: 1000 },
  { path: 'receiver.core_refractive_index', label: '纤芯折射率 n_core', min: 1, max: 5 },
  { path: 'receiver.cladding_refractive_index', label: '包层折射率 n_clad', min: 1, max: 5 },
];
const pose: Field[] = [
  { path: 'receiver.offset_x_mm', label: 'X 方向偏移', unit: 'μm', min: -1e6, max: 1e6, factor: 1000 },
  { path: 'receiver.offset_y_mm', label: 'Y 方向偏移', unit: 'μm', min: -1e6, max: 1e6, factor: 1000 },
  { path: 'receiver.axial_offset_z_mm', label: '轴向偏移 Δz', unit: 'μm', min: -1e6, max: 1e6, factor: 1000 },
  { path: 'ui.fiber_tilt_x_urad', label: 'X 方向倾角', unit: 'μrad', min: -1e6, max: 1e6 },
  { path: 'ui.fiber_tilt_y_urad', label: 'Y 方向倾角', unit: 'μrad', min: -1e6, max: 1e6 },
];
const transmission: Field[] = [
  { path: 'receiver.outside_refractive_index', label: '外部折射率 n_out', min: .1, max: 5 },
  { path: 'receiver.endface_transmission', label: '端面透射率', min: 0, max: 1 },
  { path: 'receiver.fiber_length_m', label: '光纤长度', unit: 'm', min: 0, max: 1e6 },
  { path: 'receiver.attenuation_db_per_km', label: '衰减', unit: 'dB/km', min: 0, max: 1e6 },
  { path: 'receiver.connector_loss_db', label: '连接器损耗', unit: 'dB', min: 0, max: 1e6 },
];
const atmospheric: Field[] = [
  { path: 'environment.environment_temperature_c', label: '环境温度', unit: '°C', min: -273, max: 1000 },
  { path: 'environment.environment_pressure_kpa', label: '大气压', unit: 'kPa', min: 0, max: 10000 },
];
const conjugate: Field[] = [
  { path: 'system.object_distance_mm', label: '物距', unit: 'mm', min: .1, max: 1e9 },
  { path: 'ui.image_distance_mm', label: '像面位置', unit: 'mm', min: -1e6, max: 1e6 },
];
const fieldParameters: Field[] = [
  { path: 'system.pupil_radius_mm', label: '入瞳半径', unit: 'mm', min: .01, max: 10000 },
  { path: 'source.field_x_deg', label: '视场角 X', unit: '°', min: -90, max: 90 },
  { path: 'source.field_y_deg', label: '视场角 Y', unit: '°', min: -90, max: 90 },
];
const materialNames = computed(() => [...new Set(simulation.project.surfaces.map(s=>editorValues(s).material.trim()).filter(n=>!airNames.includes(n.toUpperCase())))]);
const usedMaterials=computed(()=>materials.data.used.length?materials.data.used:materialNames.value.map(name=>({name: name.startsWith('glass_')?name.slice(6):name,canonical:name}) as MaterialRecord));
async function openMaterial(record:MaterialRecord) {
  if(!record.detail_pairs){await materials.refresh();record=materials.data.used.find(item=>item.canonical===record.canonical)??record;}
  if(record.detail_pairs)materialDetail.value=record;
}
const receiver = computed(() => simulation.project.receiver), source = computed(() => simulation.project.source);
const auxiliary = computed(() => source.value.spectral_wavelengths_nm.filter(n => Math.abs(n - source.value.wavelength_nm) > 1e-9).join(', '));
const auxiliaryDraft = ref(auxiliary.value);
function value(field: Field): number {
  if (field.path.startsWith('system.')) return Number(simulation.project[field.path.split('.')[1] as 'pupil_radius_mm' | 'object_distance_mm']);
  return Number(simulation.parameter(field.path)) * (field.factor ?? 1);
}
function update(field: Field, number: number) { simulation.setParameter(field.path, number * (1 / (field.factor ?? 1))); }
function selected(event: Event): string { return (event.target as HTMLSelectElement).value; }
function checked(event: Event): boolean { return (event.target as HTMLInputElement).checked; }
async function chooseField() {
  if (window.opticalDesktop) {
    try { const file = await window.opticalDesktop.selectComplexFieldFile(); if (file) await simulation.importField({ source_path: file.path }); }
    catch (cause) { simulation.rejectField(cause); }
  } else fileInput.value?.click();
}
async function uploadField(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0];
  input.value = ''; if (!file) return;
  if (file.size > 32 * 1024 * 1024) { simulation.rejectField('复场文件超过 32 MiB。'); return; }
  try {
    const dataUrl = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = () => reject(reader.error); reader.readAsDataURL(file); });
    await simulation.importField({ filename: file.name, contents_base64: dataUrl.split(',', 2)[1] });
  } catch (cause) { simulation.rejectField(cause); }
}
</script>

<template>
  <div class="simulation-rail-scroll">
    <div class="simulation-rail-content">
    <details v-for="category in categories" :key="category.key" class="object-category simulation-inspector-section">
      <summary>{{ category.title }}</summary>
      <div class="simulation-inspector-body">
        <template v-if="category.key === 'source'">
          <section class="simulation-field-group"><strong>基本参数</strong>
            <label class="simulation-inspector-field">光源类型<select aria-label="光源类型" :value="source.source_type" @change="simulation.setParameter('source.source_type', selected($event))"><option value="gaussian">高斯光束</option><option value="parallel_pupil">均匀光瞳</option><option value="object_space_na">点光源</option></select></label>
            <label class="simulation-inspector-field">波长<SimulationNumber label="波长" :model-value="source.wavelength_nm" unit="nm" :min="100" :max="30000" @update:model-value="simulation.setParameter('source.wavelength_nm', $event)" /></label>
            <label class="simulation-inspector-field">总功率<SimulationNumber label="总功率" :model-value="source.power_value" :min="0" :max="1e9" @update:model-value="simulation.setParameter('source.power_value', $event)"><select aria-label="功率单位" :value="source.power_unit" @change="simulation.setParameter('source.power_unit', selected($event))"><option>mW</option><option>W</option><option>μW</option></select></SimulationNumber></label>
          </section>
          <section class="simulation-field-group simulation-source-beam" :style="{ minHeight: simulation.parameter('ui.source_split') ? '666px' : '536px' }"><strong>光束参数</strong>
            <template v-if="source.source_type === 'gaussian'">
              <label v-for="field in sourceCommon" :key="field.path" class="simulation-inspector-field">{{ field.label }}<SimulationNumber :label="field.label" :model-value="value(field)" :unit="field.unit" :min="field.min" :max="field.max" :disabled="Boolean(simulation.parameter('ui.source_split'))" @update:model-value="update(field, $event)" /></label>
              <label class="simulation-inspector-check"><input type="checkbox" :checked="Boolean(simulation.parameter('ui.source_split'))" @change="simulation.setParameter('ui.source_split', checked($event))" />分轴（椭圆光斑）</label>
              <label v-for="field in sourceAxes.filter(f => f.unit || simulation.parameter('ui.source_split'))" :key="field.path" class="simulation-inspector-field">{{ field.label }}<SimulationNumber :label="field.label" :model-value="value(field)" :unit="field.unit" :min="field.min" :max="field.max" @update:model-value="update(field, $event)" /></label>
            </template>
            <template v-else-if="source.source_type === 'object_space_na'">
              <label class="simulation-inspector-field">数值孔径 NA<SimulationNumber label="数值孔径 NA" :model-value="source.object_na_x" :min="0" :max="1" :step=".00001" @update:model-value="simulation.setParameter('source.object_na_x', $event)" /></label>
              <label class="simulation-inspector-check"><input type="checkbox" :checked="Boolean(simulation.parameter('ui.source_na_split'))" @change="simulation.setParameter('ui.source_na_split', checked($event))" />分轴</label>
              <label v-if="simulation.parameter('ui.source_na_split')" class="simulation-inspector-field">NAᵧ<SimulationNumber label="光源 NAᵧ" :model-value="source.object_na_y" :min="0" :max="1" :step=".00001" @update:model-value="simulation.setParameter('source.object_na_y', $event)" /></label>
            </template>
          </section>
          <button class="simulation-more" :aria-expanded="sourceMore" @click="sourceMore = !sourceMore">更多参数</button>
          <label v-if="sourceMore" class="simulation-inspector-field">辅助波长<input v-model="auxiliaryDraft" aria-label="辅助波长" placeholder="例如 850, 1310" @blur="simulation.setAuxiliary(auxiliaryDraft)" @keydown.enter="($event.target as HTMLInputElement).blur()" /></label>
        </template>
        <ul v-else-if="category.key === 'materials'" class="simulation-used-materials" role="listbox" aria-label="当前镜头材料" aria-description="双击查看详细参数，右键打开材料库" @contextmenu.prevent="router.push('/workbench/simulation/material_library')"><li v-for="record in usedMaterials" :key="record.canonical" role="option" tabindex="0" :aria-selected="selectedMaterial===record.canonical" :title="record.name" @click="selectedMaterial=record.canonical" @dblclick="openMaterial(record)" @keydown.enter="openMaterial(record)">{{ record.name }}</li></ul>
        <template v-else-if="category.key === 'fiber'">
          <section class="simulation-field-group"><strong>规格</strong>
            <label class="simulation-inspector-field">光纤类型<select aria-label="光纤类型" :value="simulation.parameter('ui.fiber_kind')" @change="simulation.setParameter('ui.fiber_kind', selected($event))"><option value="single_mode_fiber">单模光纤</option><option value="multimode_fiber">多模光纤</option><option value="user_mode">用户模式</option></select></label>
            <label class="simulation-inspector-field">模式<select aria-label="光纤模式" :value="simulation.parameter('ui.fiber_model')" :disabled="simulation.parameter('ui.fiber_kind') !== 'single_mode_fiber'" @change="simulation.setParameter('ui.fiber_model', selected($event))"><option value="gaussian">高斯近似</option><option value="lp01">LP01</option><option value="he11">HE11</option><option value="imported">导入复场</option></select></label>
            <label class="simulation-inspector-field">工作波长<span>{{ source.wavelength_nm.toFixed(2) }} nm</span></label>
          </section>
          <section class="simulation-field-group simulation-fiber-mode"><strong>模场</strong>
            <template v-if="simulation.parameter('ui.fiber_kind') === 'multimode_fiber'">
              <label class="simulation-inspector-field">芯径<SimulationNumber label="多模芯径" :model-value="receiver.core_diameter_um" unit="μm" :min=".1" :max="1000" @update:model-value="simulation.setParameter('receiver.core_diameter_um', $event)" /></label>
              <label class="simulation-inspector-field">数值孔径 NA<SimulationNumber label="光纤数值孔径 NA" :model-value="receiver.na_x" :min=".001" :max="1" :step=".00001" @update:model-value="simulation.setParameter('receiver.na_x', $event)" /></label>
              <label class="simulation-inspector-check"><input type="checkbox" :checked="Boolean(simulation.parameter('ui.fiber_na_split'))" @change="simulation.setParameter('ui.fiber_na_split', checked($event))" />分轴</label>
              <label v-if="simulation.parameter('ui.fiber_na_split')" class="simulation-inspector-field">NAᵧ<SimulationNumber label="光纤 NAᵧ" :model-value="receiver.na_y" :min=".001" :max="1" :step=".00001" @update:model-value="simulation.setParameter('receiver.na_y', $event)" /></label>
            </template>
            <template v-else-if="receiver.mode_model === 'gaussian'">
              <label class="simulation-inspector-field">模场直径 MFD<SimulationNumber label="模场直径 MFD" :model-value="receiver.mode_field_diameter_x_um" unit="μm" :min=".01" :max="10000" @update:model-value="simulation.setParameter('receiver.mode_field_diameter_x_um', $event)" /></label>
              <label class="simulation-inspector-check"><input type="checkbox" :checked="Boolean(simulation.parameter('ui.fiber_split'))" @change="simulation.setParameter('ui.fiber_split', checked($event))" />分轴（椭圆模场）</label>
              <label class="simulation-inspector-field">MFDᵧ<SimulationNumber label="MFDᵧ" :model-value="Number(simulation.parameter('receiver.mode_field_diameter_y_um'))" unit="μm" :min=".01" :max="10000" @update:model-value="simulation.setParameter('receiver.mode_field_diameter_y_um', $event)" /></label>
            </template>
            <template v-else-if="['lp01', 'he11'].includes(receiver.mode_model)"><label v-for="field in guided" :key="field.path" class="simulation-inspector-field">{{ field.label }}<SimulationNumber :label="field.label" :model-value="value(field)" :unit="field.unit" :min="field.min" :max="field.max" @update:model-value="update(field, $event)" /></label></template>
            <template v-else>
              <div class="simulation-field-selector"><input aria-label="光纤复场文件" readonly :value="simulation.request.frontend_state?.imported_field?.path ?? ''" placeholder="尚未选择复场文件" /><button :disabled="simulation.fieldLoading" @click="chooseField">选择…</button></div>
              <p v-if="simulation.fieldError" class="simulation-import-status simulation-field-error">导入失败：{{ simulation.fieldError }}</p>
              <p v-else-if="simulation.fieldLoading" class="simulation-import-status">正在读取…</p>
              <p v-else-if="simulation.request.frontend_state?.imported_field" class="simulation-import-status">已读取 {{ simulation.request.frontend_state.imported_field.shape.join('×') }}<span v-if="simulation.request.frontend_state.imported_field.wavelength_nm">，文件波长 {{ simulation.request.frontend_state.imported_field.wavelength_nm }} nm</span></p>
            </template>
          </section>
          <section class="simulation-field-group"><strong>装调</strong><label v-for="field in pose" :key="field.path" class="simulation-inspector-field">{{ field.label }}<SimulationNumber :label="field.label" :model-value="value(field)" :unit="field.unit" :min="field.min" :max="field.max" @update:model-value="update(field, $event)" /></label></section>
          <button class="simulation-more" :aria-expanded="fiberMore" @click="fiberMore = !fiberMore">传输参数</button>
          <template v-if="fiberMore"><label v-for="field in transmission" :key="field.path" class="simulation-inspector-field">{{ field.label }}<SimulationNumber :label="field.label" :model-value="value(field)" :unit="field.unit" :min="field.min" :max="field.max" @update:model-value="update(field, $event)" /></label></template>
        </template>
        <template v-else-if="category.key === 'environment'">
          <section class="simulation-field-group"><strong>大气</strong><label v-for="field in atmospheric" :key="field.path" class="simulation-inspector-field">{{ field.label }}<SimulationNumber :label="field.label" :model-value="value(field)" :unit="field.unit" :min="field.min" :max="field.max" @update:model-value="update(field, $event)" /></label><label class="simulation-inspector-check"><input type="checkbox" :checked="simulation.project.analysis_settings.thermal_compensation" @change="simulation.setParameter('analysis_settings.thermal_compensation', checked($event))" />温度补偿</label></section>
          <section class="simulation-field-group"><strong>物像共轭</strong><label v-for="field in conjugate" :key="field.path" class="simulation-inspector-field">{{ field.label }}<SimulationNumber :label="field.label" :model-value="value(field)" :unit="field.unit" :min="field.min" :max="field.max" @update:model-value="update(field, $event)" /></label><label class="simulation-inspector-check"><input type="checkbox" :checked="simulation.project.analysis_settings.auto_best_focus" @change="simulation.setParameter('analysis_settings.auto_best_focus', checked($event))" />最佳焦面搜索</label></section>
        </template>
        <section v-else-if="category.key === 'detector'" class="simulation-field-group"><strong>观察</strong>
          <label class="simulation-inspector-check"><input type="checkbox" :checked="simulation.observation.enabled" @change="simulation.setObservation('enabled', checked($event))" />启用探测器</label>
          <label v-if="simulation.observation.enabled" class="simulation-inspector-field">观察方式<select aria-label="观察方式" :value="simulation.observation.mode" @change="simulation.setObservation('mode', selected($event))"><option value="surface">光学面</option><option value="fiber">光纤模场</option><option value="custom">自定义位置</option></select></label>
          <label v-if="simulation.observation.enabled && simulation.observation.mode === 'surface'" class="simulation-inspector-field">光学面<select aria-label="观察光学面" :value="simulation.observation.surface_index" @change="simulation.setObservation('surface_index', Number(selected($event)))"><option v-for="surface in simulation.project.surfaces" :key="surface.index" :value="surface.index">{{ surfaceName(surface) }}（面 {{ surface.index }}）</option></select></label>
          <!-- The original unit-row wrappers remain visible in every mode. -->
          <label class="simulation-inspector-field">相对最后一面<SimulationNumber label="探测器相对最后一面" :model-value="simulation.observation.offset_mm" unit="mm" :min="-1e6" :max="1e6" @update:model-value="simulation.setObservation('offset_mm', $event)" /></label>
          <label class="simulation-inspector-field">像元尺寸<SimulationNumber label="像元尺寸" :model-value="simulation.observation.pitch_um" unit="μm" :min=".001" :max="1e6" @update:model-value="simulation.setObservation('pitch_um', $event)" /></label>
          <template v-if="simulation.observation.enabled && simulation.observation.mode !== 'fiber'">
            <label class="simulation-inspector-field">X 像元数<SimulationNumber label="X 像元数" :model-value="simulation.observation.pixels_x" :min="1" :max="1e6" integer @update:model-value="simulation.setObservation('pixels_x', $event)" /></label>
            <label class="simulation-inspector-field">Y 像元数<SimulationNumber label="Y 像元数" :model-value="simulation.observation.pixels_y" :min="1" :max="1e6" integer @update:model-value="simulation.setObservation('pixels_y', $event)" /></label>
          </template>
        </section>
        <section v-else-if="category.key === 'field'" class="simulation-field-group"><strong>入瞳与视场</strong><label v-for="field in fieldParameters" :key="field.path" class="simulation-inspector-field">{{ field.label }}<SimulationNumber :label="field.label" :model-value="value(field)" :unit="field.unit" :min="field.min" :max="field.max" @update:model-value="update(field, $event)" /></label></section>
      </div>
    </details>
    </div>
    <input ref="fileInput" hidden type="file" accept=".npy,.npz,.csv" aria-label="上传光纤复场文件" @change="uploadField" />
  </div>
  <MaterialDialog v-if="materialDetail" :record="materialDetail" @close="materialDetail=null" />
</template>

