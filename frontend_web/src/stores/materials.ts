import { editorValues } from '../domain/surface-registry.js';
import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue';
import { defineStore } from 'pinia';
import { apiRequest } from '../api/http.js';
import { useSimulationStore } from './simulation.js';
import type { MaterialLibrary } from '../domain/materials.js';

export const useMaterialsStore=defineStore('materials',()=>{
  const simulation=useSimulationStore(),data=shallowRef<MaterialLibrary>({records:[],used:[]});
  const loading=ref(false),error=ref('');let sequence=0,controller:AbortController|undefined;
  const usedNames=computed(()=>[...new Set(simulation.project.surfaces.map(surface=>editorValues(surface).material))]);
  async function refresh() {
    const current=++sequence;controller?.abort();controller=new AbortController();loading.value=true;error.value='';
    data.value={records:data.value.records,used:[]};
    try {
      const response=await apiRequest<MaterialLibrary>('/api/v1/simulation/materials',{method:'POST',body:{wavelength_nm:simulation.project.source.wavelength_nm,custom_materials:simulation.customMaterials,used_names:usedNames.value},signal:controller.signal});
      if(current===sequence)data.value=response.data;
    } catch(cause) {if(current===sequence)error.value=cause instanceof Error?cause.message:String(cause);}
    finally{if(current===sequence)loading.value=false;}
  }
  watch([()=>simulation.project.source.wavelength_nm,()=>JSON.stringify(simulation.customMaterials),()=>JSON.stringify(usedNames.value)],refresh,{immediate:true});
  const unsubscribe=window.opticalDesktop?.onBackendStatus(status=>{if(status.state==='connected')void refresh();});
  onScopeDispose(()=>{sequence++;controller?.abort();unsubscribe?.();});
  return {data,loading,error,refresh};
});
