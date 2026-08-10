<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { useNavigationStore } from '@/stores/navigation'
import ErrorState from '@/components/feedback/ErrorState.vue'

const route = useRoute()
const router = useRouter()
const nav = useNavigationStore()

function goHome() {
  void router.replace({ name: nav.defaultRouteName })
}
</script>

<template>
  <ErrorState
    title="403 无权限"
    :message="
      route.query.reason === 'unknown-route'
        ? '目标页面未在前端组件白名单中注册（fail-closed）。'
        : '当前账号无权访问该页面。菜单隐藏不能替代后端权限。'
    "
  >
  </ErrorState>
  <div style="text-align: center">
    <el-button type="primary" @click="goHome">返回首页</el-button>
  </div>
</template>
