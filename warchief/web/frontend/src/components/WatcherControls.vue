<script setup>
import { ref } from 'vue'
import { useWarchiefStore } from '../stores/warchief.js'
import CreateTaskModal from './CreateTaskModal.vue'

const store = useWarchiefStore()
const busy = ref(false)
const showCreate = ref(false)

async function toggle() {
  if (busy.value) return
  busy.value = true
  try {
    const url = store.watcherRunning ? '/api/watcher/stop' : '/api/watcher/start'
    console.log('WatcherControls: toggle', url, 'watcherRunning=', store.watcherRunning)
    const result = await store.apiPost(url)
    console.log('WatcherControls: result', result)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="controls">
    <button class="btn btn-primary" @click="showCreate = true">+ New Task</button>
    <button class="btn" :class="store.watcherRunning ? 'btn-green' : 'btn-orange'"
            :title="store.watcherRunning ? `Pipeline running (PID ${store.watcherPid})` : 'Pipeline stopped'"
            :disabled="busy" @click="toggle">
      {{ busy ? '...' : (store.watcherRunning ? 'Stop Pipeline' : 'Start Pipeline') }}
    </button>
  </div>
  <CreateTaskModal v-if="showCreate" @close="showCreate = false" />
</template>

<style scoped>
.controls { display: flex; gap: 8px; }
.btn { background: #2a2a4a; border: 1px solid #444; color: #ccc; padding: 4px 12px; border-radius: 3px; font-size: 12px; cursor: pointer; }
.btn:hover { border-color: #FFD100; }
.btn-primary { background: #8C1616; border-color: #8C1616; color: #FFD100; }
.btn-green { border-color: #82e0aa; color: #82e0aa; }
.btn-orange { border-color: #f0b27a; color: #f0b27a; }
</style>
