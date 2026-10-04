import { defineStore, acceptHMRUpdate } from 'pinia';
import { computed, ref, watch, onScopeDispose } from 'vue';
import { useTeachingStore } from './teaching.js';
import { useJobsStore } from './jobs.js';
import { apiRequest, ApiError } from '../api/http.js';
import { cancelJob } from '../api/jobs.js';
import { sceneCalculationSignature, type AnalysisPresentation, type FormalAnalysis } from '../teaching/domain/analysis-types.js';
import type { TeachingScene } from '../teaching/domain/scene-types.js';
import { useTeachingSyncStore } from './teaching-sync.js';
import { clone,type SimulationRequest } from '../domain/simulation-project.js';
import { projectSettings } from '../domain/complex-field-cache.js';
import { useSimulationStore } from './simulation.js';

interface AnalysisRun { jobId:string; requestId:string; sourceScene:TeachingScene; sourceKey:string; analysis:FormalAnalysis; next:FormalAnalysis[]; stale:boolean; engineeringRequest?:SimulationRequest|null;engineeringKey?:string }
const kinds=new Set<FormalAnalysis>(['raytrace','spot','field','wavefront','coupling']);
function savedRun(value:unknown):value is AnalysisRun{
  if(!value || typeof value!=='object')return false;
  const item=value as Partial<AnalysisRun>;
  return typeof item.jobId==='string' && (!item.jobId || /^job-[a-z0-9]{12}$/.test(item.jobId))
    && typeof item.requestId==='string' && item.requestId.length>0 && item.requestId.length<=256
    && typeof item.sourceKey==='string' && !!item.sourceScene && item.sourceScene.schema_version===2
    && Array.isArray(item.sourceScene.components) && !!item.sourceScene.reference
    && Number.isInteger(item.sourceScene.revision) && !!item.analysis && kinds.has(item.analysis)
    && Array.isArray(item.next) && item.next.every(kind=>kinds.has(kind)) && typeof item.stale==='boolean';
}
const KEY='optical.teaching.analysis.v1';
const empty=():AnalysisPresentation=>({imaging_available:false,imaging_summary:'',coupling_pill:'总耦合效率：—',coupling_detail:'',spot:null});
export const useTeachingAnalysisStore=defineStore('teaching-analysis',()=>{
  const teaching=useTeachingStore(),jobs=useJobsStore(),sync=useTeachingSyncStore();
  const run=ref<AnalysisRun|null>(null),hadResult=ref(false),status=ref(''),presentationError=ref(''),presentation=ref<AnalysisPresentation>(empty());
  const initialized=ref(false),busy=computed(()=>!!run.value && !run.value.stale);
  const activeJobId=computed(()=>run.value?.jobId ?? ''),buttonText=computed(()=>busy.value?'正在计算':hadResult.value?'更新':'开始计算');
  let initializePromise:Promise<void>|undefined,handlingId='',presentationGeneration=0,presentationController:AbortController|undefined;
  function persist():void {
    if(!initialized.value)return;
    try{localStorage.setItem(KEY,JSON.stringify({run:run.value?{...run.value,engineeringRequest:run.value.engineeringRequest?projectSettings(run.value.engineeringRequest):null}:null,hadResult:hadResult.value,status:status.value}));}
    catch{status.value='计算状态未能写入本机缓存。';}
  }
  watch([run,hadResult,status],persist,{deep:true});
  async function initialize():Promise<void>{
    if(initializePromise)return initializePromise;
    initializePromise=(async()=>{
      await teaching.initialize();
      await sync.initialize();
      try{
        const cached=JSON.parse(localStorage.getItem(KEY)??'null');
        hadResult.value=!!cached?.hadResult || Object.values(teaching.sceneSnapshot().results).some(result=>result.status==='completed' && result.source!=='geometry_preview');
        if(savedRun(cached?.run)){
          const restored=cached.run as AnalysisRun;
          if(restored.engineeringRequest)restored.engineeringRequest=await useSimulationStore().prepareTeachingRequest(restored.engineeringRequest);
          if(restored.engineeringRequest && restored.engineeringKey===JSON.stringify(restored.engineeringRequest))restored.engineeringKey=JSON.stringify(projectSettings(restored.engineeringRequest));
          run.value=restored;
        }
        status.value=run.value && typeof cached?.status==='string'?cached.status:'';
      }catch{run.value=null;status.value='上一次教学计算状态无法读取，请重新计算。';}
      initialized.value=true;
      await refreshPresentation();
      if(!run.value && hadResult.value && Object.values(teaching.sceneSnapshot().results).some(result=>result.stale))status.value='场景已修改，请点击更新';
      if(run.value){
        if(!runIsCurrent(run.value)){run.value.stale=true;run.value.next=[];status.value='这是改场景之前的结果，已丢弃；需要请再点光学计算';}
        if(run.value.jobId)await jobs.trackSubmittedJob(run.value.jobId,'teaching');else await submitRun();
      }
    })();return initializePromise;
  }
  async function refreshPresentation():Promise<void>{
    const generation=++presentationGeneration;presentationController?.abort();presentationController=new AbortController();
    try{
      const response=await apiRequest<AnalysisPresentation>('/api/v1/teaching/analysis/presentation',{method:'POST',body:teaching.sceneSnapshot(),signal:presentationController.signal});
      if(generation===presentationGeneration){
        presentation.value=response.data;presentationError.value='';
        if(!run.value && response.data.imaging_available && status.value==='场景已修改，请点击更新')status.value='';
      }
    }catch(cause){if(generation===presentationGeneration){presentation.value=empty();presentationError.value=errorMessage(cause);}}
  }
  watch(()=>JSON.stringify([teaching.revision,teaching.sceneSnapshot().results.spot,teaching.sceneSnapshot().results.coupling]),()=>{if(initialized.value)void refreshPresentation();});
  watch(()=>sceneCalculationSignature(teaching.sceneSnapshot()),(key,old)=>{
    if(!initialized.value || key===old)return;
    presentation.value=empty();
    if(run.value && key!==run.value.sourceKey){run.value.stale=true;run.value.next=[];status.value='场景已改；算完后不会覆盖现在的光路';}
    else if(hadResult.value)status.value='场景已修改，请点击更新';
  });
  watch(()=>sync.engineeringSignature,()=>{
    if(initialized.value && run.value && !runIsCurrent(run.value)){run.value.stale=true;run.value.next=[];status.value='仿真工程或数值配置已修改，旧的教学分析结果将丢弃。';}
  });
  function runIsCurrent(current:AnalysisRun):boolean{return sceneCalculationSignature(teaching.sceneSnapshot())===current.sourceKey && (current.engineeringKey??'null')===sync.engineeringSignature;}
  watch(()=>[activeJobId.value,jobs.jobs[activeJobId.value]?.status],async([jobId,state])=>{
    if(!jobId || !['completed','failed','cancelled'].includes(String(state)) || handlingId===jobId)return;
    const current=run.value;if(!current || current.jobId!==jobId)return;
    handlingId=String(jobId);
    if(current.stale || !runIsCurrent(current)){run.value=null;status.value='这是改场景之前的结果，已丢弃；需要请再点光学计算';return;}
    if(state==='cancelled'){run.value=null;status.value='已取消计算';return;}
    try{
      const result=await teaching.applyFormalResult(String(jobId),sync.engineeringRequest,()=>run.value===current && runIsCurrent(current));
      if(run.value!==current)return;
      if(!result || !runIsCurrent(current)){run.value=null;status.value='这是改场景之前的结果，已丢弃；需要请再点光学计算';return;}
      if(result.success && result.status==='completed')hadResult.value=true;
      await refreshPresentation();
      if(run.value!==current)return;
      if(!result.success){status.value=result.status==='missed'?'光束未命中接收端':result.errors.join('；')||'光学计算失败';run.value=null;return;}
      const next=current.next[0];
      if(next){run.value={...current,jobId:'',requestId:crypto.randomUUID(),analysis:next,next:current.next.slice(1)};await submitRun();}
      else{run.value=null;status.value='';}
    }catch(cause){
      if(run.value===current){run.value=null;const job=jobs.jobs[String(jobId)];status.value=cause instanceof ApiError && cause.code==='JOB_RESULT_NOT_AVAILABLE' && job?.error?typeof job.error==='string'?job.error:job.error.message??errorMessage(cause):errorMessage(cause);}
    }
  });
  async function submitRun():Promise<void>{
    const current=run.value;if(!current)return;
    status.value=`正在计算${current.analysis==='spot'?'光斑':current.analysis==='coupling'?'耦合':current.analysis}，界面仍可继续操作`;
    try{
      const response=await apiRequest<{job_id:string}>('/api/v1/teaching/jobs',{method:'POST',body:{request_id:current.requestId,scene:current.sourceScene,scene_revision:current.sourceScene.revision,analysis:current.analysis,engineering_request:current.engineeringRequest??null}});
      if(!/^job-[a-z0-9]{12}$/.test(response.data.job_id))throw new Error('教学任务没有返回有效编号。');
      if(run.value!==current){await cancelJob(response.data.job_id);return;}
      current.jobId=response.data.job_id;handlingId='';
      await jobs.trackSubmittedJob(current.jobId,'teaching');
    }catch(cause){if(run.value===current){run.value=null;status.value=errorMessage(cause);}}
  }
  async function calculate(analyses:FormalAnalysis[]=['spot','coupling']):Promise<void>{
    await initialize();if(teaching.busy || teaching.dragging || !analyses.length)return;
    await cancel();
    const sourceScene=teaching.sceneSnapshot();
    run.value={jobId:'',requestId:crypto.randomUUID(),sourceScene,sourceKey:sceneCalculationSignature(sourceScene),analysis:analyses[0]!,next:analyses.slice(1),stale:false,engineeringRequest:clone(sync.engineeringRequest),engineeringKey:sync.engineeringSignature};
    await submitRun();
  }
  async function cancel():Promise<void>{
    const current=run.value;run.value=null;
    if(current?.jobId && !['completed','failed','cancelled'].includes(String(jobs.jobs[current.jobId]?.status))) {
      try{await jobs.cancel(current.jobId);}catch(cause){status.value=errorMessage(cause);throw cause;}
    }
    if(current)status.value='已取消计算';
  }
  onScopeDispose(()=>{presentationGeneration++;presentationController?.abort();});
  return {initialize,calculate,cancel,busy,activeJobId,hadResult,status,presentationError,buttonText,presentation};
});
function errorMessage(cause:unknown):string{return cause instanceof Error?cause.message:String(cause);}
if(import.meta.hot)import.meta.hot.accept(acceptHMRUpdate(useTeachingAnalysisStore,import.meta.hot));
