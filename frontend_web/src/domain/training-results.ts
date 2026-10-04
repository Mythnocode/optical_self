export const TRAINING_CHARTS = ["残差图", "实测值与预测值对照", "残差分布", "验证误差曲线"] as const;
export type TrainingChartName = typeof TRAINING_CHARTS[number];
export type ResultRecord = Record<string, unknown>;

export function record(value: unknown): ResultRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as ResultRecord : {};
}

export function trainingModels(result: ResultRecord | null): Array<{ title: string; body: ResultRecord }> {
  if (!result) return [];
  const items = [
    { title: "随机森林", body: record(result.random_forest) },
    { title: "XGBoost 物理残差", body: record(result.xgboost) },
  ].filter((item) => Object.keys(item.body).length);
  return items.length ? items : [{ title: "BiLSTM", body: result }];
}

export function trainingMetrics(result: ResultRecord): ResultRecord {
  const metadata = record(result.metadata);
  const metrics = record(result.test_metrics ?? result.metrics ?? metadata.test_metrics);
  if (["r2", "mae", "rmse"].some((key) => key in metrics)) return metrics;
  const targets = result.target_names ?? metadata.target_names;
  for (const target of Array.isArray(targets) ? targets : []) {
    const nested = record(metrics[String(target)]);
    if (Object.keys(nested).length) return nested;
  }
  return Object.values(metrics).map(record).find((item) => ["r2", "mae", "rmse"].some((key) => key in item)) ?? {};
}

export function numericMetric(value: unknown, digits = 4): string {
  return typeof value === "number" && Number.isFinite(value) ? Number(value.toPrecision(digits)).toString() : "—";
}

// The legacy charts use the first target column. Reject malformed arrays as a
// whole so filtering cannot silently pair a prediction with another sample.
function column(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  const values = value.map((item) => Array.isArray(item) ? item[0] : item);
  return values.every((item) => typeof item === "number" && Number.isFinite(item)) ? values as number[] : [];
}

function historyCurve(value: unknown): number[] {
  const keys = ["validation_mse_scaled", "validation", "valid", "rmse", "error", "validation_loss", "val_loss"];
  if (Array.isArray(value) && value.length && value.every((item) => Object.keys(record(item)).length)) {
    for (const key of keys) {
      const curve = column(value.map((item) => record(item)[key]));
      if (curve.length) return curve;
    }
    return [];
  }
  const queue: unknown[] = [value];
  while (queue.length) {
    const next = queue.shift();
    const curve = column(next);
    if (curve.length) return curve;
    const body = record(next);
    const preferred = keys.find((key) => body[key] !== undefined);
    if (preferred) queue.unshift(body[preferred]);
    else queue.push(...Object.values(body));
  }
  return [];
}

export interface TrainingPlot {
  kind: "scatter" | "histogram" | "line";
  points: Array<{ x: number; y: number }>;
  xLabel: string;
  yLabel: string;
  zeroLine?: boolean;
  identityLine?: boolean;
  reference?: number;
  bins?: number;
  description?: string;
}

export function trainingPlot(result: ResultRecord, name: TrainingChartName): TrainingPlot | null {
  const metadata = record(result.metadata);
  const evaluation = record(result.evaluation ?? metadata.evaluation);
  const actual = column(evaluation.actual);
  const predicted = column(evaluation.predicted);
  const residual = column(evaluation.residual);
  if (name === "残差图" && residual.length) {
    const useActual = actual.length === residual.length;
    return { kind: "scatter", points: residual.map((y, i) => ({ x: useActual ? actual[i] : i, y })), xLabel: useActual ? "真实仿真值" : "样本", yLabel: "残差（预测 − 真实）", zeroLine: true };
  }
  if (name === "实测值与预测值对照" && actual.length && actual.length === predicted.length) {
    return { kind: "scatter", points: actual.map((x, i) => ({ x, y: predicted[i] })), xLabel: "真实仿真值", yLabel: "模型预测值", identityLine: true };
  }
  if (name === "残差分布" && residual.length) {
    return { kind: "histogram", points: residual.map((x) => ({ x, y: 1 })), xLabel: "残差（预测 − 真实）", yLabel: "样本数", zeroLine: true, bins: Math.min(24, Math.max(8, Math.floor(Math.sqrt(residual.length)) + 2)) };
  }
  if (name === "验证误差曲线") {
    const curve = historyCurve(metadata.training_history ?? result.training_history ?? {}) || [];
    const ys = curve.length ? curve : column(result.oob_error_curve ?? metadata.oob_error_curve);
    if (!ys.length) return null;
    const rmse = trainingMetrics(result).rmse;
    return { kind: "line", points: ys.map((y, x) => ({ x, y })), xLabel: "轮次", yLabel: String(result.training_curve_label ?? metadata.training_curve_label ?? "验证误差"), reference: typeof rmse === "number" && Number.isFinite(rmse) ? rmse : undefined, description: typeof metadata.training_curve_description === "string" ? metadata.training_curve_description : undefined };
  }
  return null;
}

export function unavailableTrainingPlot(result: ResultRecord, name: TrainingChartName): string {
  if (name === "验证误差曲线") {
    const metadata = record(result.metadata);
    const summary = record(metadata.training_summary ?? result.training_summary);
    if (summary.convergence === "not_applicable") return "该模型没有逐轮训练记录；随机森林的训练收敛不按轮次定义，请查看残差图或实测值与预测值对照。";
    return "该模型没有返回逐轮训练记录，暂时无法绘制验证误差曲线。";
  }
  if (name === "实测值与预测值对照") return "训练完成，但测试集没有完整的实测值与预测值对照数据。";
  return name === "残差图" ? "训练完成，但测试集没有残差数据，无法绘制残差图。" : "训练完成，但测试集没有残差数据，无法绘制残差分布。";
}
