<script setup lang="ts">
import { ref, onMounted } from 'vue'
import client from '../api/client'
import { toast } from '../api/toast'
import type { DocumentItem, SearchHit } from '../api/types'

const docs = ref<DocumentItem[]>([])
const query = ref('')
const results = ref<SearchHit[]>([])
const searching = ref(false)
const uploading = ref(false)

onMounted(loadDocs)

async function loadDocs() {
  try {
    const { data } = await client.get<DocumentItem[]>('/documents')
    docs.value = data
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
    await client.post('/documents', form)
    toast('上传成功，正在解析入库', 'success')
    await loadDocs()
  } catch (err: any) {
    toast(err.response?.data?.detail || '上传失败', 'error')
  } finally {
    uploading.value = false
    el.value = ''
  }
}

async function removeDoc(id: string, title: string) {
  if (!confirm(`确认删除文档「${title}」？`) ) return
  try {
    await client.delete(`/documents/${id}`)
    toast('已删除', 'success')
    await loadDocs()
  } catch (err: any) {
    toast(err.response?.data?.detail || '删除失败', 'error')
  }
}

async function search() {
  if (!query.value.trim()) return
  searching.value = true
  try {
    const { data } = await client.post('/kb/search', { query: query.value })
    results.value = data.results
  } catch (err: any) {
    toast(err.response?.data?.detail || '检索失败', 'error')
  } finally {
    searching.value = false
  }
}

const statusTag: Record<string, string> = { ready: 'tag-green', parsing: 'tag-blue', failed: 'tag-red' }
</script>

<template>
  <div class="page-wrap">
    <div class="page-grid">
      <!-- 左：文档库 -->
      <div class="card">
        <div class="row-between mb-12">
          <h3 class="card-title" style="margin:0">文档库</h3>
          <label class="btn btn-primary btn-sm" :class="{ 'is-disabled': uploading }">
            {{ uploading ? '上传中…' : '+ 上传文档' }}
            <input type="file" style="display:none" @change="onUpload" />
          </label>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>标题</th><th>状态</th><th>时间</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="d in docs" :key="d.id">
                <td>{{ d.title }}</td>
                <td><span class="tag" :class="statusTag[d.status] ?? 'tag-gray'">{{ d.status }}</span></td>
                <td class="muted text-sm">{{ d.created_at?.slice(0, 16) }}</td>
                <td style="text-align:right">
                  <button class="btn btn-danger btn-sm" @click="removeDoc(d.id, d.title)">删除</button>
                </td>
              </tr>
              <tr v-if="!docs.length"><td colspan="4"><div class="empty"><span class="icon">📄</span>暂无文档，上传后供 Agent 知识检索</div></td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 右：检索测试 -->
      <div class="card">
        <h3 class="card-title">检索测试</h3>
        <div class="row">
          <input class="input grow" v-model="query" placeholder="输入问题，测试知识检索命中" @keyup.enter="search" />
          <button class="btn btn-primary" :disabled="!query.trim() || searching" @click="search">
            <span v-if="searching" class="spinner"></span>检索
          </button>
        </div>
        <div class="col mt-16">
          <div v-for="r in results" :key="r.id" class="hit">
            <div class="row-between">
              <span class="tag tag-cyan">score {{ r.score }}</span>
              <span class="muted text-sm mono">doc: {{ r.document_id.slice(0, 8) }}</span>
            </div>
            <p class="hit-content">{{ r.content }}</p>
          </div>
          <div v-if="searching" class="loading-row"><span class="spinner"></span>检索中…</div>
          <div v-else-if="!results.length && query" class="empty"><span class="icon">🔍</span>无命中结果</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-wrap { padding: 20px; }
.page-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
@media (max-width: 1100px) { .page-grid { grid-template-columns: 1fr; } }
.hit { background: var(--video-bg); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 12px; }
.hit-content { margin: 8px 0 0; font-size: 13px; line-height: 1.6; color: var(--foreground); }
.is-disabled { opacity: .6; cursor: default; }
</style>
