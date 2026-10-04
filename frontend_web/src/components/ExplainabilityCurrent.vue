<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,ref,watch} from 'vue';
import {useCurrentExplanationStore} from '../stores/current-explanation.js';
import {readCurrentPresentation,type CurrentExplanationPresentation} from '../api/explainability.js';
import ExplanationFormula from './ExplanationFormula.vue';
const explain=useCurrentExplanationStore(),canvas=ref<HTMLDivElement>(),presentation=ref<CurrentExplanationPresentation|null>(null),error=ref('');
const plotReady=ref(false);
const size=ref({width:900,height:400});let observer:ResizeObserver|undefined,timer:ReturnType<typeof setTimeout>|undefined,version=0;
onMounted(()=>{
  observer=new ResizeObserver(([entry])=>{if(entry&&entry.contentRect.width>0&&entry.contentRect.height>0)size.value={width:Math.max(160,Math.min(4096,Math.round(entry.contentRect.width))),height:Math.max(100,Math.min(4096,Math.round(entry.contentRect.height)))};});
  if(canvas.value)observer.observe(canvas.value);
});
onBeforeUnmount(()=>{version++;observer?.disconnect();clearTimeout(timer);});
watch(()=>explain.jobId,()=>{presentation.value=null;});
watch([()=>explain.jobId,()=>explain.job?.status,()=>explain.renderRevision,()=>explain.verified,size],()=>{
  clearTimeout(timer);const token=++version;error.value='';
  if(explain.job?.status!=='completed'){presentation.value=null;return;}
  timer=setTimeout(()=>void load(token),80);
},{deep:true,immediate:true});
async function load(token:number){try{const result=await readCurrentPresentation(explain.jobId,size.value.width,size.value.height,explain.verified);if(token===version)presentation.value=result;}catch(cause){if(token===version)error.value=cause instanceof Error?cause.message:String(cause);}}
const url=computed(()=>presentation.value?.svg?`data:image/svg+xml;charset=utf-8,${encodeURIComponent(presentation.value.svg)}`:'');
watch(url,value=>{if(value)plotReady.value=true;});
const message=computed(()=>explain.error||error.value||(explain.busy?'正在计算解释…':explain.job?.status==='cancelled'?'解释已取消。':!explain.selected?'请先在模型页训练，再选择该模型。':!explain.supported?'这一版不算 SHAP':presentation.value?.message||'请先在模型页训练，再选择该模型。'));
const summary=computed(()=>!explain.error&&!error.value?presentation.value?.interpretation:null);
const sections=['模型分析','物理联系','下一步'];
</script>
<template>
  <section class="explainability-layout explainability-current-layout" aria-label="当前系统验证">
    <div class="explainability-toolbar current-explanation-toolbar"><label for="current-explain-model">解释模型</label><select id="current-explain-model" v-model="explain.selectedId" aria-label="解释模型"><option v-if="!explain.models.records.length" value=""></option><option v-for="model in explain.models.records" :key="model.model_id" :value="model.model_id">{{ explain.models.displayName(model) }}</option></select><button class="primary-button" :disabled="!explain.supported||explain.busy" :title="!explain.selected?'请先在模型页训练，再选择该模型。':!explain.supported?'这一版不算 SHAP':''" @click="explain.start">计算解释</button><span title="L-x：第 x 面透镜；r：前表面曲率半径；d：透镜厚度">L-x：第几面透镜　r：曲率半径　d：厚度</span></div>
    <div class="explainability-result-pane" :class="{'is-placeholder':!plotReady}"><div ref="canvas" class="explainability-result-canvas" :class="{'is-placeholder':!plotReady}"><img v-if="url&&!error&&!explain.error" :src="url" alt="当前系统瀑布图"/><p v-else :role="explain.error||error?'alert':undefined">{{ message }}</p></div><p v-if="url&&presentation?.summary&&!error" class="explainability-result-summary">{{ presentation.summary }}</p></div>
    <section v-if="summary" class="current-explanation-summary" aria-label="当前系统解释说明">
      <div class="current-explanation-tabs" role="tablist" aria-label="解释说明"><button v-for="(name,index) in sections" :id="`current-summary-tab-${index}`" :key="name" role="tab" :aria-selected="explain.section===index" :aria-controls="`current-summary-${index}`" @click="explain.section=index">{{ name }}</button></div>
      <div class="current-explanation-stack">
        <div id="current-summary-0" :class="{'is-hidden':explain.section!==0}" :inert="explain.section!==0" :aria-hidden="explain.section!==0" role="tabpanel" aria-labelledby="current-summary-tab-0" class="current-explanation-body">{{ summary.model_text }}</div>
        <div id="current-summary-1" :class="{'is-hidden':explain.section!==1}" :inert="explain.section!==1" :aria-hidden="explain.section!==1" role="tabpanel" aria-labelledby="current-summary-tab-1" class="current-explanation-physics"><h2>{{ summary.formula_title }}</h2><div v-if="summary.formula_steps.length" class="current-explanation-equations"><template v-for="(step,index) in summary.formula_steps" :key="index"><h3>公式 {{ index+1 }} · {{ step.stage }}</h3><ExplanationFormula :image="step.image" :latex="step.latex"/></template></div><div class="current-explanation-details" v-html="summary.physics_html"></div></div>
        <div id="current-summary-2" :class="{'is-hidden':explain.section!==2}" :inert="explain.section!==2" :aria-hidden="explain.section!==2" role="tabpanel" aria-labelledby="current-summary-tab-2" class="current-explanation-body">{{ summary.next_text }}</div>
      </div>
    </section>
  </section>
</template>
