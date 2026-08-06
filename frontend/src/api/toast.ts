// frontend/src/api/toast.ts —— 全局轻量 Toast
import { reactive } from 'vue'

export interface ToastMsg { id: number; text: string; kind: 'success' | 'error' | 'info' }
const toasts = reactive<ToastMsg[]>([])
let seq = 0

export function toast(text: string, kind: ToastMsg['kind'] = 'info') {
  const id = ++seq
  toasts.push({ id, text, kind })
  setTimeout(() => {
    const i = toasts.findIndex(t => t.id === id)
    if (i >= 0) toasts.splice(i, 1)
  }, 3200)
}

export { toasts }
