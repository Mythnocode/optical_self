<script setup lang="ts">
import {computed,ref,watch,onMounted,onBeforeUnmount} from 'vue';
import {readOptimizationResult,type OptimizationResultPresentation} from '../api/optimization.js';
import {useOptimizationStore} from '../stores/optimization.js';
import {useRouter} from 'vue-router';
const optimization=useOptimizationStore(),chart=ref('过程曲线'),selected=ref(-1);
const router=useRouter();
watch(()=>optimization.jobId,()=>{selected.value=-1;chart.value='过程曲线';});
const progress=computed(()=>Math.round(Math.max(0,Math.min(1,optimization.job?.progress||0))*100));
const status=computed(()=>({queued:'排队中',running:'优化中',completed:'优化完成',failed:'优化失败',cancelled:'优化已取消'}[optimization.job?.status||'']||'优化尚未开始'));
const canvas=ref<HTMLDivElement>(),presentation=ref<OptimizationResultPresentation|null>(null),presentationError=ref('');
const size=ref({width:900,height:400});let observer:ResizeObserver|undefined,timer:ReturnType<typeof setTimeout>|undefined,version=0;
onMounted(()=>{observer=new ResizeObserver(([entry])=>{if(entry&&entry.contentRect.width>0&&entry.contentRect.height>0)size.value={width:Math.max(160,Math.min(4096,Math.round(entry.contentRect.width))),height:Math.max(100,Math.min(4096,Math.round(entry.contentRect.height)))};});if(canvas.value)observer.observe(canvas.value);});
onBeforeUnmount(()=>{version++;observer?.disconnect();clearTimeout(timer);});
watch([()=>optimization.jobId,()=>optimization.job?.status,chart,size],()=>{clearTimeout(timer);const token=++version;if(optimization.job?.status!=='completed'){presentation.value=null;return;}timer=setTimeout(()=>void loadPresentation(token),80);},{deep:true,immediate:true});
async function loadPresentation(token:number){const id=optimization.jobId;try{const next=await readOptimizationResult(id,chart.value,size.value.width,size.value.height);if(token===version){presentation.value=next;presentationError.value='';}}catch(cause){if(token===version)presentationError.value=cause instanceof Error?cause.message:String(cause);}}
const candidates=computed(()=>presentation.value?.rows??[]);
const plotUrl=computed(()=>presentation.value?.svg?`data:image/svg+xml;charset=utf-8,${encodeURIComponent(presentation.value.svg)}`:'');
const failure=computed(()=>optimization.error||(typeof optimization.job?.error==='string'?optimization.job.error:(optimization.job?.error as {message?:string}|undefined)?.message)||'');
const selectedVariables=computed(()=>candidates.value[selected.value]?.variables??{});
const canApply=computed(()=>Object.keys(selectedVariables.value).length>0&&optimization.canApply);
async function apply(){const row=candidates.value[selected.value];if(row&&canApply.value&&await optimization.applyCandidate(row.variables,row.label))await router.push('/workbench/simulation/coupling');}
</script>
<template>
  <section class="optimization-results-layout" :class="{'has-result':!!presentation?.svg}" aria-label="优化结果">
    <div v-if="optimization.jobId" class="optimization-progress" :class="{complete:optimization.job?.status==='completed'}"><span>{{ status }} {{ progress }}%</span><progress :value="progress" max="100"></progress></div>
    <select v-model="chart" class="optimization-chart-selector" aria-label="优化图表"><option>过程曲线</option><option>候选对照</option></select>
    <div class="optimization-result-pane">
      <div ref="canvas" class="optimization-result-canvas">
        <p v-if="failure||presentationError" role="alert">{{ failure||presentationError }}</p>
        <img v-else-if="plotUrl" :src="plotUrl" :alt="chart==='过程曲线'?'正式优化过程曲线':'正式优化候选对照'" />
        <p v-else>{{ presentation?.message||(chart==='候选对照'?'优化完成后，这里显示候选方案对照。':'开始优化后，这里显示过程曲线。') }}</p>
      </div>
      <p v-if="presentation?.summary" class="optimization-plot-summary">{{ presentation.summary }}</p>
    </div>
    <div class="optimization-candidates-table" :class="{'has-rows':candidates.length>0}"><table><colgroup><col v-if="candidates.length" class="optimization-row-number-column"/><col/><col/><col/><col/></colgroup><thead><tr><th v-if="candidates.length"></th><th>方案</th><th>总耦合效率</th><th>光斑半径</th><th>状态</th></tr></thead><tbody><tr v-for="(candidate,i) in candidates.slice(0,100)" :key="i" :class="{selected:selected===i}" tabindex="0" @click="selected=i" @keydown.enter="selected=i" @keydown.space.prevent="selected=i"><th class="optimization-row-number">{{ i+1 }}</th><td>{{ candidate.label }}</td><td>{{ candidate.coupling }}</td><td>{{ candidate.spot }}</td><td>{{ candidate.status }}</td></tr></tbody></table></div>
    <div class="optimization-result-footer"><button :disabled="!canApply" :title="selected<0?'先在上方候选方案表中选择一行':optimization.stale&&!optimization.canApply?'当前系统已变化，请重新优化':''" @click="apply">应用方案</button><span>{{ (optimization.validation.sourceJob===optimization.jobId?optimization.validation.status:'')||(optimization.stale?'当前仿真设置已变化，以上结果属于提交时的系统。':'') }}</span></div>
  </section>
</template>
