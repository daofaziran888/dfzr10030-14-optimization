<template>
  <section class="page" data-module="lineage">
    <header class="page-head">
      <div><h2>数据血缘追踪</h2><p class="page-desc">维护血缘关系，围绕关系编号、上游节点、下游节点、来源字段做登记、筛选与状态流转。</p></div>
      <div class="page-actions">
        <button class="btn primary" type="button" data-testid="open-create" @click="openCreate">登记血缘关系</button>
        <button class="btn" type="button" data-testid="open-ledger" @click="toggleLedger">
          {{ ledgerOpen ? '收起重复影响台账' : '重复影响台账' }}
        </button>
        <button class="btn" type="button" data-testid="export" @click="exportRows">导出关系清单</button>
      </div>
    </header>
    <section v-if="ledgerOpen" class="ledger-panel" data-testid="ledger-panel">
      <div class="ledger-head">
        <div>
          <h3>重复影响台账</h3>
          <p class="page-desc">
            读取去重服务的重复影响摘要，把被替换记录对应到下游关系；确认后接力生成可被去重服务回查的业务记录。
          </p>
        </div>
        <div class="impact-controls">
          <label class="impact-field">
            <span>窗口</span>
            <select v-model="ledgerWindow" data-testid="ledger-window" @change="loadLedger">
              <option v-for="item in ledgerOptions" :key="item.window" :value="item.window">
                {{ item.window }} · {{ item.strategy_code }} {{ item.version }}
              </option>
            </select>
          </label>
          <button class="btn" type="button" data-testid="ledger-push" @click="pushLedger">读取摘要</button>
          <button class="btn" type="button" data-testid="ledger-confirm" @click="confirmLedger">确认台账</button>
          <button class="btn primary" type="button" data-testid="ledger-relay" @click="relayLedger">生成业务记录</button>
        </div>
      </div>
      <div v-if="ledgerSummary" class="impact-preview">
        <div class="impact-metric"><span class="stat-label">摘要编号</span><strong data-testid="ledger-summary-no">{{ ledgerSummary.summary_no ?? '—' }}</strong></div>
        <div class="impact-metric"><span class="stat-label">策略版本</span><strong>{{ ledgerSummary.version }}</strong></div>
        <div class="impact-metric"><span class="stat-label">被替换记录</span><strong data-testid="ledger-record-count">{{ ledgerSummary.record_count ?? 0 }}</strong></div>
        <div class="impact-metric"><span class="stat-label">待确认</span><strong>{{ ledgerSummary.pending_count ?? 0 }}</strong></div>
        <div class="impact-metric"><span class="stat-label">业务记录</span><strong data-testid="ledger-lineage-count">{{ ledgerSummary.lineage_record_ids?.length ?? 0 }}</strong></div>
        <div class="impact-metric"><span class="stat-label">台账状态</span><strong data-testid="ledger-status">{{ ledgerSummary.status ?? '未读取' }}</strong></div>
      </div>
      <table class="data-table" data-testid="ledger-table">
        <thead><tr><th>窗口</th><th>记录编号</th><th>角色</th><th>策略版本</th><th>状态</th><th>业务记录</th></tr></thead>
        <tbody>
          <tr v-for="row in ledgerRows" :key="row.id" :data-testid="`ledger-row-${row.id}`">
            <td>{{ row.window }}</td>
            <td>{{ row.record_id }}</td>
            <td>{{ row.role }}</td>
            <td>{{ row.source_version }}</td>
            <td>{{ row.status }}</td>
            <td>{{ row.lineage_record_id ?? '—' }}</td>
          </tr>
          <tr v-if="!ledgerRows.length"><td colspan="6" class="empty-state">该窗口尚未读取重复影响摘要</td></tr>
        </tbody>
      </table>
      <p v-if="ledgerMessage" class="impact-note" data-testid="ledger-message">{{ ledgerMessage }}</p>
    </section>
    <div class="dag-wrap" ref="dagRef">
      <svg class="dag-svg" :viewBox="`0 0 ${svgW} ${svgH}`">
        <defs><marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#94a3b8"/></marker></defs>
        <g v-for="edge in graph.edges" :key="edge.from+edge.to">
          <line class="dag-edge" :x1="nodePos[edge.from]?.x||0" :y1="nodePos[edge.from]?.y||0" :x2="nodePos[edge.to]?.x||0" :y2="nodePos[edge.to]?.y||0"/>
          <text :x="(nodePos[edge.from]?.x+nodePos[edge.to]?.x)/2" :y="(nodePos[edge.from]?.y+nodePos[edge.to]?.y)/2 - 6" font-size="10" fill="#64748b" text-anchor="middle">{{ edge.label }}</text>
        </g>
        <g v-for="node in graph.nodes" :key="node.id" :class="['dag-node', {selected: selectedNode?.id===node.id}]" @click="selectNode(node)" @mousedown="startDrag($event, node)">
          <rect :x="nodePos[node.id]?.x - 60" :y="nodePos[node.id]?.y - 20" width="120" height="40" rx="6" :fill="nodeColor(node.status)"/>
          <text :x="nodePos[node.id]?.x" :y="nodePos[node.id]?.y + 4" text-anchor="middle">{{ node.name || node.label }}</text>
        </g>
      </svg>
    </div>
    <div v-if="selectedNode" class="dag-detail" data-testid="dag-detail">
      <dl><dt>编号</dt><dd>{{ selectedNode.id }}</dd></dl>
      <dl><dt>名称</dt><dd>{{ selectedNode.name || selectedNode.label }}</dd></dl>
      <dl v-for="f in detailFields" :key="f"><dt>{{ f }}</dt><dd>{{ selectedNode[f] ?? '—' }}</dd></dl>
      <div style="grid-column:1/-1; margin-top:8px; display:flex; gap:6px;">
        <button v-for="action in actions" :key="action" class="btn" :data-testid="`action-${selectedNode.id}-${action}`" @click="runAction(action, selectedNode)">{{ action }}</button>
      </div>
    </div>
    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate"><h3>登记血缘关系</h3>
        <label v-for="field in columns.slice(0,3)" :key="field" class="create-field"><span>{{ field }}</span><input v-model="createValues[field]" :placeholder="`请输入${field}`" required /></label>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
          <button class="btn" type="button" @click="showCreate=false">取消</button>
          <button class="btn primary" type="submit" data-testid="submit-create">提交</button>
        </div>
      </form>
    </div>
    <footer class="page-foot"><span>{{ graph.nodes.length }} 个节点</span></footer>
  </section>
</template>
<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { request } from '@/api/client'
const ENDPOINT = '/api/lineage'
const columns = ["关系编号", "上游节点", "下游节点", "来源字段", "目标字段", "转换说明", "采集批次", "关系版本"]
const actions = ["记录关系", "验证关系", "归档关系"]
const statuses = ["草稿", "已记录", "已验证", "已归档"]
const STATUS_COLORS: Record<string,string> = { '草稿':'#e2e8f0','待校验':'#fef3c7','已启用':'#d1fae5','已停用':'#fee2e2' }
const nodeColor = (s: string) => STATUS_COLORS[s] || '#e2e8f0'
const graph = reactive<{nodes: any[], edges: any[]}>({ nodes: [], edges: [] })
const nodePos = ref<Record<number,{x:number;y:number}>>({})
const selectedNode = ref<any>(null)
const detailFields = computed(() => columns.filter((f: string) => !['id','name','label','status'].includes(f)))
const svgW = ref(800); const svgH = ref(400)
const errorMessage = ref('')
const LEDGER_ENDPOINT = '/api/lineage/dedup-impact'
const ledgerOpen = ref(false)
type LedgerWindow = {
  window: string; strategy_code: string; version: string; summary_id: number | null
  summary_no?: string; status?: string; record_count?: number
  pending_count?: number; lineage_record_ids?: number[]
}
const ledgerWindows = ref<LedgerWindow[]>([])
const ledgerRows = ref<any[]>([])
const ledgerWindow = ref('')
const ledgerMessage = ref('')
const ledgerOptions = ref<{ window: string; strategy_code: string; version: string }[]>([])
const ledgerSummary = computed(() => ledgerWindows.value.find((item) => item.window === ledgerWindow.value) ?? null)

async function loadLedger() {
  try {
    const res = await request(`${LEDGER_ENDPOINT}/ledger`)
    const data = await res.json()
    ledgerWindows.value = data.windows ?? []
    ledgerOptions.value = data.options ?? []
    if (!ledgerWindow.value && ledgerOptions.value.length) ledgerWindow.value = ledgerOptions.value[0].window
    ledgerRows.value = (data.items ?? []).filter((row: any) => row.window === ledgerWindow.value)
  } catch (e) { ledgerMessage.value = '重复影响台账读取失败' }
}

async function pushLedger() {
  ledgerMessage.value = ''
  try {
    const res = await request(`${LEDGER_ENDPOINT}/${ledgerWindow.value}/push`, { method: 'POST' })
    const data = await res.json()
    ledgerMessage.value = data.message
    await loadLedger()
  } catch (e) { ledgerMessage.value = '读取重复影响摘要失败' }
}

async function confirmLedger() {
  ledgerMessage.value = ''
  try {
    const res = await request(`${LEDGER_ENDPOINT}/${ledgerWindow.value}/confirm`, { method: 'POST' })
    const data = await res.json()
    ledgerMessage.value = data.message
    await loadLedger()
  } catch (e) { ledgerMessage.value = '确认台账失败' }
}

async function relayLedger() {
  ledgerMessage.value = ''
  try {
    const res = await request(`${LEDGER_ENDPOINT}/${ledgerWindow.value}/relay`, { method: 'POST' })
    const data = await res.json()
    ledgerMessage.value = data.message
    await loadLedger()
    await reload()
  } catch (e) { ledgerMessage.value = '接力生成业务记录失败' }
}

async function toggleLedger() {
  ledgerOpen.value = !ledgerOpen.value
  if (ledgerOpen.value) await loadLedger()
}
const creating = ref(false); const showCreate = ref(false)
const createValues = ref<Record<string,string>>({})
let dragNode: any = null; const dagRef = ref<HTMLElement|null>(null)
function layout(nodes: any[]) {
  const w = 800; const h = Math.max(400, nodes.length * 80)
  svgW.value = w; svgH.value = h
  const pos: Record<number,{x:number;y:number}> = {}
  nodes.forEach((n,i) => { pos[n.id] = { x: 120 + (i % 5) * 150, y: 50 + Math.floor(i / 5) * 80 } })
  nodePos.value = pos
}
function selectNode(node: any) { selectedNode.value = selectedNode.value?.id === node.id ? null : node }
function startDrag(e: MouseEvent, node: any) { dragNode = node; const onMove = (ev: MouseEvent) => { if(!dragNode) return; nodePos.value[node.id] = { x: ev.offsetX, y: ev.offsetY } }; const onUp = () => { dragNode = null; document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp) }; document.addEventListener('mousemove', onMove); document.addEventListener('mouseup', onUp) }
async function reload() {
  try { const res = await request(ENDPOINT); const data = await res.json(); graph.nodes = data.nodes || []; graph.edges = data.edges || []; layout(graph.nodes) } catch(e) { errorMessage.value = '加载失败' }
}
async function runAction(action: string, node: any) {
  try { await request(`${ENDPOINT}/${node.id}/actions`, { method: 'POST', body: JSON.stringify({ action }) }); await reload() } catch(e) { errorMessage.value = '操作失败' }
}
function openCreate() { createValues.value = {}; showCreate.value = true }
async function submitCreate() {
  try { const res = await request(ENDPOINT, { method: 'POST', body: JSON.stringify({ values: createValues.value }) }); if(!res.ok) throw new Error('创建失败'); showCreate.value = false; await reload() } catch(e: any) { errorMessage.value = e.message }
}
function exportRows() { window.open(`${ENDPOINT}/export`, '_blank') }
onMounted(reload)
</script>
