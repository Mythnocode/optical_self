import {defineStore} from 'pinia';
import {ref,watch} from 'vue';
import type {LocalFileSelection} from '../../../desktop/bridge-contract.js';

const KEY='optical.model.workspace.v1';
export const useModelWorkspaceStore=defineStore('model-workspace',()=>{
  const datasetSource=ref<'import'|'generate'>('import'),datasetSampleMode=ref<'tabular'|'sequence'>('tabular');
  const datasetFile=ref<LocalFileSelection|null>(null),sequenceFileReady=ref(false),trainingOptionsOpen=ref(false);
  const randomForestTrees=ref(300),randomForestDepth=ref(0),randomForestLeaf=ref(1),randomForestMaxFeatures=ref('sqrt');
  const xgboostRounds=ref(300),xgboostLearningRate=ref(.05),xgboostDepth=ref(4),xgboostSubsample=ref(.9),xgboostFeatureSample=ref(.95);
  const bilstmEpochs=ref(200),bilstmBatchSize=ref(32);
  const sequenceSystemIdColumn=ref('system_id'),sequenceOrderColumn=ref('element_index'),sequenceElementTypeColumn=ref('element_type');
  const sequenceNumericColumns=ref('radius_mm,thickness_mm'),sequenceTargetColumns=ref('coupling_efficiency');
  const fields={datasetSource,datasetSampleMode,datasetFile,sequenceFileReady,trainingOptionsOpen,randomForestTrees,randomForestDepth,randomForestLeaf,randomForestMaxFeatures,xgboostRounds,xgboostLearningRate,xgboostDepth,xgboostSubsample,xgboostFeatureSample,bilstmEpochs,bilstmBatchSize,sequenceSystemIdColumn,sequenceOrderColumn,sequenceElementTypeColumn,sequenceNumericColumns,sequenceTargetColumns};
  try{
    const saved=JSON.parse(localStorage.getItem(KEY)||'{}');
    for(const [key,field] of Object.entries(fields)){
      const value=saved[key];
      if(value===undefined)continue;
      if(key==='datasetSource'&&!['import','generate'].includes(value))continue;
      if(key==='datasetSampleMode'&&!['tabular','sequence'].includes(value))continue;
      if(key==='datasetFile'&&(value!==null&&(typeof value!=='object'||typeof value.path!=='string'||typeof value.name!=='string')))continue;
      if(field.value!==null&&typeof value!==typeof field.value)continue;
      (field as {value:unknown}).value=value;
    }
  }catch{/* Original defaults remain available if saved settings are invalid. */}
  watch(Object.values(fields),()=>{try{localStorage.setItem(KEY,JSON.stringify(Object.fromEntries(Object.entries(fields).map(([key,field])=>[key,field.value]))));}catch{/* In-memory preferences still survive navigation. */}},{deep:true});
  return fields;
});
