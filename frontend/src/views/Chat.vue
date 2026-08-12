<script setup lang="ts">
defineOptions({ name: 'Chat' })
import { ref, computed, watch, nextTick, onMounted, onActivated } from 'vue'
import { useRouter } from 'vue-router'
import { streamChat, resumeChat, type SSEEvent } from '../api/chat'
import client from '../api/client'
import { toast } from '../api/toast'
import { fmtDateTime } from '../api/format'
import type { Conversation, Message } from '../api/types'
import Md from '../components/Md.vue'

const convs = ref<Conversation[]>([])
const currentId = ref('')
const messages = ref<Message[]>([])
const input = ref('')
const streaming = ref(false)
const listRef = ref<HTMLElement>()
// 移动端会话列表面板 → 抽屉：开关状态
const convDrawerOpen = ref(false)
const router = useRouter()
const pendingApproval = ref<{ conversationId: string; approvalId: string } | null>(null)
// 流式状态与会话绑定：切走再回来能恢复气泡与流程面板，互不串扰
const streamActive = ref(false)
const streamConv = ref('')
const streamBuf = ref('')
// 用户主动终止标志：发送后按钮变「终止」，点击后置位并 abort 流式请求
const stopping = ref(false)

onMounted(loadConvs)

// keep-alive 下从其他页面切回时刷新消息并滚动到底部
// （审批中心处理完 critical 后回复可能已落库；流式进行中则保留现场）
onActivated(async () => {
  stopAbortPoll()
  if (!streaming.value) await loadConvs()
  if (currentId.value && !streaming.value && messages.value.length) {
    await selectConv(currentId.value)
    maybePollPending()
  }
  await nextTick()
  listRef.value?.scrollTo({ top: listRef.value.scrollHeight })
})

// 新消息自动滚动到底部
watch(() => messages.value.length, async () => {
  await nextTick()
  listRef.value?.scrollTo({ top: listRef.value.scrollHeight })
})

// ---- 会话管理 ----
async function loadConvs() {
  try {
    const { data } = await client.get<Conversation[]>('/conversations')
    convs.value = data
    if (data.length && !currentId.value) selectConv(data[0].id)
  } catch { /* ignore */ }
}

async function newConv() {
  const { data } = await client.post<Conversation>('/conversations', {})
  convs.value.unshift(data)
  selectConv(data.id)
}

async function selectConv(id: string) {
  convDrawerOpen.value = false // 移动端：选中会话即收起抽屉
  stopPoll()
  stopAbortPoll()
  currentId.value = id
  messages.value = []
  try {
    const { data } = await client.get<Message[]>(`/conversations/${id}/messages`)
    messages.value = data
    if (data[data.length - 1]?.role === 'assistant') pendingApproval.value = null
    // 回到正在流式输出的会话：把已缓冲的回复气泡接回来
    if (streamActive.value && id === streamConv.value && data[data.length - 1]?.role !== 'assistant') {
      messages.value.push({ id: 'stream-buf', role: 'assistant', content: streamBuf.value })
    }
    maybePollPending()
  } catch { /* ignore */ }
}

// ---- 等待审批/生成中的回复自动刷新 ----
let pollTimer: number | undefined
const waitingReply = ref(false)

function stopPoll() {
  waitingReply.value = false
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = undefined
  }
}

function maybePollPending() {
  stopPoll()
  if (streaming.value || !currentId.value) return
  const last = messages.value[messages.value.length - 1]
  if (!last || last.role !== 'user') return
  // 最后一条是用户消息说明回复尚未生成（如 critical 审批恢复中），轮询等待
  waitingReply.value = true
  let tries = 0
  pollTimer = window.setInterval(async () => {
    tries++
    if (streaming.value || !currentId.value) return stopPoll()
    try {
      const { data } = await client.get<Message[]>(`/conversations/${currentId.value}/messages`)
      messages.value = data
      if (data[data.length - 1]?.role === 'assistant') {
        pendingApproval.value = null
        stopPoll()
      }
    } catch { /* ignore */ }
    if (tries >= 30) stopPoll()  // 最多轮询约 90 秒
  }, 3000)
}

async function removeConv(c: Conversation) {
  if (!confirm(`确认删除会话「${c.title || '新会话'}」？删除后不可恢复`)) return
  try {
    await client.delete(`/conversations/${c.id}`)
    toast('会话已删除', 'success')
    const idx = convs.value.findIndex(x => x.id === c.id)
    if (idx >= 0) convs.value.splice(idx, 1)
    if (currentId.value === c.id) {
      currentId.value = ''
      messages.value = []
      if (convs.value.length) selectConv(convs.value[0].id)
    }
  } catch (err: any) {
    toast(err.response?.data?.detail || '删除失败', 'error')
  }
}

// ---- 发送 / SSE ----
let abortCtrl: AbortController | null = null
let answerStarted = false
// 服务端 SSE error 事件置位：图执行失败时后端已落失败消息，finally 里用 DB 刷新
// 展示失败气泡，不再落入「（无响应）」占位 / 残留上一次的回复
let errorReceived = false

// 用户手动终止：置位终止标志并中断 SSE 流式请求，后端取消处理中异步落库半截回答
function stopSend() {
  stopping.value = true
  abortCtrl?.abort()
}

function agentName(code: string) {
  return ({ marketing: '营销助手', sales_analysis: '经营分析', scheduling: '调度优化', done: '完成' } as Record<string, string>)[code] || code || '未知'
}

// ---- 多 agent 分段落库渲染（方案 B）----
// 展开/收起的执行过程折叠：key = final 段落的消息 id
const expandedSteps = ref<Set<string>>(new Set())

// ---- 结构化工具卡片 ----
// 流式实时卡片：SSE tool_start/tool_end 按 run_id 配对更新；终态落库后由 DB tool 消息重建
interface LiveToolCard {
  run: string
  tool: string
  args: unknown
  result?: unknown
  status: 'running' | 'success' | 'error'
}
interface ToolCardData {
  tool: string
  args: unknown
  result?: unknown
  status: 'running' | 'success' | 'error'
}
const streamTools = ref<LiveToolCard[]>([])
// 流式占位（stream-buf）气泡展示的实时卡片；落库后 displayMessages 用 DB tool 消息重建
const liveToolCards = computed<ToolCardData[]>(() =>
  streamTools.value.map(t => ({ tool: t.tool, args: t.args, result: t.result, status: t.status })),
)
const expandedTools = ref<Set<string>>(new Set())
// 内置工具图标映射（未知工具兜底 🔧）；工具名直接展示原始英文名，不做中文映射
const TOOL_ICONS: Record<string, string> = {
  query_marketing_campaigns: '📢', create_marketing_campaign: '🛠️', publish_campaign: '🚀',
  query_sales_data: '📊', delete_order: '🗑️', query_schedule: '📅', adjust_schedule: '🔁',
  search_knowledge: '📚',
}
function toolIcon(t: string) { return TOOL_ICONS[t] ?? '🔧' }
function statusLabel(s: string) { return s === 'running' ? '执行中' : s === 'error' ? '失败' : '成功' }
function statusClass(s: string) { return s === 'running' ? 'tag-blue' : s === 'error' ? 'tag-red' : 'tag-green' }
function toggleTool(key: string) {
  const s = new Set(expandedTools.value)
  if (s.has(key)) s.delete(key)
  else s.add(key)
  expandedTools.value = s
}
function fmtValue(v: unknown) {
  if (v === null || v === undefined) return ''
  if (typeof v === 'string') return v
  try { return JSON.stringify(v, null, 2) } catch { return String(v) }
}

type RenderItem =
  | { kind: 'user'; m: Message }
  | { kind: 'assistant'; steps: Message[]; final: Message; tools: ToolCardData[] }

// 把「step 段落」（中间 agent 产出）与「tool 卡片」归入其后紧跟的「final 段落」：
// 同一轮的中间产出折叠展示，工具卡片与正文混排在助手气泡内（方案 B）。
const displayMessages = computed<RenderItem[]>(() => {
  const out: RenderItem[] = []
  let pendingSteps: Message[] = []
  let pendingTools: ToolCardData[] = []
  for (const m of messages.value) {
    if (m.role === 'user') {
      out.push({ kind: 'user', m })
    } else if (m.metadata?.segment === 'step') {
      pendingSteps.push(m)
    } else if (m.metadata?.kind === 'tool') {
      // 工具卡片：归入其后紧跟的 final 段落；终态落库的 tool 消息 status 仅 success/error
      pendingTools.push({
        tool: m.metadata.tool ?? '未知工具',
        args: m.metadata.args,
        result: m.metadata.result,
        status: m.metadata.status === 'error' ? 'error' : 'success',
      })
    } else if (m.id === 'stream-buf') {
      // 流式占位气泡：合并实时 SSE 卡片（liveToolCards），流式结束后由 refreshFromDb 重建
      out.push({ kind: 'assistant', steps: pendingSteps, final: m, tools: pendingTools.concat(liveToolCards.value) })
      pendingSteps = []
      pendingTools = []
    } else {
      out.push({ kind: 'assistant', steps: pendingSteps, final: m, tools: pendingTools })
      pendingSteps = []
      pendingTools = []
    }
  }
  return out
})

function toggleSteps(id: string) {
  const s = new Set(expandedSteps.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  expandedSteps.value = s
}

function renderStreamText() {
  const sb = messages.value.find(m => m.id === 'stream-buf')
  if (sb) sb.content = streamBuf.value
}

// 流式结束后用 DB 真实消息替换本地缓冲气泡（stream-buf），保证：
// 1. 刷新页面/切换会话后消息与服务端一致；
// 2. 不留 id='stream-buf' 残留，避免下一次发送时重复 id 覆盖上一条回复。
async function refreshFromDb() {
  try {
    const { data } = await client.get<Message[]>(`/conversations/${currentId.value}/messages`)
    messages.value = data
    await nextTick()
    listRef.value?.scrollTo({ top: listRef.value.scrollHeight })
  } catch { /* 忽略 */ }
}

// ---- 手动终止后的落库轮询 ----
// 用户点击「终止」→ SSE 断开 → 后端在取消处理中异步写半截回答+工具卡片。
// 但 SSE 已断，前端拿不到完成信号，只能轮询 DB：直到最后一条变成 assistant
//（半截回答已落库）或尝试次数耗尽。切会话/新一轮消息/组件切换时 stopAbortPoll。
let abortPollTimer: number | undefined

function stopAbortPoll() {
  if (abortPollTimer) {
    clearInterval(abortPollTimer)
    abortPollTimer = undefined
  }
}

function abortPoll() {
  stopAbortPoll()
  let tries = 0
  abortPollTimer = window.setInterval(async () => {
    tries++
    if (streaming.value || !currentId.value) return stopAbortPoll()
    try {
      const { data } = await client.get<Message[]>(`/conversations/${currentId.value}/messages`)
      messages.value = data
      if (data[data.length - 1]?.role === 'assistant') stopAbortPoll()  // 半截回答已落库
    } catch { /* ignore */ }
    if (tries >= 8) stopAbortPoll()  // 最多约 12 秒
  }, 1500)
}

function streamLine(text: string) {
  streamBuf.value = streamBuf.value === '⏳ 正在思考…' ? text : `${streamBuf.value}\n${text}`
  renderStreamText()
}

async function send() {
  const text = input.value.trim()
  if (!text || streaming.value || !currentId.value) return
  input.value = ''
  stopping.value = false
  stopAbortPoll()  // 新一轮消息开始前清掉上一轮终止后的落库轮询
  streamActive.value = true
  streamConv.value = currentId.value
  streamBuf.value = '⏳ 正在思考…'
  answerStarted = false
  errorReceived = false
  streamTools.value = []  // 上一轮的实时工具卡片（终态落库后由 DB 消息重建，不再残留）
  // 清理残留的流式缓冲气泡：若上一轮异常中断未做 DB 刷新，列表里可能还留着
  // 旧的 id='stream-buf'，与本次新 push 的重复，导致 renderStreamText 更新错
  // 对象（上一条回复被本轮回复覆盖修改）。这里统一移除旧的，只保留一条 stream-buf。
  const stale = messages.value.findIndex(m => m.id === 'stream-buf')
  if (stale >= 0) messages.value.splice(stale, 1)
  messages.value.push({ id: `u-${Date.now()}`, role: 'user', content: text })
  messages.value.push({ id: 'stream-buf', role: 'assistant', content: streamBuf.value })
  streaming.value = true
  abortCtrl = new AbortController()

  try {
    await streamChat(currentId.value, text, (e: SSEEvent) => {
      if (e.event === 'token') {
        if (!answerStarted) {
          answerStarted = true
          streamBuf.value = streamBuf.value === '⏳ 正在思考…' ? '' : `${streamBuf.value}\n\n`
        }
        streamBuf.value += e.content ?? ''
        renderStreamText()
      }
      else if (e.event === 'route') {
        streamLine(`🧭 已路由到 ${agentName(String(e.agent ?? ''))}`)
      } else if (e.event === 'tool_start') {
        // 结构化工具卡片：清除"思考中"占位（有工具调用说明已产出实质动作），
        // 推入实时卡片（running），tool_end 按 run_id 配对更新为 success/error
        if (streamBuf.value === '⏳ 正在思考…') streamBuf.value = ''
        streamTools.value.push({
          run: String(e.run_id ?? ''),
          tool: String(e.tool ?? '未知工具'),
          args: e.args,
          status: 'running',
        })
        renderStreamText()
      } else if (e.event === 'tool_end') {
        const run = String(e.run_id ?? '')
        const idx = run
          ? streamTools.value.findIndex(t => t.run === run)
          : streamTools.value.length - 1
        if (idx >= 0) {
          streamTools.value[idx].status = e.error ? 'error' : 'success'
          streamTools.value[idx].result = e.result
        } else {
          // 未找到（run_id 缺失且无 running）：补一条完成卡片
          streamTools.value.push({
            run, tool: String(e.tool ?? '未知工具'), args: undefined,
            result: e.result, status: e.error ? 'error' : 'success',
          })
        }
      } else if (e.event === 'answer') {
        // token 已流式输出时，answer 是完整文本的冗余副本，跳过避免重复；
        // 仅在没有任何 token（非流式模型/异常）时用其填充
        if (!answerStarted) {
          answerStarted = true
          streamBuf.value = streamBuf.value === '⏳ 正在思考…'
            ? (e.content ?? '')
            : `${streamBuf.value}\n\n${e.content ?? ''}`
          renderStreamText()
        }
      }
      else if (e.event === 'done' && e.title && e.title !== '新对话') {
        // 后端生成器完成后通过 done.title patch 会话列表对应项，无需全量刷新
        const c = convs.value.find(c => c.id === currentId.value)
        if (c) c.title = e.title as string
      }
      else if (e.event === 'confirm_required') {
        const p = (e.payload ?? {}) as Record<string, unknown>
        const critical = Boolean(p.approval_id)
        if (critical) {
          // 移除临时的空回复气泡，改由“待审批”状态气泡展示
          const idx = messages.value.findIndex(m => m.id === 'stream-buf')
          if (idx >= 0) messages.value.splice(idx, 1)
          pendingApproval.value = { conversationId: currentId.value, approvalId: String(p.approval_id ?? '') }
        }
        confirmState.value = {
          visible: true,
          conversationId: currentId.value,
          tool: String(p.tool ?? '未知工具'),
          args: p.args ?? {},
          reason: String(p.reason ?? '高风险操作需要确认'),
          critical,
          approvalId: String(p.approval_id ?? ''),
        }
      } else if (e.event === 'error') {
        errorReceived = true  // 后端已落失败消息，finally 用 DB 刷新替换占位气泡
        toast(String(e.content ?? '请求失败'), 'error')
      }
    }, abortCtrl.signal)
    // 标题已通过 done.title 做 inline patch，无需全量刷新
  } catch (err: any) {
    if (err.name !== 'AbortError') toast('连接中断', 'error')
  } finally {
    const targetId = streamConv.value
    const aborted = stopping.value
    stopping.value = false
    streaming.value = false
    streamActive.value = false
    streamConv.value = ''
    const sb = messages.value.find(m => m.id === 'stream-buf')
    if (aborted) {
      // 用户手动终止：无任何产出时把占位气泡改为「（已终止）」；
      // 已有半截内容则保留展示。后端在取消处理中异步落库半截回答+工具卡片，
      // 轮询等落库完成后用 DB 数据整体刷新（覆盖 stream-buf）。
      if (sb && (sb.content === '' || sb.content === '⏳ 正在思考…')) {
        sb.content = '（已终止）'
        streamBuf.value = sb.content
      }
      if (currentId.value && currentId.value === targetId && !pendingApproval.value) abortPoll()
      return  // 跳过 maybePollPending 与普通 refreshFromDb
    }
    if (errorReceived && currentId.value && currentId.value === targetId && !pendingApproval.value) {
      // 图执行失败：后端已落失败 assistant 消息（含错误摘要），DB 刷新替换占位气泡，
      // 不落入「（无响应）」占位（该占位面向连接中断等无 DB 落库场景）
      refreshFromDb()
      return
    }
    if (sb && (sb.content === '' || sb.content === '⏳ 正在思考…') && !pendingApproval.value) {
      sb.content = '（无响应）'
      streamBuf.value = sb.content
    }
    maybePollPending()
    // 流式正常产生回复后，用 DB 真实消息替换本地缓冲气泡（stream-buf）。
    // 若残留 stream-buf，下一次发送会因重复 id 覆盖修改上一条回复。
    // 审批挂起（critical/high）时后端回复尚未落库，保留现场等 decide 后刷新。
    // 工具跑了但无 token 文本（如纯查询后未输出）也需刷新，让 DB 工具卡片替换实时卡片。
    if (currentId.value && currentId.value === targetId && !pendingApproval.value
        && (answerStarted || streamTools.value.length)) {
      refreshFromDb()
    }
  }
}

// ---- high 风险即时确认 ----
const confirmState = ref<{ visible: boolean; conversationId: string; tool: string; args: unknown; reason: string; critical: boolean; approvalId: string }>({
  visible: false, conversationId: '', tool: '', args: {}, reason: '', critical: false, approvalId: '',
})

async function decide(approved: boolean) {
  const convId = confirmState.value.conversationId
  // critical 风险已进审批中心：聊天页只提示去向，不做即时确认
  if (confirmState.value.critical) {
    confirmState.value.visible = false
    toast('该操作已提交审批中心，请管理员在「审批中心」处理', 'info')
    return
  }
  confirmState.value.visible = false
  try {
    const { data } = await resumeChat(convId, approved)
    // 恢复后图内还有后续中断：critical 进审批中心 / high 继续即时确认，需要重新弹窗
    if (data?.ok === false && data.payload) {
      const p = data.payload as Record<string, unknown>
      // 后端整体超时兜底（resume 恢复执行超过限时）：不重弹确认框，提示用户稍后查看
      if (p.timeout) {
        toast('执行超时，结果可能不完整，请稍后刷新查看', 'error')
        await selectConv(convId)
        return
      }
      const critical = Boolean(p.approval_id)
      if (critical) {
        // 移除临时空回复气泡，置为待审批状态并开始轮询
        const idx = messages.value.findIndex(m => m.id === 'stream-buf')
        if (idx >= 0) {
          messages.value.splice(idx, 1)
        }
        pendingApproval.value = { conversationId: convId, approvalId: String(p.approval_id ?? '') }
        maybePollPending()
      }
      confirmState.value = {
        visible: true,
        conversationId: convId,
        tool: String(p.tool ?? '未知工具'),
        args: p.args ?? {},
        reason: String(p.reason ?? '高风险操作需要确认'),
        critical,
        approvalId: String(p.approval_id ?? ''),
      }
      toast(critical ? '该操作已提交审批中心，请管理员审批' : '还有下一步操作需要确认', 'info')
      return
    }
    toast(approved ? '已确认执行' : '已驳回', approved ? 'success' : 'info')
    await selectConv(convId) // 恢复后刷新消息
  } catch (e: any) {
    toast(e.response?.data?.detail || '恢复执行失败', 'error')
  }
}

const activeConv = computed(() => convs.value.find(c => c.id === currentId.value))
</script>

<template>
  <div class="chat-page">
    <!-- 会话列表（移动端抽屉化） -->
    <aside class="conv-panel" :class="{ open: convDrawerOpen }">
      <button class="btn btn-primary btn-block" @click="newConv">+ 新建会话</button>
      <div class="conv-list">
        <div v-for="c in convs" :key="c.id" class="conv-item"
             :data-active="c.id === currentId" @click="selectConv(c.id)">
          <button class="conv-del" title="删除会话" @click.stop="removeConv(c)">✕</button>
          <div class="conv-title">{{ c.title || '新会话' }}</div>
          <div class="conv-meta">{{ fmtDateTime(c.created_at) }}</div>
        </div>
        <div v-if="!convs.length" class="empty"><span class="icon">💬</span>暂无会话</div>
      </div>
    </aside>
    <div v-if="convDrawerOpen" class="conv-mask" @click="convDrawerOpen = false"></div>

    <!-- 消息区 -->
    <section class="msg-panel">
      <button class="conv-toggle show-mobile" aria-label="打开会话列表" @click="convDrawerOpen = true">☰ 会话</button>
      <div class="msg-list" ref="listRef">
        <div v-if="!currentId" class="empty">
          <span class="icon">💬</span>
          <p>还没有会话</p>
          <p class="text-muted text-sm">先新建一个会话，再开始对话</p>
          <button class="btn btn-primary mt-12" @click="newConv">+ 新建会话</button>
        </div>
        <div v-else-if="!messages.length" class="empty">
          <span class="icon">🤖</span>
          <p>向云枢 Agent 描述你的任务</p>
          <p class="text-muted text-sm">示例：帮我策划一个国庆营销方案</p>
        </div>
        <template v-for="(item, i) in displayMessages" :key="item.kind === 'user' ? item.m.id : item.final.id">
          <div v-if="item.kind === 'user'" class="msg user">
            <div class="avatar">我</div>
            <div class="bubble"><pre>{{ item.m.content }}</pre></div>
          </div>
          <div v-else class="msg assistant">
            <div class="avatar">云</div>
            <div class="bubble">
              <!-- 结构化工具卡片：与正文混排在气泡内，折叠态单行（图标+中文名+状态），点击展开参数/结果 -->
              <div v-if="item.tools.length" class="tool-cards">
                <div v-for="(tc, ti) in item.tools" :key="`t-${item.final.id}-${ti}`"
                     class="tool-card" :class="`tool-${tc.status}`"
                     @click="toggleTool(`${item.final.id}-${ti}`)">
                  <div class="tool-card-head">
                    <span class="tool-icon">{{ toolIcon(tc.tool) }}</span>
                    <span class="tool-name" :title="tc.tool">{{ tc.tool }}</span>
                    <span class="tool-grow"></span>
                    <span class="tag" :class="statusClass(tc.status)">
                      <span v-if="tc.status === 'running'" class="tool-spinner"></span>
                      {{ statusLabel(tc.status) }}
                    </span>
                    <span class="tool-arrow">{{ expandedTools.has(`${item.final.id}-${ti}`) ? '▾' : '▸' }}</span>
                  </div>
                  <div v-if="expandedTools.has(`${item.final.id}-${ti}`)" class="tool-card-body">
                    <div v-if="tc.args !== undefined && tc.args !== null" class="tool-sec">
                      <div class="tool-sec-label">参数</div>
                      <pre class="mono tool-pre">{{ fmtValue(tc.args) }}</pre>
                    </div>
                    <div v-if="tc.result !== undefined && tc.result !== null" class="tool-sec">
                      <div class="tool-sec-label">结果</div>
                      <pre class="mono tool-pre">{{ fmtValue(tc.result) }}</pre>
                    </div>
                  </div>
                </div>
              </div>
              <div v-if="item.final.content === '' && streaming && i === displayMessages.length - 1" class="typing"><span></span><span></span><span></span></div>
              <Md v-else :content="item.final.content" />
              <div v-if="item.steps.length" class="steps-toggle" @click="toggleSteps(item.final.id)">
                <span class="steps-arrow">{{ expandedSteps.has(item.final.id) ? '▾' : '▸' }}</span>
                <span>查看执行过程（{{ item.steps.length }} 步）</span>
              </div>
              <div v-if="item.steps.length && expandedSteps.has(item.final.id)" class="steps-panel">
                <div v-for="(s, si) in item.steps" :key="s.id" class="step-block" :class="{ 'step-first': si === 0 }">
                  <div class="step-agent">🛠 {{ agentName(s.metadata?.agent ?? '') }}</div>
                  <Md :content="s.content" />
                </div>
              </div>
            </div>
          </div>
        </template>
        <div v-if="pendingApproval && pendingApproval.conversationId === currentId" class="msg assistant">
          <div class="avatar">云</div>
          <div class="bubble pending-bubble">
            <span class="spinner"></span>
            <span>等待管理员审批（{{ pendingApproval.approvalId.slice(0, 8) }}）…</span>
            <button class="btn btn-sm btn-primary" @click="router.push('/approvals')">去审批中心</button>
          </div>
        </div>
      </div>

      <div class="input-bar" v-if="currentId">
        <textarea class="textarea" v-model="input" rows="2" placeholder="输入消息，Enter 发送 / Shift+Enter 换行"
                  :disabled="streaming" @keydown.enter.exact.prevent="send" />
        <div class="row-between mt-8">
          <span class="text-muted text-sm">{{ streaming ? 'Agent 思考中…' : waitingReply ? '⏳ 等待审批/回复中…' : activeConv ? '会话已就绪' : '' }}</span>
          <button v-if="!streaming" class="btn btn-primary" :disabled="!input.trim() || !currentId" @click="send">发送</button>
          <button v-else class="btn btn-danger" @click="stopSend"><span class="stop-icon"></span>终止</button>
        </div>
      </div>
    </section>

    <!-- high 风险即时确认浮层 -->
    <div v-if="confirmState.visible" class="modal-mask">
      <div class="modal">
        <h3 class="modal-title">{{ confirmState.critical ? '📋 已提交审批中心' : '⚠️ 高风险操作确认' }}</h3>
        <div class="modal-body col">
          <p style="margin:0">{{ confirmState.critical ? '该操作风险等级为 critical，已生成审批单，待管理员审批通过后自动恢复执行。' : confirmState.reason }}</p>
          <p class="mono text-muted" style="margin:0">工具：{{ confirmState.tool }}</p>
          <p v-if="confirmState.critical" class="mono text-muted" style="margin:0">审批单：{{ confirmState.approvalId.slice(0, 8) }}…</p>
          <div class="card" style="background:var(--video-bg)">
            <pre class="mono" style="margin:0;font-size:12px">{{ JSON.stringify(confirmState.args, null, 2) }}</pre>
          </div>
        </div>
        <div v-if="confirmState.critical" class="modal-foot">
          <button class="btn" @click="confirmState.visible = false">知道了</button>
          <button class="btn btn-primary" @click="confirmState.visible = false; router.push('/approvals')">去审批中心</button>
        </div>
        <div v-else class="modal-foot">
          <button class="btn btn-danger" @click="decide(false)">驳回</button>
          <button class="btn btn-primary" @click="decide(true)">确认执行</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-page { display: flex; height: 100%; }
.conv-panel { width: 240px; flex-shrink: 0; padding: 14px; border-right: 1px solid var(--border); display: flex; flex-direction: column; gap: 12px; background: var(--video-bg); }
.conv-list { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; }
.conv-item { position: relative; padding: 10px 12px; border-radius: var(--radius-md); cursor: pointer; transition: background .18s; }
.conv-item:hover { background: var(--card); }
.conv-item[data-active="true"] { background: var(--card-elevated); }
.conv-title { font-size: 13px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.conv-meta { font-size: 11px; color: var(--muted-foreground); margin-top: 2px; }
.conv-del { position: absolute; top: 8px; right: 8px; width: 18px; height: 18px; line-height: 16px; padding: 0; border: none; border-radius: 4px; background: transparent; color: var(--muted-foreground); opacity: .35; font-size: 11px; cursor: pointer; transition: opacity .15s, background-color .15s; }
.conv-del:hover { opacity: 1; background: var(--card); color: var(--foreground); }

.msg-panel { flex: 1; min-width: 0; position: relative; display: flex; flex-direction: column; }
.msg-list { flex: 1; min-height: 0; overflow-y: auto; padding: 20px 24px; display: flex; flex-direction: column; gap: 16px; }
/* 移动端「会话列表」抽屉触发按钮（显隐交给全局 .show-mobile） */
.conv-toggle {
  position: absolute; top: 10px; left: 10px; z-index: 5;
  height: 34px; padding: 0 12px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--card); color: var(--foreground);
  font-size: 13px; display: inline-flex; align-items: center; gap: 6px; cursor: pointer;
}
.msg { display: flex; gap: 10px; max-width: 78%; }
.msg.user { align-self: flex-end; flex-direction: row-reverse; }
.avatar { width: 30px; height: 30px; border-radius: 999px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; }
.msg.user .avatar { background: var(--secondary); color: var(--on-accent); }
.msg.assistant .avatar { background: var(--primary); color: #fff; }
.bubble { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 10px 14px; }
.msg.user .bubble { background: rgba(254, 44, 85, .14); border-color: rgba(254, 44, 85, .35); }
.bubble pre { margin: 0; white-space: pre-wrap; word-break: break-word; font-family: var(--font-sans); font-size: 13.5px; line-height: 1.65; }
.pending-bubble { display: flex; align-items: center; gap: 10px; color: var(--muted-foreground); font-size: 13px; }
/* 多 agent 分段落库（方案 B）：执行过程折叠 */
.steps-toggle { margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border); font-size: 12px; color: var(--muted-foreground); cursor: pointer; user-select: none; display: flex; align-items: center; gap: 4px; }
.steps-toggle:hover { color: var(--foreground); }
.steps-arrow { font-size: 10px; }
.steps-panel { margin-top: 8px; border-left: 2px solid var(--border); padding-left: 10px; display: flex; flex-direction: column; gap: 10px; }
.step-block { padding: 6px 8px; background: var(--video-bg); border-radius: var(--radius-md); }
.step-block.step-first { margin-top: 8px; }
.step-agent { font-size: 11px; color: var(--muted-foreground); margin-bottom: 4px; }
.typing { display: flex; gap: 4px; padding: 6px 2px; }
.typing span { width: 7px; height: 7px; border-radius: 50%; background: var(--muted-foreground); animation: blink 1.2s infinite; }
.typing span:nth-child(2) { animation-delay: .2s; }
.typing span:nth-child(3) { animation-delay: .4s; }
@keyframes blink { 0%, 80%, 100% { opacity: .2; } 40% { opacity: 1; } }

.input-bar { padding: 14px 20px 18px; border-top: 1px solid var(--border); background: var(--background); }
/* 终止按钮的实心方块图标 */
.stop-icon { width: 10px; height: 10px; display: inline-block; background: currentColor; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }

/* ===== 结构化工具卡片 ===== */
.tool-cards { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
.tool-card {
  background: var(--video-bg); border: 1px solid var(--border);
  border-radius: var(--radius-md); overflow: hidden; cursor: pointer;
  transition: border-color .18s;
}
.tool-card:hover { border-color: var(--info); }
.tool-card-head { display: flex; align-items: center; gap: 8px; padding: 6px 10px; }
.tool-icon { font-size: 14px; flex-shrink: 0; }
.tool-name { font-size: 13px; font-weight: 500; color: var(--foreground); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tool-grow { flex: 1; }
.tool-spinner { width: 10px; height: 10px; border: 2px solid color-mix(in srgb, var(--info) 30%, transparent); border-top-color: var(--info); border-radius: 50%; animation: tool-rotate .8s linear infinite; }
@keyframes tool-rotate { to { transform: rotate(360deg); } }
.tool-arrow { font-size: 10px; color: var(--muted-foreground); flex-shrink: 0; }
.tool-card-body { border-top: 1px dashed var(--border); padding: 8px 10px; display: flex; flex-direction: column; gap: 8px; }
.tool-sec-label { font-size: 11px; color: var(--muted-foreground); margin-bottom: 4px; font-family: var(--font-mono); }
.tool-pre {
  margin: 0; font-size: 11.5px; line-height: 1.55;
  max-height: 180px; overflow-y: auto; white-space: pre-wrap; word-break: break-all;
  background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-md);
  padding: 8px 10px; color: var(--foreground);
}
/* 失败卡片状态徽标颜色强调（tag-red 已够用，hover 描边换成错误色） */
.tool-card.tool-error:hover { border-color: var(--danger, #e5484d); }

/* ===== 移动端（<768px）：会话列表抽屉化 + 触控优化 ===== */
@media (max-width: 768px) {
  /* 会话面板 → 左侧滑出抽屉 */
  .conv-panel {
    position: fixed; top: 0; left: 0; bottom: 0;
    width: 280px; max-width: 85vw;
    transform: translateX(-100%);
    transition: transform .25s ease;
    z-index: 91;
    padding-bottom: calc(14px + env(safe-area-inset-bottom));
  }
  .conv-panel.open { transform: none; box-shadow: 20px 0 60px rgba(0, 0, 0, .4); }
  .conv-mask { position: fixed; inset: 0; z-index: 90; background: rgba(0, 0, 0, .6); }

  /* 消息区触控优化 */
  .msg-list { padding: 12px; }
  .msg { max-width: 88%; }
  /* 删除按钮：放大且常显（触屏无 hover，opacity:.35 几乎隐形） */
  .conv-del { opacity: .6; width: 26px; height: 26px; line-height: 24px; font-size: 12px; }
  /* 工具卡片触控优化：头部触控区加大，pre 内容区收紧 */
  .tool-card-head { padding: 9px 12px; }
  .tool-pre { max-height: 150px; }
}
</style>
