<script setup>
import { useWarchiefStore } from '../stores/warchief.js'
import TaskCard from './TaskCard.vue'
const store = useWarchiefStore()
</script>

<template>
  <div class="pipeline">
    <div class="pipeline-row">
      <div v-for="stage in store.pipeline" :key="stage.stage" class="stage-col">
        <div class="stage-header">
          <span>{{ stage.stage }}</span>
          <span class="count">{{ stage.count }}</span>
        </div>
        <div class="stage-tasks">
          <TaskCard v-for="t in stage.tasks" :key="t.id" :task="t" />
          <div v-if="!stage.tasks.length" class="empty">empty</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pipeline { background: #16213e; border: 1px solid #2a2a4a; border-radius: 6px; overflow: hidden; }
.pipeline-row { display: flex; gap: 6px; overflow-x: auto; padding: 8px; }
.stage-col { flex: 1; min-width: 150px; background: #0f0f23; border: 1px solid #2a2a4a; border-radius: 4px; }
.stage-header { padding: 5px 8px; font-size: 11px; font-weight: bold; color: #FFD100; text-transform: uppercase; border-bottom: 1px solid #2a2a4a; display: flex; justify-content: space-between; }
.count { background: #8C1616; color: #fff; border-radius: 10px; padding: 0 6px; font-size: 10px; min-width: 18px; text-align: center; }
.stage-tasks { padding: 4px; max-height: 350px; overflow-y: auto; min-height: 40px; }
.empty { color: #444; font-style: italic; text-align: center; padding: 8px; font-size: 11px; }
</style>
