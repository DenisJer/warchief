<script setup>
import { useWarchiefStore } from '../stores/warchief.js'
import PipelineView from '../components/PipelineView.vue'
import AgentPanel from '../components/AgentPanel.vue'
import TokenPanel from '../components/TokenPanel.vue'
import EventLog from '../components/EventLog.vue'
import QuestionPanel from '../components/QuestionPanel.vue'
import WatcherControls from '../components/WatcherControls.vue'

const store = useWarchiefStore()
</script>

<template>
  <div class="dashboard" v-if="store.state">
    <div class="top-bar">
      <WatcherControls />
      <div class="stats">
        <span>Tasks: <b>{{ store.metrics.total }}</b></span>
        <span>Active: <b>{{ store.metrics.in_progress }}</b></span>
        <span>Blocked: <b>{{ store.metrics.blocked }}</b></span>
        <span>Done: <b>{{ store.metrics.closed }}</b></span>
        <span>Agents: <b>{{ store.metrics.agents_running }}</b></span>
      </div>
    </div>

    <PipelineView />

    <div class="bottom-panels">
      <EventLog />
      <div class="sidebar">
        <AgentPanel />
        <TokenPanel />
        <QuestionPanel v-if="store.questions.length" />
      </div>
    </div>
  </div>
  <div v-else class="loading">Connecting...</div>
</template>

<style scoped>
.dashboard { display: flex; flex-direction: column; height: calc(100vh - 50px); overflow: hidden; }
.top-bar { display: flex; justify-content: space-between; align-items: center; padding: 8px 16px; background: #0f0f23; border-bottom: 1px solid #2a2a4a; }
.stats { display: flex; gap: 14px; font-size: 12px; color: #888; }
.stats b { color: #FFD100; }
.bottom-panels { display: grid; grid-template-columns: 1fr 300px; gap: 10px; padding: 10px; flex: 1; min-height: 0; overflow: hidden; }
.sidebar { display: flex; flex-direction: column; gap: 10px; overflow-y: auto; }
.loading { display: flex; align-items: center; justify-content: center; height: 50vh; color: #555; font-size: 18px; }
</style>
