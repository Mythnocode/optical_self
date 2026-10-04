import {defineStore} from 'pinia';
import {computed,reactive,ref,watch} from 'vue';
import {useModelsStore} from './models.js';
import {useJobsStore} from './jobs.js';
import {submitDesignExplanation,explanationCharts} from '../api/explainability.js';

const KEY='optical.explainability.v1';
const terminal=new Set(['completed','failed','cancelled']);
export const useExplainabilityStore=defineStore('explainability',()=>{
  const models=useModelsStore(),jobs=useJobsStore();
  const selectedId=ref(''),railSelectedId=ref(''),chart=ref(explanationCharts[0]!),jobByModel=reactive<Record<string,string>>({}),errorByModel=reactive<Record<string,string>>({}),submitting=reactive<Record<string,boolean>>({});
  try{const saved=JSON.parse(localStorage.getItem(KEY)||'{}');selectedId.value=saved.selectedId||'';chart.value=explanationCharts.includes(saved.chart)?saved.chart:explanationCharts[0]!;Object.assign(jobByModel,saved.jobs||{});}catch{/* Original defaults. */}
  const selected=computed(()=>models.records.find(m=>m.model_id===selectedId.value)??null);
  const supported=computed(()=>!!selected.value&&!models.isSequenceModel(selected.value));
  const jobId=computed(()=>jobByModel[selectedId.value]||'');
  const job=computed(()=>jobs.jobs[jobId.value]??null);
  const busy=computed(()=>!!submitting[selectedId.value]||!!jobId.value&&!errorByModel[selectedId.value]&&(!job.value||!terminal.has(job.value.status)));
  const error=computed(()=>errorByModel[selectedId.value]||(typeof job.value?.error==='string'?job.value.error:(job.value?.error as {message?:string}|undefined)?.message)||'');
  watch([selectedId,chart,jobByModel],()=>{try{localStorage.setItem(KEY,JSON.stringify({selectedId:selectedId.value,chart:chart.value,jobs:jobByModel}));}catch{/* Storage can be unavailable. */}},{deep:true});
  watch(()=>models.records,()=>{if(!models.loaded)return;if(!models.records.some(m=>m.model_id===selectedId.value))selectedId.value=models.records[0]?.model_id||'';},{immediate:true});
  async function restore(id:string){if(!id||jobs.jobs[id])return;await jobs.track(id);if(!jobs.jobs[id]){const model=Object.keys(jobByModel).find(key=>jobByModel[key]===id);if(model)errorByModel[model]=jobs.error||'无法读取解释任务，请重新计算。';}}
  watch(jobId,id=>{void restore(id);},{immediate:true});
  async function start(){
    const model=selectedId.value;if(!supported.value||busy.value)return;
    submitting[model]=true;errorByModel[model]='';
    try{const id=await submitDesignExplanation(model);jobByModel[model]=id;await jobs.trackSubmittedJob(id,'explainability');if(!jobs.jobs[id])errorByModel[model]=jobs.error||'解释任务已提交，暂时无法读取状态。';}
    catch(cause){errorByModel[model]=cause instanceof Error?cause.message:String(cause);}
    finally{submitting[model]=false;}
  }
  function selectFromRail(id:string){selectedId.value=id;railSelectedId.value=id;}
  return {models,selectedId,railSelectedId,selectFromRail,chart,selected,supported,jobId,job,busy,error,start};
});
