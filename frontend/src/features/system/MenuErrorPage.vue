<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useNavigationStore } from '@/stores/navigation'
import ErrorState from '@/components/feedback/ErrorState.vue'
import { ElMessage } from 'element-plus'

const nav = useNavigationStore()
const router = useRouter()

async function retry() {
  await nav.loadMenu()
  if (nav.loaded) {
    ElMessage.success('菜单已加载')
    await router.replace({ name: nav.defaultRouteName })
  }
}
</script>

<template>
  <ErrorState
    title="权限菜单加载失败"
    :message="nav.error || '无法获取授权菜单，已 fail-closed，不会显示默认管理员菜单。'"
    :request-id="nav.requestId"
    @retry="retry"
  />
</template>
