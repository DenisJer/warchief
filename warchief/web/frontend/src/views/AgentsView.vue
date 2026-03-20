<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useWarchiefStore } from '../stores/warchief.js'

const store = useWarchiefStore()
const agents = ref([])
const selectedAgent = ref(null)
const logLines = ref([])
const autoFollow = ref(true)
const userScrolledUp = ref(false)
const showHistory = ref(false)
const logEl = ref(null)
const isStreaming = ref(false)
let pollTimer = null
let lastLogHash = ''
let logWs = null
const MAX_LOG_LINES = 2000

// File/diff viewer
const viewerOpen = ref(false)
const viewerTitle = ref('')
const viewerContent = ref('')
const viewerMode = ref('file') // 'file' or 'diff'

const active = computed(() => agents.value.filter(a => a.status === 'alive' || a.status === 'zombie'))
const history = computed(() => agents.value.filter(a => a.status !== 'alive' && a.status !== 'zombie'))

async function loadAgents() {
  const data = await store.apiGet('/api/agents')
  if (Array.isArray(data)) agents.value = data
  if (!selectedAgent.value && agents.value.length) {
    const alive = active.value
    selectAgent(alive.length ? alive[0].id : agents.value[0].id)
  }
}

async function loadLog() {
  if (!selectedAgent.value) return
  const data = await store.apiGet(`/api/agent-log/${encodeURIComponent(selectedAgent.value)}?lines=500`)
  if (!data.lines) return
  const newHash = data.total + ':' + (data.lines[data.lines.length - 1] || '')
  if (newHash === lastLogHash) return
  lastLogHash = newHash
  logLines.value = data.lines
  if (autoFollow.value) {
    await nextTick()
    if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
  }
}

function disconnectLogWs() {
  if (logWs) {
    logWs.close()
    logWs = null
  }
  isStreaming.value = false
}

function connectLogWs(agentId) {
  disconnectLogWs()

  // Check if agent is alive — only stream for live agents
  const agent = agents.value.find(a => a.id === agentId)
  if (!agent || (agent.status !== 'alive' && agent.status !== 'zombie')) {
    // Dead agent — use HTTP polling
    loadLog()
    return
  }

  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${proto}//${window.location.host}/ws/agent-log/${encodeURIComponent(agentId)}`
  logWs = new WebSocket(wsUrl)
  isStreaming.value = true

  logWs.onmessage = async (event) => {
    try {
      const msg = JSON.parse(event.data)
      if (msg.type === 'initial') {
        logLines.value = msg.lines || []
      } else if (msg.type === 'append') {
        const newLines = msg.lines || []
        logLines.value = logLines.value.concat(newLines)
        // Cap at MAX_LOG_LINES to prevent memory bloat
        if (logLines.value.length > MAX_LOG_LINES) {
          logLines.value = logLines.value.slice(-MAX_LOG_LINES)
        }
      } else if (msg.type === 'done') {
        disconnectLogWs()
        return
      }
      if (autoFollow.value) {
        await nextTick()
        if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
      }
    } catch (e) {
      // Ignore parse errors
    }
  }

  logWs.onerror = () => {
    disconnectLogWs()
    // Fall back to HTTP polling
    loadLog()
  }

  logWs.onclose = () => {
    isStreaming.value = false
    logWs = null
  }
}

function selectAgent(id) {
  selectedAgent.value = id
  lastLogHash = ''
  logLines.value = []
  connectLogWs(id)
}

function logColor(line) {
  if (/error|fail|exception/i.test(line)) return '#f1948a'
  if (/warn/i.test(line)) return '#f0b27a'
  if (/success|pass|done/i.test(line)) return '#82e0aa'
  if (/^\[.*\] Tool:/i.test(line)) return '#85c1e9'
  if (/^\s*(Reading|File|Pattern|\$)/i.test(line)) return '#666'
  return '#aaa'
}

function renderLine(line) {
  // Escape HTML
  let escaped = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  // Make worktree file paths clickable
  escaped = escaped.replace(/(\/[\w.\-\/]+\.warchief-worktrees\/[^\s,)'"&]+)/g, (match) => {
    const safe = match.replace(/'/g, "\\'")
    return `<span class="file-link" onclick="window._viewFile('${safe}')">${match}</span>` +
           `<span class="diff-link" onclick="window._viewDiff('${safe}')">[diff]</span>`
  })
  return escaped
}

async function viewFile(path) {
  viewerMode.value = 'file'
  viewerTitle.value = path.split('/').pop()
  viewerContent.value = 'Loading...'
  viewerOpen.value = true
  const data = await store.apiGet(`/api/agent-file?path=${encodeURIComponent(path)}`)
  if (data.error) { viewerContent.value = data.error; return }
  const lines = data.content.split('\n')
  viewerContent.value = lines.map((l, i) => `<span class="ln">${i + 1}</span>${l.replace(/&/g,'&amp;').replace(/</g,'&lt;')}`).join('\n')
}

async function viewDiff(path) {
  viewerMode.value = 'diff'
  viewerTitle.value = 'Diff: ' + path.split('/').pop()
  viewerContent.value = 'Loading...'
  viewerOpen.value = true
  const data = await store.apiGet(`/api/agent-diff?path=${encodeURIComponent(path)}`)
  if (data.error) { viewerContent.value = data.error; return }
  const diff = data.diff || 'No diff available'
  viewerContent.value = diff.split('\n').map(l => {
    const escaped = l.replace(/&/g,'&amp;').replace(/</g,'&lt;')
    if (l.startsWith('+') && !l.startsWith('+++')) return `<span class="diff-add">${escaped}</span>`
    if (l.startsWith('-') && !l.startsWith('---')) return `<span class="diff-del">${escaped}</span>`
    if (l.startsWith('@@')) return `<span class="diff-hunk">${escaped}</span>`
    if (l.startsWith('diff ') || l.startsWith('index ') || l.startsWith('---') || l.startsWith('+++')) return `<span class="diff-meta">${escaped}</span>`
    return escaped
  }).join('\n')
}

// Expose to window for onclick in rendered HTML
if (typeof window !== 'undefined') {
  window._viewFile = viewFile
  window._viewDiff = viewDiff
}

function onLogScroll() {
  if (!logEl.value) return
  const el = logEl.value
  const atBottom = (el.scrollHeight - el.scrollTop - el.clientHeight) < 30
  if (!atBottom) { userScrolledUp.value = true; autoFollow.value = false }
  else if (userScrolledUp.value) { userScrolledUp.value = false; autoFollow.value = true }
}

onMounted(() => {
  if (window.location.hash) selectedAgent.value = window.location.hash.substring(1)
  loadAgents()
  pollTimer = setInterval(() => {
    loadAgents()
    // Only HTTP-poll log for dead agents (live agents use WebSocket)
    if (selectedAgent.value && !isStreaming.value) loadLog()
  }, 3000)
})
onUnmounted(() => {
  clearInterval(pollTimer)
  disconnectLogWs()
})
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
        {{ showHistory ? '\u25BC' : '\u25B6' }} History ({{ history.length }})
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
        <span>{{ selectedAgent || 'Select an agent' }}<span v-if="isStreaming" class="stream-badge">LIVE</span></span>
        <div class="log-controls">
          <button :class="['ctrl-btn', { active: autoFollow }]" @click="autoFollow = !autoFollow">Auto-follow</button>
        </div>
      </div>
      <pre class="log-content" ref="logEl" @scroll="onLogScroll"><template v-for="(line, i) in logLines" :key="i"><span :style="{ color: logColor(line) }" v-html="renderLine(line)"></span>
</template></pre>
    </div>

    <!-- File/Diff viewer overlay -->
    <Teleport to="body">
      <div v-if="viewerOpen" class="overlay" @click.self="viewerOpen = false">
        <div class="viewer-box">
          <div class="viewer-header">
            <span>{{ viewerTitle }}</span>
            <button class="btn" @click="viewerOpen = false">Close (Esc)</button>
          </div>
          <pre class="viewer-content" v-html="viewerContent"></pre>
        </div>
      </div>
    </Teleport>
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
.stream-badge { display: inline-block; background: #82e0aa; color: #0a0a1a; font-size: 9px; font-weight: bold; padding: 1px 5px; border-radius: 3px; margin-left: 8px; vertical-align: middle; animation: pulse 2s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

/* Overlay */
.overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 100; display: flex; align-items: center; justify-content: center; }
.viewer-box { background: #0a0a1a; border: 2px solid #8C1616; border-radius: 8px; width: 60%; max-height: 80vh; display: flex; flex-direction: column; }
.viewer-header { padding: 10px 14px; background: #0f0f23; border-bottom: 1px solid #2a2a4a; display: flex; justify-content: space-between; align-items: center; color: #FFD100; font-size: 12px; font-family: monospace; flex-shrink: 0; }
.viewer-content { flex: 1; overflow: auto; padding: 12px 16px; font-family: 'SF Mono', Consolas, monospace; font-size: 12px; line-height: 1.5; white-space: pre; color: #e0e0e0; margin: 0; }
.btn { background: #2a2a4a; border: 1px solid #444; color: #ccc; padding: 3px 10px; border-radius: 3px; font-size: 11px; cursor: pointer; }
.btn:hover { border-color: #FFD100; }
</style>

<style>
/* Global styles for rendered HTML in log lines */
.file-link { color: #FFD100; cursor: pointer; text-decoration: underline; text-decoration-style: dotted; }
.file-link:hover { color: #fff; }
.diff-link { color: #82e0aa; cursor: pointer; text-decoration: underline; text-decoration-style: dotted; font-size: 10px; margin-left: 6px; }
.diff-link:hover { color: #fff; }
.ln { color: #555; display: inline-block; width: 40px; text-align: right; margin-right: 12px; user-select: none; }
.diff-add { color: #82e0aa; background: rgba(130,224,170,0.08); }
.diff-del { color: #f1948a; background: rgba(241,148,138,0.08); }
.diff-hunk { color: #85c1e9; font-weight: bold; }
.diff-meta { color: #888; }
</style>
