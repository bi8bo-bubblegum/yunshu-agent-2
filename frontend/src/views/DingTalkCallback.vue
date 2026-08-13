<script setup lang="ts">
// 钉钉扫码登录回调页（M2，新版 OAuth2）：login.dingtalk.com/oauth2/auth 授权后
// 回跳到 /dingtalk/callback?code=&state=，用 code 换后端 JWT
// 用 code 换后端 JWT，成功后进工作台；state 校验防 CSRF。
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import client from '../api/client'
import { toast } from '../api/toast'

const route = useRoute()
const router = useRouter()

onMounted(async () => {
  const code = route.query.code as string | undefined
  const state = route.query.state as string | undefined
  const storedState = sessionStorage.getItem('dingtalk_state')

  // 调试：打印参数方便排查
  console.log('[callback] code:', code)
  console.log('[callback] state:', state)
  console.log('[callback] storedState:', storedState)
  console.log('[callback] match:', state === storedState)

  // state 与登录页跳转前存入的一致才算合法回调
  if (!code) {
    console.error('[callback] 缺少 code 参数')
    router.replace('/login')
    return
  }
  if (!state || state !== storedState) {
    console.error('[callback] state 校验失败', { state, storedState })
    router.replace('/login')
    return
  }

  sessionStorage.removeItem('dingtalk_state')

  try {
    const { data } = await client.post('/auth/dingtalk', { mode: 'scan', code })
    console.log('[callback] 登录成功:', data)
    localStorage.setItem('token', data.access_token)
    router.replace('/chat')
  } catch (e: any) {
    console.error('[callback] 登录失败:', e)
    console.error('[callback] 完整响应:', e.response)
    const detail = e.response?.data?.detail || e.message || '钉钉登录失败'
    toast(detail, 'error')
    console.error('[callback] 错误详情:', detail)
    // 延迟跳转，让用户看到错误信息
    setTimeout(() => router.replace('/login'), 3000)
  }
})
</script>

<template>
  <div class="callback-page">
    <span class="spinner"></span>
    <p>钉钉登录中…</p>
  </div>
</template>

<style scoped>
.callback-page {
  min-height: 100vh; min-height: 100dvh; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 16px;
  background: var(--background); color: var(--muted-foreground); font-size: 14px;
}
.spinner {
  width: 28px; height: 28px; border-radius: 999px;
  border: 2px solid var(--border); border-top-color: var(--primary);
  animation: spin .8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg) } }
</style>
