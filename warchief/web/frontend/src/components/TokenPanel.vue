<script setup>
import { computed } from 'vue'
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
      <div v-if="budget.session_limit" class="budget">
        <div class="budget-header"><span>Session Budget</span><span :style="{ color: barColor }">${{ (tokens.session_cost_usd || 0).toFixed(2) }} / ${{ budget.session_limit.toFixed(2) }}</span></div>
        <div class="budget-bar"><div class="budget-fill" :style="{ width: budgetPct + '%', background: barColor }"></div></div>
        <div v-if="budget.per_task_default" class="budget-note">Per-task: ${{ budget.per_task_default.toFixed(2) }}</div>
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
.budget-note { font-size: 10px; color: #555; margin-top: 3px; }
.breakdown { padding-top: 4px; border-top: 1px solid #2a2a4a; margin-top: 4px; }
.breakdown-title { font-size: 9px; color: #888; text-transform: uppercase; margin-bottom: 3px; }
.br-row { display: flex; justify-content: space-between; padding: 1px 0; font-size: 11px; }
.bm { color: #85c1e9; } .brl { color: #82e0aa; } .bc { color: #FFD100; }
</style>
