<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useNavigationStore } from '@/stores/navigation'
import ErrorState from '@/components/feedback/ErrorState.vue'

const router = useRouter()
const nav = useNavigationStore()
</script>

<template>
  <ErrorState title="404 页面不存在" message="请检查地址或从侧边栏重新进入。" />
  <div style="text-align: center">
    <el-button type="primary" @click="router.replace({ name: nav.defaultRouteName })">
      返回首页
    </el-button>
  </div>
</template>
