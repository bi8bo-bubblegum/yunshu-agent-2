<script setup lang="ts">
import { ref, onMounted } from 'vue'
import client from '../api/client'
import { toast } from '../api/toast'
import { fmtDateTime, fmtTime } from '../api/format'
import type { TraceItem, TraceEventItem } from '../api/types'

const traces = ref<TraceItem[]>([])
const loading = ref(false)
const selected = ref<TraceItem | null>(null)
const events = ref<TraceEventItem[]>([])
const detailTarget = ref<TraceEventItem | null>(null)

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
// 后端 emit 的事件 type：route / llm_call / tool_call / memory / approval；兼容旧名 llm / tool
const typeTag: Record<string, string> = { route: 'tag-blue', llm_call: 'tag-purple', tool_call: 'tag-orange', memory: 'tag-cyan', approval: 'tag-red', llm: 'tag-purple', tool: 'tag-orange' }
const typeLabel: Record<string, string> = { route: '路由', llm_call: 'LLM', tool_call: '工具', memory: '记忆', approval: '审批', llm: 'LLM', tool: '工具' }
const stageLabel: Record<string, string> = { start: '开始', end: '结束' }
const fieldLabel: Record<string, string> = {
  event: '阶段', agent: '目标智能体', reason: '路由理由', confidence: '置信度', routes: '路由序列',
  name: '名称', args: '参数', output: '输出', prompt: '提示词',
}

function fmtPayload(p: Record<string, unknown>): string {
  const s = JSON.stringify(p)
  return s.length > 120 ? s.slice(0, 120) + '…' : s
}

// 详情弹窗结构化字段：长文本/多行值标记 long，用可滚动 pre 展示
interface DetailField { label: string; value: string; long: boolean }

function describePayload(p: Record<string, unknown>): DetailField[] {
  const out: DetailField[] = []
  const stage = typeof p.event === 'string' ? stageLabel[p.event] ?? p.event : ''
  if (stage) out.push({ label: '阶段', value: stage, long: false })
  for (const [k, v] of Object.entries(p)) {
    if (k === 'event') continue
    let value: string
    if (Array.isArray(v)) value = v.map(String).join(' → ')
    else if (v && typeof v === 'object') value = JSON.stringify(v, null, 2)
    else value = String(v ?? '')
    out.push({ label: fieldLabel[k] ?? k, value, long: value.length > 200 || value.includes('\n') })
  }
  return out
}

function openDetail(e: TraceEventItem) {
  detailTarget.value = e
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
            <div class="tl-body" style="cursor:pointer" title="查看详情" @click="openDetail(e)">
              <div class="row-between">
                <span class="tag" :class="typeTag[e.type] ?? 'tag-gray'">{{ typeLabel[e.type] ?? e.type }}</span>
                <span class="muted mono text-sm">{{ fmtTime(e.created_at) }}</span>
              </div>
              <pre class="mono tl-payload">{{ fmtPayload(e.payload) }}</pre>
            </div>
          </div>
          <div v-if="!events.length" class="empty"><span class="icon">⏳</span>暂无事件（可能仍在执行）</div>
        </div>
      </div>
    </div>

    <!-- 事件详情弹窗 -->
    <div v-if="detailTarget" class="modal-mask">
      <div class="modal" style="width:720px">
        <div class="modal-title" style="display:flex;align-items:center;gap:8px">
          <span class="tag" :class="typeTag[detailTarget.type] ?? 'tag-gray'">{{ typeLabel[detailTarget.type] ?? detailTarget.type }}</span>
          <span class="muted text-sm">{{ fmtDateTime(detailTarget.created_at) }}</span>
        </div>
        <div class="modal-body col">
          <div v-for="(f, i) in describePayload(detailTarget.payload)" :key="i" class="detail-row">
            <span class="detail-label">{{ f.label }}</span>
            <pre v-if="f.long" class="mono detail-value detail-long">{{ f.value }}</pre>
            <span v-else class="detail-value">{{ f.value }}</span>
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
.page-wrap { padding: 20px; height: calc(100vh - 56px); height: calc(100dvh - 56px); box-sizing: border-box; display: flex; flex-direction: column; }
.page-grid { flex: 1; min-height: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
/* 留痕列表与事件时间线各自独立滚动，互不影响 */
.page-grid > .card { min-height: 0; overflow-y: auto; }
@media (max-width: 1100px) {
  .page-grid { grid-template-columns: 1fr; overflow-y: auto; }
  .page-grid > .card { overflow-y: visible; }
}
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
.tl-body:hover { border-color: var(--info); }
.tl-payload { margin: 8px 0 0; font-size: 11.5px; color: var(--muted-foreground); white-space: pre-wrap; word-break: break-all; }
/* 详情弹窗字段行 */
.detail-row { display: flex; gap: 10px; padding: 6px 0; border-bottom: 1px dashed var(--border); }
.detail-row:last-child { border-bottom: none; }
.detail-label { flex-shrink: 0; width: 90px; color: var(--muted-foreground); text-align: right; font-size: 12px; padding-top: 2px; }
.detail-value { flex: 1; min-width: 0; color: var(--foreground); white-space: pre-wrap; word-break: break-all; font-size: 12.5px; }
.detail-long { max-height: 300px; overflow-y: auto; margin: 0; padding: 8px 10px; background: var(--video-bg); border: 1px solid var(--border); border-radius: var(--radius-md); }
@media (max-width: 768px) {
  /* 移动端 shell 变 column + 底部 Tab 占流内高度，calc(100dvh - 56px) 不再等于内容区高度；
     改 height:auto 让整页由 .app-content 单容器滚动，消除双滚动 */
  .page-wrap { height: auto; padding: 12px; }
  .page-grid { overflow-y: visible; }
  /* 详情弹窗字段行竖排：窄屏下 label(90px) + value 横排会挤 */
  .detail-row { flex-direction: column; gap: 2px; }
  .detail-label { width: auto; text-align: left; }
}
</style>
