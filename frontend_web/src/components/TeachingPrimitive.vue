<script setup lang="ts">
import type { TeachingPrimitive } from '../teaching/domain/scene-types.js';
import { useId } from 'vue';
defineProps<{ primitive: TeachingPrimitive }>();
const clipId=useId();
function rgba(value?: number[] | null): string { return value ? `rgba(${value[0]},${value[1]},${value[2]},${(value[3] ?? 255) / 255})` : 'none'; }
</script>
<template>
  <ellipse v-if="primitive.shape === 'ellipse'" :cx="primitive.bounds[0] + primitive.bounds[2]/2" :cy="primitive.bounds[1] + primitive.bounds[3]/2" :rx="primitive.bounds[2]/2" :ry="primitive.bounds[3]/2" :fill="rgba(primitive.fill)" :stroke="rgba(primitive.stroke)" :stroke-width="primitive.width" />
  <rect v-else-if="primitive.shape === 'rect'" :x="primitive.bounds[0]" :y="primitive.bounds[1]" :width="primitive.bounds[2]" :height="primitive.bounds[3]" :rx="primitive.radius" :fill="rgba(primitive.fill)" :stroke="rgba(primitive.stroke)" :stroke-width="primitive.width" />
  <g v-else><defs><clipPath :id="clipId"><rect :x="primitive.bounds[0]" :y="primitive.bounds[1]" :width="primitive.bounds[2]" :height="primitive.bounds[3]" /></clipPath></defs><text :x="primitive.bounds[0] + primitive.bounds[2]/2" :y="primitive.bounds[1] + primitive.bounds[3]/2" text-anchor="middle" dominant-baseline="central" :fill="rgba(primitive.fill)" :font-size="(primitive.font_size ?? 8)*4/3" font-family="Microsoft YaHei UI" :clip-path="`url(#${clipId})`">{{ primitive.text }}</text></g>
</template>
