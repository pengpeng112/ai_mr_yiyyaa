<script setup lang="ts">
// 旧路由兼容壳（WP05，用户拍板 D2）：/quality/records（菜单 audit，hidden）自动
// 重定向到 /quality/patients?view=records 并完整保留原有 query 参数——书签与
// 跨页跳转（总览/反馈页等）无损；onMounted + onActivated 双触发（路由有 keepAlive）。
import { onActivated, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

function redirect() {
  void router.replace({
    path: '/quality/patients',
    query: { ...route.query, view: 'records' },
  })
}

onMounted(redirect)
onActivated(redirect)
</script>

<template>
  <div class="audit-redirect">
    <el-empty description="质控记录已并入「内涵质控工作台」，正在跳转…" :image-size="80" />
  </div>
</template>

<style scoped>
.audit-redirect {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
}
</style>
