<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import SummaryStrip, { type SummaryItem } from '@/components/base/SummaryStrip.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import SkeletonBlock from '@/components/feedback/SkeletonBlock.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import { fetchHealthApi, fetchHealthComponentApi } from '@/api/endpoints/health'
import { toUserMessage } from '@/api/errors'
import type { HealthResponse } from '@/api/types'
import { displayText } from '@/utils/format'

const loading = ref(false)
const error = ref('')
const data = ref<HealthResponse | null>(null)
const probeLoading = ref('')

const components = computed(() => {
  const raw = data.value?.components || {}
  return Object.entries(raw).map(([name, value]) => {
    if (value && typeof value === 'object') {
      const v = value as Record<string, unknown>
      return {
        name,
        status: String(v.status ?? v.state ?? 'unknown'),
        latency_ms: v.latency_ms as number | null | undefined,
        message: String(v.message ?? v.detail ?? ''),
      }
    }
    return { name, status: String(value ?? 'unknown'), latency_ms: null, message: '' }
  })
})

const summaryItems = computed<SummaryItem[]>(() => [
  { key: 'overall', label: '总体状态', value: displayText(data.value?.status), tone: 'info' },
  { key: 'count', label: '组件数', value: components.value.length },
  {
    key: 'ok',
    label: '正常组件',
    value: components.value.filter((c) => /ok|up|healthy|success/i.test(c.status)).length,
    tone: 'success',
  },
  {
    key: 'bad',
    label: '异常组件',
    value: components.value.filter((c) => /down|fail|error|unhealthy/i.test(c.status)).length,
    tone: 'danger',
  },
])

async function load(force = false) {
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchHealthApi(force)
  } catch (e) {
    error.value = toUserMessage(e, '加载健康状态失败')
  } finally {
    loading.value = false
  }
}

async function probe(name: 'oracle' | 'postgresql' | 'dify') {
  probeLoading.value = name
  try {
    await fetchHealthComponentApi(name)
    await load(true)
  } catch (e) {
    error.value = toUserMessage(e, `${name} 探测失败`)
  } finally {
    probeLoading.value = ''
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page-health">
    <PageHeader title="系统健康" description="只读组件健康与延迟；不展示内部堆栈或 SQL。">
      <template #actions>
        <el-button :loading="loading" @click="load(true)">刷新</el-button>
        <el-button :loading="probeLoading === 'oracle'" @click="probe('oracle')">探测 Oracle</el-button>
        <el-button :loading="probeLoading === 'postgresql'" @click="probe('postgresql')">探测 PG</el-button>
        <el-button :loading="probeLoading === 'dify'" @click="probe('dify')">探测 Dify</el-button>
      </template>
    </PageHeader>

    <ErrorState v-if="error && !loading" :message="error" @retry="load(true)" />
    <template v-else>
      <SummaryStrip :items="summaryItems" :loading="loading" />
      <SkeletonBlock v-if="loading && !data" :rows="6" />
      <el-row v-else :gutter="12">
        <el-col v-for="c in components" :key="c.name" :xs="24" :sm="12" :md="8" :lg="6">
          <el-card shadow="never" class="health-card">
            <div class="health-card__name">{{ c.name }}</div>
            <StatusTag :value="c.status" />
            <div class="health-card__meta">
              延迟：{{ c.latency_ms == null ? '—' : `${c.latency_ms} ms` }}
            </div>
            <div v-if="c.message" class="health-card__msg">{{ c.message }}</div>
          </el-card>
        </el-col>
      </el-row>
    </template>
  </div>
</template>

<style scoped>
.health-card {
  margin-bottom: 12px;
  border-radius: 12px;
}
.health-card__name {
  font-weight: 650;
  margin-bottom: 8px;
}
.health-card__meta,
.health-card__msg {
  margin-top: 8px;
  font-size: 12px;
  color: var(--ma-text-muted);
}
</style>
