<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import client from './api/client'
import { toasts } from './api/toast'
import type { User } from './api/types'

const route = useRoute()
const router = useRouter()

// 登录页为独立页：不渲染 app-shell（侧边栏/顶栏）
const isLogin = computed(() => route.path === '/login')

const navs = [
  { key: 'chat', label: '聊天工作台', path: '/chat' },
  { key: 'knowledge', label: '知识库', path: '/knowledge' },
  { key: 'experience', label: '经验中心', path: '/experiences' },
  { key: 'approval', label: '审批中心', path: '/approvals' },
  { key: 'org', label: '组织架构', path: '/org' },
  { key: 'config', label: '配置中心', path: '/configs' },
  { key: 'monitor', label: '监测中心', path: '/traces' },
]

// 移动端底部 Tab：4 个核心入口 + 「更多」展开全量导航抽屉（复用侧边栏）
const mobileTabs = [
  { key: 'chat', label: '聊天', path: '/chat' },
  { key: 'knowledge', label: '知识库', path: '/knowledge' },
  { key: 'approval', label: '审批', path: '/approvals' },
  { key: 'experience', label: '经验', path: '/experiences' },
]
const tabIcons: Record<string, string> = { chat: '💬', knowledge: '📚', approval: '🔔', experience: '🧠' }

const titleMap: Record<string, string> = {
  '/chat': '聊天工作台', '/knowledge': '知识库', '/experiences': '经验中心',
  '/approvals': '审批中心', '/org': '组织架构', '/configs': '配置中心', '/traces': '监测中心',
}

const me = ref<User | null>(null)
const pendingApprovals = ref(0)
// 移动端「更多」抽屉开关（复用侧边栏）
const moreOpen = ref(false)

// 登录态随路由同步：进入登录页清空用户，进入工作台重新拉取，
// 覆盖“登出后切换账号登录”仍显示上一账号的场景
watch(() => route.path, async () => {
  moreOpen.value = false // 任意路径变化都收起移动端抽屉（导航/浏览器后退/登出）
  if (route.path === '/login') {
    me.value = null
    pendingApprovals.value = 0
    return
  }
  if (!localStorage.getItem('token')) return
  try {
    const { data } = await client.get<User>('/auth/me')
    me.value = data
  } catch {
    me.value = null
    return
  }
  loadPending()
}, { immediate: true })

async function loadPending() {
  try {
    const { data } = await client.get('/approvals', { params: { status: 'pending' } })
    pendingApprovals.value = data.length
  } catch { /* ignore */ }
}

function logout() {
  localStorage.removeItem('token')
  router.push('/login')
}

// 统一导航：移动端点击任何导航/抽屉项先收起抽屉再跳转
function go(path: string) {
  moreOpen.value = false
  router.push(path)
}
</script>

<template>
  <!-- 登录页独立渲染（无 shell），其余页面走 app-shell -->
  <router-view v-if="isLogin" />
  <div v-else class="app-shell">
    <aside class="app-sidebar" :class="{ open: moreOpen }">
      <div class="sidebar-head show-mobile">
        <span class="text-muted text-sm">导航</span>
        <button class="icon-btn" aria-label="关闭导航" @click="moreOpen = false">✕</button>
      </div>
      <a class="brand-block" @click="go('/chat')">
        <span class="brand-mark">云</span>
        <span class="brand-text">
          <span class="brand-name">云枢 Agent</span>
          <span class="brand-sub">Multi-Agent Platform</span>
        </span>
      </a>
      <nav class="sidebar-nav">
        <p class="nav-label">核心工作</p>
        <a v-for="n in navs.slice(0, 3)" :key="n.key" class="nav-item"
           :data-active="route.path === n.path" @click="go(n.path)">
          <span class="nav-icon">●</span>
          <span>{{ n.label }}</span>
        </a>
        <p class="nav-label">组织与治理</p>
        <a v-for="n in navs.slice(3)" :key="n.key" class="nav-item"
           :data-active="route.path === n.path" @click="go(n.path)">
          <span class="nav-icon">●</span>
          <span>{{ n.label }}</span>
          <span v-if="n.key === 'approval' && pendingApprovals" class="nav-icon-dot">{{ pendingApprovals }}</span>
        </a>
      </nav>
      <div class="sidebar-foot">
        <div class="foot-user">
          <span class="avatar-sm">{{ me?.display_name?.slice(0, 1) || '云' }}</span>
          <div class="grow" style="min-width:0">
            <p class="foot-name">{{ me?.display_name || '未登录' }}</p>
            <p class="foot-sub">{{ me?.role_code || '' }}</p>
          </div>
          <button class="icon-btn" title="退出登录" @click="logout">
            <span style="font-size:15px">⏻</span>
          </button>
        </div>
      </div>
    </aside>
    <div class="app-main-col">
      <header class="app-topbar">
        <div class="topbar-left">
          <button class="icon-btn show-mobile" aria-label="打开导航" @click="moreOpen = true">☰</button>
          <div class="topbar-title">
            <p class="topbar-kicker hide-mobile">WORKSPACE</p>
            <h1 class="topbar-heading">{{ titleMap[route.path] || '云枢 Agent' }}</h1>
          </div>
        </div>
        <div class="topbar-actions">
          <button class="icon-btn hide-mobile" title="审批中心" @click="router.push('/approvals')">
            <span style="font-size:16px">🔔</span>
            <span v-if="pendingApprovals" class="dot-badge">{{ pendingApprovals }}</span>
          </button>
          <span class="avatar-sm hide-mobile">{{ me?.display_name?.slice(0, 1) || '云' }}</span>
        </div>
      </header>
      <div class="app-content">
        <!-- 聊天页 keep-alive：切到其他模块时保留流式对话状态，避免 agent 回复丢失/中断 -->
        <router-view v-slot="{ Component }">
          <keep-alive :include="['Chat']">
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </div>
    </div>
    <!-- 移动端底部 Tab：4 个核心入口 + 「更多」展开抽屉（复用侧边栏） -->
    <nav class="mobile-tabbar">
      <button v-for="t in mobileTabs" :key="t.key" class="tab-item"
              :data-active="route.path === t.path" @click="go(t.path)">
        <span class="tab-icon">{{ tabIcons[t.key] }}</span>
        <span class="tab-label">{{ t.label }}</span>
        <span v-if="t.key === 'approval' && pendingApprovals" class="dot-badge">{{ pendingApprovals }}</span>
      </button>
      <button class="tab-item" :data-active="moreOpen" @click="moreOpen = !moreOpen">
        <span class="tab-icon">⋯</span>
        <span class="tab-label">更多</span>
      </button>
    </nav>
    <div v-if="moreOpen" class="more-mask" @click="moreOpen = false"></div>
    <div class="toast-wrap">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="`toast-${t.kind}`">{{ t.text }}</div>
    </div>
  </div>
</template>

<style scoped>
.app-shell { display: flex; height: 100vh; height: 100dvh; overflow: hidden; background: var(--background); }
.app-sidebar { width: 232px; flex-shrink: 0; display: flex; flex-direction: column; background: var(--video-bg); border-right: 1px solid var(--border); }
.app-main-col { flex: 1; min-width: 0; display: flex; flex-direction: column; height: 100vh; height: 100dvh; }
.app-topbar { height: 56px; flex-shrink: 0; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 0 20px; border-bottom: 1px solid var(--border); background: var(--background); }
.topbar-left { display: flex; align-items: center; gap: 10px; min-width: 0; }
.app-content { flex: 1; min-height: 0; overflow-y: auto; }
/* 移动端底部 Tab 栏（<768px 才显示）与「更多」抽屉遮罩 */
.mobile-tabbar { display: none; }
.more-mask { position: fixed; inset: 0; z-index: 105; background: rgba(0, 0, 0, .6); }
.sidebar-head { display: none; }

.brand-block { display: flex; align-items: center; gap: 10px; height: 56px; padding: 0 16px; text-decoration: none; border-bottom: 1px solid var(--border); flex-shrink: 0; cursor: pointer; }
.brand-mark { width: 28px; height: 28px; border-radius: var(--radius-md); background: var(--primary); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 700; flex-shrink: 0; }
.brand-name { color: var(--foreground); font-size: 14px; font-weight: 600; line-height: 1.1; }
.brand-sub { display: block; color: var(--muted-foreground); font-family: var(--font-mono); font-size: 9px; letter-spacing: .14em; text-transform: uppercase; margin-top: 3px; }
.sidebar-nav { flex: 1; min-height: 0; overflow-y: auto; padding: 12px 10px 8px; }
.nav-label { margin: 0 10px 6px; font-family: var(--font-mono); font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: var(--muted-foreground); opacity: .85; }
.nav-label + .nav-label { margin-top: 14px; }
.nav-item { display: flex; align-items: center; gap: 10px; height: 38px; padding: 0 10px; border-radius: var(--radius-md); color: var(--muted-foreground); font-size: 13.5px; cursor: pointer; transition: background-color .18s ease, color .18s ease; }
.nav-item:hover { color: var(--foreground); background: var(--card); }
.nav-item[data-active="true"] { background: var(--card-elevated); color: var(--foreground); font-weight: 600; }
.nav-icon { width: 6px; height: 6px; border-radius: 999px; background: currentColor; opacity: .4; flex-shrink: 0; }
.nav-item[data-active="true"] .nav-icon { opacity: 1; background: var(--primary); }
.nav-icon-dot { margin-left: auto; min-width: 17px; height: 17px; padding: 0 5px; border-radius: 999px; background: var(--primary); color: #fff; font-size: 10px; font-weight: 700; line-height: 17px; text-align: center; }
.sidebar-foot { flex-shrink: 0; padding: 10px; border-top: 1px solid var(--border); }
.foot-user { display: flex; align-items: center; gap: 10px; padding: 4px 6px; }
.foot-name { margin: 0; font-size: 13px; font-weight: 600; line-height: 1.2; }
.foot-sub { margin: 2px 0 0; font-size: 11px; color: var(--muted-foreground); line-height: 1.2; }
.avatar-sm { width: 30px; height: 30px; border-radius: 999px; background: var(--primary); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; flex-shrink: 0; }
.topbar-title { display: flex; align-items: baseline; gap: 12px; min-width: 0; }
.topbar-kicker { margin: 0; font-family: var(--font-mono); font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: var(--muted-foreground); }
.topbar-heading { margin: 0; font-size: 16px; font-weight: 600; letter-spacing: -.01em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.topbar-actions { display: flex; align-items: center; gap: 10px; }
.icon-btn { position: relative; width: 34px; height: 34px; border-radius: var(--radius-md); border: 1px solid var(--border); background: var(--card); color: var(--muted-foreground); display: inline-flex; align-items: center; justify-content: center; cursor: pointer; }
.icon-btn:hover { color: var(--foreground); border-color: var(--muted-foreground); }
.dot-badge { position: absolute; top: -3px; right: -3px; min-width: 15px; height: 15px; padding: 0 4px; border-radius: 999px; background: var(--primary); color: #fff; font-size: 9px; font-weight: 700; line-height: 15px; text-align: center; border: 2px solid var(--background); }

@media (max-width: 1024px) {
  .app-sidebar { width: 64px; }
  .brand-text, .nav-label, .nav-item span { display: none; }
  .nav-item { justify-content: center; padding: 0; }
}

/* ===== 移动端（<768px）：侧边栏抽屉化 + 底部 Tab =====
   注意：1024 块把 .brand-text/.nav-label/.nav-item span 设为 display:none，
   <768 也会命中，这里必须显式恢复，否则抽屉里只剩图标。 */
@media (max-width: 768px) {
  .app-shell { flex-direction: column; }

  /* 侧边栏 → 左侧滑出抽屉 */
  .app-sidebar {
    position: fixed; top: 0; left: 0; bottom: 0;
    width: 280px; max-width: 85vw;
    transform: translateX(-100%);
    transition: transform .25s ease;
    z-index: 106;
    box-shadow: 20px 0 60px rgba(0, 0, 0, .4);
  }
  .app-sidebar.open { transform: none; }
  .sidebar-head { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
  /* 恢复 1024 块隐藏的文字（抽屉内需完整显示） */
  .app-sidebar .brand-text { display: block; }
  .app-sidebar .nav-label { display: block; }
  .app-sidebar .nav-item { justify-content: flex-start; padding: 0 10px; }
  .app-sidebar .nav-item span { display: inline; }
  .app-sidebar .nav-icon-dot { display: inline-block; margin-left: auto; }

  /* 主列：流内占满剩余高度（Tab 在下方流内占位，不遮挡内容） */
  .app-main-col { height: auto; min-height: 0; }
  .app-topbar { padding: 0 12px; }

  /* 底部 Tab 栏 */
  .mobile-tabbar {
    display: flex; align-items: stretch; flex-shrink: 0;
    height: calc(56px + env(safe-area-inset-bottom));
    padding-bottom: env(safe-area-inset-bottom);
    background: var(--video-bg);
    border-top: 1px solid var(--border);
  }
  .tab-item {
    flex: 1; position: relative;
    border: none; background: transparent; cursor: pointer;
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px;
    color: var(--muted-foreground); font-size: 10px;
    -webkit-tap-highlight-color: transparent; user-select: none;
  }
  .tab-item[data-active="true"] { color: var(--foreground); }
  .tab-icon { font-size: 17px; line-height: 1; }
  .mobile-tabbar .dot-badge { top: 4px; right: calc(50% - 24px); }
}
</style>
