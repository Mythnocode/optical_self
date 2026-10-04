import {apiRequest} from './http.js';
import type {ProjectSnapshot} from '../domain/simulation-project.js';
export const explanationCharts=['全局特征重要性排名','蜂群图','特征依赖网格图','单变量依赖趋势图','物理一致性图','瀑布图'];
export interface ExplanationPresentation {svg:string;summary:string;message:string}
export interface FormulaImage {src:string;width:number;height:number}
export interface CurrentExplanationPresentation extends ExplanationPresentation {
  interpretation:null|{model_text:string;physics_html:string;next_text:string;formula_title:string;formula_steps:{stage:string;latex:string;image:FormulaImage}[]};
}
export async function submitCurrentExplanation(modelId:string,project:ProjectSnapshot):Promise<string>{
  return (await apiRequest<{job_id:string}>(`/api/v1/models/${encodeURIComponent(modelId)}/shap/current-system/jobs`,{method:'POST',body:{project},retry:false})).data.job_id;
}
export async function readCurrentPresentation(jobId:string,width:number,height:number,verified=false):Promise<CurrentExplanationPresentation>{
  const query=new URLSearchParams({width:String(width),height:String(height),verified:String(verified)});
  return (await apiRequest<CurrentExplanationPresentation>(`/api/v1/explainability/jobs/${encodeURIComponent(jobId)}/current-presentation?${query}`)).data;
}
export interface ParameterPresentation extends ExplanationPresentation {
  ranking:{feature:string;text:string}[];selected_keys:string[];
  chain:{title:string;rows:{feature:string;name:string;path:string;note:string;steps:{stage:string;latex:string;image:FormulaImage}[]}[];overlap_formula:string;overlap_image:FormulaImage|null};
}
export async function submitParameterExplanation(modelId:string,designPaths:string[]):Promise<string>{
  return (await apiRequest<{job_id:string}>(`/api/v1/models/${encodeURIComponent(modelId)}/shap/jobs`,{method:'POST',body:{top_k:8,max_samples:80,background_sample_count:80,display_feature_paths:designPaths}})).data.job_id;
}
export async function readParameterPresentation(jobId:string,features:string[]|null,width:number,height:number,parameter=''):Promise<ParameterPresentation>{
  const query=new URLSearchParams({width:String(width),height:String(height),parameter});
  if(features!==null){if(!features.length)query.set('empty_selection','true');else features.forEach(feature=>query.append('feature',feature));}
  return (await apiRequest<ParameterPresentation>(`/api/v1/explainability/jobs/${encodeURIComponent(jobId)}/parameter-presentation?${query}`)).data;
}
export async function submitDesignExplanation(modelId:string):Promise<string>{
  return (await apiRequest<{job_id:string}>(`/api/v1/models/${encodeURIComponent(modelId)}/shap/design-variables/jobs`,{method:'POST',body:{max_samples:80,background_sample_count:80}})).data.job_id;
}
export async function readExplanationPresentation(jobId:string,chart:string,width:number,height:number):Promise<ExplanationPresentation>{
  return (await apiRequest<ExplanationPresentation>(`/api/v1/explainability/jobs/${encodeURIComponent(jobId)}/presentation?chart=${encodeURIComponent(chart)}&width=${width}&height=${height}`)).data;
}
