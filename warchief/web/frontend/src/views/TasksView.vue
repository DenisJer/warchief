<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useWarchiefStore } from '../stores/warchief.js'
const store = useWarchiefStore()
const apiGet = store.apiGet

const tasks = ref([])
const filter = ref('all')
const expanded = ref(new Set())
const expandedGroups = ref(new Set())
let pollTimer = null

const filtered = computed(() => {
  if (filter.value === 'all') return tasks.value
  return tasks.value.filter(t => t.status === filter.value)
})

const groupedTasks = computed(() => {
  const f = filtered.value
  const groups = {}
  const standalone = []

  for (const t of f) {
    if (t.group_id) {
      if (!groups[t.group_id]) groups[t.group_id] = { parent: null, children: [] }
      if (t.labels.includes('decomposed')) {
        groups[t.group_id].parent = t
      } else {
        groups[t.group_id].children.push(t)
      }
    } else {
      standalone.push(t)
    }
  }

  const result = []
  for (const t of standalone) {
    result.push({ type: 'standalone', task: t, key: t.id })
  }
  for (const [gid, group] of Object.entries(groups)) {
    result.push({
      type: 'group',
      key: 'g-' + gid,
      groupId: gid,
      parent: group.parent,
      children: group.children,
      totalCost: (group.parent ? group.parent.cost : 0) + group.children.reduce((s, c) => s + (c.cost || 0), 0)
    })
  }
  return result
})

function toggle(id) {
  if (expanded.value.has(id)) expanded.value.delete(id)
  else expanded.value.add(id)
}

function toggleGroup(gid) {
  const s = new Set(expandedGroups.value)
  if (s.has(gid)) s.delete(gid)
  else s.add(gid)
  expandedGroups.value = s
}

function eventColor(type) {
  const map = { spawn: '#82e0aa', advance: '#85c1e9', block: '#f1948a', reject: '#f0b27a', comment: '#FFD100' }
  return map[type] || '#888'
}

async function load() {
  const data = await apiGet('/api/tasks')
  if (Array.isArray(data)) tasks.value = data
}

onMounted(() => { load(); pollTimer = setInterval(load, 10000) })
onUnmounted(() => clearInterval(pollTimer))
</script>

<template>
  <div id="tasks-page" class="tasks-page">
    <div id="tasks-filters" class="tasks-page__filters">
      <button v-for="f in ['all','open','in_progress','blocked','closed']" :key="f"
              :id="'tasks-filter-' + f + '-btn'"
              :class="['tasks-page__filter-btn', { 'tasks-page__filter-btn--active': filter === f }]" @click="filter = f">
        {{ f === 'in_progress' ? 'In Progress' : f.charAt(0).toUpperCase() + f.slice(1) }}
      </button>
      <span id="tasks-count" class="tasks-page__count">{{ filtered.length }}/{{ tasks.length }}</span>
    </div>

    <div v-if="!filtered.length" id="tasks-empty" class="tasks-page__empty">No tasks found</div>

    <template v-for="item in groupedTasks" :key="item.key">

      <!-- Standalone task -->
      <div v-if="item.type === 'standalone'" :id="'task-row-' + item.task.id" class="task-row">
        <div class="task-row__header" @click="toggle(item.task.id)">
          <span class="task-row__arrow">{{ expanded.has(item.task.id) ? '\u25BC' : '\u25B6' }}</span>
          <span class="task-row__id">{{ item.task.id }}</span>
          <span class="task-row__title">{{ item.task.title }}</span>
          <div class="task-row__meta">
            <span :class="'task-row__badge task-row__badge--' + item.task.status">{{ item.task.status }}</span>
            <span v-if="item.task.stage" class="task-row__badge task-row__badge--stage">{{ item.task.stage }}</span>
            <span class="task-row__badge task-row__badge--stage">{{ item.task.type }}</span>
            <span v-if="item.task.cost" class="task-row__badge task-row__badge--cost">${{ item.task.cost.toFixed(2) }}</span>
            <span class="task-row__age">{{ item.task.created }} ago</span>
          </div>
        </div>
        <div v-if="expanded.has(item.task.id)" class="task-row__detail">
          <div class="task-row__detail-grid">
            <div class="task-row__detail-card">
              <h4>Details</h4>
              <p v-if="item.task.description">{{ item.task.description }}</p>
              <p v-else class="task-row__dim">No description</p>
              <p class="task-row__stats">
                Priority: {{ item.task.priority }} | Spawns: {{ item.task.spawns }} | Rejections: {{ item.task.rejections }} | Crashes: {{ item.task.crashes }}
                <span v-if="item.task.budget"> | Budget: ${{ item.task.budget.toFixed(2) }}</span>
              </p>
              <div v-if="item.task.labels.length" class="task-row__labels">
                <span v-for="l in item.task.labels" :key="l" class="task-row__badge task-row__badge--stage">{{ l }}</span>
              </div>
            </div>
            <div class="task-row__detail-card">
              <h4>Timeline ({{ item.task.events.length }})</h4>
              <div class="task-row__timeline">
                <div v-for="(e, i) in item.task.events" :key="i" class="task-row__tl-item">
                  <span class="task-row__tl-age">{{ e.age }}</span>
                  <span class="task-row__tl-type" :style="{ color: eventColor(e.type) }">{{ e.type }}</span>
                  <span class="task-row__tl-detail">{{ e.from_stage && e.to_stage ? `${e.from_stage} \u2192 ${e.to_stage}` : (e.reason || e.comment?.substring(0, 80) || e.agent || '') }}</span>
                </div>
              </div>
            </div>
          </div>
          <div v-if="item.task.scratchpad" class="task-row__detail-card">
            <h4>Agent Notes</h4>
            <pre class="task-row__scratchpad">{{ item.task.scratchpad }}</pre>
          </div>
          <div v-if="item.task.messages.length" class="task-row__detail-card">
            <h4>Messages</h4>
            <div v-for="(m, i) in item.task.messages" :key="i" class="task-row__msg">
              <span :class="'task-row__msg-type task-row__msg-type--' + m.type">{{ m.type }}</span>
              <span class="task-row__msg-from">{{ m.from }}</span>
              {{ m.body }}
            </div>
          </div>
        </div>
      </div>

      <!-- Task group -->
      <div v-else-if="item.type === 'group'" :id="'task-group-' + item.groupId" class="task-group">

        <!-- Parent row (or orphan header if no parent in filtered results) -->
        <div v-if="item.parent" :id="'task-group-parent-' + item.parent.id" class="task-group__parent">
          <div class="task-group__parent-header" @click="toggleGroup(item.groupId)">
            <span class="task-row__arrow">{{ expandedGroups.has(item.groupId) ? '\u25BC' : '\u25B6' }}</span>
            <span class="task-row__id">{{ item.parent.id }}</span>
            <span class="task-row__title">{{ item.parent.title }}</span>
            <div class="task-row__meta">
              <span :class="'task-row__badge task-row__badge--' + item.parent.status">{{ item.parent.status }}</span>
              <span class="task-group__badge-count">{{ item.children.length }} sub-task{{ item.children.length !== 1 ? 's' : '' }}</span>
              <span v-if="item.totalCost" class="task-row__badge task-row__badge--cost">${{ item.totalCost.toFixed(2) }}</span>
              <span class="task-row__age">{{ item.parent.created }} ago</span>
            </div>
          </div>
          <!-- Parent detail (expand independently) -->
          <div class="task-group__parent-actions">
            <button class="task-group__detail-toggle" @click.stop="toggle(item.parent.id)">
              {{ expanded.has(item.parent.id) ? 'Hide details' : 'Show details' }}
            </button>
          </div>
          <div v-if="expanded.has(item.parent.id)" class="task-row__detail">
            <div class="task-row__detail-grid">
              <div class="task-row__detail-card">
                <h4>Details</h4>
                <p v-if="item.parent.description">{{ item.parent.description }}</p>
                <p v-else class="task-row__dim">No description</p>
                <p class="task-row__stats">
                  Priority: {{ item.parent.priority }} | Spawns: {{ item.parent.spawns }} | Rejections: {{ item.parent.rejections }} | Crashes: {{ item.parent.crashes }}
                  <span v-if="item.parent.budget"> | Budget: ${{ item.parent.budget.toFixed(2) }}</span>
                </p>
                <div v-if="item.parent.labels.length" class="task-row__labels">
                  <span v-for="l in item.parent.labels" :key="l" class="task-row__badge task-row__badge--stage">{{ l }}</span>
                </div>
              </div>
              <div class="task-row__detail-card">
                <h4>Timeline ({{ item.parent.events.length }})</h4>
                <div class="task-row__timeline">
                  <div v-for="(e, i) in item.parent.events" :key="i" class="task-row__tl-item">
                    <span class="task-row__tl-age">{{ e.age }}</span>
                    <span class="task-row__tl-type" :style="{ color: eventColor(e.type) }">{{ e.type }}</span>
                    <span class="task-row__tl-detail">{{ e.from_stage && e.to_stage ? `${e.from_stage} \u2192 ${e.to_stage}` : (e.reason || e.comment?.substring(0, 80) || e.agent || '') }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="item.parent.scratchpad" class="task-row__detail-card">
              <h4>Agent Notes</h4>
              <pre class="task-row__scratchpad">{{ item.parent.scratchpad }}</pre>
            </div>
            <div v-if="item.parent.messages.length" class="task-row__detail-card">
              <h4>Messages</h4>
              <div v-for="(m, i) in item.parent.messages" :key="i" class="task-row__msg">
                <span :class="'task-row__msg-type task-row__msg-type--' + m.type">{{ m.type }}</span>
                <span class="task-row__msg-from">{{ m.from }}</span>
                {{ m.body }}
              </div>
            </div>
          </div>
        </div>

        <!-- Orphan header (children exist but parent not in filtered view) -->
        <div v-else class="task-group__orphan-header" @click="toggleGroup(item.groupId)">
          <span class="task-row__arrow">{{ expandedGroups.has(item.groupId) ? '\u25BC' : '\u25B6' }}</span>
          <span class="task-group__orphan-label">Group: {{ item.groupId }}</span>
          <div class="task-row__meta">
            <span class="task-group__badge-count">{{ item.children.length }} sub-task{{ item.children.length !== 1 ? 's' : '' }}</span>
            <span v-if="item.totalCost" class="task-row__badge task-row__badge--cost">${{ item.totalCost.toFixed(2) }}</span>
          </div>
        </div>

        <!-- Children -->
        <div v-if="expandedGroups.has(item.groupId)" class="task-group__children">
          <div v-for="child in item.children" :key="child.id" :id="'task-row-' + child.id" class="task-row task-row--child">
            <div class="task-row__header" @click="toggle(child.id)">
              <span class="task-row__arrow">{{ expanded.has(child.id) ? '\u25BC' : '\u25B6' }}</span>
              <span class="task-row__id">{{ child.id }}</span>
              <span class="task-row__title">{{ child.title }}</span>
              <div class="task-row__meta">
                <span :class="'task-row__badge task-row__badge--' + child.status">{{ child.status }}</span>
                <span v-if="child.stage" class="task-row__badge task-row__badge--stage">{{ child.stage }}</span>
                <span class="task-row__badge task-row__badge--stage">{{ child.type }}</span>
                <span v-if="child.cost" class="task-row__badge task-row__badge--cost">${{ child.cost.toFixed(2) }}</span>
                <span class="task-row__age">{{ child.created }} ago</span>
              </div>
            </div>
            <div v-if="expanded.has(child.id)" class="task-row__detail">
              <div class="task-row__detail-grid">
                <div class="task-row__detail-card">
                  <h4>Details</h4>
                  <p v-if="child.description">{{ child.description }}</p>
                  <p v-else class="task-row__dim">No description</p>
                  <p class="task-row__stats">
                    Priority: {{ child.priority }} | Spawns: {{ child.spawns }} | Rejections: {{ child.rejections }} | Crashes: {{ child.crashes }}
                    <span v-if="child.budget"> | Budget: ${{ child.budget.toFixed(2) }}</span>
                  </p>
                  <div v-if="child.labels.length" class="task-row__labels">
                    <span v-for="l in child.labels" :key="l" class="task-row__badge task-row__badge--stage">{{ l }}</span>
                  </div>
                </div>
                <div class="task-row__detail-card">
                  <h4>Timeline ({{ child.events.length }})</h4>
                  <div class="task-row__timeline">
                    <div v-for="(e, i) in child.events" :key="i" class="task-row__tl-item">
                      <span class="task-row__tl-age">{{ e.age }}</span>
                      <span class="task-row__tl-type" :style="{ color: eventColor(e.type) }">{{ e.type }}</span>
                      <span class="task-row__tl-detail">{{ e.from_stage && e.to_stage ? `${e.from_stage} \u2192 ${e.to_stage}` : (e.reason || e.comment?.substring(0, 80) || e.agent || '') }}</span>
                    </div>
                  </div>
                </div>
              </div>
              <div v-if="child.scratchpad" class="task-row__detail-card">
                <h4>Agent Notes</h4>
                <pre class="task-row__scratchpad">{{ child.scratchpad }}</pre>
              </div>
              <div v-if="child.messages.length" class="task-row__detail-card">
                <h4>Messages</h4>
                <div v-for="(m, i) in child.messages" :key="i" class="task-row__msg">
                  <span :class="'task-row__msg-type task-row__msg-type--' + m.type">{{ m.type }}</span>
                  <span class="task-row__msg-from">{{ m.from }}</span>
                  {{ m.body }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

    </template>
  </div>
</template>

<style scoped>
/* ── Page layout ── */
.tasks-page { padding: 14px 20px; max-width: 1100px; margin: 0 auto; }
.tasks-page__filters { display: flex; gap: 6px; margin-bottom: 14px; align-items: center; flex-wrap: wrap; }
.tasks-page__filter-btn { background: #16213e; border: 1px solid #2a2a4a; color: #888; padding: 4px 12px; border-radius: 14px; font-size: 12px; cursor: pointer; }
.tasks-page__filter-btn:hover { border-color: #FFD100; }
.tasks-page__filter-btn--active { border-color: #FFD100; color: #FFD100; }
.tasks-page__count { color: #555; font-size: 12px; margin-left: 8px; }
.tasks-page__empty { text-align: center; color: #555; padding: 40px; font-style: italic; }

/* ── Task row (standalone + child) ── */
.task-row { background: #16213e; border: 1px solid #2a2a4a; border-radius: 6px; margin-bottom: 6px; }
.task-row--child { margin-left: 20px; border-left: 2px solid #3a3a5a; border-radius: 0 6px 6px 0; }
.task-row__header { padding: 10px 14px; cursor: pointer; display: flex; align-items: center; gap: 10px; }
.task-row__header:hover { background: #1a2a3e; }
.task-row__arrow { color: #555; font-size: 11px; min-width: 14px; }
.task-row__id { color: #FFD100; font-weight: bold; font-size: 12px; min-width: 75px; }
.task-row__title { flex: 1; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.task-row__meta { display: flex; gap: 6px; align-items: center; }
.task-row__badge { font-size: 10px; padding: 1px 7px; border-radius: 8px; font-weight: bold; }
.task-row__badge--open { background: #1a5276; color: #85c1e9; }
.task-row__badge--in_progress { background: #1e6e3e; color: #82e0aa; }
.task-row__badge--blocked { background: #8C1616; color: #f1948a; }
.task-row__badge--closed { background: #333; color: #888; }
.task-row__badge--stage { background: #2a2a4a; color: #aaa; }
.task-row__badge--cost { background: #0f0f23; color: #FFD100; }
.task-row__age { color: #555; font-size: 11px; }

/* ── Task detail (shared by standalone, parent, child) ── */
.task-row__detail { padding: 0 14px 14px; border-top: 1px solid #2a2a4a; }
.task-row__detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }
.task-row__detail-card { background: #0f0f23; border-radius: 4px; padding: 10px 12px; }
.task-row__detail-card h4 { color: #FFD100; font-size: 11px; text-transform: uppercase; margin-bottom: 6px; letter-spacing: 1px; }
.task-row__detail-card p { font-size: 12px; color: #ccc; line-height: 1.5; }
.task-row__stats { margin-top: 6px; font-size: 11px; color: #888; }
.task-row__dim { color: #555; font-style: italic; }
.task-row__labels { margin-top: 6px; display: flex; gap: 4px; flex-wrap: wrap; }

/* Timeline */
.task-row__timeline { padding-left: 16px; border-left: 2px solid #2a2a4a; }
.task-row__tl-item { margin-bottom: 4px; font-size: 11px; }
.task-row__tl-age { color: #555; min-width: 45px; display: inline-block; }
.task-row__tl-type { font-weight: bold; min-width: 65px; display: inline-block; }
.task-row__tl-detail { color: #888; }

/* Scratchpad */
.task-row__scratchpad { background: #0a0a1a; border-radius: 4px; padding: 8px; font-family: 'SF Mono', Consolas, monospace; font-size: 11px; line-height: 1.5; white-space: pre-wrap; color: #ccc; max-height: 200px; overflow-y: auto; margin: 0; }

/* Messages */
.task-row__msg { padding: 3px 0; font-size: 12px; border-bottom: 1px solid #1a1a2e; }
.task-row__msg-type { font-weight: bold; font-size: 10px; text-transform: uppercase; margin-right: 6px; }
.task-row__msg-type--question { color: #FFD100; }
.task-row__msg-type--answer { color: #82e0aa; }
.task-row__msg-type--feedback { color: #85c1e9; }
.task-row__msg-type--rejection { color: #f1948a; }
.task-row__msg-from { color: #555; margin-right: 4px; }

/* ── Task group container ── */
.task-group { background: #131b30; border: 1px solid #3a3a5a; border-radius: 8px; margin-bottom: 8px; padding: 2px; }

/* Parent row inside group */
.task-group__parent { }
.task-group__parent-header { padding: 10px 14px; cursor: pointer; display: flex; align-items: center; gap: 10px; background: #1a2540; border-radius: 6px; }
.task-group__parent-header:hover { background: #1e2d50; }
.task-group__parent-actions { padding: 2px 14px 4px; }
.task-group__detail-toggle { background: none; border: 1px solid #2a2a4a; color: #666; font-size: 10px; padding: 2px 8px; border-radius: 4px; cursor: pointer; }
.task-group__detail-toggle:hover { color: #FFD100; border-color: #FFD100; }

/* Group badge showing sub-task count */
.task-group__badge-count { font-size: 10px; padding: 1px 7px; border-radius: 8px; font-weight: bold; background: #2a1a4a; color: #b39ddb; }

/* Orphan group header (no parent in view) */
.task-group__orphan-header { padding: 10px 14px; cursor: pointer; display: flex; align-items: center; gap: 10px; background: #1a2540; border-radius: 6px; }
.task-group__orphan-header:hover { background: #1e2d50; }
.task-group__orphan-label { color: #888; font-size: 12px; font-style: italic; flex: 1; }

/* Children container */
.task-group__children { padding: 4px 4px 2px; }
</style>
