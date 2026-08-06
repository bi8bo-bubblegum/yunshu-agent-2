<script setup lang="ts">
defineOptions({ name: 'Chat' })
import { ref, computed, watch, nextTick, onMounted, onActivated } from 'vue'
import { useRouter } from 'vue-router'
import { streamChat, resumeChat, type SSEEvent } from '../api/chat'
import client from '../api/client'
import { toast } from '../api/toast'
import type { Conversation, Message } from '../api/types'

const convs = ref<Conversation[]>([])
const currentId = ref('')
const messages = ref<Message[]>([])
const input = ref('')
const streaming = ref(false)
const listRef = ref<HTMLElement>()
const router = useRouter()

onMounted(loadConvs)

// keep-alive 下从其他页面切回时滚动到底部（流式消息可能已推进）
onActivated(async () => {
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
  currentId.value = id
  messages.value = []
  try {
    const { data } = await client.get<Message[]>(`/conversations/${id}/messages`)
    messages.value = data
  } catch { /* ignore */ }
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

async function send() {
  const text = input.value.trim()
  if (!text || streaming.value || !currentId.value) return
  input.value = ''
  messages.value.push({ id: `u-${Date.now()}`, role: 'user', content: text })
  messages.value.push({ id: `a-${Date.now()}`, role: 'assistant', content: '' })
  streaming.value = true
  abortCtrl = new AbortController()

  const ai = messages.value[messages.value.length - 1]
  try {
    await streamChat(currentId.value, text, (e: SSEEvent) => {
      if (e.event === 'token') ai.content += e.content ?? ''
      else if (e.event === 'confirm_required') {
        const p = (e.payload ?? {}) as Record<string, unknown>
        confirmState.value = {
          visible: true,
          conversationId: currentId.value,
          tool: String(p.tool ?? '未知工具'),
          args: p.args ?? {},
          reason: String(p.reason ?? '高风险操作需要确认'),
          critical: Boolean(p.approval_id),
          approvalId: String(p.approval_id ?? ''),
        }
      } else if (e.event === 'error') {
        toast(String(e.content ?? '请求失败'), 'error')
      }
    }, abortCtrl.signal)
  } catch (err: any) {
    if (err.name !== 'AbortError') toast('连接中断', 'error')
  } finally {
    streaming.value = false
    if (ai.content === '') ai.content = '（无响应）'
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
    await resumeChat(convId, approved)
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
          <div class="conv-meta">{{ c.created_at?.slice(0, 16) }}</div>
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
          <p>向云书 Agent 描述你的任务</p>
          <p class="text-muted text-sm">示例：帮我策划一个国庆营销方案</p>
        </div>
        <div v-for="(m, i) in messages" :key="m.id" class="msg" :class="m.role">
          <div class="avatar">{{ m.role === 'user' ? '我' : '云' }}</div>
          <div class="bubble">
            <div v-if="m.role === 'assistant' && m.content === '' && streaming && i === messages.length - 1" class="typing"><span></span><span></span><span></span></div>
            <pre v-else>{{ m.content }}</pre>
          </div>
        </div>
      </div>

      <div class="input-bar" v-if="currentId">
        <textarea class="textarea" v-model="input" rows="2" placeholder="输入消息，Enter 发送 / Shift+Enter 换行"
                  :disabled="streaming" @keydown.enter.exact.prevent="send" />
        <div class="row-between mt-8">
          <span class="text-muted text-sm">{{ streaming ? 'Agent 思考中…' : activeConv ? '会话已就绪' : '' }}</span>
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
.typing { display: flex; gap: 4px; padding: 6px 2px; }
.typing span { width: 7px; height: 7px; border-radius: 50%; background: var(--muted-foreground); animation: blink 1.2s infinite; }
.typing span:nth-child(2) { animation-delay: .2s; }
.typing span:nth-child(3) { animation-delay: .4s; }
@keyframes blink { 0%, 80%, 100% { opacity: .2; } 40% { opacity: 1; } }

.input-bar { padding: 14px 20px 18px; border-top: 1px solid var(--border); background: var(--background); }
</style>
