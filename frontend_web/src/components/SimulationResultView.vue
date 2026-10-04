<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { apiRequest } from '../api/http.js';
import { useSimulationStore } from '../stores/simulation.js';
import { emptyLabels, type ResultKind, type SimulationPresentation } from '../domain/simulation-results.js';
import SimulationPlot from './SimulationPlot.vue';
const SimulationRay3D = defineAsyncComponent(() => import('./SimulationRay3D.vue'));
const props = defineProps<{ kind: ResultKind }>();
const simulation=useSimulationStore(), presentation=shallowRef<SimulationPresentation|null>(null);
const loading=ref(false), error=ref(''), showText=ref(false), zoom=ref(false), retry=ref(0);
const chart=ref<{ exportPng(): Promise<void> }>();
const labels=computed(()=>presentation.value?.labels??emptyLabels[props.kind]);
const source=computed(()=>simulation.resultStale && presentation.value?'当前系统已修改 · 需重新计算':presentation.value?'已计算':loading.value?'正在读取结果…':'等待计算结果');
const message=computed(()=>error.value || (loading.value?'正在读取结果…':presentation.value?.plot.message??(presentation.value?'正式结果已返回，但当前页暂未找到可绘制的数据。':'提交计算后，这里显示对应结果。')));
let sequence=0,controller:AbortController|undefined;
watch([()=>props.kind,()=>simulation.activeJobId,()=>simulation.job?.status,()=>JSON.stringify(simulation.observation),retry],async()=>{
  const current=++sequence;controller?.abort();presentation.value=null;error.value='';loading.value=false;
  if(!simulation.activeJobId || simulation.job?.status!=='completed')return;
  controller=new AbortController();loading.value=true;
  try { const response=await apiRequest<SimulationPresentation>(`/api/v1/simulation/jobs/${simulation.activeJobId}/presentation`,{method:'POST',body:{project:simulation.submittedSnapshot??simulation.project,kind:props.kind,observation:simulation.observation},signal:controller.signal,timeoutMs:120000});if(current===sequence)presentation.value=response.data; }
  catch(cause){if(current===sequence)error.value=cause instanceof Error?cause.message:String(cause);}
  finally{if(current===sequence)loading.value=false;}
},{immediate:true});
onBeforeUnmount(()=>{sequence++;controller?.abort();});
async function exportPlot(){try{await chart.value?.exportPng();}catch(cause){error.value=cause instanceof Error?cause.message:String(cause);}}
</script>
<template>
  <section class="simulation-result-document" aria-label="仿真结果">
    <header class="simulation-result-header" :class="{ 'with-related': kind === 'ray_layout' }"><span v-for="label in labels" :key="label" class="simulation-result-metric">{{ label }}</span><span class="simulation-result-source" :class="{stale:simulation.resultStale && presentation,completed:presentation}" role="status">{{ source }}</span><button v-if="props.kind==='ray_layout'" class="simulation-result-related" @click="$emit('related', 'layout_3d')">3D 视图</button></header>
    <div class="simulation-result-workspace" :class="{populated:presentation && presentation.plot.kind!=='empty'}">
      <SimulationRay3D v-if="presentation && presentation.plot.kind==='raytrace3d'" ref="chart" :plot="presentation.plot" />
      <SimulationPlot v-else-if="presentation && ['scatter','raytrace','raytrace_section','heatmap','beam_match'].includes(presentation.plot.kind)" ref="chart" :plot="presentation.plot" />
      <div v-else class="simulation-result-placeholder"><p>{{ message }}</p><button v-if="error" @click="retry++">重新读取结果</button></div>
    </div>
    <footer class="simulation-result-actions"><button @click="showText=!showText">文字</button><button @click="zoom=true">放大</button><button :disabled="!presentation || presentation.plot.kind==='empty'" @click="exportPlot">导出</button></footer>
    <p v-if="showText" class="simulation-result-details">{{ presentation?.details || message }}</p>
    <Teleport to="body"><div v-if="zoom" class="simulation-zoom-overlay" @click.self="zoom=false"><section class="simulation-zoom-window" role="dialog" aria-modal="true" aria-label="仿真结果 · 独立窗口"><header><strong>仿真结果 · 独立窗口</strong><button @click="zoom=false" aria-label="关闭结果窗口">×</button></header><SimulationRay3D v-if="presentation?.plot.kind==='raytrace3d'" :plot="presentation.plot" /><SimulationPlot v-else-if="presentation && presentation.plot.kind!=='empty'" :plot="presentation.plot" /><p v-else>{{ message }}</p></section></div></Teleport>
  </section>
</template>
