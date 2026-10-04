import {defineStore} from 'pinia';
import {computed,reactive,ref,watch} from 'vue';
import {useSimulationStore} from './simulation.js';
import {useJobsStore} from './jobs.js';
import {getJobResult} from '../api/jobs.js';
import {readOptimizationPresentation,prepareOptimization,submitOptimization,type OptimizationConfig,type OptimizationPresentation,type OptimizationVariable} from '../api/optimization.js';
const KEY='optical.optimization.v1';
export const useOptimizationStore=defineStore('optimization',()=>{
  const simulation=useSimulationStore(),jobs=useJobsStore();
  const config=reactive<OptimizationConfig>({objective:'最大化耦合效率',evaluation_mode:'formal',surrogate_model_id:'',max_iterations:300,evaluation_plane:'光纤模场',max_system_length_mm:80,min_center_thickness_mm:.3,min_air_gap_mm:.1,aperture_within_mechanical:true,collimation_enabled:false,collimation_surface:'',collimation_span:10,collimation_radius_change:2,collimation_curvature:.05,collimation_centroid_drift:1,collimation_axis_tilt:1});
  const selected=ref<string[]>([]),rows=ref<OptimizationVariable[]>([]),presentation=ref<OptimizationPresentation|null>(null),view=ref<'variables'|'more'>('variables'),search=ref(''),group=ref('全部');
  const jobId=ref(''),result=ref<Record<string,unknown>|null>(null),error=ref(''),loading=ref(false),submitting=ref(false),resultLoading=ref(false),trackingFailed=ref(false);
  const selectionContext=ref(''),submittedContext=ref(''),submittedSignature=ref('');let version=0,completionId='',resultVersion=0;
  const validation=reactive({jobId:'',sourceJob:'',label:'',baseline:null as number|null,signature:'',context:'',status:''});
  const canApply=computed(()=>!simulation.busy&&(!stale.value||validation.sourceJob===jobId.value&&validation.context===simulation.contextId&&validation.signature===simulation.calculationSignature()));
  try{const saved=JSON.parse(localStorage.getItem(KEY)||'{}');Object.assign(config,saved.config||{});Object.assign(validation,saved.validation||{});selected.value=saved.selected||[];rows.value=saved.rows||[];jobId.value=saved.jobId||'';selectionContext.value=saved.selectionContext||'';submittedContext.value=saved.submittedContext||'';submittedSignature.value=saved.submittedSignature||'';}catch{/* Invalid preferences use the native defaults. */}
  const job=computed(()=>jobs.jobs[jobId.value]??null);
  const busy=computed(()=>submitting.value||!!(jobId.value&&!trackingFailed.value&&(!job.value||!['completed','failed','cancelled'].includes(job.value.status))));
  const stale=computed(()=>!!jobId.value&&(submittedContext.value!==simulation.contextId||submittedSignature.value!==simulation.calculationSignature()));
  const filtered=computed(()=>presentation.value?.variables.filter(row=>(group.value==='全部'||row.group===group.value)&&row.label.toLowerCase().includes(search.value.toLowerCase()))??[]);
  watch([config,selected,rows,jobId,selectionContext,submittedContext,submittedSignature,validation],()=>{try{localStorage.setItem(KEY,JSON.stringify({config,selected:selected.value,rows:rows.value,jobId:jobId.value,selectionContext:selectionContext.value,submittedContext:submittedContext.value,submittedSignature:submittedSignature.value,validation}));}catch{error.value='优化设置未能保存。';}},{deep:true});
  watch([jobId,()=>job.value?.status],([,status])=>{if(status==='completed'&&completionId!==jobId.value)void complete();},{immediate:true});
  watch(()=>jobs.jobs[validation.jobId]?.status,status=>{if(status==='completed')void completeValidation();else if(status==='failed'||status==='cancelled')validation.status=`${validation.label} 正式验证${status==='failed'?'失败':'已取消'}`;},{immediate:true});
  if(jobId.value)void jobs.track(jobId.value).catch(cause=>{trackingFailed.value=true;error.value=message(cause);});
  if(validation.jobId)void jobs.track(validation.jobId).catch(cause=>{validation.status=message(cause);});
  async function refreshPresentation():Promise<void>{
    const token=++version,context=simulation.contextId;loading.value=true;
    try{const next=await readOptimizationPresentation(await simulation.teachingEditorProject());if(token!==version||context!==simulation.contextId)return;
      const same=selectionContext.value===context;
      selected.value=same?selected.value.filter(path=>next.variables.some(row=>row.path===path)):[];
      const previous=new Map(rows.value.map(row=>[row.path,row]));
      rows.value=next.variables.filter(row=>selected.value.includes(row.path)).map(row=>same&&previous.has(row.path)?previous.get(row.path)!:{...row});
      if(!next.surfaces.some(row=>row.value===config.collimation_surface))config.collimation_surface='';
      presentation.value=next;selectionContext.value=context;
    }catch(cause){if(token===version){presentation.value=null;error.value=message(cause);}}finally{if(token===version)loading.value=false;}
  }
  function select(path:string,checked:boolean):void{
    selected.value=checked?[...new Set([...selected.value,path])]:selected.value.filter(value=>value!==path);
    // Qt rebuilds all editable ranges whenever the selected variable set changes.
    rows.value=presentation.value?.variables.filter(row=>selected.value.includes(row.path)).map(row=>({...row}))??[];
  }
  async function start():Promise<boolean>{
    if(busy.value)return false;submitting.value=true;error.value='';
    const context=simulation.contextId,signature=simulation.calculationSignature(),capturedConfig=JSON.parse(JSON.stringify(config)) as OptimizationConfig,capturedRows=JSON.parse(JSON.stringify(rows.value)) as OptimizationVariable[];
    try{const source=await simulation.teachingRequest();source.request_id=crypto.randomUUID();
      const payload=await prepareOptimization(source,capturedConfig,capturedRows);
      if(context!==simulation.contextId||signature!==simulation.calculationSignature())throw new Error('当前仿真设置已变化，请重新提交优化。');
      const id=await submitOptimization(payload);jobId.value=id;result.value=null;completionId='';trackingFailed.value=false;submittedContext.value=context;submittedSignature.value=signature;
      await jobs.trackSubmittedJob(id,'optimization');return true;
    }catch(cause){error.value=message(cause);return false;}finally{submitting.value=false;}
  }
  async function complete():Promise<void>{
    const id=jobId.value,token=++resultVersion;resultLoading.value=true;
    try{const raw=await getJobResult<Record<string,unknown>>(id);if(id===jobId.value){result.value=(raw.result??raw) as Record<string,unknown>;completionId=id;}}
    catch(cause){if(id===jobId.value)error.value=message(cause);}finally{if(token===resultVersion)resultLoading.value=false;}
  }
  function coupling(body:Record<string,unknown>|null):number|null{const result=(body?.result??body) as Record<string,unknown>|null,metrics=result?.metrics as Record<string,unknown>|undefined;const value=metrics?.total_coupling_efficiency??metrics?.coupling_efficiency;return typeof value==='number'&&Number.isFinite(value)?value:null;}
  async function applyCandidate(variables:Record<string,number>,label:string):Promise<boolean>{
    if(!canApply.value||!Object.keys(variables).length)return false;
    try{
      const before=simulation.resultStale?null:coupling(simulation.result);
      if(!simulation.applyOptimizationCandidate(variables)){validation.status='方案与当前系统相同';return false;}
      Object.assign(validation,{signature:simulation.calculationSignature(),context:simulation.contextId,sourceJob:jobId.value,label,baseline:before,status:`已应用：${label}，正在正式验证…`,jobId:''});
      const previous=simulation.activeJobId;await simulation.compute();
      if(simulation.activeJobId===previous)throw new Error(simulation.error||'正式验证未能提交。');
      validation.jobId=simulation.activeJobId;
      if(jobs.jobs[validation.jobId]?.status==='completed')await completeValidation();
      return true;
    }catch(cause){validation.status=message(cause);return false;}
  }
  async function completeValidation():Promise<void>{
    const id=validation.jobId;if(!id)return;
    try{const raw=await getJobResult<Record<string,unknown>>(id);if(id!==validation.jobId)return;const after=coupling(raw);
      if(after===null)validation.status=`${validation.label} 已应用，但正式结果没有返回耦合效率`;
      else if(validation.baseline===null)validation.status=`${validation.label} 正式验证完成：耦合效率 ${Number(after.toPrecision(4))}（缺少应用前基线）`;
      else{const delta=after-validation.baseline;validation.status=`${validation.label} 正式验证完成：${Number(validation.baseline.toPrecision(4))} → ${Number(after.toPrecision(4))}，${delta>0?'提高':delta<0?'降低':'不变'} ${Number(Math.abs(delta).toPrecision(4))}`;}
    }catch(cause){if(id===validation.jobId)validation.status=message(cause);}
  }
  async function cancel():Promise<void>{try{await jobs.cancel(jobId.value);}catch(cause){error.value=message(cause);}}
  return {config,selected,rows,presentation,view,search,group,jobId,job,result,error,loading,submitting,resultLoading,busy,stale,filtered,validation,canApply,applyCandidate,refreshPresentation,select,start,complete,cancel};
});
function message(cause:unknown):string{return cause instanceof Error?cause.message:String(cause);}
