import {apiRequest} from './http.js';
import type {SimulationRequest} from '../domain/simulation-project.js';
import type {SimulationPlot} from '../domain/simulation-results.js';
import type {OptimizationVariable} from './optimization.js';
export interface ScanConfig {scan_mode:string;response:string;scale:string;points:number}
export interface ScanPresentation {svg:string;plot:SimulationPlot|null;summary:string;message:string}
export async function prepareScan(simulation:SimulationRequest,config:ScanConfig,variables:OptimizationVariable[]):Promise<Record<string,unknown>>{
  return (await apiRequest<Record<string,unknown>>('/api/v1/scan/prepare',{method:'POST',body:{simulation,config,variables}})).data;
}
export async function submitScan(payload:Record<string,unknown>):Promise<string>{
  return (await apiRequest<{job_id:string}>('/api/v1/scan/jobs',{method:'POST',body:payload})).data.job_id;
}
export async function readScanResult(id:string,width:number,height:number):Promise<ScanPresentation>{
  return (await apiRequest<ScanPresentation>(`/api/v1/scan/jobs/${encodeURIComponent(id)}/presentation?width=${width}&height=${height}`)).data;
}
