<script setup lang="ts">
// 钉钉扫码登录回调页（M2）：qrconnect 授权后回跳到 /dingtalk/callback?code=&state=
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
  // state 与登录页跳转前存入的一致才算合法回调
  if (!code || !state || state !== sessionStorage.getItem('dingtalk_state')) {
    toast('钉钉登录回调无效，请重新扫码', 'error')
    router.replace('/login')
    return
  }
  sessionStorage.removeItem('dingtalk_state')
  try {
    const { data } = await client.post('/auth/dingtalk', { mode: 'scan', code })
    localStorage.setItem('token', data.access_token)
    router.replace('/chat')
  } catch (e: any) {
    toast(e.response?.data?.detail || '钉钉登录失败', 'error')
    router.replace('/login')
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
