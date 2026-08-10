import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

const SIDEBAR_KEY = 'ui_pref_sidebar_collapsed'
const DENSITY_KEY = 'ui_pref_table_density'

function readBool(key: string, fallback: boolean) {
  try {
    const v = localStorage.getItem(key)
    if (v === null) return fallback
    return v === '1' || v === 'true'
  } catch {
    return fallback
  }
}

function readString(key: string, fallback: string) {
  try {
    return localStorage.getItem(key) || fallback
  } catch {
    return fallback
  }
}

/** 仅非敏感 UI 偏好；禁止存患者/密钥/病历 */
export const usePreferenceStore = defineStore('preference', () => {
  const sidebarCollapsed = ref(readBool(SIDEBAR_KEY, false))
  const tableDensity = ref(readString(DENSITY_KEY, 'compact'))

  watch(sidebarCollapsed, (v) => {
    try {
      localStorage.setItem(SIDEBAR_KEY, v ? '1' : '0')
    } catch {
      /* ignore */
    }
  })

  watch(tableDensity, (v) => {
    try {
      localStorage.setItem(DENSITY_KEY, v)
    } catch {
      /* ignore */
    }
  })

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  return {
    sidebarCollapsed,
    tableDensity,
    toggleSidebar,
  }
})
