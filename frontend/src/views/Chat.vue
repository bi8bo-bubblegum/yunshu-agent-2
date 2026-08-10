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
const router = useRouter()
const pendingApproval = ref<{ conversationId: string; approvalId: string } | null>(null)
// 流式状态与会话绑定：切走再回来能恢复气泡与流程面板，互不串扰
const streamActive = ref(false)
const streamConv = ref('')
const streamBuf = ref('')

onMounted(loadConvs)

// keep-alive 下从其他页面切回时刷新消息并滚动到底部
// （审批中心处理完 critical 后回复可能已落库；流式进行中则保留现场）
onActivated(async () => {
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
  stopPoll()
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

function agentName(code: string) {
  return ({ marketing: '营销助手', sales_analysis: '经营分析', scheduling: '调度优化', done: '完成' } as Record<string, string>)[code] || code || '未知'
}

// ---- 多 agent 分段落库渲染（方案 B）----
// 展开/收起的执行过程折叠：key = final 段落的消息 id
const expandedSteps = ref<Set<string>>(new Set())

type RenderItem =
  | { kind: 'user'; m: Message }
  | { kind: 'assistant'; steps: Message[]; final: Message }

// 把「step 段落」（中间 agent 产出）归入其后紧跟的「final 段落」（最终答案）：
// 同一轮的 agent 中间产出折叠展示，气泡默认只显示最终答案（方案 B）。
const displayMessages = computed<RenderItem[]>(() => {
  const out: RenderItem[] = []
  let pendingSteps: Message[] = []
  for (const m of messages.value) {
    if (m.role === 'user') {
      out.push({ kind: 'user', m })
    } else if (m.metadata?.segment === 'step') {
      pendingSteps.push(m)
    } else {
      out.push({ kind: 'assistant', steps: pendingSteps, final: m })
      pendingSteps = []
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

function streamLine(text: string) {
  streamBuf.value = streamBuf.value === '⏳ 正在思考…' ? text : `${streamBuf.value}\n${text}`
  renderStreamText()
}

async function send() {
  const text = input.value.trim()
  if (!text || streaming.value || !currentId.value) return
  input.value = ''
  streamActive.value = true
  streamConv.value = currentId.value
  streamBuf.value = '⏳ 正在思考…'
  answerStarted = false
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
        streamLine(`🔧 调用 ${String(e.tool ?? '')}`)
      } else if (e.event === 'tool_end') {
        streamLine(`✅ ${String(e.tool ?? '')} 完成`)
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
        toast(String(e.content ?? '请求失败'), 'error')
      }
    }, abortCtrl.signal)
    // 标题已通过 done.title 做 inline patch，无需全量刷新
  } catch (err: any) {
    if (err.name !== 'AbortError') toast('连接中断', 'error')
  } finally {
    const targetId = streamConv.value
    streaming.value = false
    streamActive.value = false
    streamConv.value = ''
    const sb = messages.value.find(m => m.id === 'stream-buf')
    if (sb && (sb.content === '' || sb.content === '⏳ 正在思考…') && !pendingApproval.value) {
      sb.content = '（无响应）'
      streamBuf.value = sb.content
    }
    maybePollPending()
    // 流式正常产生回复后，用 DB 真实消息替换本地缓冲气泡（stream-buf）。
    // 若残留 stream-buf，下一次发送会因重复 id 覆盖修改上一条回复。
    // 审批挂起（critical/high）时后端回复尚未落库，保留现场等 decide 后刷新。
    if (currentId.value && currentId.value === targetId && !pendingApproval.value && answerStarted) {
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
    <!-- 会话列表 -->
    <aside class="conv-panel">
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

    <!-- 消息区 -->
    <section class="msg-panel">
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
          <button class="btn btn-primary" :disabled="!input.trim() || streaming || !currentId" @click="send">
            <span v-if="streaming" class="spinner"></span>发送
          </button>
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

.msg-panel { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.msg-list { flex: 1; min-height: 0; overflow-y: auto; padding: 20px 24px; display: flex; flex-direction: column; gap: 16px; }
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
</style>
