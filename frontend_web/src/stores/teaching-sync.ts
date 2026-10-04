import { defineStore,acceptHMRUpdate } from 'pinia';
import { computed,ref,watch } from 'vue';
import { useTeachingStore } from './teaching.js';
import { useSimulationStore } from './simulation.js';
import { apiRequest } from '../api/http.js';
import { clone,fingerprint,type SimulationRequest } from '../domain/simulation-project.js';
import { sceneCalculationSignature } from '../teaching/domain/analysis-types.js';
import defaultEngineering from '../teaching/domain/default-engineering-request.json';
import { projectSettings } from '../domain/complex-field-cache.js';

interface Contract {request:SimulationRequest;sceneKey:string;simulationKey:string}
interface SourceContract {request:SimulationRequest;simulationKey:string;contextId:string;submissionId:string}
const KEY='optical.teaching.engineering.v1';
export const useTeachingSyncStore=defineStore('teaching-sync',()=>{
  const teaching=useTeachingStore(),simulation=useSimulationStore();
  const contract=ref<Contract|null>(null),sourceContract=ref<SourceContract|null>(null),status=ref('');let initialized=false,initialization:Promise<void>|undefined;
  const engineeringRequest=computed(()=>{
    const value=contract.value;
    return value && value.sceneKey===sceneCalculationSignature(teaching.sceneSnapshot()) && value.simulationKey===simulation.calculationSignature()?value.request:null;
  });
  const engineeringSignature=computed(()=>JSON.stringify(engineeringRequest.value?projectSettings(engineeringRequest.value):null));
  function initialize():Promise<void>{
    if(initialization)return initialization;
    initialization=(async()=>{
      await teaching.initialize();
      try{const saved=JSON.parse(localStorage.getItem(KEY)??'null');
        const active=saved?.active??saved;
        if(active?.request?.project && active?.request?.options && typeof active.sceneKey==='string' && typeof active.simulationKey==='string')contract.value={...active,request:await simulation.prepareTeachingRequest(active.request)};
        const source=saved?.source??active;
        if(source?.request?.project && source?.request?.options && typeof source.simulationKey==='string')sourceContract.value={request:await simulation.prepareTeachingRequest(source.request),simulationKey:source.simulationKey,contextId:source.contextId??(source.simulationKey===simulation.calculationSignature()?simulation.contextId:''),submissionId:source.submissionId??simulation.teachingSubmittedRequest?.request_id??''};
      }catch{contract.value=null;sourceContract.value=null;status.value='工程同步记录无法读取，请从仿真重新更新教学台。';}
      initialized=true;
      if(contract.value && !engineeringRequest.value)contract.value=null;
      if(sourceContract.value?.contextId!==simulation.contextId)sourceContract.value=null;
    })();return initialization;
  }
  watch([contract,sourceContract],()=>{if(initialized){try{localStorage.setItem(KEY,JSON.stringify({active:contract.value?{...contract.value,request:projectSettings(contract.value.request)}:null,source:sourceContract.value?{...sourceContract.value,request:projectSettings(sourceContract.value.request)}:null}));}catch{status.value='工程同步记录未能保存，请重新更新教学台。';}}},{deep:true});
  watch(()=>[sceneCalculationSignature(teaching.sceneSnapshot()),simulation.calculationSignature()],()=>{if(initialized && contract.value && !engineeringRequest.value)contract.value=null;});
  watch(()=>simulation.contextId,key=>{if(initialized && sourceContract.value?.contextId!==key)sourceContract.value=null;});
  async function fromSimulation(preset?:SimulationRequest):Promise<boolean>{
    await initialize();const key=simulation.calculationSignature(),contextId=simulation.contextId;
    try{
      const submitted=simulation.teachingSubmittedRequest;
      const source=sourceContract.value?.contextId===simulation.contextId && sourceContract.value.submissionId===(submitted?.request_id??'')?sourceContract.value.request:null;
      const prior=source??submitted;
      const request=await simulation.prepareTeachingRequest(preset??prior??await simulation.teachingRequest());
      const editorProject=await simulation.teachingEditorProject();
      request.project.fingerprint=await fingerprint(request.project);
      if(key!==simulation.calculationSignature() || contextId!==simulation.contextId)throw new Error('仿真工程已修改，请重新更新教学台。');
      const inherit=!!preset || !!prior;
      const response=await teaching.synchronizeFrom(request,inherit,()=>key===simulation.calculationSignature() && contextId===simulation.contextId,editorProject);
      if(!response)return false;
      if(response.engineering_request && request.frontend_state)response.engineering_request.frontend_state=clone(request.frontend_state);
      contract.value=response.engineering_request?{request:response.engineering_request,sceneKey:sceneCalculationSignature(teaching.sceneSnapshot()),simulationKey:key}:null;
      if(response.engineering_request)sourceContract.value={request:clone(response.engineering_request),simulationKey:key,contextId:simulation.contextId,submissionId:submitted?.request_id??''};
      status.value=response.status;return true;
    }catch(cause){status.value=cause instanceof Error?cause.message:String(cause);return false;}
  }
  async function fourAsphere():Promise<boolean>{
    const request=clone(defaultEngineering) as unknown as SimulationRequest;
    delete (request.project as unknown as Record<string,unknown>).calculation_contract;
    if(!await simulation.importProject(JSON.stringify(request))){status.value=simulation.error;return false;}
    if(!await fromSimulation(request))return false;
    status.value='已载入四非球面 · 780 nm 高效耦合演示；教学与仿真共用同一计算处方';return true;
  }
  async function toSimulation():Promise<boolean>{
    await initialize();if(teaching.busy || teaching.dragging)return false;
    const scene=teaching.sceneSnapshot(),key=sceneCalculationSignature(scene),contextId=simulation.contextId;
    try{
      const response=await apiRequest<{changes:Record<string,number>;teaching_snapshot:Record<string,unknown>}>('/api/v1/teaching/scenes/publish',{method:'POST',body:scene});
      if(key!==sceneCalculationSignature(teaching.sceneSnapshot()))throw new Error('教学台已修改，请重新同步。');
      if(contextId!==simulation.contextId)throw new Error('仿真工程已替换，请重新同步。');
      const savedSource=sourceContract.value?.contextId===simulation.contextId?sourceContract.value:null;
      const originalSource=savedSource?clone(savedSource.request):null;
      const applied=simulation.applyTeachingPublish(response.data.changes,response.data.teaching_snapshot);
      if(applied){
        contract.value=null;
        if(originalSource){
          for(const [path,value] of Object.entries(response.data.changes)){
            if(path==='source.wavelength_nm')originalSource.project.source.wavelength_nm=value;
            if(path==='receiver.mode_field_diameter_x_um')originalSource.project.receiver.mode_field_diameter_x_um=value;
          }
          delete (originalSource.project as unknown as Record<string,unknown>).fingerprint;
          sourceContract.value={request:originalSource,simulationKey:simulation.calculationSignature(),contextId:simulation.contextId,submissionId:savedSource!.submissionId};
        }
      }
      status.value=applied?`已同步 ${Object.keys(response.data.changes).length} 项可映射参数并保存教学快照；请从仿真更新后再比较指标`:Object.keys(response.data.changes).length?'参数与当前仿真相同；已保存教学快照':'未发现可同步的波长或模场参数；已保存教学快照';
      return true;
    }catch(cause){status.value=cause instanceof Error?cause.message:String(cause);return false;}
  }
  return {initialize,engineeringRequest,engineeringSignature,status,fromSimulation,toSimulation,fourAsphere};
});
if(import.meta.hot)import.meta.hot.accept(acceptHMRUpdate(useTeachingSyncStore,import.meta.hot));
