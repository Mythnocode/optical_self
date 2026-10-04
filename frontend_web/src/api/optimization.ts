import {apiRequest} from './http.js';
import type {ProjectSnapshot,SimulationRequest} from '../domain/simulation-project.js';
export interface OptimizationVariable {path:string;group:string;label:string;current:string;lower:string;upper:string}
export interface OptimizationPresentation {variables:OptimizationVariable[];surfaces:{value:string;label:string}[]}
export interface OptimizationConfig {
  objective:string;evaluation_mode:'formal'|'surrogate';surrogate_model_id:string;max_iterations:number;
  evaluation_plane:string;max_system_length_mm:number;min_center_thickness_mm:number;min_air_gap_mm:number;aperture_within_mechanical:boolean;
  collimation_enabled:boolean;collimation_surface:string;collimation_span:number;collimation_radius_change:number;collimation_curvature:number;collimation_centroid_drift:number;collimation_axis_tilt:number;
}
export async function readOptimizationPresentation(project:ProjectSnapshot):Promise<OptimizationPresentation>{
  return (await apiRequest<OptimizationPresentation>('/api/v1/optimization/presentation',{method:'POST',body:project})).data;
}
export async function prepareOptimization(simulation:SimulationRequest,config:OptimizationConfig,variables:OptimizationVariable[]):Promise<Record<string,unknown>>{
  return (await apiRequest<Record<string,unknown>>('/api/v1/optimization/prepare',{method:'POST',body:{simulation,config,variables}})).data;
}
export async function submitOptimization(payload:Record<string,unknown>):Promise<string>{
  return (await apiRequest<{job_id:string}>('/api/v1/optimization/jobs',{method:'POST',body:payload})).data.job_id;
}

export interface OptimizationResultRow {label:string;coupling:string;spot:string;status:string;variables:Record<string,number>}
export interface OptimizationResultPresentation {rows:OptimizationResultRow[];svg:string;summary:string;message:string}
export async function readOptimizationResult(jobId:string,chart:string,width:number,height:number):Promise<OptimizationResultPresentation>{
  return (await apiRequest<OptimizationResultPresentation>(`/api/v1/optimization/jobs/${encodeURIComponent(jobId)}/presentation?chart=${encodeURIComponent(chart)}&width=${width}&height=${height}`)).data;
}
