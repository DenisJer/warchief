import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useWarchiefStore = defineStore('warchief', () => {
  // WebSocket state — updated every 2s
  const state = ref(null)
  const connected = ref(false)
  let ws = null

  function connect() {
    if (ws && ws.readyState <= 1) return
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    ws = new WebSocket(`${proto}//${location.host}/ws`)
    ws.onopen = () => { connected.value = true }
    ws.onmessage = (evt) => {
      try { state.value = JSON.parse(evt.data) }
      catch (e) { console.error('WS parse error', e) }
    }
    ws.onclose = () => { connected.value = false; setTimeout(connect, 3000) }
    ws.onerror = () => { ws.close() }
  }

  // Computed accessors — any component can use these directly
  const project = computed(() => state.value?.project || '')
  const projectPath = computed(() => state.value?.project_path || '')
  const paused = computed(() => state.value?.paused || false)
  const metrics = computed(() => state.value?.metrics || {})
  const pipeline = computed(() => state.value?.pipeline || [])
  const agents = computed(() => state.value?.agents || [])
  const tokens = computed(() => state.value?.tokens || {})
  const events = computed(() => state.value?.events || [])
  const questions = computed(() => state.value?.questions || [])
  const watcherRunning = computed(() => state.value?.watcher_running || false)
  const watcherPid = computed(() => state.value?.watcher_pid)

  // API helpers
  async function apiPost(url, body = {}) {
    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      return await resp.json()
    } catch (e) {
      console.error('API error', e)
      return { error: e.message }
    }
  }

  async function apiGet(url) {
    try {
      const resp = await fetch(url)
      return await resp.json()
    } catch (e) {
      console.error('API error', e)
      return { error: e.message }
    }
  }

  // Start WebSocket on store creation
  connect()

  return {
    state, connected,
    project, projectPath, paused,
    metrics, pipeline, agents, tokens, events, questions,
    watcherRunning, watcherPid,
    apiPost, apiGet,
  }
})
