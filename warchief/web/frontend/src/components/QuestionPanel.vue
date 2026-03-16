<script setup>
import { ref } from 'vue'
import { useWarchiefStore } from '../stores/warchief.js'
const store = useWarchiefStore()
const answers = ref({})

async function answer(taskId) {
  const text = answers.value[taskId]?.trim()
  if (!text) return
  await store.apiPost(`/api/answer/${taskId}`, { message: text })
  answers.value[taskId] = ''
}
</script>

<template>
  <div class="panel">
    <div class="panel-header">Questions</div>
    <div class="panel-body">
      <div v-for="q in store.questions" :key="q.task_id" class="q-item">
        <div class="q-task">{{ q.task_id }} — {{ q.title }}</div>
        <div class="q-text">{{ q.question }}</div>
        <div class="q-row">
          <input v-model="answers[q.task_id]" placeholder="Type answer..." @keydown.enter="answer(q.task_id)" class="q-input" />
          <button class="btn btn-primary" @click="answer(q.task_id)">Answer</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel { background: #16213e; border: 1px solid #2a2a4a; border-radius: 6px; }
.panel-header { background: #0f0f23; border-bottom: 1px solid #8C1616; padding: 6px 12px; font-size: 12px; font-weight: bold; color: #FFD100; text-transform: uppercase; }
.panel-body { padding: 8px 12px; }
.q-item { background: #0f0f23; border-left: 3px solid #8C1616; padding: 6px 8px; margin-bottom: 6px; border-radius: 0 4px 4px 0; }
.q-task { color: #FFD100; font-size: 11px; font-weight: bold; }
.q-text { color: #e0e0e0; margin: 4px 0; font-size: 12px; }
.q-row { display: flex; gap: 4px; margin-top: 4px; }
.q-input { flex: 1; background: #1a1a2e; border: 1px solid #2a2a4a; color: #e0e0e0; padding: 4px 8px; border-radius: 3px; font-size: 12px; }
.q-input:focus { outline: none; border-color: #FFD100; }
.btn { background: #2a2a4a; border: 1px solid #444; color: #ccc; padding: 2px 8px; border-radius: 3px; font-size: 10px; cursor: pointer; }
.btn-primary { background: #8C1616; border-color: #8C1616; color: #FFD100; }
</style>
