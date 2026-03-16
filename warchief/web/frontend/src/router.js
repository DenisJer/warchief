import { createRouter, createWebHistory } from 'vue-router'
import DashboardView from './views/DashboardView.vue'
import AgentsView from './views/AgentsView.vue'
import TasksView from './views/TasksView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: DashboardView },
    { path: '/agents', component: AgentsView },
    { path: '/tasks', component: TasksView },
  ],
})
