<script setup lang="ts">
import { computed, ref } from "vue";
import { useTrainingStore } from "../stores/training.js";
import { numericMetric, record, TRAINING_CHARTS, trainingMetrics, trainingModels, trainingPlot, unavailableTrainingPlot, type TrainingChartName } from "../domain/training-results.js";
import TrainingPlot from "./TrainingPlot.vue";

const training = useTrainingStore();
const chart = ref<TrainingChartName>("残差图");
const models = computed(() => trainingModels(training.result));
// Legacy joint training displays the residual model when available, otherwise RF.
const primary = computed(() => models.value.at(-1)?.body ?? {});
const plot = computed(() => trainingPlot(primary.value, chart.value));
const warnings = computed(() => Array.isArray(training.result?.warnings) ? training.result.warnings.map(String).join("；") : "");
const error = computed(() => training.submitError || training.resultError || (typeof training.resultJob?.error === "string" ? training.resultJob.error : String(record(training.resultJob?.error).message ?? "")));
const progress = computed(() => {
  const value = training.resultJob?.progress;
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
});
const statusLabels: Record<string, string> = { queued: "排队中", running: "训练中", completed: "训练完成", failed: "训练失败", cancelled: "训练已取消" };
const progressText = computed(() => `${statusLabels[String(training.resultJob?.status)] ?? '训练中'} ${Math.round(progress.value * 100)}%`);
const summary = computed(() => {
  if (error.value) return error.value;
  if (training.resultLoading) return "正在读取训练结果…";
  if (!training.result) return training.resultJob ? (statusLabels[String(training.resultJob.status)] ?? "训练中") : "尚未训练";
  const score = (body: Record<string, unknown>) => {
    const r2 = trainingMetrics(body).r2;
    return typeof r2 === "number" && Number.isFinite(r2) ? `R²=${r2.toFixed(3)}` : "已完成";
  };
  if (training.result.random_forest) {
    const rf = score(record(training.result.random_forest));
    if (training.result.status === "partial" || !training.result.xgboost) return `训练部分完成 随机森林 ${rf} XGBoost 未完成。${warnings.value ? `原因：${warnings.value}` : ''} 随机森林结果可用于设计变量解释；请修复数据后再训练 XGBoost。`;
    return `训练完成 随机森林 ${rf} XGBoost ${score(record(training.result.xgboost))} XGBoost为主预测，随机森林用于设计变量解释和对照。`;
  }
  const metrics = trainingMetrics(primary.value);
  const info = record(primary.value.training_summary);
  const samples = info.sample_count ?? info.training_samples ?? record(primary.value.split_counts).train;
  return `训练完成${samples !== undefined ? ` 训练样本 ${samples}` : ''}${typeof metrics.r2 === 'number' ? ` 测试 R²=${metrics.r2.toFixed(3)}` : ''}${typeof metrics.rmse === 'number' ? ` RMSE=${numericMetric(metrics.rmse)}` : ''}`;
});
const emptyMessage = computed(() => error.value || (training.result ? unavailableTrainingPlot(primary.value, chart.value) : training.resultLoading ? "正在读取训练结果…" : training.resultJob && ['queued','running'].includes(training.resultJob.status) ? "训练正在执行，完成后将显示训练结果。" : "先在数据集页训练，再查看残差图等训练结果。"));
</script>

<template>
  <section class="model-training-results-layout" aria-label="训练结果">
    <div class="training-chart-toolbar"><select v-model="chart" aria-label="训练结果图表"><option v-for="name in TRAINING_CHARTS" :key="name">{{ name }}</option></select><button v-if="training.resultJob?.status === 'completed' && !training.result" :disabled="training.resultLoading" @click="training.loadResult()">重新读取结果</button></div>
    <p class="training-summary" :class="{ error: error, partial: training.result?.status === 'partial' }" role="status">{{ summary }}</p>
    <div v-if="training.resultJob" class="training-progress-block" :class="training.resultJob.status"><span>{{ progressText }}</span><progress :value="progress" max="1" :aria-label="progressText"></progress></div>
    <div class="training-result-workspace"><TrainingPlot v-if="plot" :plot="plot" :title="chart" :metrics="trainingMetrics(primary)" /><p v-else class="training-result-empty">{{ emptyMessage }}</p></div>
  </section>
</template>
