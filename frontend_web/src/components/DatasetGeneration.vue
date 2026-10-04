<script setup lang="ts">
import {watch} from 'vue';
import {useDatasetGenerationStore} from '../stores/dataset-generation.js';
import {useSimulationStore} from '../stores/simulation.js';
import {onBackendConnected} from '../domain/backend-connection.js';
import SimulationNumber from './SimulationNumber.vue';
const props=defineProps<{visible:boolean;family:'tabular'|'sequence';trainingBusy:boolean}>();
const emit=defineEmits<{toggleFamily:[]}>();
const generation=useDatasetGenerationStore(),simulation=useSimulationStore();
watch(()=>props.family, family=>{generation.options.sample_count=Math.max(family==='sequence'?10:8,generation.options.sample_count);},{immediate:true});
watch(()=>[props.visible,simulation.contextId,simulation.revision],()=>{if(props.visible)void generation.refreshPresentation();},{immediate:true});
onBackendConnected(()=>{if(props.visible)void generation.refreshPresentation();});
</script>
<template>
  <div class="dataset-generation-controls" :class="{'generation-collapsed':!generation.more,'generation-vars-expanded':visible&&generation.more&&family==='sequence'&&generation.variablesOpen}">
    <div class="generation-two-fields generation-sample-row"><label><span>样本数</span><SimulationNumber label="样本数" v-model="generation.options.sample_count" :min="family==='sequence'?10:8" :max="100000" integer /></label><label><span>目标变量</span><select aria-label="目标变量" v-model="generation.options.target"><option v-for="value in generation.presentation?.targets??['耦合损耗(dB)','耦合效率','RMS 光斑','Strehl']" :key="value">{{value}}</option></select></label></div>
    <div class="generation-mode-row"><span>镜头结构</span><button class="fixed-lens-count" :class="{'sequence-generation-mode':family==='sequence'}" type="button" :aria-pressed="family==='sequence'" @click="emit('toggleFamily')">{{family==='sequence'?'任意镜头数':'固定镜头数'}}</button></div>
    <div class="generation-more-row"><button class="model-more-button" type="button" :aria-expanded="generation.more" @click="generation.more=!generation.more">更多参数<span>{{generation.more?'⌄':'›'}}</span></button></div>
    <div v-show="generation.more" class="generation-options">
      <div v-if="family==='tabular'" class="generation-two-fields generation-fixed-row"><label><span>研究对象</span><select aria-label="研究对象" v-model.number="generation.options.lens_count"><option :value="1">单透镜</option><option :value="2">双透镜</option><option :value="3">三透镜</option><option :value="4">四透镜</option></select></label><label><span>变量方案</span><select aria-label="变量方案" v-model="generation.options.include_conic"><option :value="false">曲率半径 + 厚度</option><option :value="true">曲率半径 + 厚度 + 圆锥系数</option></select></label></div>
      <template v-else>
        <div class="generation-lens-count"><span>当前系统镜头数</span><span>{{generation.loading?'正在识别当前系统…':generation.presentation?`已识别 ${generation.presentation.lens_count} 个实体镜片（每个系统样本保留此序列长度）`:'无法识别当前系统的实体镜片'}}</span></div>
        <div class="generation-variable-row"><span>变量方案</span><span>{{generation.options.variable_paths.length?`已选择 ${generation.options.variable_paths.length} 个变量`:'未选择变量'}}</span><button type="button" class="model-more-button" :aria-expanded="generation.variablesOpen" @click="generation.variablesOpen=!generation.variablesOpen">选择变量<span>{{generation.variablesOpen?'⌄':'›'}}</span></button></div>
        <div v-show="generation.variablesOpen" class="generation-variable-grid"><label v-for="variable in generation.presentation?.variables??[]" :key="variable.path" :title="variable.path"><input type="checkbox" :value="variable.path" v-model="generation.options.variable_paths" />{{variable.label}}</label></div>
      </template>
      <div class="generation-two-fields generation-sampling-row"><label><span>采样方法</span><select aria-label="采样方法" v-model="generation.options.sampling"><option>Latin Hypercube</option><option>Sobol低差异采样</option></select></label><label><span>验证集比例</span><SimulationNumber label="验证集比例" v-model="generation.options.validation_ratio" :min="0.05" :max="0.4" :decimals="8" :step="0.01" /></label><label><span>随机种子</span><SimulationNumber label="随机种子" v-model="generation.options.random_seed" :min="0" :max="1000000000" integer /></label><label><span>计算精度</span><select aria-label="数据集计算精度" v-model="generation.options.precision"><option>129×129</option><option>257×257</option><option>513×513</option></select></label></div>
    </div>
    <button type="button" class="generate-dataset-button" :disabled="generation.busy||trainingBusy" @click="generation.generate(family)">生成数据集</button>
    <p v-if="generation.error" class="dataset-details-error" role="alert">{{generation.error}}</p>
  </div>
</template>
