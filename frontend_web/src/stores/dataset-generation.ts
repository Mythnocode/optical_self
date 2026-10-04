import {defineStore} from 'pinia';
import {computed,reactive,ref,watch} from 'vue';
import {prepareGeneration,readGenerationPresentation,submitGeneration,type GenerationOptions,type GenerationPresentation} from '../api/datasets.js';
import {getJobResult} from '../api/jobs.js';
import {useSimulationStore} from './simulation.js';
import {useDatasetsStore} from './datasets.js';
import {useJobsStore} from './jobs.js';

const KEY='optical.dataset.generation.v1';
export const useDatasetGenerationStore=defineStore('dataset-generation',()=>{
  const simulation=useSimulationStore(),datasets=useDatasetsStore(),jobs=useJobsStore();
  const options=reactive<GenerationOptions>({dataset_name:'',family:'tabular',lens_count:4,include_conic:false,variable_paths:[],sample_count:50,target:'耦合损耗(dB)',sampling:'Latin Hypercube',validation_ratio:0.15,random_seed:42,precision:'257×257'});
  const presentation=ref<GenerationPresentation|null>(null),jobId=ref(''),completedDatasetId=ref(''),error=ref(''),loading=ref(false),submitting=ref(false),resultLoading=ref(false),cancelling=ref(false);
  const more=ref(false),variablesOpen=ref(false);let version=0,selectionContext='';
  try{const saved=JSON.parse(localStorage.getItem(KEY)||'{}');if(saved.options)Object.assign(options,saved.options);jobId.value=saved.jobId||'';completedDatasetId.value=saved.completedDatasetId||'';selectionContext=saved.selectionContext||'';}catch{/* Invalid saved preferences fall back to native defaults. */}
  const job=computed(()=>submitting.value?null:jobs.jobs[jobId.value]??null);
  const busy=computed(()=>submitting.value||!!(jobId.value && (!job.value||!['completed','failed','cancelled'].includes(job.value.status))));
  const status=computed(()=>submitting.value?'正在提交':cancelling.value?'正在取消':job.value?.status==='completed'?'已完成':job.value?.status==='failed'?'生成失败':job.value?.status==='cancelled'?'已取消':'生成中');
  watch([options,jobId,completedDatasetId],()=>{try{localStorage.setItem(KEY,JSON.stringify({options,jobId:jobId.value,completedDatasetId:completedDatasetId.value,selectionContext}));}catch{error.value='数据集生成记录未能保存。';}},{deep:true});
  let restoreCompletion=!!completedDatasetId.value;
  watch(()=>job.value?.status,status=>{
    if(status==='completed' && (!completedDatasetId.value || restoreCompletion&&!datasets.selectedId))void complete();
    if(status==='completed')restoreCompletion=false;
  },{immediate:true});
  if(jobId.value)void jobs.track(jobId.value).catch(cause=>{error.value=message(cause);});
  async function refreshPresentation():Promise<void>{
    const current=++version,context=simulation.contextId;loading.value=true;error.value='';
    try{
      const project=await simulation.teachingEditorProject(),next=await readGenerationPresentation(project);
      if(current!==version||context!==simulation.contextId)return;
      const same=selectionContext===context;
      options.variable_paths=next.variables.filter(item=>same?options.variable_paths.includes(item.path):item.selected).map(item=>item.path);
      selectionContext=context;presentation.value=next;
    }catch(cause){if(current===version){presentation.value=null;error.value=message(cause);}}
    finally{if(current===version)loading.value=false;}
  }
  function nextName():string{
    const numbers=datasets.items.map(item=>/^数据集(\d+)$/.exec(item.dataset_name||'')).filter(Boolean).map(item=>Number(item![1]));
    return `数据集${Math.max(0,...numbers)+1}`;
  }
  async function generate(family:'tabular'|'sequence'):Promise<void>{
    if(busy.value)return;submitting.value=true;error.value='';
    const context=simulation.contextId,signature=simulation.calculationSignature();options.family=family;
    const checkSource=()=>{if(context!==simulation.contextId || signature!==simulation.calculationSignature())throw new Error('当前项目已变化，请重新生成。');};
    try{
      await datasets.refresh();
      checkSource();
      options.dataset_name=nextName();
      const captured=JSON.parse(JSON.stringify(options)) as GenerationOptions;
      const source=await simulation.teachingRequest(['coupling']);
      checkSource();
      const hybrid=source.options.hybrid as Record<string,unknown>|undefined;
      const runtime=hybrid?{hybrid:{imported_mode_values:hybrid.imported_mode_values,imported_mode_source:hybrid.imported_mode_source,output_extent_x_mm:hybrid.output_extent_x_mm,output_extent_y_mm:hybrid.output_extent_y_mm}}:{};
      const payload=await prepareGeneration(source.project,captured,runtime);
      checkSource();
      const id=await submitGeneration(payload);completedDatasetId.value='';jobId.value=id;datasets.select('');
      await jobs.trackSubmittedJob(id,'dataset');
    }catch(cause){error.value=message(cause);}finally{submitting.value=false;}
  }
  async function complete():Promise<void>{
    if(resultLoading.value)return;const id=jobId.value;resultLoading.value=true;
    try{
      const raw=await getJobResult<Record<string,unknown>>(id),body=(raw.result??raw) as Record<string,unknown>;
      if(id!==jobId.value)return;
      const datasetId=String(body.dataset_id||'');if(!datasetId)throw new Error('生成任务未返回数据集编号。');
      await datasets.registerCompleted(datasetId);if(id!==jobId.value)return;
      completedDatasetId.value=datasetId;datasets.select(datasetId);
    }catch(cause){if(id===jobId.value)error.value=message(cause);}finally{if(id===jobId.value)resultLoading.value=false;}
  }
  async function cancel():Promise<void>{cancelling.value=true;try{await jobs.cancel(jobId.value);}catch(cause){error.value=message(cause);}finally{cancelling.value=false;}}
  async function retry():Promise<void>{try{const id=await jobs.retry(jobId.value);completedDatasetId.value='';jobId.value=id;datasets.select('');error.value='';}catch(cause){error.value=message(cause);}}
  return {options,presentation,jobId,job,busy,status,completedDatasetId,error,loading,submitting,resultLoading,cancelling,more,variablesOpen,refreshPresentation,generate,cancel,retry,complete};
});
function message(cause:unknown):string{return cause instanceof Error?cause.message:String(cause);}
