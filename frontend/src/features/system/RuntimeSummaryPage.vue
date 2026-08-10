<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import SkeletonBlock from '@/components/feedback/SkeletonBlock.vue'
import { apiGet } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import type { RuntimeSummary } from '@/api/types'

const loading = ref(false)
const error = ref('')
const data = ref<RuntimeSummary | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await apiGet<RuntimeSummary>('/config/runtime-summary')
  } catch (e) {
    error.value = toUserMessage(e, '加载运行总览失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page-runtime">
    <PageHeader
      title="运行总览"
      description="只读运行模式、调度配置风险与解析结果；与系统配置写表单视觉分离。"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <ErrorState v-if="error && !loading" :message="error" @retry="load" />
    <SkeletonBlock v-else-if="loading && !data" :rows="8" />
    <template v-else-if="data">
      <el-alert
        v-if="Array.isArray(data.warnings) && data.warnings.length"
        type="warning"
        :closable="false"
        show-icon
        class="mb"
        title="存在配置风险提示"
        :description="`${data.warnings.length} 条警告（详情见下方）`"
      />
      <el-row :gutter="12">
        <el-col :xs="24" :md="12">
          <el-card shadow="never" class="block">
            <template #header>运行模式</template>
            <pre class="json-pre">{{ JSON.stringify(data.run_modes ?? {}, null, 2) }}</pre>
          </el-card>
        </el-col>
        <el-col :xs="24" :md="12">
          <el-card shadow="never" class="block">
            <template #header>调度器</template>
            <pre class="json-pre">{{ JSON.stringify(data.schedulers ?? {}, null, 2) }}</pre>
          </el-card>
        </el-col>
        <el-col :xs="24" :md="12">
          <el-card shadow="never" class="block">
            <template #header>科室范围</template>
            <pre class="json-pre">{{ JSON.stringify(data.dept_scopes ?? {}, null, 2) }}</pre>
          </el-card>
        </el-col>
        <el-col :xs="24" :md="12">
          <el-card shadow="never" class="block">
            <template #header>审计类型摘要</template>
            <pre class="json-pre">{{ JSON.stringify(data.audit_types ?? {}, null, 2) }}</pre>
          </el-card>
        </el-col>
        <el-col :span="24">
          <el-card shadow="never" class="block">
            <template #header>警告</template>
            <pre class="json-pre">{{ JSON.stringify(data.warnings ?? [], null, 2) }}</pre>
          </el-card>
        </el-col>
      </el-row>
    </template>
  </div>
</template>

<style scoped>
.mb {
  margin-bottom: 12px;
}
.block {
  margin-bottom: 12px;
  border-radius: 12px;
}
.json-pre {
  margin: 0;
  max-height: 320px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--ma-text-secondary);
}
</style>
