<script setup lang="ts">
import { ref, onMounted } from 'vue'
import client from '../api/client'
import { toast } from '../api/toast'
import type { McpServer, McpToolInfo, AgentBinding, AgentInfo } from '../api/types'

// ---- MCP 服务 ----
const servers = ref<McpServer[]>([])
const showCreate = ref(false)
const newServer = ref({ name: '', url: '', auth_type: 'none', default_risk: 'medium' })

// 认证配置弹窗
const authTarget = ref<McpServer | null>(null)
const authForm = ref({ auth_type: 'none', api_key: '' })

// 工具风险弹窗
const riskTarget = ref<{ server: McpServer; tools: McpToolInfo[] } | null>(null)

// ---- Agent 绑定 ----
const agents = ref<AgentInfo[]>([])
const activeAgent = ref('marketing')
const bindings = ref<AgentBinding[]>([])
const bindServer = ref('')

onMounted(async () => {
  await Promise.all([loadServers(), loadAgents()])
})

async function loadServers() {
  try {
    const { data } = await client.get<McpServer[]>('/mcp-servers')
    servers.value = data
  } catch { /* ignore */ }
}

async function createServer() {
  const s = newServer.value
  if (!s.name.trim() || !s.url.trim()) return toast('名称与 URL 必填', 'error')
  try {
    await client.post('/mcp-servers', {
      name: s.name, url: s.url, auth_type: s.auth_type, default_risk: s.default_risk,
    })
    toast('MCP 服务已创建', 'success')
    showCreate.value = false
    newServer.value = { name: '', url: '', auth_type: 'none', default_risk: 'medium' }
    await loadServers()
  } catch (err: any) {
    toast(err.response?.data?.detail || '创建失败', 'error')
  }
}

function openAuth(s: McpServer) {
  authTarget.value = s
  authForm.value = { auth_type: s.auth_type, api_key: (s.config as any)?.api_key ?? '' }
}

async function saveAuth() {
  const s = authTarget.value
  if (!s) return
  try {
    await client.put(`/mcp-servers/${s.name}/auth`, {
      auth_type: authForm.value.auth_type,
      api_key: authForm.value.api_key || undefined,
    })
    toast('认证配置已保存', 'success')
    authTarget.value = null
    await loadServers()
  } catch (err: any) {
    toast(err.response?.data?.detail || '保存失败', 'error')
  }
}

async function openTools(s: McpServer) {
  try {
    const { data } = await client.get<McpToolInfo[]>(`/mcp-servers/${s.name}/tools`)
    riskTarget.value = { server: s, tools: data }
  } catch (err: any) {
    toast(`连接失败：${err.response?.data?.detail || '无法发现工具'}`, 'error')
  }
}

async function saveRisks() {
  const target = riskTarget.value
  if (!target) return
  const toolRisks: Record<string, string> = {}
  for (const t of target.tools) toolRisks[t.name] = t.risk
  try {
    await client.put(`/mcp-servers/${target.server.name}/tool-risks`, { tool_risks: toolRisks })
    toast('工具风险已保存', 'success')
    riskTarget.value = null
  } catch (err: any) {
    toast(err.response?.data?.detail || '保存失败', 'error')
  }
}

function setToolRisk(tool: McpToolInfo, risk: string) {
  tool.risk = risk
}

// ---- Agent 绑定 ----
async function loadAgents() {
  try {
    const { data } = await client.get<AgentInfo[]>('/agents')
    agents.value = data
    if (data.length) activeAgent.value = data[0].code
    await loadBindings()
  } catch { /* ignore */ }
}

async function selectAgent(code: string) {
  activeAgent.value = code
  await loadBindings()
}

async function loadBindings() {
  try {
    const { data } = await client.get<AgentBinding[]>(`/agents/${activeAgent.value}/mcp-bindings`)
    bindings.value = data
  } catch { /* ignore */ }
}

async function addBinding() {
  if (!bindServer.value) return
  try {
    await client.post(`/agents/${activeAgent.value}/mcp-bindings`, { mcp_server_name: bindServer.value })
    toast('绑定已添加（重启后生效）', 'success')
    bindServer.value = ''
    await loadBindings()
  } catch (err: any) {
    toast(err.response?.data?.detail || '添加失败', 'error')
  }
}

async function removeBinding(id: string) {
  try {
    await client.delete(`/agents/${activeAgent.value}/mcp-bindings/${id}`)
    await loadBindings()
  } catch (err: any) {
    toast(err.response?.data?.detail || '移除失败', 'error')
  }
}
</script>

<template>
  <div class="page-wrap">
    <div class="page-grid">
      <!-- MCP 服务管理 -->
      <div class="card">
        <div class="row-between mb-12">
          <h3 class="card-title" style="margin:0">MCP 服务</h3>
          <button class="btn btn-sm btn-primary" @click="showCreate = !showCreate">+ 新建</button>
        </div>

        <div v-if="showCreate" class="col mb-12" style="background:var(--video-bg);border:1px solid var(--border);border-radius:var(--radius-md);padding:12px">
          <input class="input" v-model="newServer.name" placeholder="名称（英文）" />
          <input class="input" v-model="newServer.url" placeholder="URL，如 http://localhost:8001/mcp" />
          <div class="row">
            <select class="select" v-model="newServer.auth_type" style="flex:1">
              <option value="none">无认证</option>
              <option value="api_key">API Key</option>
              <option value="bearer">Bearer</option>
            </select>
            <select class="select" v-model="newServer.default_risk" style="flex:1">
              <option value="low">默认风险 low</option>
              <option value="medium">默认风险 medium</option>
              <option value="high">默认风险 high</option>
              <option value="critical">默认风险 critical</option>
            </select>
          </div>
          <div class="row">
            <button class="btn btn-primary" @click="createServer">保存</button>
            <button class="btn" @click="showCreate = false">取消</button>
          </div>
        </div>

        <div class="table-wrap">
          <table>
            <thead><tr><th>名称</th><th>认证</th><th>默认风险</th><th>状态</th><th style="text-align:right">操作</th></tr></thead>
            <tbody>
              <tr v-for="s in servers" :key="s.name">
                <td>
                  <div>{{ s.name }}</div>
                  <div class="muted mono text-sm">{{ s.url }}</div>
                </td>
                <td><span class="tag" :class="s.auth_type === 'none' ? 'tag-gray' : 'tag-cyan'">{{ s.auth_type }}</span></td>
                <td><span class="tag" :class="s.default_risk === 'critical' ? 'tag-red' : s.default_risk === 'high' ? 'tag-orange' : 'tag-gray'">{{ s.default_risk }}</span></td>
                <td><span class="tag" :class="s.enabled ? 'tag-green' : 'tag-gray'">{{ s.enabled ? 'enabled' : 'disabled' }}</span></td>
                <td style="text-align:right">
                  <div class="row" style="justify-content:flex-end;gap:6px">
                    <button class="btn btn-sm" @click="openTools(s)">工具</button>
                    <button class="btn btn-sm" @click="openAuth(s)">认证</button>
                  </div>
                </td>
              </tr>
              <tr v-if="!servers.length"><td colspan="5"><div class="empty"><span class="icon">🔌</span>暂无 MCP 服务</div></td></tr>
            </tbody>
          </table>
        </div>
        <p class="text-muted text-sm mt-8">提示：新增/修改配置后需重启后端生效；认证支持 api_key/bearer，凭证存数据库。</p>
      </div>

      <!-- Agent MCP 绑定 -->
      <div class="card">
        <h3 class="card-title">Agent MCP 绑定</h3>
        <div class="row mb-12">
          <button v-for="a in agents" :key="a.code" class="btn btn-sm" :class="{ 'btn-primary': activeAgent === a.code }"
                  @click="selectAgent(a.code)">{{ a.name }}</button>
        </div>
        <div class="row mb-12">
          <select class="select grow" v-model="bindServer">
            <option value="" disabled>选择要绑定的 MCP 服务</option>
            <option v-for="s in servers" :key="s.name" :value="s.name">{{ s.name }}</option>
          </select>
          <button class="btn btn-primary" :disabled="!bindServer" @click="addBinding">绑定</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>MCP 服务</th><th>状态</th><th style="text-align:right">操作</th></tr></thead>
            <tbody>
              <tr v-for="b in bindings" :key="b.id">
                <td class="mono text-sm">{{ b.mcp_server_name }}</td>
                <td><span class="tag" :class="b.enabled ? 'tag-green' : 'tag-gray'">{{ b.enabled ? '启用' : '停用' }}</span></td>
                <td style="text-align:right"><button class="btn btn-sm btn-danger" @click="removeBinding(b.id)">移除</button></td>
              </tr>
              <tr v-if="!bindings.length"><td colspan="3"><div class="empty"><span class="icon">🔗</span>该 Agent 暂无 MCP 绑定</div></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 认证配置弹窗 -->
    <div v-if="authTarget" class="modal-mask">
      <div class="modal">
        <h3 class="modal-title">认证配置 · {{ authTarget.name }}</h3>
        <div class="modal-body col">
          <div class="row">
            <label class="text-muted text-sm" style="width:70px">认证方式</label>
            <select class="select" v-model="authForm.auth_type" style="flex:1">
              <option value="none">无认证</option>
              <option value="api_key">API Key（Bearer Header）</option>
              <option value="bearer">Bearer Token</option>
            </select>
          </div>
          <div class="row" v-if="authForm.auth_type !== 'none'">
            <label class="text-muted text-sm" style="width:70px">密钥</label>
            <input class="input" v-model="authForm.api_key" type="password" placeholder="API Key / Token" style="flex:1" />
          </div>
          <p class="text-muted text-sm" style="margin:0">凭证将存储于数据库 config JSONB，连接时组装 Authorization: Bearer &lt;key&gt;。</p>
        </div>
        <div class="modal-foot">
          <button class="btn" @click="authTarget = null">取消</button>
          <button class="btn btn-primary" @click="saveAuth">保存</button>
        </div>
      </div>
    </div>

    <!-- 工具风险弹窗 -->
    <div v-if="riskTarget" class="modal-mask">
      <div class="modal" style="width:560px">
        <h3 class="modal-title">工具风险 · {{ riskTarget.server.name }}</h3>
        <div class="modal-body">
          <p class="text-muted text-sm">为每个工具配置风险等级：low 直接执行 / high 即时确认 / critical 进审批中心。</p>
          <div v-for="t in riskTarget.tools" :key="t.name" class="risk-row">
            <div class="grow">
              <div class="mono text-sm">{{ t.name }}</div>
              <div class="muted text-sm">{{ t.description }}</div>
            </div>
            <select class="select" style="width:130px" :value="t.risk" @change="setToolRisk(t, ($event.target as HTMLSelectElement).value)">
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
            </select>
          </div>
          <div v-if="!riskTarget.tools.length" class="empty"><span class="icon">🛠️</span>未发现工具</div>
        </div>
        <div class="modal-foot">
          <button class="btn" @click="riskTarget = null">关闭</button>
          <button class="btn btn-primary" @click="saveRisks">保存风险配置</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-wrap { padding: 20px; }
.page-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
@media (max-width: 1100px) { .page-grid { grid-template-columns: 1fr; } }
.risk-row { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border); }
.risk-row:last-child { border-bottom: none; }
</style>
