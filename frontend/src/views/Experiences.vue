<script setup lang="ts">
import { ref, onMounted } from 'vue'
import client from '../api/client'
import { toast } from '../api/toast'
import type { ExperienceItem } from '../api/types'

const items = ref<ExperienceItem[]>([])
const showCreate = ref(false)
const form = ref({ title: '', summary: '', content: '', tags: '' })

onMounted(load)

async function load() {
  try {
    const { data } = await client.get<ExperienceItem[]>('/experiences')
    items.value = data
  } catch { /* ignore */ }
}

async function create() {
  if (!form.value.title.trim()) return toast('请输入标题', 'error')
  try {
    await client.post('/experiences', {
      title: form.value.title, summary: form.value.summary,
      content: form.value.content,
      tags: form.value.tags.split(/[,，]/).map(s => s.trim()).filter(Boolean),
    })
    toast('经验已创建（个人层草稿）', 'success')
    showCreate.value = false
    form.value = { title: '', summary: '', content: '', tags: '' }
    await load()
  } catch (err: any) {
    toast(err.response?.data?.detail || '创建失败', 'error')
  }
}

async function submit(id: string, title: string, toScope: 'dept' | 'company') {
  if (!confirm(`将「${title}」提交至${toScope === 'dept' ? '部门' : '公司'}层晋升审批？`)) return
  try {
    await client.post(`/experiences/${id}/submit`, { to_scope: toScope })
    toast('已提交审批，等待管理员审核', 'success')
    await load()
  } catch (err: any) {
    toast(err.response?.data?.detail || '提交失败', 'error')
  }
}

async function removeItem(e: ExperienceItem) {
  if (!confirm(`确认删除经验「${e.title}」？删除后不可恢复`)) return
  try {
    await client.delete(`/experiences/${e.id}`)
    toast('经验已删除', 'success')
    await load()
  } catch (err: any) {
    toast(err.response?.data?.detail || '删除失败', 'error')
  }
}

const scopeTag: Record<string, string> = { personal: 'tag-gray', dept: 'tag-cyan', company: 'tag-purple' }
const statusTag: Record<string, string> = { draft: 'tag-gray', pending: 'tag-orange', approved: 'tag-green', rejected: 'tag-red' }
</script>

<template>
  <div class="page-wrap">
    <div class="row-between mb-12">
      <p class="text-muted">个人经验沉淀 · 部门/公司层级晋升，经统一审批中心审核</p>
      <button class="btn btn-primary" @click="showCreate = !showCreate">+ 沉淀经验</button>
    </div>

    <div v-if="showCreate" class="card mb-12">
      <h3 class="card-title">新建经验</h3>
      <div class="col">
        <input class="input" v-model="form.title" placeholder="标题：一句话概括经验" />
        <input class="input" v-model="form.summary" placeholder="摘要：供检索与审批展示" />
        <textarea class="textarea" v-model="form.content" placeholder="详细内容：背景、做法、结果" />
        <input class="input" v-model="form.tags" placeholder="标签，逗号分隔，如：营销,复盘" />
        <div class="row">
          <button class="btn btn-primary" @click="create">保存</button>
          <button class="btn" @click="showCreate = false">取消</button>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>标题</th><th>层级</th><th>状态</th><th>摘要</th><th style="text-align:right">操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="e in items" :key="e.id">
              <td style="max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ e.title }}</td>
              <td><span class="tag" :class="scopeTag[e.scope] ?? 'tag-gray'">{{ e.scope }}</span></td>
              <td><span class="tag" :class="statusTag[e.status] ?? 'tag-gray'">{{ e.status }}</span></td>
              <td class="muted text-sm" style="max-width:280px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ e.summary }}</td>
              <td style="text-align:right">
                <span v-if="e.scope === 'personal' && e.status === 'draft'" class="row" style="justify-content:flex-end">
                  <button class="btn btn-sm" @click="submit(e.id, e.title, 'dept')">晋升部门</button>
                  <button class="btn btn-sm" @click="submit(e.id, e.title, 'company')">晋升公司</button>
                </span>
                <span v-else class="muted text-sm">{{ e.status === 'pending' ? '审批中' : e.status }}</span>
                <button class="btn btn-sm btn-danger" style="margin-left:8px" @click="removeItem(e)">删除</button>
              </td>
            </tr>
            <tr v-if="!items.length">
              <td colspan="5"><div class="empty"><span class="icon">🧠</span>暂无经验，先沉淀第一条吧</div></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-wrap { padding: 20px; }
</style>
