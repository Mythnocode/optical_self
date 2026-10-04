import { apiRaw, apiRequest } from "./http.js";
import type { ProjectSnapshot } from '../domain/simulation-project.js';

export interface GenerationOptions {
  dataset_name: string; family: 'tabular'|'sequence'; lens_count: number; include_conic: boolean;
  variable_paths: string[]; sample_count: number; target: string; sampling: string;
  validation_ratio: number; random_seed: number; precision: string;
}
export interface GenerationPresentation {
  targets:string[]; sampling:string[]; precision:string[]; lens_count:number;
  variables:Array<{path:string;label:string;selected:boolean}>;
}
export async function readGenerationPresentation(project:ProjectSnapshot):Promise<GenerationPresentation>{
  return (await apiRequest<GenerationPresentation>('/api/v1/datasets/generation/presentation',{method:'POST',body:project})).data;
}
export async function prepareGeneration(project:ProjectSnapshot,options:GenerationOptions,simulation_options:Record<string,unknown>={}):Promise<Record<string,unknown>>{
  return (await apiRequest<Record<string,unknown>>('/api/v1/datasets/generation/prepare',{method:'POST',body:{project,options,simulation_options}})).data;
}
export async function submitGeneration(payload:Record<string,unknown>):Promise<string>{
  return (await apiRequest<{job_id:string}>('/api/v1/dataset/jobs',{method:'POST',body:payload})).data.job_id;
}

export interface DatasetSummary {
  dataset_id: string;
  dataset_layout?: 'tabular'|'sequence_long';
  dataset_name?: string;
  dataset_type: string;
  target_column: string;
  sample_count: number;
  status: string;
  created_at: string;
}

export interface DatasetDetails extends DatasetSummary {
  max_surfaces: number;
  output_dir: string;
  manifest_path: string;
  samples_jsonl_path: string;
  samples_flat_csv_path: string;
}

export interface DatasetManifest {
  dataset_id: string;
  dataset_name: string;
  schema_version?: string;
  feature_schema_version?: string;
  engine_name?: string;
  engine_version?: string;
  created_at?: string;
  sample_count?: number;
  valid_sample_count?: number;
  failed_sample_count?: number;
  feature_names?: string[];
  feature_paths?: string[];
  feature_units?: string[];
  target_names?: string[];
  random_seed?: number;
  variable_scheme_id?: string | null;
  lens_count?: number | null;
  design_variable_paths?: string[];
  physics_feature_paths?: string[];
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface DatasetList {
  items: DatasetSummary[];
  total: number;
}

export interface ImportedDataset extends DatasetDetails {}

export async function listDatasets(limit = 200, offset = 0): Promise<DatasetList> {
  const response = await apiRequest<DatasetList>(
    `/api/v1/headless-datasets?limit=${clamp(limit, 1, 200)}&offset=${Math.max(0, Math.floor(offset))}`,
  );
  return response.data;
}

export async function getDataset(datasetId: string): Promise<DatasetDetails> {
  const response = await apiRequest<DatasetDetails>(
    `/api/v1/headless-datasets/${encodeURIComponent(datasetId)}`,
  );
  return response.data;
}

export async function getDatasetManifest(datasetId: string): Promise<DatasetManifest> {
  return apiRaw<DatasetManifest>(
    `/api/v1/headless-datasets/${encodeURIComponent(datasetId)}/files/manifest`,
  );
}

export async function importTabularDataset(payload: {
  source_path: string;
  dataset_name: string;
  target_name: string;
  random_seed: number;
}): Promise<ImportedDataset> {
  const response = await apiRequest<ImportedDataset>("/api/v1/headless-datasets/import-file", {
    method: "POST",
    body: payload,
  });
  return response.data;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, Math.floor(value)));
}
