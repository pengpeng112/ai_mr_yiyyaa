<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useNavigationStore } from '@/stores/navigation'
import { usePreferenceStore } from '@/stores/preference'

const props = defineProps<{
  collapsed?: boolean
  mobile?: boolean
}>()

const emit = defineEmits<{
  navigate: []
}>()

const route = useRoute()
const router = useRouter()
const nav = useNavigationStore()
const pref = usePreferenceStore()

const activeMenuId = computed(() => {
  const id = route.meta.menuId
  return typeof id === 'string' ? id : ''
})

const opened = computed({
  get: () => nav.openedGroupIds,
  set: (v: string[]) => {
    nav.openedGroupIds = v.slice(-1)
  },
})

function onSelect(menuId: string) {
  const item = nav.findByMenuId(menuId)
  if (!item) return
  nav.openGroupForMenu(menuId)
  void router.push({ name: item.entry.name })
  emit('navigate')
  if (props.mobile) nav.mobileDrawerOpen = false
}
</script>

<template>
  <aside
    class="app-sidebar"
    :class="{ 'is-collapsed': collapsed && !mobile, 'is-mobile': mobile }"
    aria-label="主导航"
  >
    <div class="app-sidebar__brand">
      <div class="app-sidebar__logo" aria-hidden="true">MA</div>
      <div v-if="!collapsed || mobile" class="app-sidebar__titles">
        <div class="app-sidebar__name">Med-Audit</div>
        <div class="app-sidebar__sub">病历质控</div>
      </div>
    </div>

    <el-menu
      :key="nav.menuTree.map((g) => g.id).join('-')"
      :default-active="activeMenuId"
      :default-openeds="opened"
      :collapse="collapsed && !mobile"
      background-color="transparent"
      text-color="#cbd5e1"
      active-text-color="#ffffff"
      class="app-sidebar__menu"
      @select="onSelect"
      @open="(id: string) => (nav.openedGroupIds = [id])"
    >
      <el-sub-menu v-for="group in nav.menuTree" :key="group.id" :index="group.id">
        <template #title>
          <span>{{ group.label }}</span>
        </template>
        <el-menu-item
          v-for="item in group.children"
          :key="item.id"
          :index="item.id"
          :aria-label="item.label"
        >
          {{ item.label }}
        </el-menu-item>
      </el-sub-menu>
    </el-menu>

    <div v-if="!collapsed || mobile" class="app-sidebar__foot">
      <button
        v-if="!mobile"
        type="button"
        class="app-sidebar__collapse-btn"
        @click="pref.toggleSidebar()"
      >
        折叠侧栏
      </button>
      <span class="app-sidebar__ver">ui-next</span>
    </div>
  </aside>
</template>

<style scoped>
.app-sidebar {
  width: var(--ma-sidebar-width);
  background: linear-gradient(180deg, #0b1220 0%, #111827 100%);
  color: var(--ma-text-on-dark);
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid rgba(148, 163, 184, 0.12);
  transition: width 0.2s ease;
}
.app-sidebar.is-collapsed {
  width: var(--ma-sidebar-collapsed);
}
.app-sidebar.is-mobile {
  width: min(86vw, 280px);
  height: 100%;
}
.app-sidebar__brand {
  display: flex;
  align-items: center;
  gap: 10px;
  height: var(--ma-header-height);
  padding: 0 14px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}
.app-sidebar__logo {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-weight: 700;
  font-size: 12px;
  background: linear-gradient(135deg, #38bdf8, #2563eb);
  color: #fff;
  flex: 0 0 auto;
}
.app-sidebar__name {
  font-weight: 700;
  font-size: 14px;
}
.app-sidebar__sub {
  font-size: 11px;
  color: #94a3b8;
}
.app-sidebar__menu {
  flex: 1;
  overflow: auto;
  border-right: none !important;
  padding: 8px 0 16px;
}
.app-sidebar__foot {
  padding: 10px 12px 14px;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.app-sidebar__collapse-btn {
  border: 0;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  font-size: 12px;
  padding: 0;
}
.app-sidebar__ver {
  font-size: 11px;
  color: #64748b;
}
:deep(.el-menu-item.is-active) {
  background: rgba(37, 99, 235, 0.28) !important;
}
:deep(.el-sub-menu__title:hover),
:deep(.el-menu-item:hover) {
  background: rgba(148, 163, 184, 0.08) !important;
}
</style>
