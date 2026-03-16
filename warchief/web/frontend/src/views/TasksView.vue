<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useWarchiefStore } from '../stores/warchief.js'
const store = useWarchiefStore()
const apiGet = store.apiGet

const tasks = ref([])
const filter = ref('all')
const expanded = ref(new Set())
let pollTimer = null

const filtered = computed(() => {
  if (filter.value === 'all') return tasks.value
  return tasks.value.filter(t => t.status === filter.value)
})

function toggle(id) {
  if (expanded.value.has(id)) expanded.value.delete(id)
  else expanded.value.add(id)
}

function eventColor(type) {
  const map = { spawn: '#82e0aa', advance: '#85c1e9', block: '#f1948a', reject: '#f0b27a', comment: '#FFD100' }
  return map[type] || '#888'
}

async function load() {
  const data = await apiGet('/api/tasks')
  if (Array.isArray(data)) tasks.value = data
}

onMounted(() => { load(); pollTimer = setInterval(load, 10000) })
onUnmounted(() => clearInterval(pollTimer))
</script>

<template>
  <div class="tasks-page">
    <div class="filters">
      <button v-for="f in ['all','open','in_progress','blocked','closed']" :key="f"
              :class="['filter-btn', { active: filter === f }]" @click="filter = f">
        {{ f === 'in_progress' ? 'In Progress' : f.charAt(0).toUpperCase() + f.slice(1) }}
      </button>
      <span class="count">{{ filtered.length }}/{{ tasks.length }}</span>
    </div>

    <div v-if="!filtered.length" class="empty">No tasks found</div>

    <div v-for="t in filtered" :key="t.id" class="task-row">
      <div class="task-header" @click="toggle(t.id)">
        <span class="arrow">{{ expanded.has(t.id) ? '▼' : '▶' }}</span>
        <span class="tid">{{ t.id }}</span>
        <span class="title">{{ t.title }}</span>
        <div class="meta">
          <span :class="'badge badge-' + t.status">{{ t.status }}</span>
          <span v-if="t.stage" class="badge badge-type">{{ t.stage }}</span>
          <span class="badge badge-type">{{ t.type }}</span>
          <span v-if="t.cost" class="badge badge-cost">${{ t.cost.toFixed(2) }}</span>
          <span class="age">{{ t.created }} ago</span>
        </div>
      </div>

      <div v-if="expanded.has(t.id)" class="task-detail">
        <div class="detail-grid">
          <div class="detail-card">
            <h4>Details</h4>
            <p v-if="t.description">{{ t.description }}</p>
            <p v-else class="dim">No description</p>
            <p class="stats">
              Priority: {{ t.priority }} | Spawns: {{ t.spawns }} | Rejections: {{ t.rejections }} | Crashes: {{ t.crashes }}
              <span v-if="t.budget"> | Budget: ${{ t.budget.toFixed(2) }}</span>
            </p>
            <div v-if="t.labels.length" class="label-list">
              <span v-for="l in t.labels" :key="l" class="badge badge-type">{{ l }}</span>
            </div>
          </div>
          <div class="detail-card">
            <h4>Timeline ({{ t.events.length }})</h4>
            <div class="timeline">
              <div v-for="(e, i) in t.events" :key="i" :class="'tl-item tl-' + e.type">
                <span class="tl-age">{{ e.age }}</span>
                <span class="tl-type" :style="{ color: eventColor(e.type) }">{{ e.type }}</span>
                <span class="tl-detail">{{ e.from_stage && e.to_stage ? `${e.from_stage} → ${e.to_stage}` : (e.reason || e.comment?.substring(0, 80) || e.agent || '') }}</span>
              </div>
            </div>
          </div>
        </div>
        <div v-if="t.scratchpad" class="detail-card">
          <h4>Agent Notes</h4>
          <pre class="scratchpad">{{ t.scratchpad }}</pre>
        </div>
        <div v-if="t.messages.length" class="detail-card">
          <h4>Messages</h4>
          <div v-for="(m, i) in t.messages" :key="i" class="msg">
            <span :class="'msg-type msg-' + m.type">{{ m.type }}</span>
            <span class="msg-from">{{ m.from }}</span>
            {{ m.body }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tasks-page { padding: 14px 20px; max-width: 1100px; margin: 0 auto; }
.filters { display: flex; gap: 6px; margin-bottom: 14px; align-items: center; flex-wrap: wrap; }
.filter-btn { background: #16213e; border: 1px solid #2a2a4a; color: #888; padding: 4px 12px; border-radius: 14px; font-size: 12px; cursor: pointer; }
.filter-btn:hover { border-color: #FFD100; }
.filter-btn.active { border-color: #FFD100; color: #FFD100; }
.count { color: #555; font-size: 12px; margin-left: 8px; }
.empty { text-align: center; color: #555; padding: 40px; font-style: italic; }
.task-row { background: #16213e; border: 1px solid #2a2a4a; border-radius: 6px; margin-bottom: 6px; }
.task-header { padding: 10px 14px; cursor: pointer; display: flex; align-items: center; gap: 10px; }
.task-header:hover { background: #1a2a3e; }
.arrow { color: #555; font-size: 11px; min-width: 14px; }
.tid { color: #FFD100; font-weight: bold; font-size: 12px; min-width: 75px; }
.title { flex: 1; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.meta { display: flex; gap: 6px; align-items: center; }
.badge { font-size: 10px; padding: 1px 7px; border-radius: 8px; font-weight: bold; }
.badge-open { background: #1a5276; color: #85c1e9; }
.badge-in_progress { background: #1e6e3e; color: #82e0aa; }
.badge-blocked { background: #8C1616; color: #f1948a; }
.badge-closed { background: #333; color: #888; }
.badge-type { background: #2a2a4a; color: #aaa; }
.badge-cost { background: #0f0f23; color: #FFD100; }
.age { color: #555; font-size: 11px; }
.task-detail { padding: 0 14px 14px; border-top: 1px solid #2a2a4a; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }
.detail-card { background: #0f0f23; border-radius: 4px; padding: 10px 12px; }
.detail-card h4 { color: #FFD100; font-size: 11px; text-transform: uppercase; margin-bottom: 6px; letter-spacing: 1px; }
.detail-card p { font-size: 12px; color: #ccc; line-height: 1.5; }
.stats { margin-top: 6px; font-size: 11px; color: #888; }
.dim { color: #555; font-style: italic; }
.label-list { margin-top: 6px; display: flex; gap: 4px; flex-wrap: wrap; }
.timeline { padding-left: 16px; border-left: 2px solid #2a2a4a; }
.tl-item { margin-bottom: 4px; font-size: 11px; }
.tl-age { color: #555; min-width: 45px; display: inline-block; }
.tl-type { font-weight: bold; min-width: 65px; display: inline-block; }
.tl-detail { color: #888; }
.scratchpad { background: #0a0a1a; border-radius: 4px; padding: 8px; font-family: 'SF Mono', Consolas, monospace; font-size: 11px; line-height: 1.5; white-space: pre-wrap; color: #ccc; max-height: 200px; overflow-y: auto; margin: 0; }
.msg { padding: 3px 0; font-size: 12px; border-bottom: 1px solid #1a1a2e; }
.msg-type { font-weight: bold; font-size: 10px; text-transform: uppercase; margin-right: 6px; }
.msg-question { color: #FFD100; }
.msg-answer { color: #82e0aa; }
.msg-feedback { color: #85c1e9; }
.msg-rejection { color: #f1948a; }
.msg-from { color: #555; margin-right: 4px; }
</style>
