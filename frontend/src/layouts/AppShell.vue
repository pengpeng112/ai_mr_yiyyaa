<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppSidebar from './AppSidebar.vue'
import { useAuthStore } from '@/stores/auth'
import { useNavigationStore } from '@/stores/navigation'
import { usePreferenceStore } from '@/stores/preference'
import { useHealthStore } from '@/stores/health'
import { useTaskStore } from '@/stores/task'
import { statusLabel } from '@/utils/status'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const nav = useNavigationStore()
const pref = usePreferenceStore()
const health = useHealthStore()
const tasks = useTaskStore()

const isNarrow = ref(false)

function updateViewport() {
  isNarrow.value = window.innerWidth < 900
  if (isNarrow.value) {
    pref.sidebarCollapsed = true
  }
}

const breadcrumbs = computed(() => {
  const groupLabel =
    nav.menuTree.find((g) => g.id === route.meta.group)?.label ||
    (typeof route.meta.group === 'string' ? route.meta.group : '')
  const title = typeof route.meta.title === 'string' ? route.meta.title : ''
  return [groupLabel, title].filter(Boolean)
})

const healthTone = computed(() => {
  const s = String(health.overallStatus || '').toLowerCase()
  if (s.includes('ok') || s.includes('healthy') || s === 'up') return 'success'
  if (s.includes('degrad') || s.includes('warn')) return 'warning'
  if (s.includes('down') || s.includes('error') || s.includes('fail')) return 'danger'
  return 'info'
})

const taskLabel = computed(() => {
  const t = tasks.latest
  if (!t) return '无运行任务'
  return `${statusLabel(t.status)} ${t.done ?? 0}/${t.total ?? 0}`
})

onMounted(() => {
  updateViewport()
  window.addEventListener('resize', updateViewport)
  void health.refresh()
  void tasks.fetchLatest(true)
  tasks.startPolling(8000)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateViewport)
  tasks.stopPolling()
})

watch(
  () => route.meta.menuId,
  (menuId) => {
    if (typeof menuId === 'string') nav.openGroupForMenu(menuId)
  },
  { immediate: true },
)

async function onLogout() {
  await auth.logout()
  await router.replace({ name: 'login' })
}

function goTaskProgress() {
  if (nav.isMenuAllowed('push-progress')) {
    void router.push({ name: 'tasks-progress' })
  }
}
</script>

<template>
  <div class="app-shell">
    <a class="skip-link" href="#main-content">跳到主内容</a>

    <AppSidebar
      v-if="!isNarrow"
      :collapsed="pref.sidebarCollapsed"
    />

    <el-drawer
      v-model="nav.mobileDrawerOpen"
      direction="ltr"
      size="280px"
      :with-header="false"
      class="mobile-nav-drawer"
    >
      <AppSidebar mobile @navigate="nav.mobileDrawerOpen = false" />
    </el-drawer>

    <div class="app-shell__main-wrap">
      <header class="app-header">
        <div class="app-header__left">
          <el-button
            v-if="isNarrow"
            text
            aria-label="打开菜单"
            @click="nav.mobileDrawerOpen = true"
          >
            菜单
          </el-button>
          <el-button
            v-else
            text
            aria-label="折叠侧栏"
            @click="pref.toggleSidebar()"
          >
            {{ pref.sidebarCollapsed ? '展开' : '折叠' }}
          </el-button>
          <nav class="app-header__crumbs" aria-label="面包屑">
            <span
              v-for="(c, idx) in breadcrumbs"
              :key="`${c}-${idx}`"
              class="app-header__crumb"
            >
              <span v-if="idx > 0" class="app-header__sep">/</span>
              {{ c }}
            </span>
          </nav>
        </div>
        <div class="app-header__right">
          <el-tag
            class="app-header__chip"
            size="small"
            effect="plain"
            :type="healthTone"
            @click="health.refresh(true)"
          >
            健康：{{ health.overallStatus || '—' }}
          </el-tag>
          <el-button text class="app-header__chip" @click="goTaskProgress">
            任务：{{ taskLabel }}
          </el-button>
          <el-dropdown>
            <span class="app-header__user" tabindex="0">
              {{ auth.displayName }}
              <small v-if="auth.roleName">({{ auth.roleName }})</small>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>{{ auth.user?.username }}</el-dropdown-item>
                <el-dropdown-item divided @click="onLogout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main id="main-content" class="app-main" tabindex="-1">
        <router-view v-slot="{ Component, route: r }">
          <keep-alive>
            <component
              :is="Component"
              v-if="r.meta.keepAlive"
              :key="String(r.name || r.path)"
            />
          </keep-alive>
          <component
            :is="Component"
            v-if="!r.meta.keepAlive"
            :key="String(r.name || r.path)"
          />
        </router-view>
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  height: 100dvh;
  overflow: hidden;
  display: flex;
  background: var(--ma-surface-page);
}
.app-shell__main-wrap {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.app-header {
  height: var(--ma-header-height);
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 14px;
  background: rgba(255, 255, 255, 0.92);
  border-bottom: 1px solid var(--ma-border);
  backdrop-filter: blur(8px);
}
.app-header__left,
.app-header__right {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.app-header__crumbs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  color: var(--ma-text-secondary);
  font-size: 13px;
}
.app-header__sep {
  margin-right: 4px;
  color: var(--ma-text-muted);
}
.app-header__user {
  cursor: pointer;
  font-size: 13px;
  color: var(--ma-text-primary);
  outline: none;
}
.app-header__user small {
  color: var(--ma-text-muted);
  margin-left: 4px;
}
.app-header__chip {
  cursor: pointer;
}
.app-main {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 16px 18px 28px;
}
@media (max-width: 640px) {
  .app-main {
    padding: 12px 10px 24px;
  }
  .app-header__crumbs {
    display: none;
  }
}
</style>
