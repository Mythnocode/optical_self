<script setup lang="ts">
import {nextTick,onMounted,ref,watch} from 'vue';
import {useOptimizationStore} from '../stores/optimization.js';
import {useSimulationStore} from '../stores/simulation.js';
import {useModelsStore} from '../stores/models.js';
import SimulationNumber from './SimulationNumber.vue';
const optimization=useOptimizationStore(),simulation=useSimulationStore(),models=useModelsStore(),config=optimization.config;
const advancedScroll=ref<HTMLDivElement>();
onMounted(()=>{void optimization.refreshPresentation();void models.refresh();});
watch(()=>simulation.revision,()=>void optimization.refreshPresentation());
watch(()=>models.records,items=>{if(!items.some(item=>item.model_id===config.surrogate_model_id))config.surrogate_model_id=items[0]?.model_id||'';});
watch(()=>config.collimation_enabled,async enabled=>{if(!enabled)return;await nextTick();const area=advancedScroll.value,target=area?.querySelector('[aria-label="最大光轴倾角"]');if(area&&target)area.scrollTop+=Math.max(0,target.getBoundingClientRect().bottom-area.getBoundingClientRect().bottom+6);});
</script>
<template>
  <div class="optimization-rail-actions"><button :class="{selected:optimization.view==='variables'}" @click="optimization.view='variables'">优化变量</button><button :class="{selected:optimization.view==='more'}" @click="optimization.view='more'">更多参数</button></div>
  <template v-if="optimization.view==='variables'">
    <input v-model="optimization.search" class="rail-search optimization-search" type="search" placeholder="筛选…" aria-label="筛选优化参数" />
    <div class="optimization-categories"><button v-for="category in ['全部','L1','L2','L3','L4','光纤']" :key="category" :class="{selected:optimization.group===category}" @click="optimization.group=category">{{ category }}</button></div>
    <div class="optimization-parameter-list"><div class="optimization-parameter-items"><label v-for="row in optimization.filtered" :key="row.path" :title="row.path"><input type="checkbox" :checked="optimization.selected.includes(row.path)" @change="optimization.select(row.path,($event.target as HTMLInputElement).checked)" />{{ row.label }}</label></div></div>
  </template>
  <div v-else ref="advancedScroll" class="optimization-advanced-scroll">
    <section class="optimization-advanced-group"><h2>评价</h2>
      <label><span>目标</span><select v-model="config.objective" aria-label="评价目标"><option>最大化耦合效率</option><option>最小化 RMS 光斑</option><option>多目标加权</option></select></label>
      <label><span>面</span><select v-model="config.evaluation_plane" aria-label="评价面"><option>光纤模场</option></select></label>
      <label><span>方式</span><select v-model="config.evaluation_mode" aria-label="评价方式"><option value="formal">光学仿真</option><option value="surrogate">已训练模型</option></select></label>
      <label v-if="config.evaluation_mode==='surrogate'"><span>模型</span><select v-model="config.surrogate_model_id" aria-label="评价模型"><option v-if="!models.records.length" value="">请先在模型页训练</option><option v-for="model in models.records" :key="model.model_id" :value="model.model_id">{{ model.name||model.model_id }}</option></select></label>
    </section>
    <section class="optimization-advanced-group"><h2>工程约束</h2>
      <label><span>最大系统总长</span><SimulationNumber v-model="config.max_system_length_mm" label="最大系统总长" unit="mm" :min=".1" :max="1e6" :decimals="3" /></label>
      <label title="当前表面模型未声明透镜前后面配对，暂不能可靠约束边缘厚度。"><span>最小边缘厚度</span><SimulationNumber :model-value=".3" label="最小边缘厚度" unit="mm" disabled :decimals="3" /></label>
      <label><span>最小厚度</span><SimulationNumber v-model="config.min_center_thickness_mm" label="最小厚度" unit="mm" :min="0" :max="100" :decimals="3" /></label>
      <label><span>最小空气厚度</span><SimulationNumber v-model="config.min_air_gap_mm" label="最小空气厚度" unit="mm" :min="0" :max="100" :decimals="3" /></label>
      <label class="optimization-advanced-check"><input v-model="config.aperture_within_mechanical" type="checkbox" />半口径不超过机械口径</label>
    </section>
    <section class="optimization-advanced-group"><h2>准直约束</h2><label class="optimization-advanced-check"><input v-model="config.collimation_enabled" type="checkbox" />启用</label>
      <template v-if="config.collimation_enabled">
        <label><span>评价面</span><select v-model="config.collimation_surface" aria-label="准直评价面"><option value="">自动识别准直输出面</option><option v-for="surface in optimization.presentation?.surfaces" :key="surface.value" :value="surface.value">{{ surface.label }}</option></select></label>
        <label><span>评价段</span><SimulationNumber v-model="config.collimation_span" label="评价段" unit="mm" :min=".1" :max="1000" :decimals="3" /></label>
        <label><span>最大半径变化</span><SimulationNumber v-model="config.collimation_radius_change" label="最大半径变化" unit="%" :min=".01" :max="100" :decimals="3" /></label>
        <label><span>最大归一化曲率</span><SimulationNumber v-model="config.collimation_curvature" label="最大归一化曲率" :min=".00001" :max="10" :decimals="5" /></label>
        <label><span>最大质心漂移</span><SimulationNumber v-model="config.collimation_centroid_drift" label="最大质心漂移" unit="%" :min=".001" :max="100" :decimals="3" /></label>
        <label><span>最大光轴倾角</span><SimulationNumber v-model="config.collimation_axis_tilt" label="最大光轴倾角" unit="mrad" :min=".001" :max="1000" :decimals="3" /></label>
      </template>
    </section>
    <section class="optimization-advanced-group"><label><span>最大评价次数</span><SimulationNumber v-model="config.max_iterations" label="最大评价次数" integer :min="10" :max="100000" /></label></section>
  </div>
</template>
