<script setup lang="ts">
import { ref, onMounted } from 'vue'
import client from '../api/client'
import { toast } from '../api/toast'
import { fmtDateTime } from '../api/format'
import type { ApprovalItem, FormSchemaField, DingTalkFormSchema } from '../api/types'

const status = ref('pending')
const items = ref<ApprovalItem[]>([])
const loading = ref(false)
const dingtalkEnabled = ref(false)
const processCodes = ref<Record<string, string>>({})

onMounted(async () => {
  try {
    const { data } = await client.get('/dingtalk/status')
    dingtalkEnabled.value = data.enabled
    processCodes.value = data.process_codes
  } catch { /* ignore */ }
  await load()
})

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

// ====== 表单弹窗 ======
const formModal = ref({
  visible: false,
  approval: null as ApprovalItem | null,
  processCode: '',
  schema: null as DingTalkFormSchema | null,
  fields: [] as FormSchemaField[],
  loaded: false,
  formValues: {} as Record<string, unknown>,
  errors: {} as Record<string, string>,
  submitting: false,
})

const categoryLabels: Record<string, string> = {
  tool_call: '工具调用审批',
  experience_promotion: '经验晋升审批',
}

// 经验层级英文 code → 模板选项中文（自动预填单选字段用）
const SCOPE_LABELS: Record<string, string> = {
  personal: '个人',
  dept: '部门',
  company: '公司',
}

/**
 * 从审批单上下文/标题启发式预填字段值：
 * - experience_promotion：「当前层级」= from_scope、「晋升目标」= to_scope、
 *   「经验标题」= title、「经验详情」= summary
 * - tool_call：「工具」= tool、「参数」= args JSON、「原因」= reason
 * 单选字段值必须命中模板选项才填，避免提交 formConverterError。
 */
function autoFillValue(field: FormSchemaField, approval: ApprovalItem): unknown {
  const ctx = (approval.context || {}) as Record<string, unknown>
  const args = (ctx.args || {}) as Record<string, unknown>
  const label = field.label || ''
  let raw: unknown

  // ---- 活动创建/发布审批（tool_call：args 带活动数据）----
  // 放最前：字段名更具体（活动名称/预算/渠道/日期），避免被通用「标题」规则抢占
  if (label.includes('活动名称') || label.includes('活动标题')) {
    raw = args.name
  } else if (label.includes('预算')) {
    raw = args.budget
  } else if (label.includes('渠道')) {
    // 发布渠道是数组，转成逗号分隔文本
    raw = Array.isArray(args.channels) ? args.channels.join('、') : args.channel
  } else if (label.includes('开始日期')) {
    raw = args.start_date
  } else if (label.includes('结束日期')) {
    raw = args.end_date
  } else if (label.includes('活动') && label.includes('ID')) {
    raw = args.campaign_id
  }
  // ---- 经验晋升审批 ----
  else if (label.includes('当前层级')) {
    raw = SCOPE_LABELS[String(ctx.from_scope ?? ctx.fromScope ?? '')]
  } else if (label.includes('晋升目标')) {
    raw = SCOPE_LABELS[String(ctx.to_scope ?? ctx.toScope ?? '')]
  } else if (label.includes('标题')) {
    raw = String(approval.title || '').replace(/^经验晋升[:：]\s*/, '') || ctx.title
  } else if (label.includes('详情')) {
    raw = ctx.summary
  } else if (label.includes('理由')) {
    raw = ctx.reason || (ctx.from_scope ? '经验晋升申请' : '')
  }
  // ---- 通用工具审批 ----
  else if (label.includes('工具')) {
    raw = ctx.tool
  } else if (label.includes('参数')) {
    raw = ctx.args ? JSON.stringify(ctx.args, null, 2) : ''
  } else if (label.includes('原因')) {
    raw = ctx.reason
  }

  if (raw === undefined || raw === '') return undefined
  // 单选：必须命中模板选项，否则不填（避免提交时钉钉校验失败）
  if (field.type === 'SingleChoiceField' && field.options) {
    return field.options.some(o => o.value === raw) ? raw : undefined
  }
  return raw
}

function initFieldValue(field: FormSchemaField): unknown {
  if (field.type === 'TableField' && field.children) {
    return [{ __rowId: genRowId(), ...initChildValues(field.children) }]
  }
  if (field.type === 'MultiChoiceField') return []
  return ''
}

function initChildValues(fields: FormSchemaField[]): Record<string, unknown> {
  const obj: Record<string, unknown> = {}
  for (const f of fields) {
    obj[f.id] = f.type === 'TableField' && f.children
      ? [{ __rowId: genRowId(), ...initChildValues(f.children) }]
      : (f.type === 'MultiChoiceField' ? [] : '')
  }
  return obj
}

function genRowId() {
  return `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

async function openFormModal(approval: ApprovalItem) {
  // 根据审批类目找 processCode
  const processCode = processCodes.value[approval.category]
  if (!processCode) {
    toast(`审批类目「${approval.category}」未配置钉钉模板`, 'error')
    return
  }

  // 加载表单 schema
  try {
    // 先打开弹窗进入加载态，请求完成后再切到表单/空态
    formModal.value = {
      visible: true,
      approval,
      processCode,
      schema: null,
      fields: [],
      loaded: false,
      formValues: {},
      errors: {},
      submitting: false,
    }
    const { data } = await client.get<{ schema: DingTalkFormSchema }>(`/dingtalk/form-schemas/${processCode}`)
    formModal.value = {
      ...formModal.value,
      schema: data.schema,
      fields: data.schema.fields,
      loaded: true,
    }
    // 预填已有的 form_values
    const existing = approval.form_values || {}
    for (const f of data.schema.fields) {
      if (existing[f.id] !== undefined) {
        formModal.value.formValues[f.id] = existing[f.id]
      } else {
        formModal.value.formValues[f.id] = initFieldValue(f)
        // 智能预填：用审批单上下文/标题匹配字段，减少手动输入
        const auto = autoFillValue(f, approval)
        if (auto !== undefined) formModal.value.formValues[f.id] = auto
      }
    }
  } catch (err: any) {
    formModal.value.visible = false
    toast(err.response?.data?.detail || '加载表单模板失败', 'error')
  }
}

// ---- TableField 操作 ----
function getTableRows(fieldId: string): Record<string, unknown>[] {
  const val = formModal.value.formValues[fieldId]
  return Array.isArray(val) ? val : []
}

function addTableRow(fieldId: string, children: FormSchemaField[]) {
  const rows = getTableRows(fieldId)
  const newRow: Record<string, unknown> = { __rowId: genRowId() }
  for (const c of children) {
    newRow[c.id] = c.type === 'TableField' && c.children
      ? [{ __rowId: genRowId(), ...initChildValues(c.children) }]
      : (c.type === 'MultiChoiceField' ? [] : '')
  }
  rows.push(newRow)
  updateFormField(fieldId, rows)
}

function removeTableRow(fieldId: string, index: number) {
  const rows = getTableRows(fieldId)
  rows.splice(index, 1)
  updateFormField(fieldId, rows)
}

function getTableValue(fieldId: string, rowIndex: number, childId: string): unknown {
  const rows = getTableRows(fieldId)
  return rows[rowIndex]?.[childId] ?? ''
}

function setTableValue(fieldId: string, rowIndex: number, childId: string, value: unknown) {
  const rows = getTableRows(fieldId)
  if (!rows[rowIndex]) rows[rowIndex] = {}
  rows[rowIndex] = { ...rows[rowIndex], [childId]: value }
  updateFormField(fieldId, [...rows])
}

function updateFormField(fieldId: string, value: unknown) {
  formModal.value.formValues = { ...formModal.value.formValues, [fieldId]: value }
  if (formModal.value.errors[fieldId]) {
    formModal.value.errors = { ...formModal.value.errors, [fieldId]: '' }
  }
}

function setFieldValue(fieldId: string, value: unknown) {
  formModal.value.formValues = { ...formModal.value.formValues, [fieldId]: value }
  if (formModal.value.errors[fieldId]) {
    formModal.value.errors = { ...formModal.value.errors, [fieldId]: '' }
  }
}

function toggleCheckbox(fieldId: string, optionValue: string, checked: boolean) {
  const current = (formModal.value.formValues[fieldId] as string[]) || []
  const updated = checked ? [...current, optionValue] : current.filter(v => v !== optionValue)
  formModal.value.formValues = { ...formModal.value.formValues, [fieldId]: updated }
}

// ---- 校验 ----
function validate(): boolean {
  formModal.value.errors = {}
  let valid = true

  function checkFields(fields: FormSchemaField[]) {
    for (const f of fields) {
      if (f.type === 'TableField' && f.children) {
        const rows = getTableRows(f.id)
        if (f.required && rows.length === 0) {
          formModal.value.errors[f.id] = `${f.label} 至少添加一行`
          valid = false
        }
        for (const row of rows) {
          checkFields(f.children)
        }
      } else {
        const val = formModal.value.formValues[f.id]
        if (f.required) {
          const isEmpty = val === '' || (Array.isArray(val) && val.length === 0)
          if (isEmpty) {
            formModal.value.errors[f.id] = `${f.label} 为必填项`
            valid = false
          }
        }
      }
    }
  }

  checkFields(formModal.value.fields)
  return valid
}

// ---- 提交 ----
async function handleSubmit() {
  if (!validate()) {
    toast('请完善必填项', 'error')
    return
  }
  formModal.value.submitting = true
  try {
    const { data } = await client.post(`/approvals/${formModal.value.approval!.id}/submit`, {
      form_values: formModal.value.formValues,
    })
    formModal.value.visible = false
    toast('审批已提交到钉钉，等待审批', 'success')
    // 刷新列表
    await load()
  } catch (err: any) {
    toast(err.response?.data?.detail || '提交失败', 'error')
  } finally {
    formModal.value.submitting = false
  }
}

function closeModal() {
  formModal.value.visible = false
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
                <!-- M4 全走钉钉审批：已推送→去钉钉处理；未推送→发起审批弹窗 -->
                <template v-if="a.status === 'pending'">
                  <a v-if="goUrl(a)" class="btn btn-sm btn-primary" :href="goUrl(a)" target="_blank" rel="noopener">去钉钉处理</a>
                  <button v-else-if="dingtalkEnabled" class="btn btn-sm btn-primary" @click="openFormModal(a)">发起审批</button>
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

    <!-- 表单弹窗 -->
    <div v-if="formModal.visible" class="modal-mask" @click.self="closeModal">
      <div class="modal modal-lg">
        <h3 class="modal-title">📋 {{ (formModal.approval ? (categoryLabels[formModal.approval.category] ?? formModal.approval.category) : '审批') }} — 填写表单</h3>
        <p class="text-muted text-sm" style="margin:4px 0 0">标题：{{ formModal.approval?.title }}</p>

        <!-- 表单加载中 -->
        <div v-if="!formModal.loaded" class="loading-row" style="padding:24px">
          <span class="spinner"></span>加载表单模板中…
        </div>

        <!-- 模板无可填写字段 -->
        <div v-else-if="!formModal.fields.length" class="modal-body col" style="gap:16px;padding:24px">
          <p class="text-muted text-sm">该审批模板没有可填写的表单字段，无法手动发起审批，请检查钉钉后台模板配置。</p>
        </div>

        <!-- 动态表单 -->
        <div v-else class="modal-body col" style="gap:16px">
          <template v-for="f in formModal.fields" :key="f.id">
            <!-- TextField -->
            <div v-if="f.type === 'TextField'" class="form-group">
              <label class="form-label">{{ f.label }}{{ f.required ? ' *' : '' }}</label>
              <input class="input" v-model="formModal.formValues[f.id] as string"
                     :placeholder="f.placeholder || `请输入${f.label}`" />
              <span v-if="formModal.errors[f.id]" class="form-error">{{ formModal.errors[f.id] }}</span>
            </div>

            <!-- TextareaField -->
            <div v-else-if="f.type === 'TextareaField'" class="form-group">
              <label class="form-label">{{ f.label }}{{ f.required ? ' *' : '' }}</label>
              <textarea class="textarea" rows="3" v-model="formModal.formValues[f.id] as string"
                        :placeholder="f.placeholder || `请输入${f.label}`" />
              <span v-if="formModal.errors[f.id]" class="form-error">{{ formModal.errors[f.id] }}</span>
            </div>

            <!-- MoneyField -->
            <div v-else-if="f.type === 'MoneyField'" class="form-group">
              <label class="form-label">{{ f.label }}{{ f.required ? ' *' : '' }}</label>
              <input class="input" type="number" step="0.01" v-model="formModal.formValues[f.id] as string"
                     :placeholder="f.placeholder || '请输入金额'" />
              <span v-if="formModal.errors[f.id]" class="form-error">{{ formModal.errors[f.id] }}</span>
            </div>

            <!-- NumericField -->
            <div v-else-if="f.type === 'NumericField'" class="form-group">
              <label class="form-label">{{ f.label }}{{ f.required ? ' *' : '' }}</label>
              <input class="input" type="number" v-model="formModal.formValues[f.id] as string"
                     :placeholder="f.placeholder || `请输入${f.label}`" />
              <span v-if="formModal.errors[f.id]" class="form-error">{{ formModal.errors[f.id] }}</span>
            </div>

            <!-- DatePickerField -->
            <div v-else-if="f.type === 'DatePickerField'" class="form-group">
              <label class="form-label">{{ f.label }}{{ f.required ? ' *' : '' }}</label>
              <input class="input" type="date" v-model="formModal.formValues[f.id] as string"
                     :placeholder="f.placeholder || `请选择${f.label}`" />
              <span v-if="formModal.errors[f.id]" class="form-error">{{ formModal.errors[f.id] }}</span>
            </div>

            <!-- SingleChoiceField -->
            <div v-else-if="f.type === 'SingleChoiceField'" class="form-group">
              <label class="form-label">{{ f.label }}{{ f.required ? ' *' : '' }}</label>
              <select class="select" v-model="formModal.formValues[f.id] as string">
                <option value="">请选择</option>
                <option v-for="opt in f.options" :key="opt.key" :value="opt.value">{{ opt.value }}</option>
              </select>
              <span v-if="formModal.errors[f.id]" class="form-error">{{ formModal.errors[f.id] }}</span>
            </div>

            <!-- MultiChoiceField -->
            <div v-else-if="f.type === 'MultiChoiceField'" class="form-group">
              <label class="form-label">{{ f.label }}{{ f.required ? ' *' : '' }}</label>
              <div class="checkbox-group">
                <label v-for="opt in f.options" :key="opt.key" class="checkbox-label">
                  <input type="checkbox"
                         :checked="(formModal.formValues[f.id] as string[] || []).includes(opt.value)"
                         @change="toggleCheckbox(f.id, opt.value, ($event.target as HTMLInputElement).checked)" />
                  <span>{{ opt.value }}</span>
                </label>
              </div>
              <span v-if="formModal.errors[f.id]" class="form-error">{{ formModal.errors[f.id] }}</span>
            </div>

            <!-- TableField (明细表) -->
            <div v-else-if="f.type === 'TableField'" class="form-group table-group">
              <div class="table-group-header">
                <span class="form-label">{{ f.label }}{{ f.required ? ' *' : '' }}</span>
                <button class="btn btn-sm btn-primary" @click="addTableRow(f.id, f.children || [])">+ 添加行</button>
              </div>
              <div v-if="getTableRows(f.id).length === 0" class="empty text-sm muted">
                暂无明细，点击「添加行」开始
              </div>
              <div v-else class="table-wrap">
                <table class="table table-sm">
                  <thead>
                    <tr>
                      <th v-for="cf in f.children" :key="cf.id" style="min-width:100px">{{ cf.label }}</th>
                      <th style="width:50px;text-align:right">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, rowIdx) in getTableRows(f.id)" :key="(row as any).__rowId || rowIdx">
                      <td v-for="cf in f.children" :key="cf.id">
                        <template v-if="cf.type === 'TextField'">
                          <input class="input" :value="getTableValue(f.id, rowIdx, cf.id) as string"
                                 placeholder="请输入" @input="setTableValue(f.id, rowIdx, cf.id, ($event.target as HTMLInputElement).value)" />
                        </template>
                        <template v-else-if="cf.type === 'TextareaField'">
                          <textarea class="textarea" rows="1" :value="getTableValue(f.id, rowIdx, cf.id) as string"
                                    @input="setTableValue(f.id, rowIdx, cf.id, ($event.target as HTMLTextAreaElement).value)" />
                        </template>
                        <template v-else-if="cf.type === 'MoneyField'">
                          <input class="input" type="number" step="0.01" :value="getTableValue(f.id, rowIdx, cf.id) as string"
                                 @input="setTableValue(f.id, rowIdx, cf.id, parseFloat(($event.target as HTMLInputElement).value) || 0)" />
                        </template>
                        <template v-else-if="cf.type === 'NumericField'">
                          <input class="input" type="number" :value="getTableValue(f.id, rowIdx, cf.id) as string"
                                 @input="setTableValue(f.id, rowIdx, cf.id, parseFloat(($event.target as HTMLInputElement).value) || 0)" />
                        </template>
                        <template v-else-if="cf.type === 'DatePickerField'">
                          <input class="input" type="date" :value="getTableValue(f.id, rowIdx, cf.id) as string"
                                 @input="setTableValue(f.id, rowIdx, cf.id, ($event.target as HTMLInputElement).value)" />
                        </template>
                        <template v-else-if="cf.type === 'SingleChoiceField'">
                          <select class="select" :value="getTableValue(f.id, rowIdx, cf.id) as string"
                                  @change="setTableValue(f.id, rowIdx, cf.id, ($event.target as HTMLSelectElement).value)">
                            <option value="">请选择</option>
                            <option v-for="opt in cf.options" :key="opt.key" :value="opt.value">{{ opt.value }}</option>
                          </select>
                        </template>
                        <template v-else>
                          <span class="muted text-sm">暂不支持</span>
                        </template>
                      </td>
                      <td style="text-align:right">
                        <button class="btn btn-sm btn-danger" @click="removeTableRow(f.id, rowIdx)">删除</button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <span v-if="formModal.errors[f.id]" class="form-error">{{ formModal.errors[f.id] }}</span>
            </div>
          </template>
        </div>

        <div class="modal-foot" v-if="formModal.loaded && formModal.fields.length">
          <button class="btn" @click="closeModal">取消</button>
          <button class="btn btn-primary" :disabled="formModal.submitting" @click="handleSubmit">
            {{ formModal.submitting ? '提交中…' : '确认提交' }}
          </button>
        </div>
        <div class="modal-foot" v-else>
          <button class="btn" @click="closeModal">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-wrap { padding: 20px; }
.form-group { margin-bottom: 12px; }
.form-label { display: block; font-size: 13px; font-weight: 500; margin-bottom: 4px; color: var(--foreground); }
.form-error { display: block; font-size: 12px; color: var(--danger, #e5484d); margin-top: 4px; }
.checkbox-group { display: flex; flex-wrap: wrap; gap: 12px; }
.checkbox-label { display: flex; align-items: center; gap: 4px; font-size: 13px; cursor: pointer; }
.table-group-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.table-sm td, .table-sm th { padding: 8px; font-size: 13px; }
.modal-lg { width: 600px; max-width: 90vw; max-height: 80vh; overflow-y: auto; }
@media (max-width: 768px) {
  .page-wrap { padding: 12px; }
  .form-label { font-size: 12px; }
  .modal-lg { width: 95vw; }
}
</style>
