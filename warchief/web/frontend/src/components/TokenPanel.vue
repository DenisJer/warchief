<script setup>
import { computed, ref } from 'vue'
import { useWarchiefStore } from '../stores/warchief.js'
const store = useWarchiefStore()
const tokens = computed(() => store.tokens)
const fmt = (n) => (n || 0).toLocaleString()
const budget = computed(() => tokens.value?.budget || {})
const budgetPct = computed(() => {
  if (!budget.value.session_limit) return 0
  return Math.min(100, ((tokens.value?.session_cost_usd || 0) / budget.value.session_limit) * 100)
})
const barColor = computed(() => budgetPct.value >= 100 ? '#8C1616' : budgetPct.value >= 80 ? '#f0b27a' : '#82e0aa')
const byModel = computed(() => Object.entries(tokens.value?.by_model || {}).sort((a, b) => b[1] - a[1]))
const byRole = computed(() => Object.entries(tokens.value?.by_role || {}).sort((a, b) => b[1] - a[1]))
const orch = computed(() => tokens.value?.orchestrator || { ticks: 0, cost_usd: 0, input_tokens: 0, output_tokens: 0, avg_cost_per_tick: 0 })
const editingBudget = ref(false)
const newSessionLimit = ref('')
const newPerTask = ref('')
const busy = ref(false)

async function togglePause() {
  busy.value = true
  try {
    await store.apiPost('/api/config', { paused: !store.paused })
  } finally { busy.value = false }
}

async function saveBudget() {
  busy.value = true
  try {
    const body = {}
    if (newSessionLimit.value) body.session_limit = parseFloat(newSessionLimit.value)
    if (newPerTask.value) body.per_task_default = parseFloat(newPerTask.value)
    await store.apiPost('/api/config', body)
    editingBudget.value = false
    newSessionLimit.value = ''
    newPerTask.value = ''
  } finally { busy.value = false }
}
</script>

<template>
  <div class="panel">
    <div class="panel-header">Tokens</div>
    <div class="panel-body">
      <div class="grid">
        <div class="item"><div class="label">Input</div><div class="val">{{ fmt(tokens.input) }}</div></div>
        <div class="item"><div class="label">Cache Read</div><div class="val">{{ fmt(tokens.cache_read) }}</div></div>
        <div class="item"><div class="label">Cache Write</div><div class="val">{{ fmt(tokens.cache_write) }}</div></div>
        <div class="item"><div class="label">Output</div><div class="val">{{ fmt(tokens.output) }}</div></div>
      </div>
      <div class="cost-row">Session: ${{ (tokens.session_cost_usd || 0).toFixed(2) }} | All-time: ${{ (tokens.cost_usd || 0).toFixed(2) }}</div>
      <div v-if="store.paused" class="paused-banner" @click="togglePause">
        PAUSED — click to resume
      </div>
      <div v-if="budget.session_limit" class="budget">
        <div class="budget-header">
          <span>Session Budget</span>
          <span :style="{ color: barColor }">${{ (tokens.session_cost_usd || 0).toFixed(2) }} / ${{ budget.session_limit.toFixed(2) }}</span>
        </div>
        <div class="budget-bar"><div class="budget-fill" :style="{ width: budgetPct + '%', background: barColor }"></div></div>
        <div class="budget-actions">
          <span v-if="budget.per_task_default" class="budget-note">Per-task: ${{ budget.per_task_default.toFixed(2) }}</span>
          <button class="btn-tiny" @click="editingBudget = !editingBudget">Edit</button>
          <button class="btn-tiny" :class="store.paused ? 'btn-resume' : 'btn-pause'" :disabled="busy" @click="togglePause">
            {{ store.paused ? 'Resume' : 'Pause' }}
          </button>
        </div>
        <div v-if="editingBudget" class="budget-edit">
          <div class="edit-row">
            <label>Session limit ($)</label>
            <input v-model="newSessionLimit" type="number" step="5" :placeholder="budget.session_limit" />
          </div>
          <div class="edit-row">
            <label>Per-task ($)</label>
            <input v-model="newPerTask" type="number" step="0.5" :placeholder="budget.per_task_default" />
          </div>
          <button class="btn-tiny btn-save" :disabled="busy" @click="saveBudget">Save</button>
        </div>
      </div>
      <div v-else class="budget-actions" style="margin-top: 4px">
        <button class="btn-tiny" :class="store.paused ? 'btn-resume' : 'btn-pause'" :disabled="busy" @click="togglePause">
          {{ store.paused ? 'Resume Pipeline' : 'Pause Pipeline' }}
        </button>
      </div>
      <div v-if="orch.ticks" class="breakdown orchestrator-stats">
        <div class="breakdown-title">AI Orchestrator</div>
        <div class="br-row"><span class="brl">Ticks</span><span class="bc">{{ orch.ticks }}</span></div>
        <div class="br-row"><span class="brl">Cost</span><span class="bc">${{ orch.cost_usd.toFixed(4) }}</span></div>
        <div class="br-row"><span class="brl">Avg/tick</span><span class="bc">${{ orch.avg_cost_per_tick.toFixed(4) }}</span></div>
        <div class="br-row"><span class="brl">Input</span><span class="bc">{{ fmt(orch.input_tokens) }}</span></div>
        <div class="br-row"><span class="brl">Output</span><span class="bc">{{ fmt(orch.output_tokens) }}</span></div>
      </div>
      <div v-if="byModel.length" class="breakdown"><div class="breakdown-title">By Model</div><div v-for="[n,c] in byModel" :key="n" class="br-row"><span class="bm">{{ n.split('-')[1] || n }}</span><span class="bc">${{ c.toFixed(4) }}</span></div></div>
      <div v-if="byRole.length" class="breakdown"><div class="breakdown-title">By Role</div><div v-for="[n,c] in byRole" :key="n" class="br-row"><span class="brl">{{ n }}</span><span class="bc">${{ c.toFixed(4) }}</span></div></div>
    </div>
  </div>
</template>

<style scoped>
.panel { background: #16213e; border: 1px solid #2a2a4a; border-radius: 6px; }
.panel-header { background: #0f0f23; border-bottom: 1px solid #8C1616; padding: 6px 12px; font-size: 12px; font-weight: bold; color: #FFD100; text-transform: uppercase; }
.panel-body { padding: 8px 12px; font-size: 12px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
.item { background: #0f0f23; border-radius: 4px; padding: 6px; text-align: center; }
.label { font-size: 9px; color: #888; text-transform: uppercase; }
.val { font-size: 14px; font-weight: bold; color: #FFD100; margin-top: 2px; }
.cost-row { text-align: center; padding: 4px; font-size: 13px; color: #82e0aa; font-weight: bold; margin-top: 4px; }
.budget { padding-top: 6px; border-top: 1px solid #2a2a4a; margin-top: 4px; }
.budget-header { display: flex; justify-content: space-between; font-size: 10px; color: #888; text-transform: uppercase; margin-bottom: 3px; }
.budget-bar { background: #0f0f23; border-radius: 3px; height: 5px; overflow: hidden; }
.budget-fill { height: 100%; transition: width 0.5s; }
.budget-note { font-size: 10px; color: #555; }
.budget-actions { display: flex; align-items: center; gap: 6px; margin-top: 3px; }
.btn-tiny { background: #2a2a4a; border: 1px solid #444; color: #ccc; padding: 2px 8px; border-radius: 3px; font-size: 10px; cursor: pointer; }
.btn-tiny:hover { border-color: #FFD100; }
.btn-pause { border-color: #f0b27a; color: #f0b27a; }
.btn-resume { border-color: #82e0aa; color: #82e0aa; }
.btn-save { border-color: #85c1e9; color: #85c1e9; }
.paused-banner { background: #8C1616; color: #FFD100; text-align: center; padding: 6px; font-size: 11px; font-weight: bold; border-radius: 4px; margin-bottom: 6px; cursor: pointer; text-transform: uppercase; letter-spacing: 1px; }
.paused-banner:hover { background: #a01c1c; }
.budget-edit { background: #0f0f23; border-radius: 4px; padding: 6px; margin-top: 4px; }
.edit-row { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.edit-row label { font-size: 10px; color: #888; min-width: 80px; }
.edit-row input { background: #16213e; border: 1px solid #444; color: #FFD100; padding: 3px 6px; border-radius: 3px; font-size: 11px; width: 80px; }
.breakdown { padding-top: 4px; border-top: 1px solid #2a2a4a; margin-top: 4px; }
.breakdown-title { font-size: 9px; color: #888; text-transform: uppercase; margin-bottom: 3px; }
.br-row { display: flex; justify-content: space-between; padding: 1px 0; font-size: 11px; }
.bm { color: #85c1e9; } .brl { color: #82e0aa; } .bc { color: #FFD100; }
.orchestrator-stats { background: #0f0f23; border-radius: 4px; padding: 6px; }
</style>
