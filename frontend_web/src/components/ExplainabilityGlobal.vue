<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,ref,watch} from 'vue';
import {useExplainabilityStore} from '../stores/explainability.js';
import {explanationCharts,readExplanationPresentation,type ExplanationPresentation} from '../api/explainability.js';
const explain=useExplainabilityStore(),canvas=ref<HTMLDivElement>(),presentation=ref<ExplanationPresentation|null>(null),error=ref(''),renderedChart=ref('');
const size=ref({width:900,height:400});let observer:ResizeObserver|undefined,timer:ReturnType<typeof setTimeout>|undefined,version=0;
onMounted(()=>{observer=new ResizeObserver(([entry])=>{if(entry&&entry.contentRect.width>0&&entry.contentRect.height>0)size.value={width:Math.max(160,Math.min(4096,Math.round(entry.contentRect.width))),height:Math.max(100,Math.min(4096,Math.round(entry.contentRect.height)))};});if(canvas.value)observer.observe(canvas.value);});
onBeforeUnmount(()=>{version++;observer?.disconnect();clearTimeout(timer);});
watch(()=>explain.jobId,()=>{presentation.value=null;});
watch([()=>explain.jobId,()=>explain.job?.status,()=>explain.chart,size],()=>{clearTimeout(timer);const token=++version;error.value='';if(explain.job?.status!=='completed'){presentation.value=null;return;}timer=setTimeout(()=>void load(token),80);},{deep:true,immediate:true});
async function load(token:number){const chart=explain.chart;try{const result=await readExplanationPresentation(explain.jobId,chart,size.value.width,size.value.height);if(token===version){presentation.value=result;renderedChart.value=chart;}}catch(cause){if(token===version)error.value=cause instanceof Error?cause.message:String(cause);}}
const url=computed(()=>presentation.value?.svg?`data:image/svg+xml;charset=utf-8,${encodeURIComponent(presentation.value.svg)}`:'');
const message=computed(()=>explain.error||error.value||(explain.busy?'计算中…':explain.job?.status==='cancelled'?'解释已取消。':!explain.selected?'请先在模型页训练，再选择该模型。':!explain.supported?'这一版不算 SHAP':presentation.value?.message||'选择已训练模型后计算，这里把 17 特征 SHAP 经数值雅可比回传到 8 个设计变量。'));
</script>
<template>
  <section class="explainability-layout" aria-label="贡献排序">
    <div class="explainability-toolbar"><label for="explain-model">解释模型</label><select id="explain-model" v-model="explain.selectedId" aria-label="解释模型"><option v-if="!explain.models.records.length" value=""></option><option v-for="model in explain.models.records" :key="model.model_id" :value="model.model_id">{{ explain.models.displayName(model) }}</option></select><label for="explain-chart">图表</label><select id="explain-chart" v-model="explain.chart" aria-label="图表类型"><option v-for="chart in explanationCharts" :key="chart">{{ chart }}</option></select><button class="primary-button" :disabled="!explain.supported||explain.busy" :title="!explain.selected?'请先在模型页训练，再选择该模型。':!explain.supported?'这一版不算 SHAP':''" @click="explain.start">计算解释</button><span title="L-x：第 x 面透镜；r：前表面曲率半径；d：透镜厚度">L-x：第几面透镜　r：曲率半径　d：厚度</span></div>
    <div class="explainability-result-pane"><div ref="canvas" class="explainability-result-canvas"><img v-if="url&&!error" :src="url" :alt="renderedChart"/><p v-else :role="explain.error||error?'alert':undefined">{{ message }}</p></div><p v-if="url&&presentation?.summary&&!error" class="explainability-result-summary">{{ presentation.summary }}</p></div>
  </section>
</template>
