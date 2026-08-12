// frontend/src/api/confirm.ts —— 全局确认弹窗（替代浏览器原生 confirm 提示框）
// 与 toast 同为全局单例：askConfirm 弹出弹窗并返回 Promise，确认/取消后 resolve。
import { reactive } from 'vue'

export interface ConfirmOptions {
  title?: string
  message: string
  danger?: boolean  // 危险操作：确认按钮红色 + 标题栏「危险操作」标记
}
interface ConfirmState {
  show: boolean
  title: string
  message: string
  danger: boolean
  resolve?: (v: boolean) => void
}
const state = reactive<ConfirmState>({ show: false, title: '确认操作', message: '', danger: false })

/** 弹出确认框，返回用户点击「确认」/「取消」的结果（Promise<boolean>）。 */
export function askConfirm(opts: ConfirmOptions): Promise<boolean> {
  if (opts.title) state.title = opts.title
  state.message = opts.message
  state.danger = opts.danger ?? false
  state.show = true
  return new Promise(resolve => { state.resolve = resolve })
}

function settle(v: boolean) {
  state.show = false
  state.resolve?.(v)
  state.resolve = undefined
}
export function confirmOk() { settle(true) }
export function confirmCancel() { settle(false) }
export { state as confirmState }
