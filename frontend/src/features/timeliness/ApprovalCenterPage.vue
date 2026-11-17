<template>
  <section class="approval-center">
    <PageHeader
      title="解锁审批与豁免"
      description="集中处理临床提交的病历超时解锁申请与人工特殊豁免审批"
    >
      <template #actions>
        <el-button data-testid="open-mobile-entry" @click="mobileEntryVisible = true">
          📱 手机端入口
        </el-button>
      </template>
    </PageHeader>
    <el-card shadow="never">
      <ApprovalLedgerPage />
    </el-card>

    <!-- 2026-11-16：企微手机端访问入口便捷弹窗 -->
    <el-dialog v-model="mobileEntryVisible" title="企业微信手机端访问入口" width="min(92vw, 520px)">
      <p class="mobile-entry-tip">
        可将此链接配置到企业微信工作台自建应用主页，或发送至企业微信收藏夹，手机点开即可查询超时解锁与统计报表。
      </p>
      <el-input :model-value="mobileUrl" readonly>
        <template #append>
          <el-button @click="copyMobileUrl">一键复制链接</el-button>
        </template>
      </el-input>
      <template #footer>
        <el-button @click="mobileEntryVisible = false">关闭</el-button>
        <el-button type="primary" @click="previewMobile">
          <a :href="mobileUrl" target="_blank" rel="noopener" class="mobile-entry-link">新窗口预览手机端</a>
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
// 解锁审批中心（2026-11-15 菜单体系重构独立成页）：
// 复用 ApprovalLedgerPage 全部筛选/豁免/审批解锁（dry-run 预览）能力，
// 本层只负责标准页头；月度考核页内仍保留同名页签入口（兼容既有契约）。
// 2026-11-16：新增「📱 手机端入口」弹窗（展示企微 H5 链接，一键复制/新窗预览）。
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/base/PageHeader.vue'
import ApprovalLedgerPage from './ApprovalLedgerPage.vue'

const mobileEntryVisible = ref(false)
const mobileUrl = computed(() => `${window.location.origin}/mobile/qc/timeliness`)

async function copyMobileUrl(): Promise<void> {
  try {
    await navigator.clipboard.writeText(mobileUrl.value)
    ElMessage.success('手机端链接已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择链接复制')
  }
}

function previewMobile(): void {
  mobileEntryVisible.value = false
}
</script>

<style scoped>
.approval-center {
  padding: 4px;
}
.mobile-entry-tip {
  margin: 0 0 12px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}
.mobile-entry-link {
  color: inherit;
  text-decoration: none;
}
</style>
