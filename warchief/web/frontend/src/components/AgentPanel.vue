<script setup>
import { useWarchiefStore } from '../stores/warchief.js'
const store = useWarchiefStore()
</script>

<template>
  <div class="panel">
    <div class="panel-header">Agents</div>
    <div class="panel-body">
      <div v-if="store.agents.length" v-for="a in store.agents" :key="a.id" class="agent-row">
        <span class="agent-id">{{ a.id }}</span>
        <span class="agent-role">{{ a.role }}</span>
        <span class="agent-task">{{ a.task || '-' }}</span>
        <span class="agent-age">{{ a.age }}</span>
      </div>
      <div v-else class="empty">No active agents</div>
    </div>
  </div>
</template>

<style scoped>
.panel { background: #16213e; border: 1px solid #2a2a4a; border-radius: 6px; }
.panel-header { background: #0f0f23; border-bottom: 1px solid #8C1616; padding: 6px 12px; font-size: 12px; font-weight: bold; color: #FFD100; text-transform: uppercase; letter-spacing: 1px; }
.panel-body { padding: 8px 12px; font-size: 12px; max-height: 200px; overflow-y: auto; }
.agent-row { display: flex; justify-content: space-between; padding: 3px 0; border-bottom: 1px solid #1a1a2e; }
.agent-id { color: #FFD100; font-weight: bold; }
.agent-role { color: #85c1e9; }
.agent-task { color: #aaa; }
.agent-age { color: #555; }
.empty { color: #444; font-style: italic; text-align: center; padding: 8px; }
</style>
