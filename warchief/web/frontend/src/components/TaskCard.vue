<script setup>
import { ref, computed } from 'vue'
import { useWarchiefStore } from '../stores/warchief.js'
const store = useWarchiefStore()
const apiPost = store.apiPost
const apiGet = store.apiGet

const props = defineProps({ task: Object })
const emit = defineEmits(['refresh'])
const showModal = ref(null) // 'nudge', 'grant', 'retry', 'reject-plan', 'reject-investigation', 'qa'
const modalInput = ref('')
const scratchpadContent = ref('')
const showScratchpad = ref(false)
const qaMessages = ref([])

const t = computed(() => props.task)

const blockedReason = computed(() => {
  if (t.value.status !== 'blocked') return ''
  const labels = t.value.labels || []
  if (labels.includes('needs-plan-approval')) return 'Waiting for your plan approval'
  if (labels.includes('needs-review')) return 'Waiting for your review of findings'
  if (labels.includes('question')) return 'Agent has a question for you'
  if (labels.includes('budget-exceeded')) return 'Budget limit exceeded'
  if (labels.includes('needs-triage')) return 'Conductor analyzing failure...'
  if (labels.includes('triage-done')) return 'Diagnosis ready — review and decide'
  if (labels.includes('needs-testing')) return 'Waiting for manual test approval'
  return t.value.block_reason || 'Blocked'
})

const viewLabel = computed(() => {
  const labels = t.value.labels || []
  if (labels.includes('needs-plan-approval')) return 'View Plan'
  if (labels.includes('needs-review')) return 'View Findings'
  if (labels.includes('triage-done')) return 'View Diagnosis'
  return 'View Notes'
})

async function doAction(action) {
  if (action === 'drop') {
    if (!confirm(`Drop task ${t.value.id}?\nKill agent, close task, clean up.`)) return
    await apiPost(`/api/drop/${t.value.id}`)
  }
}

async function approvePlan() { await apiPost(`/api/approve-plan/${t.value.id}`) }
async function approveInvestigation() {
  const close = confirm('Click OK to close investigation.\nClick Cancel to escalate to development tasks.')
  if (close) await apiPost(`/api/approve-investigation/${t.value.id}`)
  else await apiPost(`/api/escalate/${t.value.id}`)
}
async function retryWithDiagnosis() {
  const data = await apiGet(`/api/scratchpad/${t.value.id}`)
  let diagnosis = data.content || 'Retry'
  const idx = diagnosis.lastIndexOf('DIAGNOSIS:')
  if (idx >= 0) diagnosis = diagnosis.substring(idx)
  if (diagnosis.length > 1024) diagnosis = diagnosis.substring(0, 1024)
  await apiPost(`/api/retry/${t.value.id}`, { message: diagnosis })
}
async function increaseBudget(amount) { await apiPost(`/api/increase-budget/${t.value.id}`, { message: String(amount) }) }

async function openScratchpad() {
  const data = await apiGet(`/api/scratchpad/${t.value.id}`)
  scratchpadContent.value = data.content || '(no notes)'
  showScratchpad.value = true
}

async function openQA() {
  const msgs = await apiGet(`/api/messages/${t.value.id}`)
  qaMessages.value = Array.isArray(msgs) ? msgs : []
  showModal.value = 'qa'
}

async function submitModal() {
  if (!modalInput.value.trim()) return
  const action = showModal.value
  if (action === 'qa') {
    await apiPost(`/api/answer/${t.value.id}`, { message: modalInput.value.trim() })
  } else if (action === 'nudge') {
    await apiPost(`/api/nudge/${t.value.id}`, { message: modalInput.value.trim() })
  } else if (action === 'grant') {
    await apiPost(`/api/grant/${t.value.id}`, { message: modalInput.value.trim() })
  } else if (action === 'retry') {
    await apiPost(`/api/retry/${t.value.id}`, { message: modalInput.value.trim() })
  } else if (action === 'reject-plan') {
    await apiPost(`/api/reject-plan/${t.value.id}`, { message: modalInput.value.trim() })
  } else if (action === 'reject-investigation') {
    await apiPost(`/api/reject-investigation/${t.value.id}`, { message: modalInput.value.trim() })
  }
  modalInput.value = ''
  showModal.value = null
}

function openModal(action) {
  showModal.value = action
  modalInput.value = ''
}
</script>

<template>
  <div class="card">
    <div class="card-id">{{ t.id }}</div>
    <div class="card-title">{{ t.title }}</div>
    <div class="card-meta">
      <span :class="'badge badge-' + t.status">{{ t.status }}</span>
      <span v-if="t.labels?.includes('budget-exceeded')" class="badge badge-over">$OVER</span>
      <span class="age">{{ t.age }}</span>
    </div>
    <div v-if="t.agent_id" class="agent-line">{{ t.agent_id }}</div>

    <!-- Blocked reason -->
    <div v-if="blockedReason" class="blocked-banner">{{ blockedReason }}</div>

    <!-- Question -->
    <button v-if="t.question" class="btn btn-gold full" @click="openQA">❓ Answer Question</button>

    <!-- Scratchpad -->
    <button v-if="t.scratchpad" class="btn btn-gold full" @click="openScratchpad">{{ viewLabel }}</button>

    <!-- Action buttons -->
    <div class="actions">
      <!-- Plan approval -->
      <template v-if="t.labels?.includes('needs-plan-approval')">
        <button class="btn btn-green" title="Approve plan → development" @click="approvePlan">Approve</button>
        <button class="btn" title="Reject with feedback" @click="openModal('reject-plan')">Reject</button>
      </template>
      <!-- Investigation review -->
      <template v-else-if="t.labels?.includes('needs-review')">
        <button class="btn btn-green" title="Accept findings" @click="approveInvestigation">Accept</button>
        <button class="btn" title="Request more info" @click="openModal('reject-investigation')">More Info</button>
      </template>
      <!-- Triage done -->
      <template v-else-if="t.labels?.includes('triage-done')">
        <button class="btn btn-green" title="Retry with diagnosis" @click="retryWithDiagnosis">Retry</button>
      </template>
      <!-- Budget exceeded -->
      <template v-if="t.labels?.includes('budget-exceeded')">
        <button class="btn btn-gold" @click="increaseBudget(2)">+$2</button>
        <button class="btn btn-gold" @click="increaseBudget(5)">+$5</button>
      </template>
      <!-- Retry for other blocked -->
      <button v-if="t.status === 'blocked' && !t.labels?.includes('needs-plan-approval') && !t.labels?.includes('needs-review')"
              class="btn btn-green" title="Retry with guidance" @click="openModal('retry')">Retry</button>
      <!-- Logs -->
      <a v-if="t.agent_id || t.last_agent_id" class="btn" title="View agent log"
         :href="'/agents#' + (t.agent_id || t.last_agent_id)" target="_blank">logs</a>
      <!-- Default actions -->
      <button class="btn btn-blue" title="Send message to agent" @click="openModal('nudge')">message</button>
      <button class="btn" title="Grant MCP tools" @click="openModal('grant')">grant</button>
      <button class="btn btn-danger" title="Drop task" @click="doAction('drop')">drop</button>
    </div>

    <!-- Scratchpad overlay -->
    <Teleport to="body">
      <div v-if="showScratchpad" class="overlay" @click.self="showScratchpad = false">
        <div class="modal-box">
          <div class="modal-header">
            <span>{{ viewLabel }} — {{ t.id }}</span>
            <button class="btn" @click="showScratchpad = false">Close</button>
          </div>
          <pre class="scratchpad-content">{{ scratchpadContent }}</pre>
        </div>
      </div>
    </Teleport>

    <!-- Action modal -->
    <Teleport to="body">
      <div v-if="showModal && showModal !== 'qa'" class="overlay" @click.self="showModal = null">
        <div class="modal-box modal-sm">
          <h3>{{ showModal }} — {{ t.id }}</h3>
          <input v-model="modalInput" :placeholder="showModal === 'grant' ? 'e.g. figma console' : 'Enter message...'"
                 @keydown.enter="submitModal" @keydown.esc="showModal = null" ref="modalInputRef" autofocus />
          <div class="modal-actions">
            <button class="btn" @click="showModal = null">Cancel</button>
            <button class="btn btn-primary" @click="submitModal">Send</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Q&A modal -->
    <Teleport to="body">
      <div v-if="showModal === 'qa'" class="overlay" @click.self="showModal = null">
        <div class="modal-box">
          <div class="modal-header">
            <span>Q&A — {{ t.id }}</span>
            <button class="btn" @click="showModal = null">Close</button>
          </div>
          <div class="qa-messages">
            <div v-for="m in qaMessages" :key="m.created_at"
                 :class="['qa-msg', m.type === 'answer' || m.type === 'feedback' ? 'qa-user' : 'qa-agent']">
              <div class="qa-label">{{ m.type === 'question' ? '❓ Agent' : '✅ You' }}</div>
              <div class="qa-body">{{ m.body }}</div>
            </div>
          </div>
          <div class="qa-input-row">
            <input v-model="modalInput" placeholder="Type your answer..." @keydown.enter="submitModal" autofocus />
            <button class="btn btn-primary" @click="submitModal">Send</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.card { background: #16213e; border: 1px solid #2a2a4a; border-radius: 4px; padding: 6px 8px; margin-bottom: 4px; font-size: 12px; }
.card:hover { border-color: #FFD100; }
.card-id { color: #FFD100; font-weight: bold; font-size: 11px; }
.card-title { color: #ccc; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card-meta { display: flex; justify-content: space-between; margin-top: 3px; font-size: 11px; color: #888; }
.agent-line { color: #85c1e9; font-size: 10px; margin-top: 2px; }
.blocked-banner { margin-top: 4px; padding: 4px 6px; background: #2a1a0a; border-left: 3px solid #f0b27a; border-radius: 0 3px 3px 0; font-size: 10px; color: #f0b27a; }
.badge { font-size: 10px; padding: 1px 6px; border-radius: 3px; font-weight: bold; }
.badge-open { background: #1a5276; color: #85c1e9; }
.badge-in_progress { background: #1e6e3e; color: #82e0aa; }
.badge-blocked { background: #8C1616; color: #f1948a; }
.badge-closed { background: #333; color: #888; }
.badge-over { background: #8C1616; color: #FFD100; }
.age { color: #555; }
.actions { display: flex; flex-wrap: wrap; gap: 3px; margin-top: 4px; }
.btn { background: #2a2a4a; border: 1px solid #444; color: #ccc; padding: 2px 7px; border-radius: 3px; font-size: 10px; cursor: pointer; text-decoration: none; }
.btn:hover { border-color: #FFD100; color: #FFD100; }
.btn-danger { border-color: #8C1616; }
.btn-danger:hover { background: #8C1616; color: #fff; }
.btn-green { border-color: #82e0aa; color: #82e0aa; }
.btn-blue { border-color: #85c1e9; color: #85c1e9; }
.btn-gold { border-color: #FFD100; color: #FFD100; }
.btn-primary { background: #8C1616; border-color: #8C1616; color: #FFD100; }
.full { width: 100%; margin-top: 4px; padding: 4px; }

/* Overlay */
.overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 100; display: flex; align-items: center; justify-content: center; }
.modal-box { background: #16213e; border: 2px solid #8C1616; border-radius: 8px; padding: 16px; min-width: 500px; max-width: 750px; max-height: 80vh; display: flex; flex-direction: column; }
.modal-sm { min-width: 400px; max-width: 500px; }
.modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; color: #FFD100; font-weight: bold; }
.modal-box h3 { color: #FFD100; margin-bottom: 10px; }
.modal-box input { width: 100%; background: #1a1a2e; border: 1px solid #2a2a4a; color: #e0e0e0; padding: 8px 12px; border-radius: 4px; font-size: 14px; margin-bottom: 10px; }
.modal-box input:focus { outline: none; border-color: #FFD100; }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; }
.scratchpad-content { flex: 1; overflow-y: auto; background: #0a0a1a; border-radius: 4px; padding: 14px; font-family: 'SF Mono', Consolas, monospace; font-size: 12px; line-height: 1.6; white-space: pre-wrap; color: #e0e0e0; }

/* Q&A */
.qa-messages { flex: 1; overflow-y: auto; margin-bottom: 10px; min-height: 100px; }
.qa-msg { margin-bottom: 8px; max-width: 85%; }
.qa-agent { margin-right: auto; }
.qa-user { margin-left: auto; }
.qa-agent .qa-body { background: #2a1a0a; border-left: 3px solid #FFD100; }
.qa-user .qa-body { background: #1a3a1a; border-left: 3px solid #82e0aa; }
.qa-label { font-size: 10px; font-weight: bold; margin-bottom: 2px; color: #888; }
.qa-body { padding: 6px 10px; border-radius: 0 6px 6px 0; font-size: 12px; white-space: pre-wrap; }
.qa-input-row { display: flex; gap: 8px; }
.qa-input-row input { flex: 1; margin: 0; }
</style>
