<script setup lang="ts">
import {computed} from 'vue';
import type {FormulaImage} from '../api/explainability.js';
const props=defineProps<{image:FormulaImage;latex:string}>();
const style=computed(()=>({width:`${props.image.width}px`,maxWidth:'100%',aspectRatio:`${props.image.width} / ${props.image.height}`}));
</script>
<template><div class="explanation-formula"><img :src="image.src" :alt="latex" :width="image.width" :height="image.height" :style="style"/></div></template>
