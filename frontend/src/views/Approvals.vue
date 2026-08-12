<script setup lang="ts">
import { ref, onMounted } from 'vue'
import client from '../api/client'
import { toast } from '../api/toast'
import { fmtDateTime } from '../api/format'
import type { ApprovalItem } from '../api/types'

const status = ref('pending')
const items = ref<ApprovalItem[]>([])
const loading = ref(false)

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

const categoryLabel: Record<string, string> = { tool_call: '工具调用', experience_promotion: '经验晋升' }
const riskLabel: Record<string, string> = { critical: '高危', high: '较高', medium: '中危' }
const riskTag: Record<string, string> = { critical: 'tag-red', high: 'tag-orange', medium: 'tag-blue' }
const statusLabel: Record<string, string> = { pending: '待审批', approved: '已通过', rejected: '已驳回' }
const statusTag: Record<string, string> = { pending: 'tag-orange', approved: 'tag-green', rejected: 'tag-red' }

// 钉钉处理跳转地址：优先移动端短链，其次 PC 端（均为钉钉审批实例链接，钉钉内/浏览器均可打开）
function goUrl(a: ApprovalItem): string {
  return a.mobile_url || a.pc_url || ''
}

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
          {{ statusLabel[s] }}
        </button>
      </div>
      <span class="text-muted text-sm">共 {{ items.length }} 条</span>
    </div>

    <div class="card">
      <div v-if="loading" class="loading-row"><span class="spinner"></span>加载中…</div>
      <div class="table-wrap" v-else>
        <table>
          <thead>
            <tr><th>类型</th><th>标题</th><th>风险</th><th>详情</th><th>发起人</th><th>提交时间</th><th>状态</th><th>审批人</th><th style="text-align:right">去向 / 备注</th></tr>
          </thead>
          <tbody>
            <tr v-for="a in items" :key="a.id">
              <td><span class="tag tag-blue">{{ categoryLabel[a.category] ?? a.category }}</span></td>
              <td style="max-width:220px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ a.title }}</td>
              <td>
                <span v-if="a.risk" class="tag" :class="riskTag[a.risk] ?? 'tag-gray'">{{ riskLabel[a.risk] ?? a.risk }}</span>
                <span v-else class="tag tag-gray">—</span>
              </td>
              <td class="muted text-sm mono" style="max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ fmtArgs(a.context) }}</td>
              <td class="muted text-sm">{{ a.requester_name || a.requester_id?.slice(0, 8) }}</td>
              <td class="muted text-sm">{{ fmtDateTime(a.submitted_at) }}</td>
              <td>
                <!-- 待审批：展示钉钉推送状态；已处理：正常状态标签 -->
                <template v-if="a.status === 'pending'">
                  <span class="tag" :class="a.push_status === 'pushed' ? 'tag-orange' : 'tag-gray'">
                    {{ a.push_status === 'pushed' ? '已推送·待审批' : '未推送' }}
                  </span>
                </template>
                <span v-else class="tag" :class="statusTag[a.status] ?? 'tag-gray'">{{ statusLabel[a.status] ?? a.status }}</span>
              </td>
              <td class="muted text-sm">{{ a.approver_name || '—' }}</td>
              <td style="text-align:right">
                <!-- M4 全走钉钉审批：去钉钉处理（跳转钉钉审批实例），无本地审批按钮 -->
                <template v-if="a.status === 'pending'">
                  <a v-if="goUrl(a)" class="btn btn-sm btn-primary" :href="goUrl(a)" target="_blank" rel="noopener">去钉钉处理</a>
                  <span v-else class="muted text-sm">{{ a.push_status === 'pushed' ? '回填中' : '未推送' }}</span>
                </template>
                <span v-else class="muted text-sm">{{ a.comment || '—' }}</span>
              </td>
            </tr>
            <tr v-if="!items.length">
              <td colspan="9"><div class="empty"><span class="icon">📋</span>{{ status === 'pending' ? '暂无待审批事项' : '暂无记录' }}</div></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-wrap { padding: 20px; }
@media (max-width: 768px) {
  .page-wrap { padding: 12px; }
  /* 顶部状态切换按钮行窄屏换行，避免溢出 */
  .row-between { flex-wrap: wrap; row-gap: 8px; }
}
</style>
