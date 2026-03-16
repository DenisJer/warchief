import { ref, onUnmounted } from 'vue'

const state = ref(null)
const connected = ref(false)
let ws = null
let reconnectTimer = null

function connect() {
  if (ws && ws.readyState <= 1) return

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  ws = new WebSocket(`${proto}//${location.host}/ws`)

  ws.onopen = () => { connected.value = true }

  ws.onmessage = (evt) => {
    try {
      state.value = JSON.parse(evt.data)
    } catch (e) {
      console.error('WS parse error', e)
    }
  }

  ws.onclose = () => {
    connected.value = false
    reconnectTimer = setTimeout(connect, 3000)
  }

  ws.onerror = () => { ws.close() }
}

export function useWebSocket() {
  if (!ws) connect()
  return { state, connected }
}

export async function apiPost(url, body = {}) {
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

export async function apiGet(url) {
  try {
    const resp = await fetch(url)
    return await resp.json()
  } catch (e) {
    console.error('API error', e)
    return { error: e.message }
  }
}
