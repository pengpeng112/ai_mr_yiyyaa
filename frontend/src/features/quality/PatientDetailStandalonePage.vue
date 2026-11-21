<script setup lang="ts">
// 患者质控详情独立页（WP05）：复用 PatientQcDetailView（与工作台抽屉同一套高可读
// 组件，inDrawer=false 显示「打印质控单」）；保留路由路径 /quality/patient-detail 与
// 登录鉴权；打印样式隐藏交互按钮。
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PatientQcDetailView from './components/PatientQcDetailView.vue'

const route = useRoute()
const router = useRouter()

const patientId = computed(() => String(route.query.patient_id || ''))
const visitNumber = computed(() => String(route.query.visit_number || ''))
const dept = computed(() => String(route.query.dept || ''))

function back() {
  if (window.history.length > 1) router.back()
  else void router.push({ name: 'quality-patients' })
}
</script>

<template>
  <div class="standalone-detail">
    <div class="sd-toolbar no-print">
      <el-button size="small" @click="back">返回</el-button>
      <span class="sd-hint">本页为独立详情入口，受登录鉴权保护，可直接打印留档。</span>
    </div>

    <PatientQcDetailView
      :key="`${patientId}__${visitNumber}`"
      :patient-id="patientId"
      :visit-number="visitNumber"
      :dept="dept"
      :in-drawer="false"
    />
  </div>
</template>

<style scoped>
.standalone-detail { width: 100%; max-width: 1080px; margin: 0 auto; padding: 8px 4px; }
.sd-toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
.sd-hint { font-size: 12px; color: var(--el-text-color-secondary); }

@media print {
  .no-print { display: none !important; }
  .standalone-detail { max-width: none; padding: 0; }
}
</style>
