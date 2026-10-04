import {defineStore} from 'pinia';
import {computed,reactive,ref,watch} from 'vue';
import {useSimulationStore} from './simulation.js';
import {useOptimizationStore} from './optimization.js';
import {useJobsStore} from './jobs.js';
import {prepareScan,submitScan,type ScanConfig} from '../api/scan.js';
import type {OptimizationVariable} from '../api/optimization.js';
const KEY='optical.scan.v1';
export const useScanStore=defineStore('scan',()=>{
  const simulation=useSimulationStore(),optimization=useOptimizationStore(),jobs=useJobsStore();
  const config=reactive<ScanConfig>({scan_mode:'一维扫描',response:'耦合效率',scale:'线性采样',points:21});
  const rows=ref<OptimizationVariable[]>([]),rangeSelection=ref(''),rangeContext=ref(''),jobId=ref(''),error=ref(''),submitting=ref(false),trackingFailed=ref(false),submittedContext=ref(''),submittedSignature=ref('');
  try{const saved=JSON.parse(localStorage.getItem(KEY)||'{}');Object.assign(config,saved.config||{});rows.value=saved.rows||[];rangeSelection.value=saved.rangeSelection||'';rangeContext.value=saved.rangeContext||'';jobId.value=saved.jobId||'';submittedContext.value=saved.submittedContext||'';submittedSignature.value=saved.submittedSignature||'';}catch{/* Use original defaults if preferences are invalid. */}
  const job=computed(()=>jobs.jobs[jobId.value]??null);
  const busy=computed(()=>submitting.value||!!(jobId.value&&!trackingFailed.value&&(!job.value||!['completed','failed','cancelled'].includes(job.value.status))));
  const stale=computed(()=>!!jobId.value&&(submittedContext.value!==simulation.contextId||submittedSignature.value!==simulation.calculationSignature()));
  watch([()=>optimization.presentation,()=>optimization.selected.join('|')],()=>{
    if(!optimization.presentation)return;
    const catalog=optimization.presentation.variables.filter(row=>optimization.selected.includes(row.path)).slice(0,2),selection=optimization.selected.join('|');
    if(selection!==rangeSelection.value||simulation.contextId!==rangeContext.value)rows.value=catalog.map(row=>({...row}));
    else{const previous=new Map(rows.value.map(row=>[row.path,row]));rows.value=catalog.map(row=>previous.get(row.path)??{...row});}
    rangeSelection.value=selection;rangeContext.value=simulation.contextId;
  },{immediate:true});
  watch([config,rows,rangeSelection,rangeContext,jobId,submittedContext,submittedSignature],()=>{try{localStorage.setItem(KEY,JSON.stringify({config,rows:rows.value,rangeSelection:rangeSelection.value,rangeContext:rangeContext.value,jobId:jobId.value,submittedContext:submittedContext.value,submittedSignature:submittedSignature.value}));}catch{error.value='扫描设置未能保存。';}},{deep:true});
  if(jobId.value)void restoreJob();
  async function restoreJob():Promise<void>{const id=jobId.value;try{await jobs.track(id);if(!jobs.jobs[id])throw new Error(jobs.error||'扫描任务未能恢复，请重新提交。');}catch(cause){if(id===jobId.value){trackingFailed.value=true;error.value=message(cause);}}}
  async function start():Promise<void>{
    if(busy.value)return;submitting.value=true;error.value='';
    const context=simulation.contextId,signature=simulation.calculationSignature(),capturedConfig=JSON.parse(JSON.stringify(config)) as ScanConfig,capturedRows=JSON.parse(JSON.stringify(rows.value)) as OptimizationVariable[];
    try{
      const source=await simulation.teachingRequest();source.request_id=crypto.randomUUID();
      const payload=await prepareScan(source,capturedConfig,capturedRows);
      if(context!==simulation.contextId||signature!==simulation.calculationSignature())throw new Error('当前仿真设置已变化，请重新提交扫描。');
      const id=await submitScan(payload);jobId.value=id;submittedContext.value=context;submittedSignature.value=signature;trackingFailed.value=false;
      await jobs.trackSubmittedJob(id,'scan');
    }catch(cause){error.value=message(cause);}finally{submitting.value=false;}
  }
  return {config,rows,jobId,job,busy,error,stale,submitting,start};
});
function message(cause:unknown):string{return cause instanceof Error?cause.message:String(cause);}
