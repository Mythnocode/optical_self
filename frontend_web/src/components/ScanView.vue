<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,ref,watch} from 'vue';
import {useScanStore} from '../stores/scan.js';
import {readScanResult,type ScanPresentation} from '../api/scan.js';
import SimulationNumber from './SimulationNumber.vue';
import SimulationPlot from './SimulationPlot.vue';
const scan=useScanStore(),canvas=ref<HTMLDivElement>(),presentation=ref<ScanPresentation|null>(null),presentationError=ref('');
const size=ref({width:900,height:400});let observer:ResizeObserver|undefined,timer:ReturnType<typeof setTimeout>|undefined,version=0;
onMounted(()=>{observer=new ResizeObserver(([entry])=>{if(entry&&entry.contentRect.width>0&&entry.contentRect.height>0)size.value={width:Math.max(160,Math.min(4096,Math.round(entry.contentRect.width))),height:Math.max(100,Math.min(4096,Math.round(entry.contentRect.height)))};});if(canvas.value)observer.observe(canvas.value);});
onBeforeUnmount(()=>{version++;observer?.disconnect();clearTimeout(timer);});
watch([()=>scan.jobId,()=>scan.job?.status,size],()=>{clearTimeout(timer);const token=++version;if(scan.job?.status!=='completed'){presentation.value=null;return;}timer=setTimeout(()=>void load(token),80);},{deep:true,immediate:true});
async function load(token:number){try{const result=await readScanResult(scan.jobId,size.value.width,size.value.height);if(token===version){presentation.value=result;presentationError.value='';}}catch(cause){if(token===version)presentationError.value=cause instanceof Error?cause.message:String(cause);}}
const progress=computed(()=>Math.round(Math.max(0,Math.min(1,scan.job?.progress||0))*100));
const status=computed(()=>({queued:'排队中',running:'扫描中',completed:'扫描完成',failed:'扫描失败',cancelled:'扫描已取消'}[scan.job?.status||'']||'扫描尚未开始'));
const failure=computed(()=>scan.error||presentationError.value||(typeof scan.job?.error==='string'?scan.job.error:(scan.job?.error as {message?:string}|undefined)?.message)||'');
const plotUrl=computed(()=>presentation.value?.svg?`data:image/svg+xml;charset=utf-8,${encodeURIComponent(presentation.value.svg)}`:'');
const message=computed(()=>failure.value||(scan.busy?'正在扫描…':scan.job?.status==='cancelled'?'扫描已取消':presentation.value?.message||'勾选 1～2 个变量并运行后，这里显示响应曲线。'));
const hasResult=computed(()=>!scan.submitting&&!failure.value&&!!(plotUrl.value||presentation.value?.plot));
</script>
<template>
  <section class="scan-layout" :class="{'has-job':!!scan.jobId,'has-result':hasResult}" aria-label="扫描">
    <section class="scan-settings"><h2>设置</h2>
      <div class="scan-fields">
        <label><span>模式</span><select v-model="scan.config.scan_mode" aria-label="扫描模式"><option>一维扫描</option><option>二维扫描</option><option>多参数采样</option></select></label>
        <label><span>响应量</span><select v-model="scan.config.response" aria-label="扫描响应量"><option>耦合效率</option><option>RMS 光斑</option><option>Strehl</option><option>边缘功率</option></select></label>
        <label class="scan-scale"><span>采样尺度</span><select v-model="scan.config.scale" aria-label="扫描采样尺度"><option>线性采样</option><option>对数采样</option><option title="当前后端尚未实现自适应加密">自适应加密</option></select></label>
        <label class="scan-points"><span>采样点数</span><SimulationNumber v-model="scan.config.points" label="扫描采样点数" integer :min="5" :max="401" /></label>
        <div class="scan-variable-summary"><span>变量</span><span>{{ scan.rows.map(row=>row.label).join('、')||'（未勾选）' }}</span></div>
      </div>
      <div class="scan-range-table"><table><colgroup><col v-if="scan.rows.length" class="scan-row-number"/><col/><col/><col/></colgroup><thead><tr><th v-if="scan.rows.length"></th><th>参数</th><th>最小</th><th>最大</th></tr></thead><tbody><tr v-for="(row,i) in scan.rows" :key="row.path"><th>{{ i+1 }}</th><td>{{ row.label.split(' / ').at(-1) }}</td><td><input v-model="row.lower" :aria-label="`${row.label} 扫描最小值`" /></td><td><input v-model="row.upper" :aria-label="`${row.label} 扫描最大值`" /></td></tr></tbody></table></div>
      <button class="scan-run primary-button" :disabled="!scan.rows.length||scan.busy" :title="scan.rows.length?'':'请先在左栏勾选 1～2 个变量。'" @click="scan.start">运行</button>
      <div v-if="scan.jobId&&!scan.submitting" class="scan-progress optimization-progress" :class="{complete:scan.job?.status==='completed',failed:scan.job?.status==='failed',cancelled:scan.job?.status==='cancelled'}"><span>{{ status }} {{ progress }}%</span><progress :value="progress" max="100"></progress></div>
    </section>
    <div class="scan-result-pane" :class="{'has-result':hasResult}">
      <div ref="canvas" class="scan-result-canvas"><p v-if="!hasResult" :role="failure?'alert':undefined">{{ message }}</p><img v-else-if="plotUrl" :src="plotUrl" alt="正式参数扫描响应曲线" /><SimulationPlot v-else-if="presentation?.plot" :plot="presentation.plot" smooth-heatmap /></div>
      <p v-if="hasResult&&presentation?.summary" class="optimization-plot-summary">{{ presentation.summary }}</p>
    </div>
    <p v-if="scan.stale" class="scan-stale">当前仿真设置已变化，以上结果属于提交时的系统。</p>
  </section>
</template>
