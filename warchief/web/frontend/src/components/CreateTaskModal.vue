<script setup>
import { ref } from 'vue'
import { useWarchiefStore } from '../stores/warchief.js'
const store = useWarchiefStore()

const emit = defineEmits(['close'])
const title = ref('')
const desc = ref('')
const type = ref('feature')
const priority = ref(5)
const showAdvanced = ref(false)
const labels = ref(new Set())
const customLabels = ref('')
const deps = ref('')
const tools = ref('')
const budget = ref(0)

function toggleLabel(l) {
  if (labels.value.has(l)) labels.value.delete(l)
  else labels.value.add(l)
}

async function submit() {
  if (!title.value.trim()) return
  const allLabels = [...labels.value, ...customLabels.value.split(',').filter(s => s.trim())].join(',')
  await store.apiPost('/api/create', {
    title: title.value.trim(),
    description: desc.value.trim(),
    type: type.value,
    priority: priority.value,
    labels: allLabels,
    deps: deps.value.trim(),
    tools: tools.value.trim(),
    budget: budget.value,
  })
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <div class="overlay" @click.self="emit('close')">
      <div class="modal">
        <h3>New Task</h3>
        <input v-model="title" placeholder="Task title (required)" @keydown.enter="submit" autofocus />
        <textarea v-model="desc" placeholder="Description — what should the agent build?" rows="3"></textarea>
        <div class="row">
          <div class="field">
            <label>Type</label>
            <select v-model="type">
              <option value="feature">Feature — new functionality</option>
              <option value="bug">Bug — fix broken behavior</option>
              <option value="investigation">Investigation — research</option>
            </select>
          </div>
          <div class="field" style="width:120px">
            <label>Priority ({{ priority }})</label>
            <input type="range" v-model.number="priority" min="1" max="10" />
          </div>
        </div>
        <div class="label-section">
          <label>Labels <span class="hint">(auto-detected from code if not set)</span></label>
          <div class="label-picker">
            <button v-for="l in [{n:'security',i:'🔒'},{n:'frontend',i:'🎨'}]" :key="l.n"
                    :class="['label-btn', { active: labels.has(l.n) }]" @click="toggleLabel(l.n)">
              {{ l.i }} {{ l.n }}
            </button>
          </div>
        </div>
        <div v-if="showAdvanced" class="advanced">
          <input v-model="customLabels" placeholder="Custom labels (comma-separated)" />
          <input v-model="deps" placeholder="Dependencies (task IDs, comma-separated)" />
          <input v-model="tools" placeholder="MCP tools (e.g. figma console, supabase)" />
          <div class="row">
            <label style="font-size:11px;color:#888">Budget $</label>
            <input type="number" v-model.number="budget" min="0" step="0.5" style="width:100px" />
            <span class="hint">0 = default</span>
          </div>
        </div>
        <a href="#" class="toggle-link" @click.prevent="showAdvanced = !showAdvanced">
          {{ showAdvanced ? 'Hide' : 'Show' }} advanced options
        </a>
        <div class="actions">
          <button class="btn" @click="emit('close')">Cancel</button>
          <button class="btn btn-primary" @click="submit">Create Task</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 100; display: flex; align-items: center; justify-content: center; }
.modal { background: #16213e; border: 2px solid #8C1616; border-radius: 8px; padding: 20px; min-width: 500px; }
h3 { color: #FFD100; margin-bottom: 12px; }
input, textarea, select { width: 100%; background: #1a1a2e; border: 1px solid #2a2a4a; color: #e0e0e0; padding: 8px 12px; border-radius: 4px; font-size: 13px; margin-bottom: 8px; font-family: inherit; }
input:focus, textarea:focus, select:focus { outline: none; border-color: #FFD100; }
.row { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.field { flex: 1; }
.field label { font-size: 10px; color: #888; text-transform: uppercase; display: block; margin-bottom: 3px; }
.label-section { margin-bottom: 8px; }
.label-section label { font-size: 10px; color: #888; text-transform: uppercase; display: block; margin-bottom: 4px; }
.hint { text-transform: none; color: #555; }
.label-picker { display: flex; gap: 4px; flex-wrap: wrap; }
.label-btn { background: #0f0f23; border: 1px solid #2a2a4a; color: #888; padding: 4px 10px; border-radius: 12px; font-size: 12px; cursor: pointer; }
.label-btn.active { border-color: #82e0aa; color: #82e0aa; background: #1a3a1a; }
.advanced { border-top: 1px solid #2a2a4a; padding-top: 8px; margin-top: 4px; }
.toggle-link { font-size: 12px; color: #85c1e9; display: block; margin-bottom: 12px; }
.actions { display: flex; gap: 8px; justify-content: flex-end; }
.btn { background: #2a2a4a; border: 1px solid #444; color: #ccc; padding: 6px 16px; border-radius: 4px; font-size: 13px; cursor: pointer; }
.btn:hover { border-color: #FFD100; }
.btn-primary { background: #8C1616; border-color: #8C1616; color: #FFD100; }
</style>
