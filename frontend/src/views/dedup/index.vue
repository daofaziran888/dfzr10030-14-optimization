<template>
  <section class="page" data-module="dedup">
    <header class="page-head">
      <div>
        <h2>采集去重管理</h2>
        <p class="page-desc">维护去重策略，围绕策略编号、输入来源、去重键、排序字段做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">登记去重策略</button>
        <button class="btn" data-testid="open-impact" type="button" @click="toggleImpact">
          {{ impactOpen ? '收起重复影响摘要' : '重复影响摘要' }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">导出采集去重清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section v-if="impactOpen" class="impact-panel" data-testid="impact-panel">
      <header class="impact-head">
        <div>
          <h3>重复影响摘要</h3>
          <p class="page-desc">
            按策略窗口汇总重复记录与影响范围，只抽样每组重复记录，不再展开全部原始记录逐条比对。
            同一窗口只呈现一个策略版本，避免两轮调整的影响被重复计算。
          </p>
        </div>
        <div class="impact-controls">
          <label class="impact-field">
            <span>口径</span>
            <select v-model="impactScope" data-testid="impact-scope" @change="previewImpact">
              <option v-for="item in impactScopes" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
          <label class="impact-field">
            <span>窗口</span>
            <select v-model="impactWindow" data-testid="impact-window" @change="previewImpact">
              <option v-for="item in impactWindows" :key="item.window" :value="item.window">
                {{ item.window }} · {{ item.strategy_code }} {{ item.version }}
              </option>
            </select>
          </label>
          <button class="btn" type="button" data-testid="impact-preview" @click="previewImpact">汇总预览</button>
          <button class="btn primary" type="button" data-testid="impact-generate" @click="generateImpact">
            生成摘要
          </button>
        </div>
      </header>

      <div v-if="impactPreview" class="impact-preview" data-testid="impact-preview-card">
        <div class="impact-metric">
          <span class="stat-label">窗口重复记录</span>
          <strong data-testid="preview-duplicate">{{ impactPreview.duplicate_count }}</strong>
        </div>
        <div class="impact-metric">
          <span class="stat-label">被替换记录</span>
          <strong data-testid="preview-replaced">{{ impactPreview.replaced_count }}</strong>
        </div>
        <div class="impact-metric">
          <span class="stat-label">影响窗口范围</span>
          <strong>{{ impactPreview.replaced_range }}</strong>
        </div>
        <div class="impact-metric">
          <span class="stat-label">策略版本</span>
          <strong>{{ impactPreview.version_label }}</strong>
        </div>
        <div class="impact-metric">
          <span class="stat-label">历史版本核对</span>
          <strong :class="impactPreview.history_matches ? 'ok-text' : 'warn-text'">
            {{ impactPreview.history_matches ? '一致' : '不一致（以历史版本为准）' }}
          </strong>
        </div>
        <p class="impact-note">
          历史快照：{{ impactPreview.history_duplicate_count }} 条重复 / 替换
          {{ impactPreview.history_replaced_count }} 条；本次摘要把
          {{ impactPreview.raw_records_avoided }} 条原始记录折叠为分组样本。
        </p>
      </div>

      <div class="stat-row impact-stats">
        <article class="stat-card">
          <span class="stat-label">已汇总窗口</span>
          <strong class="stat-value" data-testid="impact-window-count">{{ impactTotals.windows }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">重复记录合计</span>
          <strong class="stat-value" data-testid="impact-duplicate-total">{{ impactTotals.duplicates }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">被替换记录合计</span>
          <strong class="stat-value" data-testid="impact-replaced-total">{{ impactTotals.replaced }}</strong>
        </article>
      </div>

      <table class="data-table impact-table" data-testid="impact-table">
        <thead>
          <tr>
            <th>窗口</th>
            <th>策略版本</th>
            <th>重复记录</th>
            <th>被替换记录</th>
            <th>影响范围</th>
            <th>历史核对</th>
            <th>状态</th>
            <th>展开</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="summary in impactRows" :key="summary.id">
            <tr :data-testid="`impact-row-${summary.id}`" :data-window="summary.window">
              <td>{{ summary.window }}</td>
              <td data-testid="summary-version">{{ summary.version }}</td>
              <td data-testid="summary-duplicate">{{ summary.duplicate_count }}</td>
              <td data-testid="summary-replaced">{{ summary.replaced_count }}</td>
              <td>{{ summary.replaced_range }}</td>
              <td :class="summary.history_matches ? 'ok-text' : 'warn-text'">
                {{ summary.history_matches ? '与历史一致' : '按历史版本判定' }}
              </td>
              <td>{{ summary.status }}</td>
              <td class="row-actions">
                <button class="link" type="button" :data-testid="`impact-expand-${summary.id}`"
                        @click="toggleSummary(summary.id)">
                  {{ expanded[summary.id] ? '收起' : '展开' }}
                </button>
                <button class="link" type="button" :data-testid="`impact-regenerate-${summary.id}`"
                        @click="regenerateImpact(summary)">
                  核对
                </button>
                <button class="link" type="button" :data-testid="`impact-push-${summary.id}`"
                        @click="pushImpact(summary)">
                  交血缘
                </button>
                <button class="link" type="button" :data-testid="`impact-lookup-${summary.id}`"
                        @click="lookupImpact(summary)">
                  回查
                </button>
              </td>
            </tr>
            <tr v-if="expanded[summary.id]" :data-testid="`impact-detail-${summary.id}`">
              <td colspan="8">
                <div v-for="group in summary.records" :key="group.group" class="impact-group"
                     :data-testid="`impact-group-${group.group}`">
                  <div class="impact-group-head">
                    <strong>{{ group.group }}</strong>
                    <span>版本 {{ group.version }}</span>
                    <span>重复 {{ group.duplicate_count }}</span>
                    <span>替换 {{ group.replaced_count }}</span>
                    <span v-if="group.sample_truncated" class="warn-text">
                      仅展示 {{ group.records.length }}/{{ group.sample_total }} 条样本
                    </span>
                  </div>
                  <table class="data-table">
                    <thead>
                      <tr><th>记录编号</th><th>首次受影响版本</th><th>处理结果</th></tr>
                    </thead>
                    <tbody>
                      <tr v-for="record in group.records" :key="record.record_id">
                        <td>{{ record.record_id }}</td>
                        <td>{{ record.first_version }}</td>
                        <td>{{ record.role }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p v-if="summary.verdict" class="impact-note">{{ summary.verdict }}：{{ summary.verdict_note }}</p>
                <div v-if="lookupResult?.window === summary.window && lookupResult.found" class="impact-group"
                     data-testid="impact-lookup-result">
                  <div class="impact-group-head">
                    <strong>血缘回查 {{ summary.window }}</strong>
                    <span>台账 {{ lookupResult.ledger.length }} 条</span>
                    <span>业务记录 {{ lookupResult.lineage_records.length }} 条</span>
                  </div>
                  <p class="impact-note">
                    {{ lookupResult.lineage_records.length
                      ? lookupResult.lineage_records.map((r) => r['关系编号']).join('、')
                      : '血缘服务尚未生成业务记录，可先在血缘页读取摘要并接力。' }}
                  </p>
                </div>
              </td>
            </tr>
          </template>
          <tr v-if="!impactRows.length">
            <td colspan="8" class="empty-state">暂无重复影响摘要，可选择窗口先汇总预览再生成</td>
          </tr>
        </tbody>
      </table>
      <p v-if="impactMessage" class="impact-note" data-testid="impact-message">{{ impactMessage }}</p>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无采集去重数据，可先登记去重策略</td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记去重策略</h3>
        <label v-for="field in columns" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条采集去重记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/dedup'
const columns = ["策略编号", "输入来源", "去重键", "排序字段", "保留策略", "时间窗口", "重复阈值", "策略状态"]
const actions = ["提交配置", "启用策略", "停用策略"]
const statuses = ["草稿", "已配置", "生效中", "已停用"]
const metricNames = ["策略总数", "生效中策略", "待配置策略"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const stats = computed(() => [
  { label: metricNames[0], value: total.value },
  { label: metricNames[1], value: rows.value.filter((row) => row.status === statuses[1]).length },
  { label: metricNames[2], value: rows.value.filter((row) => row.status === statuses[statuses.length - 1]).length },
])

type ImpactRecord = { record_id: string; group: string; first_version: string; role: string }
type ImpactGroup = {
  group: string
  duplicate_count: number
  replaced_count: number
  sample_total: number
  sample_truncated: boolean
  raw_records_avoided: number
  version: string
  records: ImpactRecord[]
}
type ImpactSummary = {
  id: number
  summary_no: string
  window: string
  scope: string
  scope_label: string
  strategy_code: string
  version: string
  basis_version: string | null
  version_label: string
  duplicate_count: number
  replaced_count: number
  replaced_range: string
  history_duplicate_count: number
  history_replaced_count: number
  history_matches: boolean
  raw_records_avoided: number
  status: string
  records: ImpactGroup[]
  verdict?: string
  verdict_note?: string
}

const IMPACT_ENDPOINT = '/api/dedup/impact'
const impactOpen = ref(false)
const impactSummaries = ref<ImpactSummary[]>([])
const impactWindows = ref<{ window: string; strategy_code: string; version: string }[]>([])
const impactScopes = ref<{ value: string; label: string }[]>([
  { value: 'window', label: '按窗口边界（整段影响）' },
  { value: 'version', label: '按策略版本（新增影响）' },
])
const impactWindow = ref('')
const impactScope = ref('window')
const impactPreview = ref<ImpactSummary | null>(null)
const impactMessage = ref('')
const expanded = ref<Record<number, boolean>>({})
const lookupResult = ref<LookupResult | null>(null)

const impactRows = computed(() => impactSummaries.value.filter((item) => item.scope === impactScope.value))
const impactTotals = computed(() => ({
  windows: new Set(impactRows.value.map((item) => item.window)).size,
  duplicates: impactRows.value.reduce((sum, item) => sum + Number(item.duplicate_count || 0), 0),
  replaced: impactRows.value.reduce((sum, item) => sum + Number(item.replaced_count || 0), 0),
}))

async function loadImpact() {
  try {
    const response = await request(IMPACT_ENDPOINT)
    if (!response.ok) throw new Error('重复影响摘要读取失败')
    const payload = await response.json()
    impactSummaries.value = payload.items ?? []
    impactWindows.value = payload.windows ?? []
    if (payload.scopes?.length) impactScopes.value = payload.scopes
    if (!impactWindow.value && impactWindows.value.length) impactWindow.value = impactWindows.value[0].window
  } catch (error) {
    impactMessage.value = error instanceof Error ? error.message : '重复影响摘要读取失败'
  }
}

async function previewImpact() {
  impactMessage.value = ''
  try {
    const query = new URLSearchParams({ window: impactWindow.value, scope: impactScope.value })
    const response = await request(`${IMPACT_ENDPOINT}/preview?${query}`)
    if (!response.ok) throw new Error('窗口汇总预览失败')
    impactPreview.value = await response.json()
  } catch (error) {
    impactPreview.value = null
    impactMessage.value = error instanceof Error ? error.message : '窗口汇总预览失败'
  }
}

async function generateImpact() {
  impactMessage.value = ''
  try {
    const response = await request(IMPACT_ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { window: impactWindow.value, scope: impactScope.value } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '摘要生成失败')
    impactMessage.value = payload.message
    await loadImpact()
    const created = impactSummaries.value.find(
      (item) => item.window === impactWindow.value && item.scope === impactScope.value,
    )
    if (created) expanded.value = { ...expanded.value, [created.id]: true }
  } catch (error) {
    impactMessage.value = error instanceof Error ? error.message : '摘要生成失败'
  }
}

function toggleSummary(id: number) {
  expanded.value = { ...expanded.value, [id]: !expanded.value[id] }
}

async function regenerateImpact(summary: ImpactSummary) {
  impactMessage.value = ''
  try {
    const response = await request(`${IMPACT_ENDPOINT}/${summary.id}/regenerate`, { method: 'POST' })
    const payload = await response.json()
    impactMessage.value = payload.message
    if (!response.ok || !payload.ok) return
    await loadImpact()
  } catch (error) {
    impactMessage.value = error instanceof Error ? error.message : '核对失败'
  }
}

async function pushImpact(summary: ImpactSummary) {
  impactMessage.value = ''
  try {
    const response = await request(`${IMPACT_ENDPOINT}/${summary.id}/push-lineage`, { method: 'POST' })
    const payload = await response.json()
    impactMessage.value = payload.message
    if (response.ok && payload.ok) await loadImpact()
  } catch (error) {
    impactMessage.value = error instanceof Error ? error.message : '交血缘失败'
  }
}

type LookupResult = {
  window: string
  found: boolean
  ledger: Record<string, unknown>[]
  lineage_records: Record<string, string | number>[]
}

async function lookupImpact(summary: ImpactSummary) {
  impactMessage.value = ''
  expanded.value = { ...expanded.value, [summary.id]: true }
  try {
    const response = await request(`${IMPACT_ENDPOINT}/${summary.id}/lineage`)
    if (!response.ok) throw new Error('血缘回查失败')
    lookupResult.value = await response.json()
  } catch (error) {
    impactMessage.value = error instanceof Error ? error.message : '血缘回查失败'
  }
}

async function toggleImpact() {
  impactOpen.value = !impactOpen.value
  if (impactOpen.value) {
    await loadImpact()
    if (!impactPreview.value) await previewImpact()
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value).toString()
  try {
    const response = await request(`${ENDPOINT}/export?${query}`)
    if (!response.ok) throw new Error('导出失败，请稍后重试')
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = 'dedup.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(columns.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST', body: JSON.stringify(createValues.value),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '登记失败')
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('采集去重动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集去重操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('去重策略列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集去重列表读取失败'
  }
}

onMounted(reload)
</script>
