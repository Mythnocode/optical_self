import {defineStore} from 'pinia';
import {computed,reactive,ref,watch} from 'vue';
import {useModelsStore} from './models.js';
import {useJobsStore} from './jobs.js';
import {useSimulationStore} from './simulation.js';
import {submitCurrentExplanation} from '../api/explainability.js';

const KEY='optical.current-explanation.v1';
const terminal=new Set(['completed','failed','cancelled']);
interface Submitted {id:string;context:string;signature:string}
interface Failure {message:string;context:string;signature:string}
export const useCurrentExplanationStore=defineStore('current-explanation',()=>{
  const models=useModelsStore(),jobs=useJobsStore(),simulation=useSimulationStore();
  const selectedId=ref(''),railSelectedId=ref(''),section=ref(0),renderRevision=ref(0);
  const submitted=reactive<Record<string,Submitted>>({}),failures=reactive<Record<string,Failure>>({}),submitting=reactive<Record<string,boolean>>({});
  try {
    const saved=JSON.parse(localStorage.getItem(KEY)||'{}');
    selectedId.value=saved.selectedId||'';
    section.value=[0,1,2].includes(saved.section)?saved.section:0;
    Object.assign(submitted,saved.jobs||{});
  } catch {/* Native defaults. */}
  const signature=computed(()=>simulation.calculationSignature());
  const selected=computed(()=>models.records.find(model=>model.model_id===selectedId.value)??null);
  const supported=computed(()=>!!selected.value&&!models.isSequenceModel(selected.value));
  const sourceMatches=(source:{context:string;signature:string}|undefined)=>source?.context===simulation.contextId&&source.signature===signature.value;
  const jobId=computed(()=>sourceMatches(submitted[selectedId.value])?submitted[selectedId.value]!.id:'');
  const job=computed(()=>jobs.jobs[jobId.value]??null);
  const error=computed(()=>sourceMatches(failures[selectedId.value])?failures[selectedId.value]!.message:
    (typeof job.value?.error==='string'?job.value.error:(job.value?.error as {message?:string}|undefined)?.message)||'');
  const busy=computed(()=>!!submitting[selectedId.value]||!!jobId.value&&!error.value&&(!job.value||!terminal.has(job.value.status)));
  // A result for a previous optical prescription does not confirm the current one.
  const verified=computed(()=>!!simulation.result&&!simulation.resultStale&&simulation.job?.status==='completed');
  watch([selectedId,section,submitted],()=>{
    try {localStorage.setItem(KEY,JSON.stringify({selectedId:selectedId.value,section:section.value,jobs:submitted}));}
    catch {/* Storage can be unavailable. */}
  },{deep:true});
  watch(()=>models.records,()=>{
    if(models.loaded&&!models.records.some(model=>model.model_id===selectedId.value))selectedId.value=models.records[0]?.model_id||'';
  },{immediate:true});
  watch(jobId,id=>{if(id&&!jobs.jobs[id])void restore(id);},{immediate:true});
  async function restore(id:string){
    const model=selectedId.value,source=submitted[model];
    await jobs.track(id);
    if(!jobs.jobs[id]&&source?.id===id)failures[model]={...source,message:jobs.error||'无法读取解释任务，请重新计算。'};
  }
  async function start(){
    const model=selected.value;
    if(!model||!supported.value||busy.value)return;
    if(job.value?.status==='completed'&&!error.value){section.value=0;renderRevision.value++;return;}
    const id=model.model_id,context=simulation.contextId,captured=signature.value;
    submitting[id]=true;delete failures[id];
    try {
      const project=await simulation.teachingEditorProject();
      if(context!==simulation.contextId||captured!==signature.value)throw new Error('当前镜头已变化，请重新计算解释。');
      const task=await submitCurrentExplanation(id,project);
      submitted[id]={id:task,context,signature:captured};section.value=0;
      await jobs.trackSubmittedJob(task,'explainability');
      if(!jobs.jobs[task])failures[id]={context,signature:captured,message:jobs.error||'解释任务已提交，暂时无法读取状态。'};
    } catch(cause){failures[id]={context,signature:captured,message:cause instanceof Error?cause.message:String(cause)};}
    finally{submitting[id]=false;}
  }
  function selectFromRail(id:string){selectedId.value=id;railSelectedId.value=id;}
  return {models,selectedId,railSelectedId,section,renderRevision,selected,supported,jobId,job,busy,error,verified,start,selectFromRail};
});
