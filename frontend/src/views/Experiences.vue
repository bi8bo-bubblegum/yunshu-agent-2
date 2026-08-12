<script setup lang="ts">
import { ref, onMounted } from 'vue'
import client from '../api/client'
import { toast } from '../api/toast'
import { fmtDateTime } from '../api/format'
import type { ExperienceDetail, ExperienceItem } from '../api/types'
import Md from '../components/Md.vue'

const items = ref<ExperienceItem[]>([])
const showCreate = ref(false)
const uploading = ref(false)
const form = ref({ title: '', summary: '', content: '', tags: '' })
const detailTarget = ref<ExperienceDetail | null>(null)

onMounted(load)

async function load() {
  try {
    const { data } = await client.get<ExperienceItem[]>('/experiences')
    items.value = data
  } catch { /* ignore */ }
}

async function onUpload(e: Event) {
  const el = e.target as HTMLInputElement
  const file = el.files?.[0]
  if (!file) return
  uploading.value = true
  const form = new FormData()
  form.append('file', file)
  try {
    await client.post('/experiences/upload', form)
    toast('已生成经验草稿', 'success')
    await load()
  } catch (err: any) {
    toast(err.response?.data?.detail || '解析失败', 'error')
  } finally {
    uploading.value = false
    el.value = ''
  }
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

async function openDetail(e: ExperienceItem) {
  try {
    const { data } = await client.get<ExperienceDetail>(`/experiences/${e.id}`)
    detailTarget.value = data
  } catch (err: any) {
    toast(err.response?.data?.detail || '加载详情失败', 'error')
  }
}

const scopeTag: Record<string, string> = { personal: 'tag-gray', dept: 'tag-cyan', company: 'tag-purple' }
const statusTag: Record<string, string> = { draft: 'tag-gray', pending: 'tag-orange', approved: 'tag-green', rejected: 'tag-red' }
const scopeLabel: Record<string, string> = { personal: '个人', dept: '部门', company: '公司' }
const statusLabel: Record<string, string> = { draft: '草稿', pending: '审批中', approved: '已通过', rejected: '已驳回' }
</script>

<template>
  <div class="page-wrap">
    <div class="row-between mb-12">
      <p class="text-muted">个人经验沉淀 · 部门/公司层级晋升，经统一审批中心审核</p>
      <div class="row" style="gap:8px">
        <label class="btn">
          {{ uploading ? '解析中…' : '上传活动文件' }}
          <input type="file" style="display:none" accept=".pdf,.doc,.docx,.txt,.md" @change="onUpload" />
        </label>
        <button class="btn btn-primary" @click="showCreate = !showCreate">+ 沉淀经验</button>
      </div>
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
              <td><span class="tag" :class="scopeTag[e.scope] ?? 'tag-gray'">{{ scopeLabel[e.scope] ?? e.scope }}</span></td>
              <td><span class="tag" :class="statusTag[e.status] ?? 'tag-gray'">{{ statusLabel[e.status] ?? e.status }}</span></td>
              <td class="muted text-sm" style="max-width:280px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ e.summary }}</td>
              <td style="text-align:right;white-space:nowrap">
                <div class="row" style="justify-content:flex-end;gap:6px">
                  <button class="btn btn-sm" @click="openDetail(e)">查看</button>
                  <button class="btn btn-sm btn-danger" @click="removeItem(e)">删除</button>
                  <template v-if="e.scope === 'personal' && e.status === 'draft'">
                  <button class="btn btn-sm" @click="submit(e.id, e.title, 'dept')">晋升部门</button>
                  <button class="btn btn-sm" @click="submit(e.id, e.title, 'company')">晋升公司</button>
                  </template>
                  <span v-else class="muted text-sm">{{ statusLabel[e.status] ?? e.status }}</span>
                </div>
              </td>
            </tr>
            <tr v-if="!items.length">
              <td colspan="5"><div class="empty"><span class="icon">🧠</span>暂无经验，先沉淀第一条吧</div></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 详情弹窗 -->
    <div v-if="detailTarget" class="modal-mask">
      <div class="modal" style="width:640px">
        <div class="modal-title">
          <span>{{ detailTarget.title }}</span>
          <span class="tag" :class="scopeTag[detailTarget.scope] ?? 'tag-gray'">{{ scopeLabel[detailTarget.scope] ?? detailTarget.scope }}</span>
          <span class="tag" :class="statusTag[detailTarget.status] ?? 'tag-gray'">{{ statusLabel[detailTarget.status] ?? detailTarget.status }}</span>
        </div>
        <div class="modal-body col">
          <div class="row" style="flex-wrap:wrap;gap:6px">
            <span v-for="t in detailTarget.tags" :key="t" class="tag tag-cyan">{{ t }}</span>
            <span class="muted text-sm">事件时间：{{ detailTarget.event_time ?? '—' }}</span>
            <span class="muted text-sm">沉淀时间：{{ fmtDateTime(detailTarget.created_at) }}</span>
          </div>
          <p class="text-muted" style="margin:4px 0 0">{{ detailTarget.summary }}</p>
          <div class="card" style="background:var(--video-bg);padding:12px">
            <Md :content="detailTarget.content || '（无详细内容）'" />
          </div>
          <div v-if="detailTarget.result_metrics" class="card" style="background:var(--video-bg);padding:12px">
            <p class="text-muted text-sm" style="margin:0 0 6px">效果复盘</p>
            <pre class="mono" style="margin:0;font-size:12px">{{ JSON.stringify(detailTarget.result_metrics, null, 2) }}</pre>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn btn-primary" @click="detailTarget = null">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-wrap { padding: 20px; }
@media (max-width: 768px) {
  .page-wrap { padding: 12px; }
  /* 详情弹窗标题行（标题 + 2 个 tag）窄屏允许换行 */
  .modal-title { flex-wrap: wrap; row-gap: 6px; }
}
</style>
