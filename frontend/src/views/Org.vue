<script setup lang="ts">
import { ref, onMounted } from 'vue'
import client from '../api/client'
import { toast } from '../api/toast'
import type { Department, User } from '../api/types'

const departments = ref<Department[]>([])
const users = ref<User[]>([])
const showCreateDept = ref(false)
const newDeptName = ref('')

onMounted(async () => {
  await Promise.all([loadDepts(), loadUsers()])
})

async function loadDepts() {
  try {
    const { data } = await client.get<Department[]>('/departments')
    departments.value = data
  } catch { /* ignore */ }
}

async function loadUsers() {
  try {
    const { data } = await client.get<User[]>('/users')
    users.value = data
  } catch { /* ignore */ }
}

async function createDept() {
  if (!newDeptName.value.trim()) return toast('请输入部门名称', 'error')
  try {
    await client.post('/departments', { name: newDeptName.value.trim() })
    toast('部门已创建', 'success')
    newDeptName.value = ''
    showCreateDept.value = false
    await loadDepts()
  } catch (err: any) {
    toast(err.response?.data?.detail || '创建失败', 'error')
  }
}

const roleTag: Record<string, string> = { admin: 'tag-red', dept_owner: 'tag-orange', staff: 'tag-blue' }
</script>

<template>
  <div class="page-wrap">
    <div class="page-grid">
      <!-- 部门 -->
      <div class="card">
        <div class="row-between mb-12">
          <h3 class="card-title" style="margin:0">部门</h3>
          <button class="btn btn-sm btn-primary" @click="showCreateDept = !showCreateDept">+ 新建部门</button>
        </div>
        <div v-if="showCreateDept" class="row mb-12">
          <input class="input grow" v-model="newDeptName" placeholder="部门名称" @keyup.enter="createDept" />
          <button class="btn btn-primary" @click="createDept">保存</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>名称</th><th>ID</th></tr></thead>
            <tbody>
              <tr v-for="d in departments" :key="d.id">
                <td>{{ d.name }}</td>
                <td class="muted mono text-sm">{{ d.id.slice(0, 8) }}</td>
              </tr>
              <tr v-if="!departments.length"><td colspan="2"><div class="empty"><span class="icon">🏢</span>暂无部门</div></td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 用户 -->
      <div class="card">
        <h3 class="card-title">用户</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>用户名</th><th>显示名</th><th>角色</th><th>部门</th></tr></thead>
            <tbody>
              <tr v-for="u in users" :key="u.id">
                <td class="mono text-sm">{{ u.username }}</td>
                <td>{{ u.display_name }}</td>
                <td><span class="tag" :class="roleTag[u.role_code] ?? 'tag-gray'">{{ u.role_code }}</span></td>
                <td class="muted text-sm">{{ departments.find(d => d.id === u.department_id)?.name || '—' }}</td>
              </tr>
              <tr v-if="!users.length"><td colspan="4"><div class="empty"><span class="icon">👤</span>暂无用户</div></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-wrap { padding: 20px; height: calc(100vh - 56px); box-sizing: border-box; display: flex; flex-direction: column; }
.page-grid { flex: 1; min-height: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
/* 部门与用户各自独立滚动，互不影响 */
.page-grid > .card { min-height: 0; overflow-y: auto; }
@media (max-width: 1100px) {
  .page-grid { grid-template-columns: 1fr; overflow-y: auto; }
  .page-grid > .card { overflow-y: visible; }
}
</style>
