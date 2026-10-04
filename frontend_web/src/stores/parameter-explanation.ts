import {defineStore} from 'pinia';
import {computed,reactive,ref,watch} from 'vue';
import {useModelsStore} from './models.js';
import {useJobsStore} from './jobs.js';
import {submitParameterExplanation} from '../api/explainability.js';
import {useSimulationStore} from './simulation.js';
import {readOptimizationPresentation,type OptimizationVariable} from '../api/optimization.js';
const KEY='optical.parameter-explanation.v1',terminal=new Set(['completed','failed','cancelled']);
export const useParameterExplanationStore=defineStore('parameter-explanation',()=>{
  const models=useModelsStore(),jobs=useJobsStore();
  const selectedId=ref(''),view=ref(0),jobByModel=reactive<Record<string,string>>({}),errorByModel=reactive<Record<string,string>>({}),submitting=reactive<Record<string,boolean>>({});
  const featuresByModel=reactive<Record<string,string[]>>({}),renderRevision=ref(0);
  const simulation=useSimulationStore(),variables=ref<OptimizationVariable[]>([]),search=ref(''),group=ref('全部'),selectedFeature=ref(''),plottedFeature=ref(''),variableError=ref('');let variableVersion=0;
  try{const saved=JSON.parse(localStorage.getItem(KEY)||'{}');selectedId.value=saved.selectedId||'';view.value=saved.view===1?1:0;selectedFeature.value=saved.selectedFeature||'';plottedFeature.value=saved.plottedFeature||'';Object.assign(jobByModel,saved.jobs||{});Object.assign(featuresByModel,saved.features||{});}catch{/* Native defaults. */}
  const selected=computed(()=>models.records.find(m=>m.model_id===selectedId.value)??null);
  const supported=computed(()=>!!selected.value&&!models.isSequenceModel(selected.value));
  const jobId=computed(()=>jobByModel[selectedId.value]||'');
  const job=computed(()=>jobs.jobs[jobId.value]??null);
  const busy=computed(()=>!!submitting[selectedId.value]||!!jobId.value&&!errorByModel[selectedId.value]&&(!job.value||!terminal.has(job.value.status)));
  const error=computed(()=>errorByModel[selectedId.value]||(typeof job.value?.error==='string'?job.value.error:(job.value?.error as {message?:string}|undefined)?.message)||'');
  const features=computed(()=>featuresByModel[selectedId.value]??null);
  const filtered=computed(()=>variables.value.filter(row=>(group.value==='全部'||row.group===group.value)&&row.label.toLowerCase().includes(search.value.toLowerCase())));
  watch([selectedId,view,jobByModel,featuresByModel,selectedFeature,plottedFeature],()=>{try{localStorage.setItem(KEY,JSON.stringify({selectedId:selectedId.value,view:view.value,jobs:jobByModel,features:featuresByModel,selectedFeature:selectedFeature.value,plottedFeature:plottedFeature.value}));}catch{/* Storage can be unavailable. */}},{deep:true});
  watch(()=>models.records,()=>{if(!models.loaded)return;if(!models.records.some(m=>m.model_id===selectedId.value))selectedId.value=models.records[0]?.model_id||'';},{immediate:true});
  watch(jobId,async id=>{if(!id||jobs.jobs[id])return;const model=selectedId.value;await jobs.track(id);if(!jobs.jobs[id])errorByModel[model]=jobs.error||'无法读取解释任务，请重新计算。';},{immediate:true});
  async function start(){
    const model=selected.value;if(!model||!supported.value||busy.value)return;
    if(job.value?.status==='completed'&&!error.value){plottedFeature.value=selectedFeature.value;delete featuresByModel[model.model_id];renderRevision.value++;return;}
    view.value=0;plottedFeature.value=selectedFeature.value;
    submitting[model.model_id]=true;errorByModel[model.model_id]='';
    try{const id=await submitParameterExplanation(model.model_id,model.design_variable_paths||[]);jobByModel[model.model_id]=id;delete featuresByModel[model.model_id];await jobs.trackSubmittedJob(id,'explainability');if(!jobs.jobs[id])errorByModel[model.model_id]=jobs.error||'解释任务已提交，暂时无法读取状态。';}
    catch(cause){errorByModel[model.model_id]=cause instanceof Error?cause.message:String(cause);}
    finally{submitting[model.model_id]=false;}
  }
  function selectFeatures(keys:string[]){featuresByModel[selectedId.value]=keys.slice(0,3);}
  async function refreshVariables(){const token=++variableVersion,context=simulation.contextId;variableError.value='';try{const result=await readOptimizationPresentation(await simulation.teachingEditorProject());if(token===variableVersion&&context===simulation.contextId){variables.value=result.variables;if(selectedFeature.value&&!variables.value.some(row=>row.path===selectedFeature.value))selectedFeature.value='';}}catch(cause){if(token===variableVersion)variableError.value=cause instanceof Error?cause.message:String(cause);}}
  return {models,selectedId,view,selected,supported,jobId,job,busy,error,features,renderRevision,start,selectFeatures,search,group,selectedFeature,plottedFeature,filtered,variableError,refreshVariables};
});
