<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref,watch} from 'vue';
import {useParameterExplanationStore} from '../stores/parameter-explanation.js';
import {readParameterPresentation,type ParameterPresentation} from '../api/explainability.js';
import ExplanationFormula from './ExplanationFormula.vue';
const explain=useParameterExplanationStore(),canvas=ref<HTMLDivElement>(),presentation=ref<ParameterPresentation|null>(null),error=ref('');
const size=ref({width:900,height:400});let observer:ResizeObserver|undefined,timer:ReturnType<typeof setTimeout>|undefined,version=0;
onMounted(()=>{observer=new ResizeObserver(([entry])=>{if(entry&&entry.contentRect.width>0&&entry.contentRect.height>0)size.value={width:Math.max(160,Math.min(4096,Math.round(entry.contentRect.width))),height:Math.max(100,Math.min(4096,Math.round(entry.contentRect.height)))};});if(canvas.value)observer.observe(canvas.value);});
onBeforeUnmount(()=>{version++;observer?.disconnect();clearTimeout(timer);});
watch(()=>explain.jobId,()=>{presentation.value=null;});
watch([()=>explain.jobId,()=>explain.job?.status,()=>explain.features,()=>explain.plottedFeature,()=>explain.renderRevision,size],()=>{clearTimeout(timer);const token=++version;error.value='';if(explain.job?.status!=='completed'){presentation.value=null;return;}timer=setTimeout(()=>void load(token),80);},{deep:true,immediate:true});
async function load(token:number){try{const result=await readParameterPresentation(explain.jobId,explain.features,size.value.width,size.value.height,explain.plottedFeature);if(token===version)presentation.value=result;}catch(cause){if(token===version)error.value=cause instanceof Error?cause.message:String(cause);}}
const url=computed(()=>presentation.value?.svg?`data:image/svg+xml;charset=utf-8,${encodeURIComponent(presentation.value.svg)}`:'');
const message=computed(()=>explain.error||error.value||(explain.busy?'正在计算解释…':explain.job?.status==='cancelled'?'解释已取消。':!explain.selected?'请先在模型页训练，再选择该模型。':!explain.supported?'这一版不算 SHAP':presentation.value?.message||'暂无解释结果。'));
const hasRanking=computed(()=>!!presentation.value?.ranking.length&&!explain.error&&!error.value);
const selectedKeys=computed(()=>explain.features??presentation.value?.selected_keys??[]);
function toggleFeature(key:string,checked:boolean){const keys=selectedKeys.value;if(checked&&keys.length>=3)return;explain.selectFeatures(checked?[...keys,key]:keys.filter(item=>item!==key));}
function onFeature(event:Event,key:string){const input=event.target as HTMLInputElement;toggleFeature(key,input.checked);input.checked=selectedKeys.value.includes(key);}
function regenerate(){clearTimeout(timer);void load(++version);}
</script>
<template>
  <section class="explainability-layout explainability-parameter-layout" aria-label="物理链路">
    <div class="explainability-toolbar parameter-toolbar"><label for="parameter-model">解释模型</label><select id="parameter-model" v-model="explain.selectedId" aria-label="解释模型"><option v-if="!explain.models.records.length" value=""></option><option v-for="model in explain.models.records" :key="model.model_id" :value="model.model_id">{{ explain.models.displayName(model) }}</option></select><button class="primary-button" :disabled="!explain.supported||explain.busy" :title="!explain.selected?'请先在模型页训练，再选择该模型。':!explain.supported?'这一版不算 SHAP':''" @click="explain.start">计算解释</button><button class="parameter-view-button" :aria-pressed="explain.view===0" @click="explain.view=0">单参数贡献图</button><button class="parameter-view-button" :aria-pressed="explain.view===1" @click="explain.view=1">物理链路</button><span title="L-x：第 x 面透镜；r：前表面曲率半径；d：透镜厚度">L-x：第几面透镜　r：曲率半径　d：厚度</span></div>
    <div v-show="explain.view===0" class="explainability-result-pane"><div ref="canvas" class="explainability-result-canvas"><img v-if="url&&!error&&!explain.error" :src="url" alt="单参数 SHAP 依赖"/><p v-else :role="explain.error||error?'alert':undefined">{{ message }}</p></div><p v-if="url&&presentation?.summary&&!error" class="explainability-result-summary">{{ presentation.summary }}</p></div>
    <div v-if="explain.view===1&&hasRanking&&presentation" class="explanation-chain-scroll" role="region" tabindex="0" aria-label="公式链路滚动区域">
      <section class="explanation-selection-card"><header><h2>从贡献排序选择关键参数</h2><button @click="regenerate">生成物理链路</button></header><div class="explanation-feature-picker" role="group" aria-label="关键参数选择"><label v-for="row in presentation.ranking" :key="row.feature"><input type="checkbox" :checked="selectedKeys.includes(row.feature)" @change="onFeature($event,row.feature)"/><span>{{ row.text }}</span></label></div></section>
      <section class="explanation-chain-card"><h2>{{ presentation.chain.title }}</h2><div v-for="row in presentation.chain.rows" :key="row.feature" class="explanation-chain-row"><h3>参数：{{ row.name }}</h3><p class="explanation-chain-path">{{ row.path }}</p><template v-for="(step,index) in row.steps" :key="index"><h4>公式 {{ index+1 }} · {{ step.stage }}</h4><ExplanationFormula :image="step.image" :latex="step.latex"/><p v-if="index<row.steps.length-1" class="explanation-chain-arrow">↓</p></template><p v-if="row.note" class="explanation-chain-note">{{ row.note }}</p></div><div v-if="presentation.chain.overlap_image" class="explanation-chain-row"><h4>共同输出公式 · 归一化复场重叠</h4><ExplanationFormula :image="presentation.chain.overlap_image" :latex="presentation.chain.overlap_formula"/><p class="explanation-chain-note">复场重叠结果进入当前模型解释的目标输出。</p></div></section>
    </div>
    <p v-if="explain.view===1&&(error||explain.error)" class="explanation-chain-error" role="alert">{{ message }}</p>
  </section>
</template>
