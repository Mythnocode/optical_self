<script setup lang="ts">
import { useRouter } from "vue-router";

interface WorkflowNode {
  kind: string;
  module: string;
  title: string;
  subtitle: string;
  icon: string;
}

interface WorkflowSection {
  key: string;
  title: string;
  subtitle: string;
  icon: string;
  accent: string;
  intro: string;
  nodes: WorkflowNode[];
}

const router = useRouter();

const sections: WorkflowSection[] = [
  {
    key: "teaching",
    title: "教学",
    subtitle: "认识器材与光路",
    icon: "teaching-section.svg",
    accent: "#0E7490",
    intro: "在实验台上摆好光源、镜片和接收端，画布即时显示光路示意。示意只说明光去了哪里；确认光路后再做正式波动光学计算，得到的成像与耦合数据才算结论。",
    nodes: [
      { kind: "teaching", module: "teaching", title: "教学入门", subtitle: "打开教学实验台", icon: "guide.svg" },
      { kind: "equipment", module: "teaching", title: "器材库", subtitle: "摆放光源与器件", icon: "toolbox.svg" },
      { kind: "analysis", module: "teaching", title: "成像与耦合", subtitle: "正式计算光斑与效率", icon: "intensity.svg" },
      { kind: "sync_to_simulation", module: "teaching", title: "同步到仿真", subtitle: "把教学场景写入工程", icon: "next.svg" },
    ],
  },
  {
    key: "simulation",
    title: "仿真",
    subtitle: "搭建、观察与测量",
    icon: "simulation-section.svg",
    accent: "#155EEF",
    intro: "先建立镜头与光源，再由内核追迹光线并给出结果。四个入口按「搭—看—量—算」的顺序走，彼此共享同一份系统状态，任意一步改动的参数会自动让下游结果失效并标记为待重算。",
    nodes: [
      { kind: "lens_data", module: "simulation", title: "搭建系统", subtitle: "进入仿真镜头表", icon: "settings.svg" },
      { kind: "ray_layout", module: "simulation", title: "观察结果", subtitle: "进入仿真光路图", icon: "chart.svg" },
      { kind: "spot", module: "simulation", title: "测量数据", subtitle: "进入仿真光斑图", icon: "intensity.svg" },
      { kind: "coupling", module: "simulation", title: "分析结果", subtitle: "进入仿真光纤耦合", icon: "phase.svg" },
    ],
  },
  {
    key: "model",
    title: "模型",
    subtitle: "数据集与训练",
    icon: "machine-learning-section.svg",
    accent: "#7C3AED",
    intro: "先生成覆盖参数范围的样本，再用随机森林和 XGBoost 物理残差联合训练。数据集缺少解析物理特征时只训练随机森林，训练页会写明原因，不会把不完整的模型当作可用结果。",
    nodes: [
      { kind: "dataset", module: "model", title: "准备数据集", subtitle: "生成样本或导入表格", icon: "ml_dataset.png" },
      { kind: "train_result", module: "model", title: "训练模型", subtitle: "随机森林与物理残差", icon: "ml_train_result.png" },
      { kind: "predict", module: "model", title: "模型预测", subtitle: "用当前镜头做推理", icon: "ml_predict.png" },
    ],
  },
  {
    key: "optimization",
    title: "优化",
    subtitle: "目标与变量范围",
    icon: "optimization-section.svg",
    accent: "#B45309",
    intro: "先定优化目标和每个变量的取值范围，再运行扫描或寻优。代理模型只负责筛选候选，候选结果要经过正式光学计算复核，才允许写入镜头表。",
    nodes: [
      { kind: "opt_vars", module: "optimization", title: "优化变量", subtitle: "选择变量与范围", icon: "opt_vars.png" },
      { kind: "scan", module: "optimization", title: "参数扫描", subtitle: "单变量与双变量扫描", icon: "opt_scan.png" },
      { kind: "opt_result", module: "optimization", title: "优化结果", subtitle: "候选对照与写入", icon: "opt_result.png" },
    ],
  },
  {
    key: "explainability",
    title: "解释",
    subtitle: "模型为什么这样选",
    icon: "explainability-section.svg",
    accent: "#155EEF",
    intro: "用 SHAP 给出参数的平均贡献排序，再顺着物理公式链路回到曲率半径、厚度和圆锥系数。SHAP 只回答模型依赖谁，物理因果仍要用正式光学计算复核。",
    nodes: [
      { kind: "global_contrib", module: "explainability", title: "贡献排序", subtitle: "把 SHAP 回传到 8 个设计变量", icon: "explain_global.png" },
      { kind: "param_trend", module: "explainability", title: "物理链路", subtitle: "参数 → 公式 → 目标", icon: "explain_trend.png" },
      { kind: "current_system", module: "explainability", title: "当前系统验证", subtitle: "把当前镜头当作样本", icon: "explain_current.png" },
    ],
  },
];

function openNode(node: WorkflowNode): void {
  if (node.module === "teaching") {
    void router.push({ name: "teaching-three", query: node.kind === "teaching" ? {} : { tool: node.kind } });
    return;
  }
  void router.push({ name: "workbench", params: { module: node.module, kind: node.kind } });
}
</script>

<template>
  <section class="home-page">
    <div class="workflow-canvas">
      <div class="workflow-title">
        <span class="title-rule"></span>
        <h1>光学研究工作流</h1>
        <span class="title-rule"></span>
      </div>

      <div class="workflow-columns" aria-label="光学研究工作流入口">
        <div class="workflow-columns-host">
          <section v-for="section in sections" :key="section.key" class="workflow-section">
            <header class="workflow-section-header">
              <div class="section-heading">
                <span class="section-icon"><img :src="`/icons/${section.icon}`" alt="" :style="{ color: section.accent }" /></span>
                <h2>{{ section.title }}</h2>
              </div>
              <div class="section-hint">{{ section.subtitle }}</div>
            </header>

            <p class="workflow-section-intro">{{ section.intro }}</p>

            <div class="workflow-nodes">
              <template v-for="(node, index) in section.nodes" :key="node.kind">
                <div v-if="index > 0" class="workflow-connector" aria-hidden="true"><span></span></div>
                <button
                  class="workflow-node"
                  :class="{ 'workflow-node-featured': node.kind === 'teaching' }"
                  type="button"
                  :aria-label="`${node.title}：${node.subtitle}`"
                  @click="openNode(node)"
                >
                  <span class="workflow-node-heading">
                    <span class="workflow-node-icon"><img :src="`/icons/${node.icon}`" alt="" /></span>
                    <strong>{{ node.title }}</strong>
                  </span>
                  <span class="workflow-node-subtitle">{{ node.subtitle }}</span>
                </button>
              </template>
            </div>
          </section>
        </div>
      </div>
    </div>
  </section>
</template>
