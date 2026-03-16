<script setup>
import { ref, onMounted } from 'vue'
import { useWarchiefStore } from '../stores/warchief.js'
const store = useWarchiefStore()
const tab = ref('events')
const watcherLog = ref([])

async function loadWatcherLog() {
  const data = await store.apiGet('/api/watcher-log?lines=150')
  if (data.lines) watcherLog.value = data.lines
}

function logColor(line) {
  if (/\[ERROR\]/.test(line)) return '#f1948a'
  if (/\[WARNING\]/.test(line)) return '#f0b27a'
  if (/Spawned|Released/.test(line)) return '#82e0aa'
  if (/EMIT/.test(line)) return '#85c1e9'
  if (/Budget/.test(line)) return '#FFD100'
  return '#888'
}

function eventColor(type) {
  return { spawn: '#82e0aa', advance: '#85c1e9', crash: '#f1948a', block: '#f1948a', reject: '#f0b27a', answer: '#FFD100' }[type] || '#888'
}

onMounted(() => { setInterval(() => { if (tab.value === 'watcher') loadWatcherLog() }, 5000) })
</script>

<template>
  <div class="panel">
    <div class="panel-header">
      <span>Orchestrator</span>
      <div class="tabs">
        <button :class="['tab', { active: tab === 'events' }]" @click="tab = 'events'">Events</button>
        <button :class="['tab', { active: tab === 'watcher' }]" @click="tab = 'watcher'; loadWatcherLog()">Watcher Log</button>
      </div>
    </div>
    <div class="panel-body">
      <div v-if="tab === 'events'">
        <div v-if="store.events.length" v-for="e in store.events" :key="e.age + e.type" class="event-row">
          <span class="event-age">{{ e.age }}</span>
          <span class="event-type" :style="{ color: eventColor(e.type) }">{{ e.type }}</span>
          <span class="event-task">{{ e.task_id }}</span>
        </div>
        <div v-else class="empty">No recent events</div>
      </div>
      <pre v-else class="watcher-log"><span v-for="(line, i) in watcherLog" :key="i" :style="{ color: logColor(line) }">{{ line }}
</span></pre>
    </div>
  </div>
</template>

<style scoped>
.panel { background: #16213e; border: 1px solid #2a2a4a; border-radius: 6px; display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
.panel-header { background: #0f0f23; border-bottom: 1px solid #8C1616; padding: 6px 12px; font-size: 12px; font-weight: bold; color: #FFD100; text-transform: uppercase; display: flex; justify-content: space-between; align-items: center; flex-shrink: 0; }
.panel-body { padding: 8px 12px; font-size: 12px; overflow-y: auto; flex: 1; }
.tabs { display: flex; gap: 4px; }
.tab { background: #2a2a4a; border: 1px solid #444; color: #ccc; padding: 2px 8px; border-radius: 3px; font-size: 10px; cursor: pointer; }
.tab.active { border-color: #FFD100; color: #FFD100; }
.event-row { display: flex; gap: 8px; padding: 2px 0; border-bottom: 1px solid #1a1a2e; }
.event-age { color: #555; min-width: 35px; text-align: right; }
.event-type { font-weight: bold; min-width: 70px; }
.event-task { color: #aaa; }
.empty { color: #444; font-style: italic; text-align: center; padding: 8px; }
.watcher-log { font-family: 'SF Mono', Consolas, monospace; font-size: 11px; line-height: 1.4; white-space: pre-wrap; margin: 0; }
</style>
