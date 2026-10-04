import { canonicalProject } from '../domain/surface-registry.js';
import { apiRequest } from "./http.js";
import type { ProjectSnapshot } from "../domain/simulation-project.js";

export interface ModelQuality {
  prediction_usable?: boolean;
  test_r2?: number | null;
  reason?: string;
}

export interface ModelRecord {
  model_id: string;
  name?: string;
  model_type?: string;
  model_version?: string;
  version?: string;
  status?: string;
  created_at?: string;
  feature_paths?: string[];
  feature_names?: string[];
  feature_units?: Record<string, string> | string[];
  design_variable_paths?: string[];
  target_names?: string[];
  numeric_feature_names?: string[];
  element_types?: string[];
  metrics?: Record<string, unknown>;
  test_metrics?: Record<string, unknown>;
  model_quality?: ModelQuality;
  dataset_id?: string;
  manifest_error?: string;
}

export interface PredictionResult {
  model_id: string;
  predictions?: Record<string, number>;
  warnings?: string[];
  in_training_domain?: boolean;
  target_name?: string;
  target_names?: string[];
  prediction?: number | number[];
  values?: number[];
}

export async function listModels(): Promise<ModelRecord[]> {
  const response = await apiRequest<{ models: ModelRecord[] }>("/api/v1/models");
  return response.data.models ?? [];
}

export async function listStructureModels(): Promise<ModelRecord[]> {
  const response = await apiRequest<{ models: ModelRecord[] }>("/api/v1/structure-models");
  return response.data.models ?? [];
}

export async function getStructureModelDetails(modelId: string): Promise<Record<string, unknown>> {
  const response = await apiRequest<Record<string, unknown>>(`/api/v1/structure-models/${encodeURIComponent(modelId)}`);
  return response.data;
}

export async function getProjectFeatures(project: ProjectSnapshot, featurePaths: string[]): Promise<Record<string, number>> {
  const response = await apiRequest<{ features: Record<string, number> }>("/api/v1/models/project-features", {
    method: "POST", body: { project: await canonicalProject(project), feature_paths: featurePaths }, retry: false,
  });
  return response.data.features;
}

export async function predictModel(modelId: string, features: Record<string, number>): Promise<PredictionResult> {
  const response = await apiRequest<PredictionResult>(`/api/v1/models/${encodeURIComponent(modelId)}/predict`, {
    method: "POST",
    body: { model_id: modelId, features },
    retry: false,
  });
  return response.data;
}

export async function predictStructureModel(
  modelId: string,
  payload: { element_types: string[]; numeric_values: number[][] },
): Promise<PredictionResult> {
  const response = await apiRequest<PredictionResult>(
    `/api/v1/structure-models/${encodeURIComponent(modelId)}/predict`,
    { method: "POST", body: payload, retry: false },
  );
  return response.data;
}
