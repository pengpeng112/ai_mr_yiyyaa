import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiGet } from '@/api/client'
import type { PushProgress } from '@/api/types'

export const useTaskStore = defineStore('task', () => {
  const latest = ref<PushProgress | null>(null)
  const polling = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null
  let pollGeneration = 0

  function clear() {
    latest.value = null
  }

  function stopPolling() {
    pollGeneration += 1
    polling.value = false
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  async function fetchLatest(silent = true) {
    try {
      const data = await apiGet<PushProgress>('/push/tasks/latest')
      latest.value = data
      return data
    } catch (e) {
      if (!silent) throw e
      return null
    }
  }

  function startPolling(intervalMs = 5000) {
    stopPolling()
    const gen = pollGeneration
    polling.value = true
    void fetchLatest(true)
    timer = setInterval(() => {
      if (gen !== pollGeneration) return
      void fetchLatest(true)
    }, intervalMs)
  }

  return {
    latest,
    polling,
    clear,
    stopPolling,
    fetchLatest,
    startPolling,
  }
})
