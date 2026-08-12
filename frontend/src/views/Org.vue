<script setup lang="ts">
import { ref, onMounted } from 'vue'
import client from '../api/client'
import { toast } from '../api/toast'
import type { Department, User } from '../api/types'

const departments = ref<Department[]>([])
const users = ref<User[]>([])
const showCreateDept = ref(false)
const newDeptName = ref('')
// 分配角色/部门弹窗：编辑目标 + 表单（department_id 空串表示无部门）
const editUser = ref<User | null>(null)
const editForm = ref({ role_code: 'member', department_id: '' })

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

// 角色选项：与后端 ROLES（member/dept_owner/admin）一致；roleTag 修复 staff 残留映射
const roleLabel: Record<string, string> = { member: '成员', dept_owner: '部门负责人', admin: '公司管理员' }
const roleTag: Record<string, string> = { admin: 'tag-red', dept_owner: 'tag-orange', member: 'tag-blue' }
const roleOptions = [
  { value: 'member', label: '成员' },
  { value: 'dept_owner', label: '部门负责人' },
  { value: 'admin', label: '公司管理员' },
]

function openEditUser(u: User) {
  editUser.value = u
  editForm.value = { role_code: u.role_code || 'member', department_id: u.department_id || '' }
}

async function saveEditUser() {
  const u = editUser.value
  if (!u) return
  try {
    await client.patch(`/users/${u.id}`, {
      role_code: editForm.value.role_code || null,
      department_id: editForm.value.department_id || null,
    })
    toast(`已更新用户「${u.username}」的角色与部门`, 'success')
    editUser.value = null
    await loadUsers()
  } catch (err: any) {
    toast(err.response?.data?.detail || '保存失败', 'error')
  }
}
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
            <thead><tr><th>用户名</th><th>显示名</th><th>角色</th><th>部门</th><th style="text-align:right">操作</th></tr></thead>
            <tbody>
              <tr v-for="u in users" :key="u.id">
                <td class="mono text-sm">{{ u.username }}</td>
                <td>{{ u.display_name }}</td>
                <td><span class="tag" :class="roleTag[u.role_code] ?? 'tag-gray'">{{ roleLabel[u.role_code] ?? u.role_code ?? '—' }}</span></td>
                <td class="muted text-sm">{{ departments.find(d => d.id === u.department_id)?.name || '—' }}</td>
                <td style="text-align:right;white-space:nowrap">
                  <button class="btn btn-sm" @click="openEditUser(u)">分配</button>
                </td>
              </tr>
              <tr v-if="!users.length"><td colspan="5"><div class="empty"><span class="icon">👤</span>暂无用户</div></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 分配角色与部门弹窗（仅 admin 可操作，后端兜底校验） -->
    <div v-if="editUser" class="modal-mask">
      <div class="modal" style="width:420px">
        <div class="modal-title"><span>分配角色与部门：{{ editUser.username }}</span></div>
        <div class="modal-body col">
          <p class="text-muted text-sm" style="margin:0 0 4px">角色</p>
          <select class="select" v-model="editForm.role_code">
            <option v-for="r in roleOptions" :key="r.value" :value="r.value">{{ r.label }}</option>
          </select>
          <p class="text-muted text-sm" style="margin:8px 0 4px">所属部门</p>
          <select class="select" v-model="editForm.department_id">
            <option value="">无部门</option>
            <option v-for="d in departments" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
        </div>
        <div class="modal-foot">
          <button class="btn btn-primary" @click="saveEditUser">保存</button>
          <button class="btn" @click="editUser = null">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-wrap { padding: 20px; height: calc(100vh - 56px); height: calc(100dvh - 56px); box-sizing: border-box; display: flex; flex-direction: column; }
.page-grid { flex: 1; min-height: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
/* 部门与用户各自独立滚动，互不影响 */
.page-grid > .card { min-height: 0; overflow-y: auto; }
@media (max-width: 1100px) {
  .page-grid { grid-template-columns: 1fr; overflow-y: auto; }
  .page-grid > .card { overflow-y: visible; }
}
@media (max-width: 768px) {
  /* 移动端 shell 变 column + 底部 Tab 占流内高度，calc(100dvh - 56px) 不再等于内容区高度；
     改 height:auto 让整页由 .app-content 单容器滚动，消除双滚动 */
  .page-wrap { height: auto; padding: 12px; }
  .page-grid { overflow-y: visible; }
}
</style>
