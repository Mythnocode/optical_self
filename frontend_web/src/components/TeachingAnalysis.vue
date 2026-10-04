<script setup lang="ts">
import { computed } from 'vue';
import { useTeachingAnalysisStore } from '../stores/teaching-analysis.js';
import { useTeachingStore } from '../stores/teaching.js';
const emit=defineEmits<{close:[]}>();
const analysis=useTeachingAnalysisStore(),teaching=useTeachingStore();
const showStatus=computed(()=>analysis.busy || !!analysis.status || !!analysis.presentationError);
async function calculate():Promise<void>{try{await analysis.calculate();}catch(cause){analysis.status=cause instanceof Error?cause.message:String(cause);}}
</script>

<template>
  <aside class="teaching-analysis-window" role="dialog" aria-label="成像与耦合" @keydown.esc="emit('close')">
    <button class="teaching-inspector-close" aria-label="关闭成像与耦合" @click="emit('close')">×</button>
    <div class="teaching-analysis-client">
      <div class="teaching-analysis-run">
        <button class="teaching-analysis-primary" :class="{'with-status':showStatus}" :disabled="analysis.busy || teaching.busy || teaching.dragging" @click="calculate">{{ analysis.buttonText }}</button>
        <div v-if="showStatus" class="teaching-analysis-status" role="status">{{ analysis.status || analysis.presentationError }}</div>
      </div>
      <div v-if="analysis.busy" class="teaching-analysis-progress-slot"><div class="teaching-analysis-progress" role="progressbar" aria-label="光学计算进行中"><span /></div></div>
      <section v-if="analysis.presentation.imaging_available" class="teaching-analysis-imaging">
        <div class="teaching-analysis-title">成像预览</div>
        <div class="teaching-analysis-summary">{{ analysis.presentation.imaging_summary }}</div>
        <svg v-if="analysis.presentation.spot" class="teaching-analysis-spot" viewBox="0 0 472 168" role="img" :aria-label="analysis.presentation.spot.caption">
          <rect x="1" y="1" width="470" height="166" fill="#101828" />
          <rect x="1" y="1" width="470" height="166" rx="8" fill="none" stroke="#344054" />
          <circle v-for="(ring,index) in analysis.presentation.spot.rings" :key="index" cx="235" cy="83" :r="ring.radius" :fill="ring.color" />
          <text x="235" y="161" text-anchor="middle" fill="#FFFFFF">{{ analysis.presentation.spot.caption }}</text>
        </svg>
      </section>
      <section class="teaching-analysis-coupling">
        <div class="teaching-analysis-title">耦合数据</div>
        <div class="teaching-analysis-pill">{{ analysis.presentation.coupling_pill }}</div>
        <div v-if="analysis.presentation.coupling_detail" class="teaching-analysis-detail">{{ analysis.presentation.coupling_detail }}</div>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.teaching-analysis-window{position:absolute;z-index:5;top:18px;right:78px;width:500px;height:640px;background:#EEF1F5;box-shadow:0 8px 24px #34405430;color:#101828;font-size:17px;}
.teaching-analysis-client{height:100%;padding:12px 14px 14px;overflow:auto;}
.teaching-analysis-run{display:flex;gap:8px;height:54px;}
.teaching-analysis-primary{width:100%;height:54px;padding:7px 16px;border:1px solid #155EEF;border-radius:6px;background:#155EEF;color:white;font-size:16px;font-weight:800;cursor:pointer;}
.teaching-analysis-primary.with-status{width:156px;flex:0 0 156px;}
.teaching-analysis-primary:disabled{background:#84ADFF;border-color:#84ADFF;cursor:default;}
.teaching-analysis-status{flex:1;display:flex;align-items:center;line-height:21px;white-space:pre-wrap;overflow-wrap:anywhere;color:#101828;}
.teaching-analysis-title{height:26px;padding:5px 6px 0;color:#344054;font-weight:750;line-height:21px;}
.teaching-analysis-progress-slot{position:relative;height:34px;margin-top:8px;}
.teaching-analysis-progress{position:absolute;top:13px;width:100%;height:34px;border:1px solid #98A2B3;border-radius:7px;overflow:hidden;background:white;}
.teaching-analysis-progress span{display:block;width:30%;height:100%;border-radius:6px;background:#1D4ED8;animation:teaching-analysis-busy 1.6s linear infinite;}
@keyframes teaching-analysis-busy{from{transform:translateX(-100%)}to{transform:translateX(334%)}}
.teaching-analysis-imaging,.teaching-analysis-coupling{margin-top:8px;}
.teaching-analysis-summary{height:46px;margin-top:6px;padding:10px 17px;border:1px solid #6EE7B7;border-radius:8px;background:#ECFDF3;color:#047857;font-size:19px;font-weight:800;line-height:24px;white-space:pre-wrap;}
.teaching-analysis-spot{display:block;width:472px;height:168px;margin-top:6px;overflow:hidden;font-size:17px;}
.teaching-analysis-pill{height:33px;margin-top:8px;padding:4px 7px;border:2px solid #CBD5E1;border-radius:10px;background:#F59E0B;color:white;font-weight:700;line-height:21px;text-align:center;}
.teaching-analysis-detail{margin-top:6px;line-height:23px;}
</style>
