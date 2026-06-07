import {
  severityLabel,
  pushStatusLabel,
  feedbackStatusLabel,
  feedbackStatusTagType,
  statusTagType,
  severityTagType,
  auditStatusLabel,
  formatDateTimeFallback,
} from './utils/formatters.js';
import { apiGet, apiPost } from './utils/api.js?v=20260524-download-blob';
import { dashboardMethods } from './modules/dashboard.js';
import { authMethods } from './modules/auth.js';
import { logsMethods } from './modules/logs.js?v=20260524-api-cache-fix';
import { feedbackMethods } from './modules/feedback.js?v=20260524-api-cache-fix';
import { pushMethods } from './modules/push.js?v=20260525-fulltext-diagnostics';
import { patientQcMethods } from './modules/patient_qc.js';
import { statsMethods } from './modules/stats.js';
import { configMethods } from './modules/config.js?v=20260607-runtime-summary';
import { schedulerMethods } from './modules/scheduler.js?v=20260608-redesign';
import { adminMethods } from './modules/admin.js';
import { auditTypeMethods, createAuditTypeEditorState } from './modules/audit_types.js?v=20260607-audit-runtime-summary-dify-safe';
import { FALLBACK_GROUPS, FALLBACK_MENU, SAFE_FALLBACK_MENU, buildMenuTree, flattenMenuTree } from './navigation.js';

const { createApp } = Vue;

function collectTemplatePartialTargets() {
  const targets = Array.from(document.querySelectorAll('[data-template-src]'));
  document.querySelectorAll('template').forEach((tpl) => {
    if (tpl.content) {
      targets.push(...Array.from(tpl.content.querySelectorAll('[data-template-src]')));
    }
  });
  return targets;
}

function replaceTemplateTarget(target, html) {
  const wrapper = document.createElement('template');
  wrapper.innerHTML = html;
  target.replaceWith(wrapper.content.cloneNode(true));
}

async function loadTemplatePartials() {
  const targets = collectTemplatePartialTargets();
  if (!targets.length) return;

  const results = await Promise.all(targets.map(async (target) => {
    const src = target.getAttribute('data-template-src');
    if (!src) return { ok: true };
    try {
      const response = await fetch(src, { cache: 'no-cache' });
      if (!response.ok) {
        return { ok: false, src, message: `${response.status} ${response.statusText || ''}`.trim() };
      }
      replaceTemplateTarget(target, await response.text());
      return { ok: true };
    } catch (error) {
      return { ok: false, src, message: error?.message || String(error) };
    }
  }));

  const failures = results.filter((item) => item && !item.ok);
  if (failures.length) {
    const detail = failures.map((item) => `${item.src}: ${item.message}`).join('; ');
    throw new Error(`页面模板加载失败: ${detail}`);
  }
}

// BUG-02 修复：删除此处重复且乱码的 createFieldMapping()
// 字段映射统一由 config.js 内部管理，此处不再重复定义

function createNotifyChannel() {
  return {
    type: 'webhook',
    enabled: true,
    config: {},
    configText: '{}',
  };
}

const app = createApp({
  data() {
    return {
      isAuthenticated: false,
      authToken: localStorage.getItem('auth_token') || '',
      currentUser: {},
      loginLoading: false,
      loginHint: '默认调试账号：admin / Admin123456',
      loginForm: { username: '', password: '' },
      activeMenu: 'dashboard',
      currentLogicalMenu: 'dashboard',
      menuGroups: FALLBACK_GROUPS,
      menuItems: FALLBACK_MENU,
      menuTree: buildMenuTree(FALLBACK_MENU, FALLBACK_GROUPS),
      openedMenuGroups: ['workbench'],
      menuRenderKey: 0,
      menuLoading: false,
      _handlingMenuSelect: false,
      currentTime: new Date().toLocaleString('zh-CN'),
      overallHealth: 'healthy',
      dataSourceType: 'oracle',
      dataSourceTypeBeforeSwitch: 'oracle',
      summary: {},
      dashboardToday: {
        date: '',
        total: 0,
        success: 0,
        inconsistency: 0,
        newCases: 0,
        pendingCases: 0,
        latestRunTime: '',
      },
      dashboardAlerts: [],
      dashboardKpis: {
        date: '',
        total: 0,
        todaySuccess: 0,
        successRate: 0,
        inconsistency: 0,
        highRisk: 0,
        pendingFeedback: 0,
        relaySuccessRate: null,
        relayRecentTotal: 0,
        viewRate: null,
        relayViewed: 0,
        closureRate: null,
      },
      dashboardDeptTop: [],
      dashboardEvents: [],
      dashboardRelay: { total: 0, success: 0, failed: 0, viewed: 0, unviewed: 0 },
      dashboardScheduler: { lastRunTime: '', nextRunTime: '' },
      dashboardLoading: false,
      healthComps: {},
      healthTime: '',
      pushForm: {
        date_mode: 'single',
        date_dimension: 'record_create_date',
        query_date: '',
        date_range: [],
        dept_filter: '',
        audit_type_codes: [],
        parallel_audit_types: false,
        dry_run: false,
        async_mode: true,
        parallel_workers: 1,
        empty_retry_max: 0,
        empty_retry_backoff_ms: 1000,
        target_strategy: 'round_robin',
        dify_targets: [],
      },
      pushQueryLoading: false,
      pushQueryRows: [],
      pushQuerySummary: null,
      pushQueryPage: 1,
      pushQueryPageSize: 50,
      pushQueryTotal: 0,
      selectedPushRecordKeys: [],
      selectedPushRecordMap: {},
      syncingPushTableSelection: false,
      pushQueryOnlyUnpushed: false,
      pushQueryKeyword: '',
      pushMatchDiagnosticsLoadingKeys: new Set(),
      pushMatchDiagnosticsVisible: false,
      pushMatchDiagnosticsResult: null,
      pushMatchFullTextVisible: false,
      pushMatchFullTextTitle: '',
      pushMatchFullTextContent: '',
      pendingPushAnchor: '',
      pushLoading: false,
      precheckLoading: false,
      precheckResult: null,
      precheckDialogVisible: false,
      pushResult: null,
      pushResultPage: 1,
      pushResultPageSize: 20,
      taskId: null,
      taskProg: null,
      taskPoller: null,
      taskPollCount: 0,
      // 3s * 3600 = 3 小时，覆盖大批量推送场景（3万+）
      maxTaskPoll: 3600,
      pushIndicator: {
        visible: false,
        status: 'idle',
        processed: 0,
        total: 0,
        success: 0,
        failed: 0,
        task_id: '',
        message: '',
      },
      pushProgressDrawerVisible: false,
      pushIndicatorHideTimer: null,
      visibilityHandlerBound: false,
      chartInstances: {},
      clockTimer: null,
      mobileMenuVisible: false,
      mobileMenuOpeneds: [],
      auditTab: 'logs',
      configTab: 'oracle',
      accessTab: 'users',
      logs: [],
      logTotal: 0,
      logPage: 1,
      logLimit: 20,
      selectedLogIds: [],
      skipReasonStats: { total_skipped: 0, items: [] },
      lf: { status: '', dept: '', date_from: '', date_to: '', patient_id: '', audit_type_code: '' },
      auditTypeOptions: [],
      logTimeWindow: null,
      logDetailVisible: false,
      logDetail: null,
      logDetailIndex: -1,
      reportVisible: false,
      reportData: null,
      fullTextVisible: false,
      fullTextTitle: '',
      fullTextContent: '',
      feedbackStats: {},
      feedbackList: [],
      feedbackSelectedRows: [],
      feedbackPage: 1,
      feedbackLimit: 20,
      feedbackTotal: 0,
      feedbackViewMode: 'pending',
      feedbackViewType: 'list',
      feedbackFilter: { status: 'pending', severity: '', audit_type_code: '', dept_id: null, days: 30, keyword: '' },
      feedbackDepartments: [],
      feedbackUsers: [],
      feedbackDetailVisible: false,
      feedbackDetailLoading: false,
      feedbackConfirmForm: { log_id: null, action: 'acknowledged', review_comment: '' },
      feedbackDetail: null,
      pqFilter: { patient_id: '', patient_name: '', admission_no: '', visit_number: '', dept: '', severity: '', status: '', date_range: [] },
      patientQcTab: 'patients',
      relayAlertLoading: false,
      relayAlertList: [],
      relayAlertTotal: 0,
      relayAlertPage: 1,
      relayAlertPageSize: 20,
      relayAlertFilter: { patient_id: '', status: '', viewed_flag: '' },
      pqLoading: false,
      pqList: [],
      pqPage: 1,
      pqPageSize: 20,
      pqTotal: 0,
      pqDetailVisible: false,
      pqDetailLoading: false,
      pqDetail: null,
      pqExpandedGroups: [],
      pqActionLoading: {},
      pqOtherReasonVisible: false,
      pqOtherReasonText: '',
      pqOtherReasonLogId: null,
      pqExportLoading: false,
      pqDetailSection: 'overview',
      pqEvidenceTab: 'medical',
      pqSelectedPushLogId: '',
      usersList: [],
      usersPage: 1,
      usersLimit: 20,
      usersTotal: 0,
      userDialogVisible: false,
      userDialogMode: 'create',
      userForm: { id: null, username: '', password: '', full_name: '', email: '', dept_id: null, role_id: null },
      userPasswordDialogVisible: false,
      userPasswordForm: { id: null, old_password: '', new_password: '' },
      rolesList: [],
      roleDialogVisible: false,
      roleDetail: null,
      menuCatalog: [],
      permissionsList: [],
      permissionFilter: { module: '' },
      permissionDialogVisible: false,
      permissionDialogMode: 'create',
      permissionForm: { id: null, name: '', description: '', module: '' },
      departmentsList: [],
      departmentDialogVisible: false,
      departmentDialogMode: 'create',
      departmentForm: { id: null, name: '', code: '', manager_id: null },
      auditTypesList: [],
      auditTypeDialogVisible: false,
      auditTypeDialogMode: 'create',
      auditTypeEditorTab: 'basic',
      auditTypeForm: createAuditTypeEditorState(),
      auditTypeCloneDialogVisible: false,
      auditTypeCloneForm: { source_code: '', new_code: '', new_name: '' },
      auditTypeSourceTestDialogVisible: false,
      auditTypeSourceTestForm: { code: '', query_date: '', date_dimension: 'query_date', dept_filter_text: '' },
      auditTypeSourceTestResult: null,
      auditTypeDifyTestDialogVisible: false,
      auditTypeDifyTestForm: { code: '', mr_txt_sample: '' },
      auditTypeDifyTestResult: null,
      auditTypeRuntimeSummary: null,
      auditTypeRuntimeSummaryLoading: false,
      auditTypeRuntimeSummaryError: '',
      auditTypeRuntimeWarningsExpanded: false,
      cfgLoading: false,
      oracleForm: {
        host: '', port: 1521, service_name: '', username: '', password: '', password_masked: '',
        instant_client_dir: '', query_sql: '', dept_sql: '',
        field_mapping: { patient_id: '患者ID', visit_number: '次数', patient_name: '患者姓名', dept: '所在科室名称', admission_no: '住院号' },
      },
      postgresqlForm: {
        host: 'localhost', port: 5432, database: '', username: '', password: '', password_masked: '',
        query_sql: '', dept_sql: '',
        field_mapping: { patient_id: '患者ID', visit_number: '次数', patient_name: '患者姓名', dept: '所在科室名称', admission_no: '住院号' },
      },
      difyForm: {
        base_url: '', api_key: '', api_key_masked: '', workflow_input_variable: 'mr_txt',
        workflow_output_key: 'aa', user_identifier: '', timeout_seconds: 90, extra_inputs_text: '{}', full_debug_log: false,
      },
      deptForm: { mode: 'include', listText: '' },
      deptCandidates: [],
      pushSettingsForm: { interval_ms: 500, max_retry: 3, batch_size: 50 },
      privacyMaskingForm: {
        enabled: false,
        mask_name: true,
        mask_id_card: true,
        mask_address: true,
        mask_phone: true,
      },
      notifyChannels: [],
      relayAlertForm: {
        enabled: false,
        base_url: '',
        endpoint: '/qc-record-alert',
        secret_key: '',
        secret_key_masked: '',
        timeout_seconds: 10,
        severity_levels: ['high'],
        source: '病历质控系统',
        max_retry: 3,
        retry_backoff_seconds: 5,
        payload_fields: [],
        available_sources: [],
      },
      showPayloadPreview: false,
      configTestResult: {},
      configStatusConfigured: {
        oracle: false,
        postgresql: false,
        dify: false,
        dept: false,
        push: false,
        privacy: false,
        notify: false,
        relayAlert: false,
        runtimeSummary: false,
      },
      runtimeSummary: null,
      runtimeSummaryLoading: false,
      runtimeSummaryError: '',
      schedulerState: {
        running: false,
        enabled: false,
        cron: '',
        schedule_mode: 'daily',
        daily_time: '06:00',
        interval_value: 10,
        interval_unit: 'minutes',
        audit_run_mode: 'daily_increment',
        audit_type_codes: [],
        dept_filter: [],
        next_run: '',
        last_run: null,
      },
      schedulerDischargeState: {
        running: false,
        enabled: false,
        cron: '0 11 * * *',
        schedule_mode: 'daily',
        daily_time: '11:00',
        interval_value: 10,
        interval_unit: 'minutes',
        audit_run_mode: 'discharge_final',
        audit_type_codes: ['progress_vs_nursing'],
        dept_filter: [],
        next_run: '',
        last_run: null,
      },
      hasDualScheduler: false,
      schedulerRuntimeSummary: null,
      schedulerRuntimeSummaryLoading: false,
      schedulerRuntimeSummaryError: '',
      schedulerRuntimeWarningsExpanded: false,
      schedulerHistory: [],
      schedulerDeptCandidates: [],
      schedulerDeptFilterText: '',
      schedulerDischargeDeptFilterText: '',
      schedulerTriggerDeptFilterText: '',
      schedulerTriggerForm: { query_date: '', audit_type_codes: [], dept_filter: [], audit_run_mode: 'daily_increment' },
      schedulerPage: 1,
      schedulerLimit: 10,
      schedulerActiveTab: 'daily',
      // ── 前置机推送人员配置 ──
      relayConfig: {
        enabled: false,
        severity_levels: [],
        base_url: '',
        nurse_heads: [],
        rulesTable: [],
        previewPushLogId: '',
        previewSeverity: 'high',
        previewing: false,
        previewResult: null,
        nhCode: '',
        nhName: '',
        nhLoading: false,
        nhResult: null,
      },
      debugForm: {
        input_mode: 'json',
        mr_txt: '',
        payload_json_text: '',
        user: 'debug-user',
        workflow_input_variable: '',
        workflow_output_key: '',
        extra_inputs_text: '{}',
      },
      debugResult: null,
      debouncedLoadLogsFn: null,
      debouncedLoadFeedbackFn: null,
      jsonErrors: {
        difyExtraInputs: '',
        debugExtraInputs: '',
        debugPayload: '',
        notifyConfig: {},
      },
    };
  },

  computed: {
    pageTitle() {
      const m = {
        dashboard: '🏠 仪表盘',
        audit: '📊 审计中心',
        push: '🚀 手动推送',
        'push-dify': '🚀 Dify 节点',
        logs: '📋 推送日志',
        stats: '📊 数据统计',
        feedback: '💬 质控反馈',
        'patient-qc': '🧑‍⚕️ 患者质控总览',
        'relay-alert-logs': '📨 前置机告警',
        'config-runtime': '🧭 运行总览',
        access: '👥 权限管理',
        users: '👥 用户管理',
        roles: '🧩 角色管理',
        permissions: '🔐 权限管理',
        departments: '🏥 科室管理',
        'audit-types': '🧩 审计类型管理',
        config: '⚙️ 系统配置',
        'cfg-oracle': '⚙️ Oracle 连接',
        'cfg-postgresql': '⚙️ PostgreSQL 连接',
        'cfg-dify': '⚙️ Dify 配置',
        'cfg-dept': '⚙️ 科室管理',
        'cfg-push': '⚙️ 推送参数',
        'cfg-privacy': '⚙️ 隐私脱敏',
        'cfg-notify': '⚙️ 通知渠道',
        scheduler: '⏰ 定时任务',
        relay: '📡 人员配置',
        health: '💚 系统健康',
        debug: '🔧 Dify 调试',
      };
      return m[this.currentLogicalMenu] || m[this.activeMenu] || '医保控费-医疗使用合理性智能审核系统';
    },

    accessTabTitle() {
      return {
        users: '用户管理',
        roles: '角色管理',
        permissions: '权限管理',
        departments: '科室管理',
      }[this.accessTab] || '权限管理';
    },

    availableRolePermissions() {
      if (!this.roleDetail) return [];
      const assigned = new Set((this.roleDetail.permissions || []).map((item) => item.id));
      return this.permissionsList.filter((item) => !assigned.has(item.id));
    },

    availableRoleMenus() {
      if (!this.roleDetail) return [];
      const assigned = new Set((this.roleDetail.menus || []).map((item) => item.id));
      return (this.menuCatalog || []).filter((item) => !assigned.has(item.id));
    },

    availableRoleDepartments() {
      if (!this.roleDetail) return [];
      const assigned = new Set((this.roleDetail.departments || []).map((item) => item.id));
      return (this.departmentsList || []).filter((item) => !assigned.has(item.id));
    },

    pushIndicatorTagType() {
      if (this.pushIndicator.status === 'completed') return 'success';
      if (this.pushIndicator.status === 'failed') return 'danger';
      if (this.pushIndicator.status === 'running') return 'warning';
      if (this.pushIndicator.status === 'cancelled') return 'info';
      return 'info';
    },

    pushIndicatorText() {
      const p = this.pushIndicator || {};
      if (p.status === 'running') {
        const done = Number(p.processed || 0);
        const total = Number(p.total || 0);
        return `🔄 推送中 ${done}/${total || '?'}`;
      }
      if (p.status === 'completed') {
        const success = Number(p.success || 0);
        const total = Number(p.total || 0);
        return `✅ 推送完成 ${success}/${total || success}`;
      }
      if (p.status === 'cancelled') {
        const done = Number(p.processed || 0);
        const total = Number(p.total || 0);
        return `⏹ 已停止 ${done}/${total || '?'}`;
      }
      if (p.status === 'failed') return '❌ 推送异常';
      return '';
    },

    feedbackKanbanColumns() {
      return [
        { key: 'pending', title: '待处理' },
        { key: 'acknowledged', title: '已确认' },
        { key: 'rectified', title: '已整改' },
        { key: 'closed', title: '已关闭' },
      ];
    },

    feedbackKanbanGroups() {
      const groups = {
        pending: [],
        acknowledged: [],
        rectified: [],
        closed: [],
      };
      (this.feedbackList || []).forEach((item) => {
        const status = this.normalizeFeedbackStatus(item?.feedback_status || item?.status);
        if (!groups[status]) groups[status] = [];
        groups[status].push(item);
      });
      return groups;
    },
  },

  methods: {
    ...authMethods,
    ...dashboardMethods,
    ...logsMethods,
    ...feedbackMethods,
    ...pushMethods,
    ...statsMethods,
    ...configMethods,
    ...schedulerMethods,

    // ── 前置机推送人员配置 ──
    async loadRelayConfig() {
      try {
        const r = await apiGet('/api/relay/receiver-config');
        const d = r.data;
        this.relayConfig.enabled = !!d.enabled;
        this.relayConfig.severity_levels = d.severity_levels || [];
        this.relayConfig.base_url = d.base_url || '';
        this.relayConfig.nurse_heads = d.nurse_heads || [];
        const rules = d.receiver_rules || {};
        this.relayConfig.rulesTable = Object.keys(rules).map(severity => {
          const r = rules[severity] || {};
          return {
            severity,
            attending: !!r.attending_doctor,
            creator: !!r.record_creator,
            nurse_head: !!r.nurse_head,
            fixed: (r.fixed_users || []).map(u => (typeof u === 'object' ? u.user_name || u.userid : u)),
            max: r.max_receivers || 0,
          };
        });
      } catch (e) {
        showApiError(e, '加载人员配置失败');
      }
    },
    async relayPreview() {
      const id = parseInt(this.relayConfig.previewPushLogId);
      if (!id) return ElMessage.warning('请输入推送日志ID');
      this.relayConfig.previewing = true;
      try {
        const r = await apiPost('/api/relay/preview-receivers', {
          push_log_id: id,
          severity: this.relayConfig.previewSeverity,
        });
        this.relayConfig.previewResult = r.data;
      } catch (e) {
        showApiError(e, '预览失败');
      } finally {
        this.relayConfig.previewing = false;
      }
    },
    async relayQueryNH() {
      this.relayConfig.nhLoading = true;
      try {
        const r = await apiGet('/api/relay/test-nurse-head', {
          params: {
            dept_code: this.relayConfig.nhCode || '',
            dept_name: this.relayConfig.nhName || '',
          },
        });
        this.relayConfig.nhResult = r.data;
      } catch (e) {
        showApiError(e, '查询失败');
      } finally {
        this.relayConfig.nhLoading = false;
      }
    },

    findMenuItem(menuId) {
      return flattenMenuTree(this.menuTree).find((item) => item.id === menuId);
    },

    isActiveMenuGroup(group) {
      const current = this.currentLogicalMenu || this.activeMenu;
      return (group.children || []).some((item) => item.id === current);
    },

    _getOpenGroupForMenu(menuId) {
      const item = flattenMenuTree(this.menuTree).find((i) => i.id === menuId);
      return item?.group ? [item.group] : ['workbench'];
    },

    handleMenuOpen(groupId) {
      this.openedMenuGroups = [groupId];
    },

    handleMenuClose(groupId) {
      this.openedMenuGroups = this.openedMenuGroups.filter((g) => g !== groupId);
    },

    handleMenuSelect(menuId) {
      const item = this.findMenuItem(menuId);
      const target = item?.target || {};
      this.currentLogicalMenu = menuId;
      this._handlingMenuSelect = true;

      if (item?.group) {
        this.openedMenuGroups = [item.group];
      }

      if (target.tab) {
        if (target.activeMenu === 'config') this.configTab = target.tab;
        if (target.activeMenu === 'access') this.accessTab = target.tab;
        if (target.activeMenu === 'audit') this.auditTab = target.tab;
        if (target.activeMenu === 'patient-qc') this.patientQcTab = target.tab;
      }

      this.switchMenu(target.activeMenu || menuId);
      this._handlingMenuSelect = false;
    },

    async loadCurrentMenu() {
      this.menuLoading = true;
      try {
        const r = await apiGet('/api/menu');
        const menu = Array.isArray(r.data?.menu) ? r.data.menu : [];
        const groups = Array.isArray(r.data?.groups) && r.data.groups.length
          ? r.data.groups : FALLBACK_GROUPS;
        this.menuGroups = groups;
        this.menuItems = menu;
        this.menuTree = buildMenuTree(this.menuItems, this.menuGroups);
        this.openedMenuGroups = this._getOpenGroupForMenu(this.currentLogicalMenu);
        this.menuRenderKey++;
      } catch (e) {
        console.warn('菜单加载失败，使用前端兜底菜单', e);
        this.menuGroups = FALLBACK_GROUPS;
        this.menuItems = SAFE_FALLBACK_MENU;
        this.menuTree = buildMenuTree(SAFE_FALLBACK_MENU, FALLBACK_GROUPS);
        this.openedMenuGroups = this._getOpenGroupForMenu(this.currentLogicalMenu);
        this.menuRenderKey++;
      } finally {
        this.menuLoading = false;
      }
    },

    ...adminMethods,
    ...auditTypeMethods,
    ...patientQcMethods,

    formatDateTime(dateTimeStr) {
      if (!dateTimeStr) return '--';
      return formatDateTimeFallback(dateTimeStr);
    },

    formatRelativeTime(dateTimeStr) {
      if (!dateTimeStr) return '--';
      if (typeof dayjs === 'function') {
        const d = dayjs(dateTimeStr);
        if (d?.isValid && d.isValid()) return d.fromNow();
      }
      const ts = new Date(dateTimeStr).getTime();
      if (Number.isNaN(ts)) return '--';
      const now = Date.now();
      const diff = ts - now;
      const abs = Math.abs(diff);
      const sec = Math.floor(abs / 1000);
      const min = Math.floor(sec / 60);
      const hour = Math.floor(min / 60);
      const day = Math.floor(hour / 24);
      const future = diff > 0;
      if (sec < 60) return future ? '即将' : '刚刚';
      if (min < 60) return future ? `约${min}分钟后` : `${min}分钟前`;
      if (hour < 24) return future ? `约${hour}小时后` : `${hour}小时前`;
      return future ? `约${day}天后` : `${day}天前`;
    },

    deptNameById(deptId) {
      if (!deptId) return '--';
      return this.feedbackDepartments.find((item) => item.id === deptId)?.name
        || this.departmentsList.find((item) => item.id === deptId)?.name
        || `#${deptId}`;
    },

    userNameById(userId) {
      if (!userId) return '--';
      const user = this.feedbackUsers.find((item) => item.id === userId)
        || this.usersList.find((item) => item.id === userId);
      return user ? (user.full_name || user.username) : `#${userId}`;
    },

    feedbackStatusLabel,
    feedbackStatusTagType,
    severityLabel,
    severityTagType,
    pushStatusLabel,
    statusTagType,
    auditStatusLabel,

    feedbackViewedLabel(row) {
      if (row?.is_viewed) return `已查看(${row.view_count || 1})`;
      return '未查看';
    },

    feedbackViewedTagType(row) {
      return row?.is_viewed ? 'success' : 'info';
    },

    feedbackRectifyProgressLabel(row) {
      if (row?.status === 'rectified') return '已整改完成';
      if (row?.rectification_clicked) return '整改处理中';
      return '未整改';
    },

    feedbackRectifyProgressTagType(row) {
      if (row?.status === 'rectified') return 'success';
      if (row?.rectification_clicked) return 'warning';
      return 'info';
    },

    getErrorMessage(e, fallback = '请求失败') {
      const detail = e?.response?.data?.detail;
      if (Array.isArray(detail) && detail.length) {
        const first = detail[0] || {};
        const loc = Array.isArray(first.loc) ? first.loc.join('.') : '';
        const msg = first.msg || '';
        return [loc ? `参数 ${loc}` : '', msg].filter(Boolean).join('：') || fallback;
      }
      if (typeof detail === 'string' && detail.trim()) return detail;
      if (detail && typeof detail === 'object') {
        try {
          return JSON.stringify(detail, null, 2);
        } catch (_) {
          return fallback;
        }
      }
      return e?.response?.data?.message || e?.message || fallback;
    },

    showApiError(e, fallback = '操作失败') {
      const msg = this.getErrorMessage(e, fallback);
      ElementPlus.ElMessage.error(msg);
      console.error(e);
      return msg;
    },

    debounce(fn, delay = 500) {
      let timer = null;
      return (...args) => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
      };
    },

    showFullText(title, content) {
      this.fullTextTitle = title || '完整内容';
      this.fullTextContent = content || '--';
      this.fullTextVisible = true;
    },

    textPreview(content, size = 60) {
      const text = String(content || '').trim();
      if (!text) return '--';
      if (text.length <= size) return text;
      return `${text.slice(0, size)}...`;
    },

    toDateInputString(dateLike) {
      const d = dateLike instanceof Date ? dateLike : new Date(dateLike);
      if (Number.isNaN(d.getTime())) return '';
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      return `${y}-${m}-${day}`;
    },

    switchAuditTab(tab) {
      this.auditTab = tab;
      if (tab === 'stats') {
        this.loadStats();
        return;
      }
      this.loadLogs(1);
    },

    // BUG-05 修复：switchMenu 中只执行一次加载，避免双重触发
    switchMenu(key) {
      const legacyAuditTabMap = { logs: 'logs', stats: 'stats', audit: this.auditTab || 'logs' };
      const legacyConfigTabMap = {
        'cfg-oracle': 'oracle',
        'cfg-postgresql': 'postgresql',
        'cfg-dify': 'dify',
        'cfg-dept': 'dept',
        'cfg-push': 'push',
        'cfg-privacy': 'privacy',
        'cfg-notify': 'notify',
        'cfg-runtime': 'runtime-summary',
        'config-runtime': 'runtime-summary',
      };
      const legacyAccessTabMap = {
        users: 'users',
        roles: 'roles',
        permissions: 'permissions',
        departments: 'departments',
      };
      const pushMenuAnchorMap = {
        'push-dify': 'dify-targets',
      };
      const patientQcTabMap = {
        'relay-alert-logs': 'relay-alerts',
      };

      if (legacyAuditTabMap[key]) {
        this.activeMenu = 'audit';
        this.auditTab = legacyAuditTabMap[key];
      } else if (legacyConfigTabMap[key]) {
        this.activeMenu = 'config';
        this.configTab = legacyConfigTabMap[key];
      } else if (legacyAccessTabMap[key]) {
        this.activeMenu = 'access';
        this.accessTab = legacyAccessTabMap[key];
      } else if (pushMenuAnchorMap[key]) {
        this.activeMenu = 'push';
        this.pendingPushAnchor = pushMenuAnchorMap[key];
      } else if (patientQcTabMap[key]) {
        this.activeMenu = 'patient-qc';
        this.patientQcTab = patientQcTabMap[key];
      } else {
        this.activeMenu = key;
        if (key !== 'push') {
          this.pendingPushAnchor = '';
        }
      }

      if (!Object.keys(legacyAuditTabMap).find((k) => k === key)
        && !Object.keys(legacyConfigTabMap).find((k) => k === key)
        && !Object.keys(legacyAccessTabMap).find((k) => k === key)
        && !Object.keys(pushMenuAnchorMap).find((k) => k === key)
        && !Object.keys(patientQcTabMap).find((k) => k === key)) {
        if (!this._handlingMenuSelect) {
          this.currentLogicalMenu = key;
        }
      }

      // 只用 normalizedKey（activeMenu 最终值）执行一次加载，不再 fallback 到原始 key
      const normalizedKey = this.activeMenu;
        const loaders = {
          dashboard: () => this.loadDashboard(),
          audit: () => this.switchAuditTab(this.auditTab || 'logs'),
          'audit-types': () => this.loadAuditTypesPage(),
          config: () => {
            this.loadConfigStatusSummary();
            this.switchConfigTab(this.configTab || 'oracle');
        },
        access: () => this.switchAccessTab(this.accessTab || 'users'),
        push: () => Promise.all([this.loadDataSource(), this.loadAuditTypeOptions()]),
        feedback: () => this.loadFeedbackPage(),
        'patient-qc': () => this.switchPatientQcTab(this.patientQcTab || 'patients'),
        health: () => this.loadHealth(),
        scheduler: () => Promise.all([this.loadAuditTypeOptions(), this.loadSchedulerPage()]),
        relay: () => this.loadRelayConfig(),
        debug: () => this.resetDebugPage(),
      };
      if (loaders[normalizedKey]) {
        loaders[normalizedKey]();
      }
      if (normalizedKey === 'push' && this.pendingPushAnchor) {
        const anchor = this.pendingPushAnchor;
        this.$nextTick(() => {
          if (anchor === 'dify-targets') {
            this.focusPushDifyTargetsSection();
          }
          this.pendingPushAnchor = '';
        });
      }
    },

    parsePossibleJson(value) {
      if (value === null || value === undefined || value === '') return null;
      if (typeof value === 'object') return value;
      try {
        return JSON.parse(value);
      } catch (e) {
        return null;
      }
    },

    normalizeAuditStatus(status) {
      const raw = String(status || '').toLowerCase();
      const map = {
        pass: 'pass',
        passed: 'pass',
        success: 'pass',
        ok: 'pass',
        fail: 'fail',
        failed: 'fail',
        error: 'fail',
        mismatch: 'fail',
        inconsistent: 'fail',
        warn: 'warn',
        warning: 'warn',
        medium: 'warn',
        high: 'fail',
        low: 'pass',
      };
      return map[raw] || (raw ? 'unknown' : 'unknown');
    },

    normalizeSeverity(level, fallbackStatus = 'unknown') {
      const raw = String(level || '').toLowerCase();
      if (['high', 'h', '严重', '高'].includes(raw)) return 'high';
      if (['medium', 'mid', 'm', '中'].includes(raw)) return 'medium';
      if (['low', 'l', '低'].includes(raw)) return 'low';
      if (fallbackStatus === 'fail') return 'high';
      if (fallbackStatus === 'warn') return 'medium';
      if (fallbackStatus === 'pass') return 'low';
      return 'unknown';
    },

    auditStatusIcon(status) {
      return { pass: '✅', fail: '❌', warn: '⚠️', unknown: '❓' }[status] || '❓';
    },

    auditStatusText(status) {
      return { pass: '通过', fail: '不一致', warn: '警告', unknown: '未知' }[status] || '未知';
    },

    auditSeverityText(level) {
      return { high: '高风险', medium: '中风险', low: '低风险', unknown: '未标注' }[level] || '未标注';
    },

    auditRiskLevel(score) {
      if (score >= 80) return 'high';
      if (score >= 50) return 'medium';
      if (score > 0) return 'low';
      return 'unknown';
    },

    parseAiResultStructured(logDetail) {
      const aiParsed = this.parsePossibleJson(logDetail?.ai_result);
      const responseParsed = this.parsePossibleJson(logDetail?.response_json);
      const root = aiParsed || responseParsed || {};
      const structuredRoot = root.result && typeof root.result === 'object' ? root.result : root;
      const summary = structuredRoot.audit_summary && typeof structuredRoot.audit_summary === 'object'
        ? structuredRoot.audit_summary
        : {};
      const sourceDimensions = Array.isArray(structuredRoot.dimensions)
        ? structuredRoot.dimensions
        : Array.isArray(structuredRoot['核查结果'])
          ? structuredRoot['核查结果']
          : [];
      const dimensions = sourceDimensions.map((item, index) => {
        const status = this.normalizeAuditStatus(item?.status || item?.['状态']);
        return {
          key: `${item?.dimension || item?.['维度'] || 'dimension'}-${index}`,
          dimension: item?.dimension || item?.['维度'] || item?.name || `维度${index + 1}`,
          status,
          severity: this.normalizeSeverity(item?.severity || item?.['严重度'], status),
          explanation: item?.explanation || item?.['说明'] || '',
        };
      });

      const focusItemsRaw = summary.focus_items || summary['重点关注项']
        || structuredRoot.focus_items || structuredRoot['重点关注项'] || [];
      const focusItems = Array.isArray(focusItemsRaw)
        ? focusItemsRaw.map((item) => String(item || '').trim()).filter(Boolean)
        : [];
      const overallConclusion = summary.overall_conclusion
        || summary['总体结论']
        || structuredRoot.overall_conclusion
        || structuredRoot['总体结论']
        || '';
      const qualitySummary = structuredRoot.reasoning_brief
        || summary.reasoning_brief
        || structuredRoot['整体质控描述']
        || structuredRoot.quality_summary
        || '';
      const riskScore = Number(
        summary.risk_score
          ?? summary['风险分值']
          ?? structuredRoot.risk_score
          ?? structuredRoot['风险分值']
          ?? logDetail?.risk_score
          ?? 0,
      ) || 0;

      return {
        dimensions,
        focusItems,
        overallConclusion,
        qualitySummary,
        riskScore,
        riskLevel: this.auditRiskLevel(riskScore),
      };
    },

    prettyJson(value) {
      if (!value) return '';
      if (typeof value === 'object') {
        try {
          return JSON.stringify(value, null, 2);
        } catch (e) {
          return String(value);
        }
      }
      if (typeof value !== 'string') return String(value);
      try {
        return JSON.stringify(JSON.parse(value), null, 2);
      } catch (e) {
        return value;
      }
    },

    formatTargetMetrics(metrics) {
      if (!metrics || typeof metrics !== 'object') return [];
      return Object.entries(metrics).map(([target_name, item]) => ({
        target_name,
        selected: Number(item?.selected || 0),
        success: Number(item?.success || 0),
        failed: Number(item?.failed || 0),
        empty: Number(item?.empty || 0),
      }));
    },

    renderAuditBlockValue(block) {
      const value = block?.value;
      if (value === null || value === undefined || value === '') return '无';
      if (Array.isArray(value)) return value.length ? value.join('，') : '无';
      if (typeof value === 'object') return this.prettyJson(value);
      return String(value);
    },

    renderAuditTableRows(block) {
      return Array.isArray(block?.value) ? block.value : [];
    },
  },

  mounted() {
    this.setupAxiosAuth();
    this.clockTimer = setInterval(() => {
      this.currentTime = new Date().toLocaleString('zh-CN');
    }, 1000);
    this.restoreSession();
    this.debouncedLoadLogsFn = this.debounce(() => this.loadLogs(1), 500);
    this.debouncedLoadFeedbackFn = this.debounce(() => this.loadFeedbackList(1), 500);
    window.addEventListener('resize', () => {
      document.querySelectorAll('[id$="Chart"]').forEach((el) => {
        try {
          echarts.getInstanceByDom(el)?.resize();
        } catch (e) {
          console.warn('图表 resize 失败', e);
        }
      });
    });
  },

  beforeUnmount() {
    this.stopTaskPolling();
    this.clearPushIndicatorTimer();
    if (this.clockTimer) {
      clearInterval(this.clockTimer);
      this.clockTimer = null;
    }
    Object.values(this.chartInstances || {}).forEach((chart) => {
      try {
        chart.dispose();
      } catch (e) {
        console.warn('图表销毁失败', e);
      }
    });
    this.chartInstances = {};
  },
});

app.use(ElementPlus);

// 注册全局方法到模板上下文，确保在所有插槽作用域中都能访问
app.config.globalProperties.severityLabel = severityLabel;
app.config.globalProperties.pushStatusLabel = pushStatusLabel;
app.config.globalProperties.feedbackStatusLabel = feedbackStatusLabel;
app.config.globalProperties.feedbackStatusTagType = feedbackStatusTagType;
app.config.globalProperties.statusTagType = statusTagType;
app.config.globalProperties.severityTagType = severityTagType;
app.config.globalProperties.auditStatusLabel = auditStatusLabel;
app.config.globalProperties.formatDateTime = function(v) {
  return formatDateTimeFallback(v);
};

loadTemplatePartials()
  .then(() => app.mount('#app'))
  .catch((error) => {
    console.error('页面模板加载失败', error);
    const root = document.getElementById('app');
    if (root) {
      root.innerHTML = '<div style="padding:24px;color:#b42318">页面模板加载失败，请刷新页面或联系管理员。</div>';
    }
  });
