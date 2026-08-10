import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { fetchMenuApi } from '@/api/endpoints/menu'
import type { MenuGroup, MenuItem } from '@/api/types'
import { toUserMessage } from '@/api/errors'
import {
  getManifestByMenuId,
  intersectMenuWithManifest,
  type RouteManifestEntry,
} from '@/router/route-manifest'

export interface NavMenuItem extends MenuItem {
  entry: RouteManifestEntry
}

export interface NavGroup {
  id: string
  label: string
  order: number
  children: NavMenuItem[]
}

export const useNavigationStore = defineStore('navigation', () => {
  const loaded = ref(false)
  const loading = ref(false)
  const error = ref('')
  const requestId = ref<string | undefined>()
  const role = ref<string | null>(null)
  const rawMenu = ref<MenuItem[]>([])
  const groups = ref<MenuGroup[]>([])
  const defaultHome = ref<string | null>(null)
  const unknownMenuIds = ref<string[]>([])
  const openedGroupIds = ref<string[]>([])
  const mobileDrawerOpen = ref(false)

  const allowedMenu = computed<NavMenuItem[]>(() => {
    const { allowed } = intersectMenuWithManifest(rawMenu.value)
    return allowed
  })

  const menuTree = computed<NavGroup[]>(() => {
    const groupMap = new Map<string, NavGroup>()
    const sortedGroups = [...groups.value].sort(
      (a, b) => Number(a.order || 999) - Number(b.order || 999),
    )
    for (const g of sortedGroups) {
      groupMap.set(g.id, {
        id: g.id,
        label: g.label,
        order: Number(g.order || 999),
        children: [],
      })
    }
    const items = [...allowedMenu.value].sort(
      (a, b) => Number(a.order || 999) - Number(b.order || 999),
    )
    for (const item of items) {
      const gid = item.group || item.entry.group || 'workbench'
      if (!groupMap.has(gid)) {
        groupMap.set(gid, {
          id: gid,
          label: gid,
          order: 999,
          children: [],
        })
      }
      groupMap.get(gid)!.children.push(item)
    }
    return Array.from(groupMap.values())
      .filter((g) => g.children.length > 0)
      .sort((a, b) => a.order - b.order)
  })

  const allowedMenuIds = computed(() => new Set(allowedMenu.value.map((m) => m.id)))

  const defaultRouteName = computed(() => {
    const homeId = defaultHome.value
    if (homeId && allowedMenuIds.value.has(homeId)) {
      return getManifestByMenuId(homeId)?.name || 'workbench'
    }
    const first = allowedMenu.value[0]
    return first?.entry.name || 'workbench'
  })

  function isMenuAllowed(menuId: string) {
    return allowedMenuIds.value.has(menuId)
  }

  function findByMenuId(menuId: string) {
    return allowedMenu.value.find((m) => m.id === menuId)
  }

  function openGroupForMenu(menuId: string) {
    const item = findByMenuId(menuId)
    const gid = item?.group || item?.entry.group
    if (gid) openedGroupIds.value = [gid]
  }

  async function loadMenu() {
    loading.value = true
    error.value = ''
    requestId.value = undefined
    try {
      const data = await fetchMenuApi()
      rawMenu.value = Array.isArray(data.menu) ? data.menu : []
      groups.value = Array.isArray(data.groups) ? data.groups : []
      role.value = data.role ?? null
      defaultHome.value = data.default_home ?? null
      // 触发 unknown 诊断
      const { unknownIds } = intersectMenuWithManifest(rawMenu.value)
      unknownMenuIds.value = unknownIds
      if (unknownIds.length) {
        // 诊断信息：不展示给最终用户详情，仅 console 级别警告（无敏感）
        console.warn('[menu] unknown menu ids (fail-closed):', unknownIds.join(','))
      }
      loaded.value = true
      if (!openedGroupIds.value.length && menuTree.value[0]) {
        openedGroupIds.value = [menuTree.value[0].id]
      }
    } catch (e) {
      loaded.value = false
      rawMenu.value = []
      groups.value = []
      error.value = toUserMessage(e, '权限菜单加载失败')
      if (e && typeof e === 'object' && 'requestId' in e) {
        requestId.value = String((e as { requestId?: string }).requestId || '')
      }
    } finally {
      loading.value = false
    }
  }

  function reset() {
    loaded.value = false
    loading.value = false
    error.value = ''
    requestId.value = undefined
    role.value = null
    rawMenu.value = []
    groups.value = []
    defaultHome.value = null
    unknownMenuIds.value = []
    openedGroupIds.value = []
    mobileDrawerOpen.value = false
  }

  return {
    loaded,
    loading,
    error,
    requestId,
    role,
    rawMenu,
    groups,
    defaultHome,
    unknownMenuIds,
    openedGroupIds,
    mobileDrawerOpen,
    allowedMenu,
    menuTree,
    allowedMenuIds,
    defaultRouteName,
    isMenuAllowed,
    findByMenuId,
    openGroupForMenu,
    loadMenu,
    reset,
  }
})
