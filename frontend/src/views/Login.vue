<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import client from '../api/client'
import { toast } from '../api/toast'

const router = useRouter()
const mode = ref<'login' | 'register'>('login')
const username = ref('')
const password = ref('')
const displayName = ref('')
const loading = ref(false)
const showPwd = ref(false)

// 钉钉扫码登录（M2）：enabled 时才显示入口；跳转 qrconnect 授权页后回跳 /dingtalk/callback
const dingtalkEnabled = ref(false)
const dingtalkClientId = ref('')
onMounted(async () => {
  try {
    const { data } = await client.get('/auth/dingtalk/config')
    dingtalkEnabled.value = !!data.enabled
    dingtalkClientId.value = data.client_id || ''
  } catch { /* 未配置钉钉时保持隐藏 */ }
})

function dingtalkLogin() {
  // state 随机串存 sessionStorage，回调页校验防止 CSRF
  const state = Math.random().toString(36).slice(2)
  sessionStorage.setItem('dingtalk_state', state)
  const redirectUri = `${window.location.origin}/dingtalk/callback`
  const params = new URLSearchParams({
    appid: dingtalkClientId.value,
    response_type: 'code',
    scope: 'snsapi_login',
    state,
    redirect_uri: redirectUri,
  })
  location.href = `https://oapi.dingtalk.com/connect/qrconnect?${params}`
}

async function submit() {
  if (!username.value || !password.value) return toast('请输入账号和密码', 'error')
  loading.value = true
  try {
    if (mode.value === 'login') {
      const { data } = await client.post('/auth/login', { username: username.value, password: password.value })
      localStorage.setItem('token', data.access_token)
      router.push('/chat')
    } else {
      await client.post('/auth/register', {
        username: username.value, password: password.value,
        display_name: displayName.value || username.value,
      })
      toast('注册成功，请登录', 'success')
      mode.value = 'login'
    }
  } catch (e: any) {
    toast(e.response?.data?.detail || '操作失败', 'error')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <!-- ===== 左 · 品牌编辑面板 ===== -->
    <section class="brand-panel">
      <div aria-hidden="true" class="grid-overlay"></div>
      <div aria-hidden="true" class="glow glow-primary"></div>
      <div aria-hidden="true" class="glow glow-secondary"></div>

      <div class="brand-panel-inner">
        <div class="brand-row">
          <span class="brand-logo">云</span>
          <div class="brand-title-group">
            <span class="brand-name">云枢 Agent</span>
            <span class="brand-en">Multi-Agent Platform</span>
          </div>
        </div>

        <div class="story">
          <p class="kicker">Supervisor · Agent Orchestration</p>
          <h1 class="story-title">让每个决策，<br />都有 <em class="em-primary">记忆</em> 与 <em class="em-secondary">依据</em></h1>
          <p class="story-desc">云枢 Agent 以 Supervisor 统一调度专业 Agent，自动召回四层记忆并结合企业数据综合分析；高风险操作人工确认，全链路执行留痕、可回放。</p>

          <ul class="caps">
            <li class="cap">
              <span class="cap-dot"></span>
              <div>
                <div class="cap-label">Supervisor 路由</div>
                <div class="cap-desc">意图识别与多 Agent 分发</div>
              </div>
            </li>
            <li class="cap">
              <span class="cap-dot"></span>
              <div>
                <div class="cap-label">Four-Layer Memory</div>
                <div class="cap-desc">偏好 / 经验 / 知识四层记忆召回</div>
              </div>
            </li>
            <li class="cap">
              <span class="cap-dot"></span>
              <div>
                <div class="cap-label">Hitl + Trace</div>
                <div class="cap-desc">高风险人工确认与全链路回放</div>
              </div>
            </li>
          </ul>
        </div>

        <div class="brand-foot">
          <span>版本 v2.4.0</span>
          <span class="sep">·</span>
          <span>企业内测</span>
          <span class="sep">·</span>
          <span>© 2026 云数科技</span>
        </div>
      </div>
    </section>

    <!-- ===== 右 · 认证面板 ===== -->
    <section class="auth-panel">
      <div class="auth-inner">
        <p class="kicker">Sign In</p>
        <h2 class="auth-title">{{ mode === 'login' ? '登录云枢 Agent' : '创建账户' }}</h2>
        <p class="auth-sub">{{ mode === 'login' ? '账号由企业管理员开通，支持 SSO 单点登录' : '注册后即可使用企业多 Agent 协作平台' }}</p>

        <form class="auth-form" @submit.prevent="submit">
          <div class="field">
            <label class="field-label" for="login-account">账号</label>
            <input id="login-account" class="input" v-model="username" type="text"
                   placeholder="邮箱或工号" autocomplete="username" />
          </div>

          <div class="field">
            <label class="field-label" for="login-password">密码</label>
            <div class="pwd-wrap">
              <input id="login-password" class="input" v-model="password"
                     :type="showPwd ? 'text' : 'password'"
                     placeholder="请输入密码" autocomplete="current-password" />
              <button type="button" class="pwd-toggle" :aria-label="showPwd ? '隐藏密码' : '显示密码'"
                      @click="showPwd = !showPwd">{{ showPwd ? '👁' : '🙈' }}</button>
            </div>
          </div>

          <div v-if="mode === 'register'" class="field">
            <label class="field-label" for="login-name">显示名称（可选）</label>
            <input id="login-name" class="input" v-model="displayName" type="text" placeholder="将显示在侧边栏" />
          </div>

          <div class="row-between">
            <label class="remember">
              <input type="checkbox" checked class="remember-check" />
              <span>记住我</span>
            </label>
            <a href="#" class="link" @click.prevent>忘记密码？</a>
          </div>

          <button class="login-btn" :disabled="loading" type="submit">
            <span v-if="loading" class="spinner"></span>{{ mode === 'login' ? '登 录' : '注 册' }}
          </button>

          <div class="divider">
            <span class="divider-line"></span>
            <span class="divider-text">或使用钉钉扫码登录</span>
            <span class="divider-line"></span>
          </div>

          <button v-if="dingtalkEnabled" type="button" class="sso-btn" :disabled="loading" @click="dingtalkLogin">
            <span class="sso-icon">💙</span>钉钉扫码登录
          </button>
          <button v-else type="button" class="sso-btn" :disabled="loading"
                  @click="toast('企业 SSO 尚未开通，请联系管理员配置钉钉', 'info')">
            <span class="sso-icon">🛡</span>通过企业 SSO 登录
          </button>

          <p class="auth-foot">
            {{ mode === 'login' ? '还没有账号？' : '已有账号？' }}
            <a href="#" class="link" @click.prevent="mode = mode === 'login' ? 'register' : 'login'">
              {{ mode === 'login' ? '立即注册' : '去登录' }}
            </a>
          </p>
          <p class="demo-note">演示账号 admin@yunshu.cn · 密码随意 · 数据加密传输 · 等保三级</p>
        </form>
      </div>
    </section>
  </div>
</template>

<style scoped>
.login-page { display: flex; min-height: 100vh; min-height: 100dvh; width: 100%; background: var(--background); }

/* ===== 左 · 品牌面板 ===== */
.brand-panel {
  position: relative; display: none; width: 55%; min-height: 100vh; overflow: hidden;
  background: var(--video-bg); border-right: 1px solid var(--border);
}
@media (min-width: 1024px) { .brand-panel { display: flex; } }
.grid-overlay {
  position: absolute; inset: 0; pointer-events: none;
  background-image:
    linear-gradient(color-mix(in srgb, var(--border) 30%, transparent) 1px, transparent 1px),
    linear-gradient(90deg, color-mix(in srgb, var(--border) 30%, transparent) 1px, transparent 1px);
  background-size: 48px 48px;
}
.glow { position: absolute; width: 384px; height: 384px; border-radius: 999px; pointer-events: none; }
.glow-primary { top: -128px; left: -128px; background: radial-gradient(circle, color-mix(in srgb, var(--primary) 12%, transparent) 0%, transparent 70%); }
.glow-secondary { bottom: -128px; right: -128px; background: radial-gradient(circle, color-mix(in srgb, var(--secondary) 10%, transparent) 0%, transparent 70%); }

.brand-panel-inner {
  position: relative; z-index: 1; display: flex; flex-direction: column; justify-content: space-between;
  min-height: 100vh; width: 100%; padding: 48px 64px;
}
.brand-row { display: flex; align-items: center; gap: 12px; }
.brand-title-group { display: flex; align-items: baseline; gap: 12px; }
.brand-logo {
  width: 32px; height: 32px; border-radius: var(--radius-md); flex-shrink: 0;
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--primary); color: #fff; font-size: 15px; font-weight: 600;
}
.brand-name { font-size: 16px; font-weight: 600; color: var(--foreground); }
.brand-en { font-size: 10px; text-transform: uppercase; color: var(--muted-foreground); font-family: var(--font-mono); letter-spacing: .14em; }

.story { padding: 64px 0; }
.kicker {
  margin: 0 0 20px; font-size: 11px; text-transform: uppercase; letter-spacing: .14em;
  font-family: var(--font-mono); color: var(--muted-foreground);
}
.story-title {
  margin: 0; font-size: clamp(44px, 4.5vw, 56px); line-height: 1.05; letter-spacing: -.02em;
  font-weight: 700; color: var(--foreground);
}
.em-primary { font-style: normal; color: var(--primary); }
.em-secondary { font-style: normal; color: var(--secondary); }
.story-desc { margin: 28px 0 0; max-width: 460px; font-size: 14px; line-height: 1.7; color: var(--muted-foreground); }

.caps { list-style: none; margin: 40px 0 0; padding: 0; display: flex; flex-direction: column; gap: 20px; }
.cap { display: flex; align-items: flex-start; gap: 12px; }
.cap-dot { margin-top: 7px; width: 6px; height: 6px; border-radius: 999px; flex-shrink: 0; background: var(--primary); }
.cap-label { font-size: 11px; text-transform: uppercase; letter-spacing: .14em; font-family: var(--font-mono); color: var(--foreground); }
.cap-desc { margin-top: 4px; font-size: 14px; color: var(--muted-foreground); line-height: 1.6; }

.brand-foot { display: flex; align-items: center; gap: 8px; font-size: 11px; font-family: var(--font-mono); letter-spacing: .1em; color: var(--muted-foreground); }
.sep { color: var(--border); }

/* ===== 右 · 认证面板 ===== */
.auth-panel { display: flex; width: 100%; align-items: center; justify-content: center; padding: 48px 20px; }
@media (min-width: 1024px) { .auth-panel { width: 45%; padding: 48px 32px; } }
.auth-inner { width: 100%; max-width: 400px; }
.auth-title { margin: 12px 0 0; font-size: 28px; font-weight: 600; line-height: 1.2; letter-spacing: -.01em; color: var(--foreground); }
.auth-sub { margin: 8px 0 0; font-size: 14px; line-height: 1.6; color: var(--muted-foreground); }

.auth-form { margin-top: 32px; display: flex; flex-direction: column; gap: 20px; }
.field-label { display: block; margin-bottom: 8px; font-size: 13px; font-weight: 500; color: var(--foreground); }
.pwd-wrap { position: relative; }
.pwd-wrap .input { padding-right: 44px; }
.pwd-toggle {
  position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
  width: 28px; height: 28px; border: 0; background: transparent; cursor: pointer;
  font-size: 14px; display: inline-flex; align-items: center; justify-content: center;
}
.row-between { display: flex; align-items: center; justify-content: space-between; }
.remember { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted-foreground); cursor: pointer; }
.remember-check { width: 16px; height: 16px; accent-color: var(--primary); cursor: pointer; }
.link { font-size: 13px; color: var(--muted-foreground); text-decoration: none; transition: color .18s; }
.link:hover { color: var(--foreground); }

.login-btn {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  height: 40px; width: 100%; border: 0; border-radius: var(--radius-md);
  background: var(--primary); color: #fff; font-size: 14px; font-weight: 600;
  cursor: pointer; transition: background .18s;
}
.login-btn:hover:not(:disabled) { background: var(--primary-hover); }
.login-btn:disabled { opacity: .6; cursor: not-allowed; }

.divider { display: flex; align-items: center; gap: 12px; padding: 4px 0; }
.divider-line { height: 1px; flex: 1; background: var(--border); }
.divider-text { font-size: 11px; font-family: var(--font-mono); letter-spacing: .14em; color: var(--muted-foreground); }

.sso-btn {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  height: 40px; width: 100%; border-radius: var(--radius-md);
  border: 1px solid var(--border); background: transparent; color: var(--foreground);
  font-size: 14px; font-weight: 500; cursor: pointer; transition: background .18s;
}
.sso-btn:hover:not(:disabled) { background: var(--card-elevated); }
.sso-btn:disabled { opacity: .6; cursor: not-allowed; }
.sso-icon { font-size: 15px; }

.auth-foot { margin: 0; padding-top: 8px; text-align: center; font-size: 14px; color: var(--muted-foreground); }
.auth-foot .link { color: var(--secondary); }
.demo-note {
  margin: 0; text-align: center; font-size: 11px; font-family: var(--font-mono); letter-spacing: .08em; line-height: 1.6; color: var(--muted-foreground);
}
</style>
