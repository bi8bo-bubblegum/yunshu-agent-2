<script setup lang="ts">
import { ref, onMounted } from 'vue'
import client from '../api/client'
import { toast } from '../api/toast'
import type { TraceItem, TraceEventItem } from '../api/types'

const traces = ref<TraceItem[]>([])
const loading = ref(false)
const selected = ref<TraceItem | null>(null)
const events = ref<TraceEventItem[]>([])

onMounted(load)

async function load() {
  loading.value = true
  try {
    const { data } = await client.get<TraceItem[]>('/traces')
    traces.value = data
  } catch (err: any) {
    toast(err.response?.data?.detail || '加载失败', 'error')
  } finally {
    loading.value = false
  }
}

async function openTrace(t: TraceItem) {
  selected.value = t
  events.value = []
  try {
    const { data } = await client.get<TraceEventItem[]>(`/traces/${t.id}/events`)
    events.value = data
  } catch { /* ignore */ }
}

const statusTag: Record<string, string> = { running: 'tag-blue', completed: 'tag-green', interrupted: 'tag-orange', failed: 'tag-red' }
const typeTag: Record<string, string> = { route: 'tag-blue', llm: 'tag-purple', tool: 'tag-orange', memory: 'tag-cyan', approval: 'tag-red' }
const typeLabel: Record<string, string> = { route: '路由', llm: 'LLM', tool: '工具', memory: '记忆', approval: '审批' }

function fmtPayload(p: Record<string, unknown>): string {
  const s = JSON.stringify(p)
  return s.length > 120 ? s.slice(0, 120) + '…' : s
}
</script>

<template>
  <div class="page-wrap">
    <div class="row-between mb-12">
      <p class="text-muted">全链路执行留痕：路由 → LLM → 工具调用 → 记忆 → 审批</p>
      <button class="btn btn-sm" @click="load">刷新</button>
    </div>

    <div class="page-grid">
      <!-- trace 列表 -->
      <div class="card">
        <div v-if="loading" class="loading-row"><span class="spinner"></span>加载中…</div>
        <div class="table-wrap" v-else>
          <table>
            <thead><tr><th>状态</th><th>路由序列</th><th>会话</th></tr></thead>
            <tbody>
              <tr v-for="t in traces" :key="t.id" :class="{ 'row-active': selected?.id === t.id }" style="cursor:pointer" @click="openTrace(t)">
                <td><span class="tag" :class="statusTag[t.status] ?? 'tag-gray'">{{ t.status }}</span></td>
                <td>
                  <span v-for="(r, i) in (t.supervisor_routes ?? [])" :key="i" class="route-chip">{{ r }}</span>
                  <span v-if="!t.supervisor_routes?.length" class="muted">—</span>
                </td>
                <td class="muted mono text-sm">{{ t.conversation_id?.slice(0, 8) ?? '—' }}</td>
              </tr>
              <tr v-if="!traces.length"><td colspan="3"><div class="empty"><span class="icon">📡</span>暂无留痕记录</div></td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 事件时间线 -->
      <div class="card">
        <h3 class="card-title" style="margin-bottom:16px">
          {{ selected ? `事件时间线 · ${selected.id.slice(0, 8)}` : '事件时间线' }}
        </h3>
        <div v-if="!selected" class="empty"><span class="icon">🕐</span>点击左侧记录查看事件</div>
        <div v-else class="timeline">
          <div v-for="(e, idx) in events" :key="`${e.created_at}-${idx}`" class="tl-item">
            <div class="tl-dot" :class="`dot-${e.type}`"></div>
            <div class="tl-body">
              <div class="row-between">
                <span class="tag" :class="typeTag[e.type] ?? 'tag-gray'">{{ typeLabel[e.type] ?? e.type }}</span>
                <span class="muted mono text-sm">{{ e.created_at?.slice(11, 19) }}</span>
              </div>
              <pre class="mono tl-payload">{{ fmtPayload(e.payload) }}</pre>
            </div>
          </div>
          <div v-if="!events.length" class="empty"><span class="icon">⏳</span>暂无事件（可能仍在执行）</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-wrap { padding: 20px; }
.page-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
@media (max-width: 1100px) { .page-grid { grid-template-columns: 1fr; } }
.row-active td { background: rgba(37, 244, 238, .05); }
.route-chip { display: inline-block; margin: 1px 2px; padding: 1px 7px; border-radius: 999px; background: var(--card-elevated); border: 1px solid var(--border); font-size: 11px; color: var(--muted-foreground); }
.timeline { display: flex; flex-direction: column; }
.tl-item { display: flex; gap: 12px; position: relative; padding-bottom: 16px; }
.tl-item::before { content: ''; position: absolute; left: 5px; top: 18px; bottom: 0; width: 1px; background: var(--border); }
.tl-item:last-child::before { display: none; }
.tl-dot { width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0; margin-top: 4px; z-index: 1; }
.dot-route { background: var(--info); }
.dot-llm { background: var(--purple); }
.dot-tool { background: var(--warning); }
.dot-memory { background: var(--secondary); }
.dot-approval { background: var(--primary); }
.tl-body { flex: 1; min-width: 0; background: var(--video-bg); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px 12px; }
.tl-payload { margin: 8px 0 0; font-size: 11.5px; color: var(--muted-foreground); white-space: pre-wrap; word-break: break-all; }
</style>
