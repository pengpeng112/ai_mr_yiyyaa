<template>
  <section class="approval-center">
    <PageHeader
      title="解锁审批与豁免"
      description="集中处理临床提交的病历超时解锁申请与人工特殊豁免审批"
    >
      <template #actions>
        <el-button
          v-if="canManage"
          type="primary"
          plain
          size="small"
          :loading="syncing"
          data-testid="approval-sync"
          @click="runSync"
        >
          立即同步 JHEMR 审批
        </el-button>
        <el-button data-testid="open-mobile-entry" @click="mobileEntryVisible = true">
          📱 手机端入口
        </el-button>
      </template>
    </PageHeader>
    <el-card shadow="never">
      <ApprovalLedgerPage :key="ledgerKey" />
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
// WP04（064 总计划）：页头新增「立即同步 JHEMR 审批」（POST /approvals/sync，
// timeliness_admin；只读源未配置后端 503）——成功后提示同步条数并刷新台账子组件。
import { computed, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/base/PageHeader.vue'
import ApprovalLedgerPage from './ApprovalLedgerPage.vue'
import { syncApprovalsApi } from './api'

const auth = useAuthStore()
const canManage = computed(() => auth.roleName === 'admin' || auth.user?.permissions?.includes('timeliness_admin'))

const mobileEntryVisible = ref(false)
const mobileUrl = computed(() => `${window.location.origin}/mobile/qc/timeliness`)

const syncing = ref(false)
const ledgerKey = ref(0)

async function runSync(): Promise<void> {
  syncing.value = true
  try {
    const result = await syncApprovalsApi()
    ElMessage.success(`已同步 ${result.synced} 条`)
    // key 自增强制子组件重挂载（重新拉取台账与状态汇总）。
    ledgerKey.value += 1
  } catch (exc) {
    const message = exc instanceof Error ? exc.message : '同步失败'
    if (message.includes('503')) {
      ElMessage.warning('JHEMR 只读数据源未配置，暂无法同步审批')
    } else if (message.includes('403')) {
      ElMessage.error('需要 timeliness_admin 权限与全院操作范围')
    } else {
      ElMessage.error(message)
    }
  } finally {
    syncing.value = false
  }
}

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
