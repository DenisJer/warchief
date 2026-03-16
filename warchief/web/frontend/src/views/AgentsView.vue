<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useWarchiefStore } from '../stores/warchief.js'
const store = useWarchiefStore()
const apiGet = store.apiGet

const agents = ref([])
const selectedAgent = ref(null)
const logLines = ref([])
const autoFollow = ref(true)
const showHistory = ref(false)
let pollTimer = null

const active = computed(() => agents.value.filter(a => a.status === 'alive' || a.status === 'zombie'))
const history = computed(() => agents.value.filter(a => a.status !== 'alive' && a.status !== 'zombie'))

async function loadAgents() {
  const data = await apiGet('/api/agents')
  if (Array.isArray(data)) agents.value = data
  if (!selectedAgent.value && agents.value.length) {
    const alive = active.value
    selectAgent(alive.length ? alive[0].id : agents.value[0].id)
  }
}

async function loadLog() {
  if (!selectedAgent.value) return
  const data = await apiGet(`/api/agent-log/${encodeURIComponent(selectedAgent.value)}?lines=500`)
  if (data.lines) logLines.value = data.lines
}

function selectAgent(id) {
  selectedAgent.value = id
  loadLog()
}

function logColor(line) {
  if (/error|fail|exception/i.test(line)) return '#f1948a'
  if (/warn/i.test(line)) return '#f0b27a'
  if (/success|pass|done/i.test(line)) return '#82e0aa'
  if (/^(Reading|Glob|Grep|Edit|Write|Bash):/i.test(line)) return '#85c1e9'
  return '#888'
}

onMounted(() => {
  // Check URL hash for pre-selected agent
  if (window.location.hash) selectedAgent.value = window.location.hash.substring(1)
  loadAgents()
  pollTimer = setInterval(() => { loadAgents(); if (selectedAgent.value) loadLog() }, 3000)
})
onUnmounted(() => clearInterval(pollTimer))
</script>

<template>
  <div class="agents-page">
    <div class="agent-list">
      <div class="section-header green">Active ({{ active.length }})</div>
      <div v-for="a in active" :key="a.id" :class="['agent-item', { selected: a.id === selectedAgent }]"
           @click="selectAgent(a.id)">
        <div class="agent-name"><span class="dot alive"></span>{{ a.id }}</div>
        <div class="agent-meta"><span class="role">{{ a.role }}</span><span>{{ a.task || 'idle' }}</span><span>{{ a.age }}</span></div>
      </div>
      <div v-if="!active.length" class="empty-section">No active agents</div>

      <div class="section-header" @click="showHistory = !showHistory" style="cursor:pointer">
        {{ showHistory ? '▼' : '▶' }} History ({{ history.length }})
      </div>
      <template v-if="showHistory">
        <div v-for="a in history" :key="a.id" :class="['agent-item', { selected: a.id === selectedAgent }]"
             @click="selectAgent(a.id)">
          <div class="agent-name"><span class="dot dead"></span>{{ a.id }}</div>
          <div class="agent-meta"><span class="role">{{ a.role }}</span><span>{{ a.task || 'idle' }}</span><span>{{ a.age }}</span></div>
        </div>
      </template>
    </div>

    <div class="log-panel">
      <div class="log-header">
        <span>{{ selectedAgent || 'Select an agent' }}</span>
        <div class="log-controls">
          <button :class="['ctrl-btn', { active: autoFollow }]" @click="autoFollow = !autoFollow">Auto-follow</button>
        </div>
      </div>
      <pre class="log-content" ref="logEl"><template v-for="(line, i) in logLines" :key="i"><span :style="{ color: logColor(line) }">{{ line }}
</span></template></pre>
    </div>
  </div>
</template>

<style scoped>
.agents-page { display: flex; height: calc(100vh - 50px); overflow: hidden; }
.agent-list { width: 300px; border-right: 1px solid #2a2a4a; overflow-y: auto; flex-shrink: 0; }
.section-header { padding: 8px 12px; font-size: 11px; font-weight: bold; color: #FFD100; text-transform: uppercase; background: #0f0f23; border-bottom: 1px solid #2a2a4a; position: sticky; top: 0; }
.section-header.green { background: #0a2a0a; color: #82e0aa; }
.agent-item { padding: 8px 12px; border-bottom: 1px solid #1a1a2e; cursor: pointer; }
.agent-item:hover { background: #16213e; }
.agent-item.selected { background: #16213e; border-left: 3px solid #FFD100; }
.agent-name { font-weight: bold; font-size: 12px; color: #FFD100; }
.agent-meta { display: flex; justify-content: space-between; font-size: 10px; color: #888; margin-top: 2px; }
.role { color: #85c1e9; }
.dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; margin-right: 5px; }
.dot.alive { background: #82e0aa; }
.dot.dead { background: #555; }
.empty-section { padding: 12px; color: #555; font-size: 11px; font-style: italic; }
.log-panel { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.log-header { padding: 8px 12px; font-size: 12px; font-weight: bold; color: #FFD100; background: #0f0f23; border-bottom: 1px solid #2a2a4a; display: flex; justify-content: space-between; align-items: center; flex-shrink: 0; }
.log-controls { display: flex; gap: 6px; }
.ctrl-btn { background: #2a2a4a; border: 1px solid #444; color: #ccc; padding: 2px 8px; border-radius: 3px; font-size: 10px; cursor: pointer; }
.ctrl-btn.active { border-color: #82e0aa; color: #82e0aa; }
.log-content { flex: 1; overflow-y: auto; padding: 10px 14px; font-family: 'SF Mono', Consolas, monospace; font-size: 11px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; background: #0a0a1a; margin: 0; }
</style>
