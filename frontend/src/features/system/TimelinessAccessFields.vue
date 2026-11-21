<script setup lang="ts">
import type { TimelinessAccessDraft } from '@/utils/access-contracts'

defineProps<{ departments: { name?: string; code?: string }[]; inheritLabel: string }>()
const draft = defineModel<TimelinessAccessDraft>({ required: true })
</script>

<template>
  <el-form-item label="病历时效查看范围">
    <el-select v-model="draft.scope">
      <el-option :label="inheritLabel" value="" />
      <el-option label="本科室" value="home" />
      <el-option label="指定科室" value="selected" />
      <el-option label="全院" value="all" />
    </el-select>
  </el-form-item>
  <el-form-item v-if="draft.scope === 'selected'" label="可查看科室" required>
    <el-select v-model="draft.department_codes" multiple filterable>
      <template v-for="dept in departments" :key="dept.code">
        <el-option v-if="dept.code" :label="dept.name" :value="dept.code" />
      </template>
    </el-select>
  </el-form-item>
  <el-form-item v-if="draft.scope" label="登录后默认显示">
    <el-radio-group v-model="draft.default_view">
      <el-radio value="home">优先显示本科室</el-radio>
      <el-radio value="all">显示全部授权科室</el-radio>
    </el-radio-group>
  </el-form-item>
</template>
