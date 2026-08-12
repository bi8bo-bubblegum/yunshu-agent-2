<!-- frontend/src/components/ConfirmDialog.vue —— 全局确认弹窗
     配合 src/api/confirm.ts 单例：确认/取消分别调用 confirmOk/confirmCancel，
     样式复用全局 modal-mask/modal/btn-danger，与各视图弹窗视觉统一。 -->
<script setup lang="ts">
import { confirmState, confirmOk, confirmCancel } from '../api/confirm'
</script>

<template>
  <div v-if="confirmState.show" class="modal-mask">
    <div class="modal" style="width:400px">
      <div class="modal-title">
        <span>{{ confirmState.title }}</span>
        <span v-if="confirmState.danger" class="tag tag-red">危险操作</span>
      </div>
      <div class="modal-body">
        <p style="margin:0;color:var(--foreground)">{{ confirmState.message }}</p>
      </div>
      <div class="modal-foot">
        <button class="btn" @click="confirmCancel">取消</button>
        <button class="btn" :class="confirmState.danger ? 'btn-danger' : 'btn-primary'" @click="confirmOk">确认</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-title { display: flex; align-items: center; gap: 8px; }
/* 全局 modal-mask 是 z-index 100，低于 toast-wrap 的 200：确认弹窗需盖在 toast 之上 */
.modal-mask { z-index: 300; }
</style>
