<script setup lang="ts">
import { ref, onMounted } from 'vue'
import client from '../api/client'
import { toast } from '../api/toast'
import type { ApprovalItem } from '../api/types'

const status = ref('pending')
const items = ref<ApprovalItem[]>([])
const loading = ref(false)

// 审批弹窗
const decideTarget = ref<ApprovalItem | null>(null)
const comment = ref('')

onMounted(load)

async function load() {
  loading.value = true
  try {
    const { data } = await client.get<ApprovalItem[]>('/approvals', { params: { status: status.value } })
    items.value = data
  } catch (err: any) {
    toast(err.response?.data?.detail || '加载失败', 'error')
  } finally {
    loading.value = false
  }
}

function openDecide(item: ApprovalItem) {
  decideTarget.value = item
  comment.value = ''
}

async function decide(approve: boolean) {
  const target = decideTarget.value
  if (!target) return
  try {
    await client.post(`/approvals/${target.id}/decide`, { approve, comment: comment.value })
    toast(approve ? '已通过' : '已驳回', approve ? 'success' : 'info')
    decideTarget.value = null
    await load()
  } catch (err: any) {
    toast(err.response?.data?.detail || '操作失败', 'error')
  }
}

const categoryLabel: Record<string, string> = { tool_call: '工具调用', experience_promotion: '经验晋升' }
const riskTag: Record<string, string> = { critical: 'tag-red', high: 'tag-orange', medium: 'tag-blue' }
const statusTag: Record<string, string> = { pending: 'tag-orange', approved: 'tag-green', rejected: 'tag-red' }

function fmtArgs(ctx: Record<string, unknown> | null): string {
  if (!ctx) return ''
  const { tool, args, ...rest } = ctx as Record<string, any>
  if (tool) return `${tool} ${JSON.stringify(args ?? '')}`
  return JSON.stringify(rest).slice(0, 80)
}
</script>

<template>
  <div class="page-wrap">
    <div class="row-between mb-12">
      <div class="row">
        <button v-for="s in ['pending', 'approved', 'rejected']" :key="s" class="btn btn-sm"
                :class="{ 'btn-primary': status === s }" @click="status = s; load()">
          {{ { pending: '待审批', approved: '已通过', rejected: '已驳回' }[s] }}
        </button>
      </div>
      <span class="text-muted text-sm">共 {{ items.length }} 条</span>
    </div>

    <div class="card">
      <div v-if="loading" class="loading-row"><span class="spinner"></span>加载中…</div>
      <div class="table-wrap" v-else>
        <table>
          <thead>
            <tr><th>类型</th><th>标题</th><th>风险</th><th>详情</th><th>发起人</th><th>提交时间</th><th>状态</th><th style="text-align:right">操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="a in items" :key="a.id">
              <td><span class="tag tag-blue">{{ categoryLabel[a.category] ?? a.category }}</span></td>
              <td style="max-width:220px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ a.title }}</td>
              <td>
                <span v-if="a.risk" class="tag" :class="riskTag[a.risk] ?? 'tag-gray'">{{ a.risk }}</span>
                <span v-else class="tag tag-gray">—</span>
              </td>
              <td class="muted text-sm mono" style="max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ fmtArgs(a.context) }}</td>
              <td class="muted text-sm">{{ a.requester_id?.slice(0, 8) }}</td>
              <td class="muted text-sm">{{ a.submitted_at?.slice(0, 16) }}</td>
              <td><span class="tag" :class="statusTag[a.status] ?? 'tag-gray'">{{ a.status }}</span></td>
              <td style="text-align:right">
                <button v-if="a.status === 'pending'" class="btn btn-sm btn-primary" @click="openDecide(a)">审批</button>
                <span v-else class="muted text-sm">{{ a.comment || '—' }}</span>
              </td>
            </tr>
            <tr v-if="!items.length">
              <td colspan="8"><div class="empty"><span class="icon">📋</span>{{ status === 'pending' ? '暂无待审批事项' : '暂无记录' }}</div></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 审批弹窗 -->
    <div v-if="decideTarget" class="modal-mask">
      <div class="modal">
        <h3 class="modal-title">审批 · {{ decideTarget.title }}</h3>
        <div class="modal-body col">
          <div class="card" style="background:var(--video-bg)">
            <pre class="mono" style="margin:0;font-size:12px">{{ JSON.stringify(decideTarget.context, null, 2) }}</pre>
          </div>
          <input class="input" v-model="comment" placeholder="审批意见（可选）" />
        </div>
        <div class="modal-foot">
          <button class="btn" @click="decideTarget = null">取消</button>
          <button class="btn btn-danger" @click="decide(false)">驳回</button>
          <button class="btn btn-primary" @click="decide(true)">通过</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-wrap { padding: 20px; }
</style>
