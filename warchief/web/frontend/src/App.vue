<script setup>
import { useWarchiefStore } from './stores/warchief.js'
import { useRoute } from 'vue-router'

const store = useWarchiefStore()
const route = useRoute()
</script>

<template>
  <header class="header">
    <div class="header-left">
      <h1>Warchief</h1>
      <span class="project-name" :title="store.projectPath">{{ store.project }}</span>
      <nav>
        <router-link to="/" :class="{ active: route.path === '/' }">Dashboard</router-link>
        <router-link to="/agents" :class="{ active: route.path === '/agents' }">Agents</router-link>
        <router-link to="/tasks" :class="{ active: route.path === '/tasks' }">Tasks</router-link>
      </nav>
      <span v-if="store.paused" class="paused-badge">PAUSED</span>
    </div>
    <div class="header-right">
      <span class="conn-status">
        <span class="conn-dot" :class="store.connected ? 'connected' : 'disconnected'"></span>
        {{ store.connected ? 'Live' : 'Disconnected' }}
      </span>
    </div>
  </header>
  <router-view />
</template>

<style scoped>
.header {
  background: linear-gradient(135deg, #0f0f23 0%, #1a1a2e 50%, #16213e 100%);
  border-bottom: 3px solid #8C1616;
  padding: 10px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}
.header-left { display: flex; align-items: center; gap: 14px; }
.header-right { display: flex; align-items: center; gap: 12px; font-size: 13px; color: #888; }
h1 { color: #FFD100; font-size: 20px; letter-spacing: 2px; text-transform: uppercase; margin: 0; }
.project-name { color: #85c1e9; font-size: 13px; }
nav { display: flex; gap: 8px; font-size: 13px; }
nav a { color: #888; padding-bottom: 2px; }
nav a.active { color: #FFD100; border-bottom: 2px solid #FFD100; }
.paused-badge { background: #8C1616; color: #FFD100; padding: 2px 10px; border-radius: 4px; font-weight: bold; font-size: 11px; }
.conn-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 4px; }
.conn-dot.connected { background: #82e0aa; }
.conn-dot.disconnected { background: #f1948a; }
.conn-status { font-size: 12px; }
</style>
