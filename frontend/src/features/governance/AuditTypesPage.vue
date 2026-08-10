<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import DataTableShell from '@/components/base/DataTableShell.vue'
import DetailDrawer from '@/components/base/DetailDrawer.vue'
import { apiGet, apiPut } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { displayText } from '@/utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'

interface AuditTypeRow {
  code: string
  name?: string
  enabled?: boolean
  [key: string]: unknown
}

const loading = ref(false)
const error = ref('')
const items = ref<AuditTypeRow[]>([])
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<AuditTypeRow | null>(null)
const editJson = ref('')
const saving = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiGet<{ items?: AuditTypeRow[] } | AuditTypeRow[]>('/audit-types')
    items.value = Array.isArray(data) ? data : data.items || []
  } catch (e) {
    error.value = toUserMessage(e, '加载质控类型失败')
  } finally {
    loading.value = false
  }
}

async function openDetail(row: AuditTypeRow) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    const full = await apiGet<AuditTypeRow>(`/audit-types/${row.code}`)
    detail.value = full
    // 脱敏后的配置；secret 以 mask 形式存在，保存时留空保留
    editJson.value = JSON.stringify(full, null, 2)
  } catch (e) {
    ElMessage.error(toUserMessage(e, '加载详情失败'))
  } finally {
    detailLoading.value = false
  }
}

async function save() {
  if (!detail.value?.code) return
  let body: Record<string, unknown>
  try {
    body = JSON.parse(editJson.value) as Record<string, unknown>
  } catch {
    ElMessage.error('JSON 格式无效')
    return
  }
  try {
    await ElMessageBox.confirm(
      '确认保存质控类型？密钥字段留空将保留旧密文；builder 输出仍须为 mr_text。',
      '请确认',
      { type: 'warning' },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    await apiPut(`/audit-types/${detail.value.code}`, body)
    ElMessage.success('已保存')
    await load()
    await openDetail(detail.value)
  } catch (e) {
    ElMessage.error(toUserMessage(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page-audit-types">
    <PageHeader
      title="质控类型"
      description="来源、builder、Dify、JSONPath 分层管理。mr_text/mr_txt 映射与 SQL/JSONPath 校验不可回退。"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <DataTableShell
      :loading="loading"
      :error="error"
      :empty="!items.length"
      :show-pagination="false"
      @retry="load"
    >
      <el-table v-loading="loading" :data="items" stripe border size="small">
        <el-table-column prop="code" label="Code" min-width="160" />
        <el-table-column label="名称" min-width="160">
          <template #default="{ row }">{{ displayText(row.name) }}</template>
        </el-table-column>
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.enabled ? 'success' : 'info'">
              {{ row.enabled ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row as AuditTypeRow)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </DataTableShell>

    <DetailDrawer v-model="detailVisible" title="质控类型详情" :loading="detailLoading" size="720px">
      <el-input v-model="editJson" type="textarea" :rows="22" class="mono" />
      <template #footer>
        <el-button @click="detailVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </DetailDrawer>
  </div>
</template>

<style scoped>
.mono :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
</style>
