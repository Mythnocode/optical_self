import { apiRequest } from "./http.js";

export interface TrainingJobSubmission {
  job_id: string;
}

export interface JointTrainingPayload {
  dataset_id: string;
  random_seed: number;
  random_forest_hyperparameters: Record<string, unknown>;
  xgboost_hyperparameters: Record<string, unknown>;
}

export interface BiLSTMTrainingPayload {
  dataset_path: string;
  system_id_column: string;
  order_column: string;
  element_type_column: string;
  numeric_feature_columns: string[];
  target_columns: string[];
  config: Record<string, unknown>;
}

export async function submitJointTraining(payload: JointTrainingPayload): Promise<string> {
  const response = await apiRequest<TrainingJobSubmission>("/api/v1/training/joint/jobs", {
    method: "POST",
    body: payload,
    retry: false,
    timeoutMs: 30_000,
  });
  if (!response.data?.job_id) throw new Error("训练接口没有返回任务编号。");
  return response.data.job_id;
}

export async function submitBiLSTMTraining(payload: BiLSTMTrainingPayload): Promise<string> {
  const response = await apiRequest<TrainingJobSubmission>("/api/v1/structure-models/bilstm/jobs", {
    method: "POST",
    body: payload,
    retry: false,
    timeoutMs: 30_000,
  });
  if (!response.data?.job_id) throw new Error("BiLSTM 接口没有返回任务编号。");
  return response.data.job_id;
}
