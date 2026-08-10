import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { fetchHealthApi } from '@/api/endpoints/health'
import type { HealthResponse } from '@/api/types'

export const useHealthStore = defineStore('health', () => {
  const summary = ref<HealthResponse | null>(null)
  const loading = ref(false)
  const lastError = ref('')

  const overallStatus = computed(() => summary.value?.status || 'unknown')

  async function refresh(force = false) {
    loading.value = true
    lastError.value = ''
    try {
      summary.value = await fetchHealthApi(force)
    } catch {
      lastError.value = '健康状态暂不可用'
    } finally {
      loading.value = false
    }
  }

  return {
    summary,
    loading,
    lastError,
    overallStatus,
    refresh,
  }
})
