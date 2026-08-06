// frontend/src/router.ts —— 路由 + 登录守卫
// 平级路由：login 独立页（App.vue 按 isLogin 条件跳过 app-shell 渲染）
import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/login', component: () => import('./views/Login.vue'), meta: { public: true } },
    { path: '/chat', component: () => import('./views/Chat.vue') },
    { path: '/knowledge', component: () => import('./views/Knowledge.vue') },
    { path: '/experiences', component: () => import('./views/Experiences.vue') },
    { path: '/approvals', component: () => import('./views/Approvals.vue') },
    { path: '/org', component: () => import('./views/Org.vue') },
    { path: '/configs', component: () => import('./views/Configs.vue') },
    { path: '/traces', component: () => import('./views/Traces.vue') },
  ],
})

router.beforeEach(to => {
  const token = localStorage.getItem('token')
  if (!to.meta.public && !token) return '/login'
  if (to.path === '/login' && token) return '/chat'
  return true
})

export default router
