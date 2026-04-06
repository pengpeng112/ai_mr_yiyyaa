const { createApp } = Vue;

// --- 全局辅助函数（避免 Vue 3 运行时模板编译在插槽作用域中找不到 methods 的问题） ---
function severityLabel(severity) {
  return { high: '高', medium: '中', low: '低' }[severity] || severity || '--';
}

function pushStatusLabel(status) {
  return { success: '成功', failed: '失败', skipped: '跳过', pending: '待处理', error: '错误' }[status] || status || '--';
}

function feedbackStatusLabel(status) {
  return { pending: '待处理', acknowledged: '已确认', rectified: '已整改', closed: '已关闭' }[status] || status || '--';
}

function feedbackStatusTagType(status) {
  return { pending: 'warning', acknowledged: 'primary', rectified: 'success', closed: 'info' }[status] || 'info';
}

function statusTagType(status) {
  return { success: 'success', failed: 'danger', skipped: 'info', pending: 'warning', error: 'danger' }[status] || 'info';
}

function severityTagType(severity) {
  return { high: 'danger', medium: 'warning', low: 'success' }[severity] || 'info';
}

function auditStatusLabel(status) {
  return { pass: '通过', fail: '不一致', warn: '警告', unknown: '未知' }[status] || status || '--';
}
// --- 全局辅助函数结束 ---

function createFieldMapping() {
  return {
    patient_id: '患者ID',
    visit_number: '次数',
    patient_name: '患者姓名',
    dept: '所在科室名称',
    admission_no: '住院号',
  };
}

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
      healthComps: {},
      healthTime: '',
      pushForm: { query_date: '', dept_filter: '', dry_run: false, async_mode: false },
      pushLoading: false,
      pushResult: null,
      taskId: null,
      taskProg: null,
      taskPoller: null,
      taskPollCount: 0,
      maxTaskPoll: 120,
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
      lf: { status: '', dept: '', date_from: '', date_to: '', patient_id: '' },
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
      feedbackPage: 1,
      feedbackLimit: 20,
      feedbackTotal: 0,
      feedbackViewMode: 'pending',
      feedbackViewType: 'list',
      feedbackFilter: { status: 'pending', severity: '', dept_id: null, days: 30, keyword: '' },
      feedbackDepartments: [],
      feedbackUsers: [],
      feedbackDetailVisible: false,
      feedbackDetailLoading: false,
      feedbackConfirmForm: { log_id: null, action: 'acknowledged', review_comment: '' },
      feedbackDetail: null,
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
      permissionsList: [],
      permissionFilter: { module: '' },
      permissionDialogVisible: false,
      permissionDialogMode: 'create',
      permissionForm: { id: null, name: '', description: '', module: '' },
      departmentsList: [],
      departmentDialogVisible: false,
      departmentDialogMode: 'create',
      departmentForm: { id: null, name: '', code: '', manager_id: null },
      cfgLoading: false,
      oracleForm: {
        host: '', port: 1521, service_name: '', username: '', password: '', password_masked: '',
        instant_client_dir: '', query_sql: '', dept_sql: '', field_mapping: createFieldMapping(),
      },
      postgresqlForm: {
        host: 'localhost', port: 5432, database: '', username: '', password: '', password_masked: '',
        query_sql: '', dept_sql: '', field_mapping: createFieldMapping(),
      },
      difyForm: {
        base_url: '', api_key: '', api_key_masked: '', workflow_input_variable: 'mr_txt',
        workflow_output_key: 'aa', user_identifier: '', timeout_seconds: 90, extra_inputs_text: '{}',
      },
      deptForm: { mode: 'include', listText: '' },
      deptCandidates: [],
      pushSettingsForm: { interval_ms: 500, max_retry: 3, batch_size: 50 },
      notifyChannels: [],
      configTestResult: {},
      configStatusConfigured: {
        oracle: false,
        postgresql: false,
        dify: false,
        dept: false,
        push: false,
        notify: false,
      },
      schedulerState: {
        running: false,
        enabled: false,
        cron: '',
        schedule_mode: 'daily',
        daily_time: '06:00',
        interval_value: 10,
        interval_unit: 'minutes',
        next_run: '',
        last_run: null,
      },
      schedulerHistory: [],
      schedulerTriggerForm: { query_date: '' },
      schedulerPage: 1,
      schedulerLimit: 10,
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
        push: '🚀 数据推送',
        logs: '📋 推送日志',
        stats: '📊 数据统计',
        feedback: '💬 质控反馈',
        access: '👥 权限管理',
        users: '👥 用户管理',
        roles: '🧩 角色管理',
        permissions: '🔐 权限管理',
        departments: '🏥 科室管理',
        config: '⚙️ 系统配置',
        'cfg-oracle': '⚙️ Oracle 连接',
        'cfg-postgresql': '⚙️ PostgreSQL 连接',
        'cfg-dify': '⚙️ Dify 配置',
        'cfg-dept': '⚙️ 科室管理',
        'cfg-push': '⚙️ 推送参数',
        'cfg-notify': '⚙️ 通知渠道',
        scheduler: '⏰ 定时任务',
        health: '💚 系统健康',
        debug: '🔧 Dify 调试',
      };
      return m[this.activeMenu] || '医疗记录一致性审计系统';
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

    pushIndicatorTagType() {
      if (this.pushIndicator.status === 'completed') return 'success';
      if (this.pushIndicator.status === 'failed') return 'danger';
      if (this.pushIndicator.status === 'running') return 'warning';
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
    formatDateTime(dateTimeStr) {
      if (!dateTimeStr) return '--';
      // 将 ISO 格式时间（2026-04-05T14:30:11）转换为中文友好格式（2026-04-05 14:30:11）
      return String(dateTimeStr).replace('T', ' ').split('.')[0];
    },

    setupAxiosAuth() {
      axios.interceptors.request.use((config) => {
        const token = this.authToken || localStorage.getItem('auth_token');
        if (token) {
          config.headers = config.headers || {};
          config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
      });

      axios.interceptors.response.use(
        (response) => response,
        (error) => {
          if (!error?.response) {
            ElementPlus.ElMessage.error('网络连接失败，请检查服务是否可达');
          } else if (error.response.status === 401) {
            this.clearAuthState();
            this.loginHint = '登录已失效，请重新登录。';
          } else if (error.response.status >= 500) {
            ElementPlus.ElMessage.error('服务器内部错误，请稍后重试');
          }
          return Promise.reject(error);
        },
      );
    },

    isValidJwtToken(token) {
      if (!token || typeof token !== 'string') return false;
      return /^[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+$/.test(token);
    },

    clearAuthState() {
      this.isAuthenticated = false;
      this.authToken = '';
      this.currentUser = {};
      localStorage.removeItem('auth_token');
      this.clearPushIndicator();
    },

    async login() {
      if (!this.loginForm.username || !this.loginForm.password) {
        ElementPlus.ElMessage.warning('请输入用户名和密码');
        return;
      }
      this.loginLoading = true;
      try {
        const res = await axios.post('/api/users/login', this.loginForm);
        this.authToken = res.data.access_token || '';
        if (!this.isValidJwtToken(this.authToken)) {
          throw new Error('登录返回的 Token 格式无效');
        }
        localStorage.setItem('auth_token', this.authToken);
        this.currentUser = res.data.user || {};
        this.isAuthenticated = true;
        this.loginForm.password = '';
        this.loginHint = '登录成功';
        ElementPlus.ElMessage.success('登录成功');
        await this.bootstrapApp();
      } catch (e) {
        this.clearAuthState();
        this.loginHint = this.getErrorMessage(e, '登录失败');
        ElementPlus.ElMessage.error(this.loginHint);
      } finally {
        this.loginLoading = false;
      }
    },

    async restoreSession() {
      if (!this.authToken || !this.isValidJwtToken(this.authToken)) {
        this.clearAuthState();
        return;
      }
      try {
        const res = await axios.get('/api/users/me');
        this.currentUser = res.data || {};
        this.isAuthenticated = true;
        await this.bootstrapApp();
      } catch (e) {
        this.clearAuthState();
      }
    },

    async logout() {
      try {
        if (this.authToken) await axios.post('/api/users/logout');
      } catch (e) {
        this.showApiError(e, '退出登录时发生异常');
      }
      this.clearAuthState();
      this.loginHint = '已退出，请重新登录。';
      this.activeMenu = 'dashboard';
    },

    async bootstrapApp() {
      await this.loadDataSource();
      await this.loadDashboard();
    },

    pct(v) {
      return v !== undefined && v !== null && v !== '' ? Number(v).toFixed(1) + '%' : '--';
    },

    cname(k) {
      return {
        oracle: 'Oracle 数据库',
        postgresql: 'PostgreSQL 数据库',
        dify: 'Dify Workflow',
        scheduler: 'APScheduler 调度器',
      }[k] || k;
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
      return e?.response?.data?.detail || e?.response?.data?.message || e?.message || fallback;
    },

    showApiError(e, fallback = '操作失败') {
      const msg = this.getErrorMessage(e, fallback);
      ElementPlus.ElMessage.error(msg);
      console.error(e);
      return msg;
    },

    clearPushIndicatorTimer() {
      if (this.pushIndicatorHideTimer) {
        clearTimeout(this.pushIndicatorHideTimer);
        this.pushIndicatorHideTimer = null;
      }
    },

    clearPushIndicator() {
      this.clearPushIndicatorTimer();
      this.pushProgressDrawerVisible = false;
      this.pushIndicator = {
        visible: false,
        status: 'idle',
        processed: 0,
        total: 0,
        success: 0,
        failed: 0,
        task_id: '',
        message: '',
      };
    },

    schedulePushIndicatorHide() {
      this.clearPushIndicatorTimer();
      this.pushIndicatorHideTimer = setTimeout(() => {
        if (this.pushIndicator.status === 'completed') {
          this.clearPushIndicator();
        }
      }, 3000);
    },

    markPushIndicatorRunning(payload = {}) {
      this.clearPushIndicatorTimer();
      this.pushIndicator = {
        visible: true,
        status: 'running',
        processed: Number(payload.processed || 0),
        total: Number(payload.total || 0),
        success: Number(payload.success || 0),
        failed: Number(payload.failed || 0),
        task_id: payload.task_id || this.taskId || '',
        message: payload.message || '',
      };
    },

    markPushIndicatorCompleted(payload = {}) {
      this.pushIndicator = {
        visible: true,
        status: 'completed',
        processed: Number(payload.processed ?? payload.total ?? 0),
        total: Number(payload.total || 0),
        success: Number(payload.success ?? payload.processed ?? payload.total ?? 0),
        failed: Number(payload.failed || 0),
        task_id: payload.task_id || this.taskId || '',
        message: payload.message || '',
      };
      this.schedulePushIndicatorHide();
    },

    markPushIndicatorFailed(payload = {}) {
      this.clearPushIndicatorTimer();
      this.pushIndicator = {
        visible: true,
        status: 'failed',
        processed: Number(payload.processed || 0),
        total: Number(payload.total || 0),
        success: Number(payload.success || 0),
        failed: Number(payload.failed || 0),
        task_id: payload.task_id || this.taskId || '',
        message: payload.message || '推送任务执行失败',
      };
    },

    syncPushIndicatorWithTask(taskData = {}) {
      const status = String(taskData.status || '').toLowerCase();
      if (status === 'completed') {
        this.markPushIndicatorCompleted({
          processed: taskData.processed,
          total: taskData.total,
          success: taskData.success,
          failed: taskData.failed,
          task_id: taskData.task_id,
        });
        return;
      }
      if (status === 'failed' || status === 'not_found') {
        this.markPushIndicatorFailed({
          processed: taskData.processed,
          total: taskData.total,
          success: taskData.success,
          failed: taskData.failed,
          task_id: taskData.task_id,
          message: status === 'not_found' ? '任务状态未找到' : '推送任务执行失败',
        });
        return;
      }
      this.markPushIndicatorRunning({
        processed: taskData.processed,
        total: taskData.total,
        success: taskData.success,
        failed: taskData.failed,
        task_id: taskData.task_id,
      });
    },

    openPushProgressDrawer() {
      this.pushProgressDrawerVisible = true;
    },

    normalizeFeedbackStatus(status) {
      const value = String(status || '').toLowerCase();
      if (['pending', '待处理'].includes(value)) return 'pending';
      if (['acknowledged', 'confirmed', '已确认'].includes(value)) return 'acknowledged';
      if (['rectified', 'fixed', '已整改'].includes(value)) return 'rectified';
      if (['closed', 'done', '已关闭'].includes(value)) return 'closed';
      return 'pending';
    },

    switchFeedbackViewType(type) {
      this.feedbackViewType = type === 'kanban' ? 'kanban' : 'list';
    },

    feedbackKanbanCount(status) {
      return (this.feedbackKanbanGroups?.[status] || []).length;
    },

    feedbackKanbanTime(row) {
      return this.formatDateTime(row?.reviewed_at || row?.push_time || row?.query_date);
    },

    debounce(fn, delay = 500) {
      let timer = null;
      return (...args) => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
      };
    },

    async onDataSourceChange(newType) {
      const previous = this.dataSourceTypeBeforeSwitch || this.dataSourceType;
      try {
        await ElementPlus.ElMessageBox.confirm(
          `确认将数据源切换为 ${newType === 'postgresql' ? 'PostgreSQL' : 'Oracle'}？`,
          '切换数据源',
          {
            confirmButtonText: '确认切换',
            cancelButtonText: '取消',
            type: 'warning',
          },
        );
        await this.saveDataSource();
        this.dataSourceTypeBeforeSwitch = this.dataSourceType;
      } catch (e) {
        this.dataSourceType = previous;
      }
    },

    onLogFilterChange() {
      this.logTimeWindow = null;
      this.logPage = 1;
      this.loadLogs(1);
    },

    onLogFilterInput() {
      this.logTimeWindow = null;
      if (!this.debouncedLoadLogsFn) {
        this.debouncedLoadLogsFn = this.debounce(() => this.loadLogs(1), 500);
      }
      this.logPage = 1;
      this.debouncedLoadLogsFn();
    },

    onFeedbackSearchInput() {
      if (!this.debouncedLoadFeedbackFn) {
        this.debouncedLoadFeedbackFn = this.debounce(() => this.loadFeedbackList(1), 500);
      }
      this.feedbackPage = 1;
      this.debouncedLoadFeedbackFn();
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

    schedulerSuccessRate(row) {
      const total = Number(row?.total_records || 0);
      const success = Number(row?.success_count || 0);
      if (!total) return null;
      return Math.max(0, Math.min(100, (success / total) * 100));
    },

    schedulerSuccessRateLabel(row) {
      const rate = this.schedulerSuccessRate(row);
      if (rate === null) return '--';
      const success = Number(row?.success_count || 0);
      const total = Number(row?.total_records || 0);
      return `${success}/${total} (${rate.toFixed(1)}%)`;
    },

    clearLogTimeWindow() {
      this.logTimeWindow = null;
      this.loadLogs(1);
    },

    parseLogTime(log) {
      const value = log?.push_time || log?.run_time || '';
      const ts = new Date(value).getTime();
      return Number.isNaN(ts) ? 0 : ts;
    },

    buildSchedulerWindow(runTime) {
      const base = new Date(runTime);
      if (Number.isNaN(base.getTime())) return null;
      const from = new Date(base.getTime() - 60 * 60 * 1000);
      const to = new Date(base.getTime() + 60 * 60 * 1000);
      return {
        startMs: from.getTime(),
        endMs: to.getTime(),
        dateFrom: this.toDateInputString(from),
        dateTo: this.toDateInputString(to),
        label: `${this.formatDateTime(from.toISOString())} ~ ${this.formatDateTime(to.toISOString())}`,
      };
    },

    async viewSchedulerHistoryLogs(row) {
      const runTime = row?.run_time || row?.started_at || row?.created_at;
      const window = this.buildSchedulerWindow(runTime);
      if (!window) {
        ElementPlus.ElMessage.warning('执行时间缺失，无法定位日志');
        return;
      }

      this.lf = {
        status: '',
        dept: '',
        date_from: window.dateFrom,
        date_to: window.dateTo,
        patient_id: '',
      };
      this.logTimeWindow = window;
      this.logLimit = 200;
      this.logPage = 1;
      this.activeMenu = 'audit';
      this.auditTab = 'logs';
      await this.loadLogs(1);
      ElementPlus.ElMessage.success('已定位到该次执行前后 1 小时日志');
    },

    parseJsonText(text, fieldName) {
      const raw = (text || '').trim();
      if (!raw) return {};
      try {
        return JSON.parse(raw);
      } catch (e) {
        throw new Error(`${fieldName} 不是合法 JSON`);
      }
    },

    validateJsonRealtime(text, targetKey, label, allowEmpty = true) {
      const raw = String(text || '').trim();
      if (!raw) {
        this.jsonErrors[targetKey] = allowEmpty ? '' : `${label}不能为空`;
        return;
      }
      try {
        JSON.parse(raw);
        this.jsonErrors[targetKey] = '';
      } catch (e) {
        this.jsonErrors[targetKey] = `${label} JSON 格式错误: ${e.message}`;
      }
    },

    validateNotifyJsonRealtime(index, text) {
      const raw = String(text || '').trim();
      const next = { ...(this.jsonErrors.notifyConfig || {}) };
      if (!raw) {
        next[index] = '';
      } else {
        try {
          JSON.parse(raw);
          next[index] = '';
        } catch (e) {
          next[index] = `通知渠道 JSON 格式错误: ${e.message}`;
        }
      }
      this.jsonErrors.notifyConfig = next;
    },

    onDifyExtraInputsInput() {
      this.validateJsonRealtime(this.difyForm.extra_inputs_text, 'difyExtraInputs', '额外参数');
    },

    onDebugExtraInputsInput() {
      this.validateJsonRealtime(this.debugForm.extra_inputs_text, 'debugExtraInputs', '调试额外参数');
    },

    onDebugPayloadInput() {
      this.validateJsonRealtime(this.debugForm.payload_json_text, 'debugPayload', '结构化调试 JSON');
    },

    onNotifyConfigInput(index) {
      const item = this.notifyChannels[index] || {};
      this.validateNotifyJsonRealtime(index, item.configText || '');
    },

    normalizeDeptList(text) {
      return (text || '')
        .split(/\r?\n|,|，/)
        .map((item) => item.trim())
        .filter(Boolean);
    },

    updateTestResult(key, payload) {
      this.configTestResult = { ...this.configTestResult, [key]: payload };
    },

    switchAuditTab(tab) {
      this.auditTab = tab;
      if (tab === 'stats') {
        this.loadStats();
        return;
      }
      this.loadLogs(1);
    },

    switchConfigTab(tab) {
      this.configTab = tab;
      const loaders = {
        oracle: () => this.loadOracleConfig(),
        postgresql: () => this.loadPostgresqlConfig(),
        dify: () => this.loadDifyConfig(),
        dept: () => this.loadDeptConfig(),
        push: () => this.loadPushSettings(),
        notify: () => this.loadNotifyConfig(),
      };
      if (loaders[tab]) loaders[tab]();
    },

    normalizeConfigTabName(name) {
      if (name === 'data-source') return this.dataSourceType === 'postgresql' ? 'postgresql' : 'oracle';
      return String(name || '');
    },

    configTabStatus(tabName) {
      const tab = this.normalizeConfigTabName(tabName);
      const configured = !!this.configStatusConfigured[tab];
      if (!configured) return 'missing';
      if (this.configTabTested(tab)) return 'ready';
      return 'untested';
    },

    configTabTested(tab) {
      if (tab === 'oracle') return this.configTestResult?.oracle?.status === 'up';
      if (tab === 'postgresql') return this.configTestResult?.postgresql?.status === 'up';
      if (tab === 'dify') return this.configTestResult?.dify?.status === 'up';
      if (tab === 'notify') {
        const keys = Object.keys(this.configTestResult || {}).filter((key) => key.startsWith('notify-'));
        return keys.some((key) => this.configTestResult?.[key]?.success);
      }
      if (tab === 'dept' || tab === 'push') return false;
      return false;
    },

    configStatusText(tabName) {
      const state = this.configTabStatus(tabName);
      if (state === 'ready') return '🟢 已配置并测试通过';
      if (state === 'untested') return '🟡 已配置未测试';
      return '🔴 未配置';
    },

    configStatusTagType(tabName) {
      const state = this.configTabStatus(tabName);
      if (state === 'ready') return 'success';
      if (state === 'untested') return 'warning';
      return 'danger';
    },

    isOracleConfigured(data) {
      return !!(data?.host && data?.service_name && data?.username && (data?.password_masked || data?.password));
    },

    isPostgresqlConfigured(data) {
      return !!(data?.host && data?.database && data?.username && (data?.password_masked || data?.password));
    },

    isDifyConfigured(data) {
      return !!(data?.base_url && (data?.api_key_masked || data?.api_key) && data?.workflow_input_variable && data?.workflow_output_key);
    },

    isDeptConfigured(data) {
      return Array.isArray(data?.list) && data.list.length > 0;
    },

    isPushConfigured(data) {
      return Number(data?.interval_ms) > 0 && Number(data?.max_retry) >= 0 && Number(data?.batch_size) > 0;
    },

    isNotifyConfigured(data) {
      return Array.isArray(data?.channels) && data.channels.length > 0;
    },

    async loadConfigStatusSummary() {
      try {
        const [oracleR, postgresqlR, difyR, deptR, pushR, notifyR] = await Promise.all([
          axios.get('/api/config/oracle').catch(() => ({ data: {} })),
          axios.get('/api/config/postgresql').catch(() => ({ data: {} })),
          axios.get('/api/config/dify').catch(() => ({ data: {} })),
          axios.get('/api/config/departments').catch(() => ({ data: {} })),
          axios.get('/api/config/push').catch(() => ({ data: {} })),
          axios.get('/api/config/notify').catch(() => ({ data: {} })),
        ]);
        this.configStatusConfigured = {
          oracle: this.isOracleConfigured(oracleR.data || {}),
          postgresql: this.isPostgresqlConfigured(postgresqlR.data || {}),
          dify: this.isDifyConfigured(difyR.data || {}),
          dept: this.isDeptConfigured(deptR.data || {}),
          push: this.isPushConfigured(pushR.data || {}),
          notify: this.isNotifyConfigured(notifyR.data || {}),
        };
      } catch (e) {
        this.showApiError(e, '加载配置状态失败');
      }
    },

    switchAccessTab(tab) {
      this.accessTab = tab;
      const loaders = {
        users: () => this.loadUsersPage(),
        roles: () => this.loadRolesPage(),
        permissions: () => this.loadPermissionsPage(),
        departments: () => this.loadDepartmentsPage(),
      };
      if (loaders[tab]) loaders[tab]();
    },

    switchMenu(key) {
      const legacyAuditTabMap = { logs: 'logs', stats: 'stats', audit: this.auditTab || 'logs' };
      const legacyConfigTabMap = {
        'cfg-oracle': 'oracle',
        'cfg-postgresql': 'postgresql',
        'cfg-dify': 'dify',
        'cfg-dept': 'dept',
        'cfg-push': 'push',
        'cfg-notify': 'notify',
      };
      const legacyAccessTabMap = {
        users: 'users',
        roles: 'roles',
        permissions: 'permissions',
        departments: 'departments',
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
      } else {
        this.activeMenu = key;
      }

      const loaders = {
        dashboard: () => this.loadDashboard(),
        audit: () => this.switchAuditTab(this.auditTab || 'logs'),
        config: () => {
          this.loadConfigStatusSummary();
          this.switchConfigTab(this.configTab || 'oracle');
        },
        access: () => this.switchAccessTab(this.accessTab || 'users'),
        push: () => this.loadDataSource(),
        logs: () => this.loadLogs(1),
        stats: () => this.loadStats(),
        feedback: () => this.loadFeedbackPage(),
        users: () => this.loadUsersPage(),
        roles: () => this.loadRolesPage(),
        permissions: () => this.loadPermissionsPage(),
        departments: () => this.loadDepartmentsPage(),
        health: () => this.loadHealth(),
        'cfg-oracle': () => this.loadOracleConfig(),
        'cfg-postgresql': () => this.loadPostgresqlConfig(),
        'cfg-dify': () => this.loadDifyConfig(),
        'cfg-dept': () => this.loadDeptConfig(),
        'cfg-push': () => this.loadPushSettings(),
        'cfg-notify': () => this.loadNotifyConfig(),
        scheduler: () => this.loadSchedulerPage(),
        debug: () => this.resetDebugPage(),
      };
      const normalizedKey = this.activeMenu;
      if (loaders[normalizedKey]) {
        loaders[normalizedKey]();
      } else if (loaders[key]) {
        loaders[key]();
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
        : Array.isArray(structuredRoot.核查结果)
          ? structuredRoot.核查结果
          : [];
      const dimensions = sourceDimensions.map((item, index) => {
        const status = this.normalizeAuditStatus(item?.status || item?.状态);
        return {
          key: `${item?.dimension || item?.维度 || 'dimension'}-${index}`,
          dimension: item?.dimension || item?.维度 || item?.name || `维度${index + 1}`,
          status,
          severity: this.normalizeSeverity(item?.severity || item?.严重度, status),
          explanation: item?.explanation || item?.说明 || '',
        };
      });

      const focusItemsRaw = summary.focus_items || summary.重点关注项 || structuredRoot.focus_items || structuredRoot.重点关注项 || [];
      const focusItems = Array.isArray(focusItemsRaw)
        ? focusItemsRaw.map((item) => String(item || '').trim()).filter(Boolean)
        : [];
      const overallConclusion = summary.overall_conclusion
        || summary.总体结论
        || structuredRoot.overall_conclusion
        || structuredRoot.总体结论
        || '';
      const qualitySummary = structuredRoot.reasoning_brief
        || summary.reasoning_brief
        || structuredRoot.整体质控描述
        || structuredRoot.quality_summary
        || '';
      const riskScore = Number(
        summary.risk_score
          ?? summary.风险分值
          ?? structuredRoot.risk_score
          ?? structuredRoot.风险分值
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

    async loadDataSource() {
      try {
        const r = await axios.get('/api/config/data-source');
        this.dataSourceType = r.data.type || 'oracle';
        this.dataSourceTypeBeforeSwitch = this.dataSourceType;
      } catch (e) {
        this.showApiError(e, '加载数据源失败');
      }
    },

    async saveDataSource() {
      try {
        await axios.post('/api/config/data-source', { type: this.dataSourceType });
        ElementPlus.ElMessage.success('数据源已切换');
      } catch (e) {
        this.showApiError(e, '切换数据源失败');
      }
    },

    todayDateString() {
      const now = new Date();
      const y = now.getFullYear();
      const m = String(now.getMonth() + 1).padStart(2, '0');
      const d = String(now.getDate()).padStart(2, '0');
      return `${y}-${m}-${d}`;
    },

    parseTimeValue(value) {
      if (!value) return 0;
      const ts = new Date(value).getTime();
      return Number.isNaN(ts) ? 0 : ts;
    },

    extractSchedulerLastRun(statusPayload = {}) {
      const lastRun = statusPayload?.last_run;
      if (!lastRun) return '';
      if (typeof lastRun === 'string') return lastRun;
      if (typeof lastRun === 'object') {
        return lastRun.run_time || lastRun.time || lastRun.completed_at || '';
      }
      return '';
    },

    async openDashboardAlert(item) {
      const logId = item?.id;
      if (!logId) return;
      await this.switchMenu('audit');
      this.auditTab = 'logs';
      await this.viewLogDetail(logId);
    },

    openDashboardFeedback(mode = 'all') {
      this.switchMenu('feedback');
      if (mode === 'pending') {
        this.switchFeedbackView('pending');
      } else {
        this.switchFeedbackView('all');
      }
    },

    async loadDashboard() {
      try {
        const today = this.todayDateString();
        const [s, h, todayLogsR, pendingFeedbackR, schedulerStatusR, recentLogsR] = await Promise.all([
          axios.get('/api/stats/summary'),
          axios.get('/api/health'),
          axios.get('/api/logs', { params: { page: 1, limit: 300, date_from: today, date_to: today } }).catch(() => ({ data: { items: [] } })),
          axios.get('/api/qc/feedback/cases', { params: { page: 1, limit: 1, status: 'pending', days: 30 } }).catch(() => ({ data: { total: 0 } })),
          axios.get('/api/scheduler/status').catch(() => ({ data: {} })),
          axios.get('/api/logs', { params: { page: 1, limit: 120 } }).catch(() => ({ data: { items: [] } })),
        ]);
        this.summary = s.data || {};
        this.healthComps = h.data.components || {};
        this.overallHealth = h.data.status || 'healthy';

        const todayLogs = todayLogsR.data?.items || [];
        const todayTotal = todayLogs.length;
        const todaySuccess = todayLogs.filter((item) => item.status === 'success').length;
        const todayInconsistency = todayLogs.filter((item) => Number(item.inconsistency || 0) === 1).length;
        const pendingCases = Number(pendingFeedbackR.data?.total || 0) || 0;
        const latestRunRaw = this.extractSchedulerLastRun(schedulerStatusR.data || {});
        const latestRunTime = latestRunRaw ? this.formatDateTime(latestRunRaw) : '--';

        const recentLogs = recentLogsR.data?.items || [];
        const alerts = recentLogs
          .filter((item) => Number(item.inconsistency || 0) === 1 && (item.severity === 'high' || Number(item.risk_score || 0) >= 80))
          .slice(0, 5)
          .map((item) => ({
            id: item.id,
            patient_name: item.patient_name || '--',
            patient_id: item.patient_id || '--',
            dept: item.dept || '--',
            risk_score: Number(item.risk_score || 0),
            severity: item.severity || '',
            push_time: this.formatDateTime(item.push_time),
            raw_push_time: item.push_time || '',
            status_text: this.severityLabel(item.severity || 'high'),
          }))
          .sort((a, b) => this.parseTimeValue(b.raw_push_time) - this.parseTimeValue(a.raw_push_time));

        this.dashboardToday = {
          date: today,
          total: todayTotal,
          success: todaySuccess,
          inconsistency: todayInconsistency,
          newCases: todayInconsistency,
          pendingCases,
          latestRunTime,
        };
        this.dashboardAlerts = alerts;
      } catch (e) {
        this.showApiError(e, '加载仪表盘失败');
      }
      this.$nextTick(() => this.renderDash());
    },

    async renderDash() {
      try {
        const r = await axios.get('/api/stats/daily', { params: { days: 30 } });
        const el = document.getElementById('dashChart');
        if (!el) return;
        const chart = this.getChart('dashChart');
        if (!chart) return;
        const d = r.data.items || r.data || [];
        chart.setOption({
          tooltip: { trigger: 'axis' },
          legend: { data: ['总数', '成功', '失败'], bottom: 0 },
          grid: { left: 36, right: 10, top: 10, bottom: 40 },
          xAxis: { type: 'category', data: d.map((i) => i.date), axisLabel: { rotate: 40, fontSize: 10 } },
          yAxis: { type: 'value' },
          series: [
            { name: '总数', type: 'line', data: d.map((i) => i.total), smooth: true, itemStyle: { color: '#1677ff' } },
            { name: '成功', type: 'line', data: d.map((i) => i.success), smooth: true, itemStyle: { color: '#52c41a' } },
            { name: '失败', type: 'line', data: d.map((i) => i.failed), smooth: true, itemStyle: { color: '#ff4d4f' } },
          ],
        });
      } catch (e) {
        this.showApiError(e, '加载趋势图失败');
      }
    },

    async loadStats() {
      try {
        const s = await axios.get('/api/stats/summary');
        this.summary = s.data || {};
      } catch (e) {
        this.showApiError(e, '加载统计摘要失败');
      }

      this.$nextTick(async () => {
        try {
          const [dr, sr, br, dimR, monthlyR, anomalyDeptR, anomalyPatientR] = await Promise.all([
            axios.get('/api/stats/daily', { params: { days: 30 } }),
            axios.get('/api/stats/severity'),
            axios.get('/api/stats/dept'),
            axios.get('/api/stats/dimensions'),
            axios.get('/api/stats/monthly'),
            axios.get('/api/stats/anomaly-top', { params: { group_by: 'dept' } }),
            axios.get('/api/stats/anomaly-top', { params: { group_by: 'patient' } }),
          ]);

          const trendEl = document.getElementById('trendChart');
          if (trendEl) {
            const chart = this.getChart('trendChart');
            if (!chart) return;
            const d = dr.data.items || dr.data || [];
            chart.setOption({
              tooltip: { trigger: 'axis' },
              legend: { data: ['总数', '成功', '失败'], bottom: 0 },
              grid: { left: 36, right: 10, top: 10, bottom: 40 },
              xAxis: { type: 'category', data: d.map((i) => i.date), axisLabel: { rotate: 40, fontSize: 10 } },
              yAxis: { type: 'value' },
              series: [
                { name: '总数', type: 'line', data: d.map((i) => i.total), smooth: true, itemStyle: { color: '#1677ff' } },
                { name: '成功', type: 'line', data: d.map((i) => i.success), smooth: true, itemStyle: { color: '#52c41a' } },
                { name: '失败', type: 'line', data: d.map((i) => i.failed), smooth: true, itemStyle: { color: '#ff4d4f' } },
              ],
            });
          }

          const pieEl = document.getElementById('pieChart');
          if (pieEl) {
            const chart = this.getChart('pieChart');
            if (!chart) return;
            const items = sr.data.items || sr.data || [];
            chart.setOption({
              tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
              legend: { orient: 'vertical', left: 'left' },
              series: [{
                type: 'pie',
                radius: ['40%', '70%'],
                data: items.map((i) => ({ name: this.severityLabel(i.severity), value: i.count })),
                color: ['#ff4d4f', '#fa8c16', '#52c41a', '#8c8c8c'],
              }],
            });
          }

          const barEl = document.getElementById('barChart');
          if (barEl) {
            const chart = this.getChart('barChart');
            if (!chart) return;
            const deps = (br.data.items || br.data || []).slice(0, 10);
            chart.setOption({
              tooltip: { trigger: 'axis' },
              legend: { data: ['不一致数', '总推送'], bottom: 0 },
              grid: { left: 80, right: 20, top: 10, bottom: 40 },
              xAxis: { type: 'value' },
              yAxis: { type: 'category', data: deps.map((i) => i.dept), axisLabel: { fontSize: 12 } },
              series: [
                { name: '不一致数', type: 'bar', data: deps.map((i) => i.inconsistency), itemStyle: { color: '#ff4d4f' } },
                { name: '总推送', type: 'bar', data: deps.map((i) => i.total), itemStyle: { color: '#1677ff' } },
              ],
            });
          }

          const dimEl = document.getElementById('dimChart');
          if (dimEl) {
            const chart = this.getChart('dimChart');
            if (!chart) return;
            const dims = dimR.data.items || dimR.data || [];
            chart.setOption({
              tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
              legend: { data: ['通过', '不一致', '警告', '未知'], bottom: 0 },
              grid: { left: 120, right: 30, top: 10, bottom: 40 },
              xAxis: { type: 'value' },
              yAxis: { type: 'category', data: dims.map((i) => i.dimension), axisLabel: { fontSize: 12 } },
              series: [
                { name: '通过', type: 'bar', stack: 'total', data: dims.map((i) => i.pass_count), itemStyle: { color: '#52c41a' } },
                { name: '不一致', type: 'bar', stack: 'total', data: dims.map((i) => i.fail_count), itemStyle: { color: '#ff4d4f' } },
                { name: '警告', type: 'bar', stack: 'total', data: dims.map((i) => i.warn_count), itemStyle: { color: '#fa8c16' } },
                { name: '未知', type: 'bar', stack: 'total', data: dims.map((i) => i.unknown_count), itemStyle: { color: '#8c8c8c' } },
              ],
            });
          }

          const monthlyEl = document.getElementById('monthlyChart');
          if (monthlyEl) {
            const chart = this.getChart('monthlyChart');
            if (!chart) return;
            const items = monthlyR.data.items || [];
            chart.setOption({
              tooltip: { trigger: 'axis' },
              legend: { data: ['总数', '成功', '不一致'], bottom: 0 },
              grid: { left: 40, right: 20, top: 10, bottom: 40 },
              xAxis: { type: 'category', data: items.map((i) => i.month) },
              yAxis: { type: 'value' },
              series: [
                { name: '总数', type: 'bar', data: items.map((i) => i.total), itemStyle: { color: '#1677ff' } },
                { name: '成功', type: 'bar', data: items.map((i) => i.success), itemStyle: { color: '#52c41a' } },
                { name: '不一致', type: 'line', data: items.map((i) => i.inconsistency), itemStyle: { color: '#fa8c16' } },
              ],
            });
          }

          const anomalyDeptEl = document.getElementById('anomalyDeptChart');
          if (anomalyDeptEl) {
            const chart = this.getChart('anomalyDeptChart');
            if (!chart) return;
            const items = anomalyDeptR.data.items || [];
            chart.setOption({
              tooltip: { trigger: 'axis' },
              grid: { left: 80, right: 20, top: 10, bottom: 20 },
              xAxis: { type: 'value' },
              yAxis: { type: 'category', data: items.map((i) => i.dept), axisLabel: { fontSize: 12 } },
              series: [{ name: '异常次数', type: 'bar', data: items.map((i) => i.inconsistency_count), itemStyle: { color: '#ff4d4f' } }],
            });
          }

          const anomalyPatientEl = document.getElementById('anomalyPatientChart');
          if (anomalyPatientEl) {
            const chart = this.getChart('anomalyPatientChart');
            if (!chart) return;
            const items = anomalyPatientR.data.items || [];
            chart.setOption({
              tooltip: { trigger: 'axis' },
              grid: { left: 120, right: 20, top: 10, bottom: 20 },
              xAxis: { type: 'value' },
              yAxis: { type: 'category', data: items.map((i) => `${i.patient_name || ''}(${i.patient_id || ''})`), axisLabel: { fontSize: 11 } },
              series: [{ name: '异常次数', type: 'bar', data: items.map((i) => i.inconsistency_count), itemStyle: { color: '#722ed1' } }],
            });
          }
        } catch (e) {
          this.showApiError(e, '加载图表失败');
        }
      });
    },

    async doPush() {
      if (!this.pushForm.query_date) {
        ElementPlus.ElMessage.warning('请选择查询日期');
        return;
      }
      this.pushLoading = true;
      this.pushResult = null;
      try {
        const body = {
          query_date: this.pushForm.query_date,
          dept_filter: this.pushForm.dept_filter ? this.pushForm.dept_filter.split(',').map((s) => s.trim()).filter(Boolean) : null,
          dry_run: this.pushForm.dry_run,
          async_mode: this.pushForm.async_mode && !this.pushForm.dry_run,
        };
        const res = await axios.post('/api/push/manual', body);
        if (res.data.task_id) {
          this.taskId = res.data.task_id;
          this.taskProg = null;
          this.markPushIndicatorRunning({ task_id: this.taskId });
          this.startTaskPolling();
          ElementPlus.ElMessage.success('异步任务已提交');
        } else {
          this.pushResult = res.data;
          const results = res.data.results || [];
          const total = Number(res.data.total_patients || results.length || 0);
          const success = results.filter((item) => item.status === 'success').length;
          const failed = results.filter((item) => item.status === 'failed').length;
          this.markPushIndicatorCompleted({ total, success, failed, processed: total });
          ElementPlus.ElMessage.success('完成');
        }
      } catch (e) {
        this.markPushIndicatorFailed({ message: this.getErrorMessage(e, '推送失败') });
        this.showApiError(e, '推送失败');
      } finally {
        this.pushLoading = false;
      }
    },

    async queryProgress() {
      if (!this.taskId) return;
      const r = await axios.get('/api/push/status/' + this.taskId);
      this.taskProg = r.data;
      this.syncPushIndicatorWithTask(r.data);
      if (['completed', 'failed', 'not_found'].includes(r.data.status)) {
        this.stopTaskPolling();
        this.loadLogs(1);
      }
    },

    startTaskPolling() {
      this.stopTaskPolling();
      this.taskPollCount = 0;
      this.queryProgress();
      this.taskPoller = setInterval(async () => {
        this.taskPollCount += 1;
        await this.queryProgress();
        if (this.taskPollCount >= this.maxTaskPoll) {
          this.stopTaskPolling();
          ElementPlus.ElMessage.warning('推送任务轮询超时，请稍后手动查询结果');
        }
      }, 3000);

      if (!this.visibilityHandlerBound) {
        document.addEventListener('visibilitychange', () => {
          if (document.hidden) this.stopTaskPolling();
        });
        this.visibilityHandlerBound = true;
      }
    },

    stopTaskPolling() {
      if (this.taskPoller) {
        clearInterval(this.taskPoller);
        this.taskPoller = null;
      }
      this.taskPollCount = 0;
    },

    getChart(elId) {
      const el = document.getElementById(elId);
      if (!el) return null;
      if (this.chartInstances[elId]) {
        try {
          this.chartInstances[elId].dispose();
        } catch (e) {
          console.warn('释放图表失败', e);
        }
      }
      const chart = echarts.init(el);
      this.chartInstances[elId] = chart;
      return chart;
    },

    async loadLogs(page) {
      if (page) this.logPage = page;
      try {
        const params = { page: this.logPage, limit: this.logLimit };
        Object.entries(this.lf).forEach(([k, v]) => { if (v) params[k] = v; });
        const r = await axios.get('/api/logs', { params });
        let items = r.data.items || [];
        if (this.logTimeWindow) {
          items = items.filter((item) => {
            const ts = this.parseLogTime(item);
            return ts >= this.logTimeWindow.startMs && ts <= this.logTimeWindow.endMs;
          });
          this.logTotal = items.length;
        } else {
          this.logTotal = r.data.total || 0;
        }
        this.logs = items;
        this.selectedLogIds = [];
      } catch (e) {
        this.showApiError(e, '加载日志失败');
      }
    },

    closeLogDetail() {
      this.logDetailVisible = false;
    },

    onLogDetailClosed() {
      this.logDetail = null;
      this.logDetailIndex = -1;
    },

    closeReport() {
      this.reportVisible = false;
    },

    onReportClosed() {
      this.reportData = null;
    },

    handleLogSelectionChange(rows) {
      this.selectedLogIds = (rows || []).map((item) => item.id);
    },

    async handleLogPageChange(page) {
      this.logPage = page;
      await this.loadLogs();
    },

    async viewLogDetail(logId) {
      await this.runConfigAction(async () => {
        const r = await axios.get(`/api/logs/${logId}`);
        const detail = r.data || {};
        const aiStructured = this.parseAiResultStructured(detail);
        this.logDetail = {
          ...detail,
          request_json_pretty: this.prettyJson(detail.request_json),
          response_json_pretty: this.prettyJson(detail.response_json || detail.ai_result),
          ai_result_pretty: this.prettyJson(detail.ai_result),
          ai_structured: aiStructured,
        };
        this.logDetailIndex = this.logs.findIndex((item) => item.id === logId);
        this.logDetailVisible = true;
      });
    },

    hasPrevLog() {
      return this.logDetailIndex > 0;
    },

    hasNextLog() {
      return this.logDetailIndex >= 0 && this.logDetailIndex < this.logs.length - 1;
    },

    async prevLogDetail() {
      if (!this.hasPrevLog()) return;
      const target = this.logs[this.logDetailIndex - 1];
      if (!target) return;
      await this.viewLogDetail(target.id);
    },

    async nextLogDetail() {
      if (!this.hasNextLog()) return;
      const target = this.logs[this.logDetailIndex + 1];
      if (!target) return;
      await this.viewLogDetail(target.id);
    },

    async handleLogAction(command, row) {
      if (command === 'retry') return this.retrySingleLog(row.id);
      if (command === 'report') return this.viewReport(row.id);
      if (command === 'print') return this.openPrintableReport(row.id);
    },

    async retrySingleLog(logId) {
      await this.runConfigAction(async () => {
        await axios.post(`/api/logs/${logId}/retry`);
        await this.loadLogs();
        if (this.logDetail && this.logDetail.id === logId) {
          await this.viewLogDetail(logId);
        }
      }, '重推已完成');
    },

    async retrySelectedLogs() {
      if (!this.selectedLogIds.length) {
        ElementPlus.ElMessage.warning('请先选择需要重推的日志');
        return;
      }
      await this.runConfigAction(async () => {
        await axios.post('/api/push/retry', { log_ids: this.selectedLogIds });
        await this.loadLogs();
      }, `已提交 ${this.selectedLogIds.length} 条日志重推`);
    },

    async viewReport(logId) {
      await this.runConfigAction(async () => {
        const r = await axios.get(`/api/report/${logId}/data`);
        this.reportData = r.data;
        this.reportVisible = true;
      });
    },

    openPrintableReport(logId) {
      window.open(`/report/${logId}`, '_blank');
    },

    statusTagType,
    severityTagType,
    auditStatusLabel,

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

    debugParseSuccess(result) {
      return !!(result && result.parsed_output && result.parsed_output.parse_success);
    },

    debugValidationType(result) {
      if (!result) return 'info';
      if (this.debugParseSuccess(result)) return 'success';
      if (result.parse_error || result.parsed_output?.parse_error) return 'error';
      return 'warning';
    },

    debugValidationText(result) {
      if (!result) return '未执行调试';
      if (this.debugParseSuccess(result)) return 'JSON 合法，已成功解析为结构化结果';
      if (result.parse_error || result.parsed_output?.parse_error) return 'JSON 解析失败，已进入兼容兜底逻辑';
      return '未解析出标准 JSON，结果可能仅完成了部分兼容处理';
    },

    debugParseError(result) {
      return result?.parse_error || result?.parsed_output?.parse_error || '';
    },

    debugRawOutput(result) {
      return this.prettyJson(result?.result || result?.raw_text || '');
    },

    debugParsedPreview(result) {
      return this.prettyJson(result?.parsed_output || '');
    },

    createDebugPayloadTemplate() {
      return {
        request_id: 'demo_patient_1_2026-04-02',
        audit_date: '2026-04-02',
        match_rule: 'patient_id + visit_number + date',
        patient_info: {
          patient_id: 'demo_patient_1',
          visit_number: '1',
          admission_no: 'demo001',
          patient_name: '测试患者',
          gender: '男',
          birth_date: '1970-01-01',
          admission_date: '2026-04-02 08:00:00',
          bed_no: '01',
          admission_diagnosis: '双侧感音神经性耳聋',
          admission_condition: '普通',
          nursing_level_order: '一级护理',
          department: '听觉植入科',
          attending_doctor: '测试医生',
        },
        medical_documents: [
          {
            document_time: '2026-04-02 09:00:00',
            document_name: '首次病程记录',
            signed_doctor: '测试医生',
            content: '患者因双耳听力下降入院，精神状态尚可，拟完善术前检查。',
          },
        ],
        nursing_records: [
          {
            record_time: '2026-04-02 09:10:00',
            record_type: '一般患者护理记录单',
            recorder: '测试护士',
            content: '患者神志清，已完成入科宣教，嘱留陪人。',
            vitals: {
              temperature: '36.6',
              heart_rate_pulse: '80',
              respiratory_rate: '20',
              blood_pressure: '116/74',
              oxygen_saturation: '',
              blood_glucose: '',
            },
            assessment: {
              consciousness: '清醒',
              skin_condition: '完好',
              wound_condition: '',
              tube_care: '',
              high_risk: '',
            },
            supportive_care: {
              oxygen_nasal_cannula: '',
              oxygen_mask: '',
              intake: '',
              output: '',
              urine_volume: '',
            },
          },
        ],
      };
    },

    fillDebugPayloadTemplate() {
      this.debugForm.payload_json_text = JSON.stringify(this.createDebugPayloadTemplate(), null, 2);
    },

    resetLF() {
      this.lf = { status: '', dept: '', date_from: '', date_to: '', patient_id: '' };
      this.logTimeWindow = null;
      this.loadLogs(1);
    },

    exportCsv() {
      const p = new URLSearchParams();
      Object.entries(this.lf).forEach(([k, v]) => { if (v) p.set(k, v); });
      window.open('/api/logs/export/csv?' + p.toString());
    },

    async loadHealth() {
      try {
        const r = await axios.get('/api/health');
        this.healthComps = r.data.components || {};
        this.overallHealth = r.data.status || 'healthy';
        this.healthTime = new Date().toLocaleString('zh-CN');
      } catch (e) {
        this.overallHealth = 'unhealthy';
      }
    },

    async loadFeedbackPage() {
      await this.runConfigAction(async () => {
        if (!this.feedbackFilter.status) {
          this.feedbackViewMode = 'pending';
          this.feedbackFilter.status = 'pending';
        }
        await this.loadFeedbackAuxData();
        await this.loadFeedbackList();
      });
    },

    switchFeedbackView(mode) {
      this.feedbackViewMode = mode;
      this.feedbackFilter.status = mode === 'pending' ? 'pending' : '';
      this.loadFeedbackList(1);
    },

    async loadFeedbackAuxData() {
      const [deptResp, userResp] = await Promise.all([
        axios.get('/api/departments').catch(() => ({ data: [] })),
        axios.get('/api/users', { params: { page: 1, limit: 100 } }).catch(() => ({ data: { items: [] } })),
      ]);
      this.feedbackDepartments = Array.isArray(deptResp.data) ? deptResp.data : [];
      this.feedbackUsers = userResp.data.items || [];
    },

    async loadFeedbackList(page) {
      if (page) this.feedbackPage = page;
      const params = { page: this.feedbackPage, limit: this.feedbackLimit };
      Object.entries(this.feedbackFilter).forEach(([k, v]) => {
        if (v !== '' && v !== null && v !== undefined) params[k] = v;
      });
      const r = await axios.get('/api/qc/feedback/cases', { params });
      this.feedbackList = r.data.items || [];
      this.feedbackTotal = r.data.total || 0;
      this.feedbackStats = r.data.stats || {};
    },

    async handleFeedbackPageChange(page) {
      this.feedbackPage = page;
      await this.loadFeedbackList();
    },

    resetFeedbackFilter() {
      this.feedbackViewMode = 'pending';
      this.feedbackFilter = { status: 'pending', severity: '', dept_id: null, days: 30, keyword: '' };
      this.loadFeedbackList(1);
    },

    closeFeedbackDetail() {
      this.feedbackDetailVisible = false;
    },

    onFeedbackDetailClosed() {
      this.feedbackDetail = null;
      this.feedbackConfirmForm = { log_id: null, action: 'acknowledged', review_comment: '' };
    },

    async loadFeedbackStatsView() {
      return;
    },

    async viewFeedbackDetail(logId) {
      await this.runConfigAction(async () => {
        this.feedbackDetailLoading = true;
        const r = await axios.get(`/api/qc/feedback/cases/${logId}`);
        this.feedbackDetail = r.data;
        this.feedbackConfirmForm = {
          log_id: r.data.log_id,
          action: r.data.feedback_status === 'closed' ? 'closed' : 'acknowledged',
          review_comment: r.data.feedback?.feedback_text || r.data.feedback_text || '',
        };
        this.feedbackDetailVisible = true;
        await this.loadFeedbackList(this.feedbackPage);
      }).finally(() => {
        this.feedbackDetailLoading = false;
      });
    },

    async submitFeedbackConfirm(action = 'acknowledged') {
      if (!this.feedbackDetail?.log_id) return;
      await this.runConfigAction(async () => {
        await axios.post(`/api/qc/feedback/cases/${this.feedbackDetail.log_id}/confirm`, {
          action,
          review_comment: this.feedbackConfirmForm.review_comment || '',
        });
        await this.viewFeedbackDetail(this.feedbackDetail.log_id);
        await this.loadFeedbackList(this.feedbackPage);
      }, action === 'closed' ? '已确认无问题并关闭' : '已确认并反馈');
    },

    exportFeedbackCsv() {
      window.open('/api/qc/feedback/export/csv');
    },

    async loadUsersPage() {
      await this.runConfigAction(async () => {
        await Promise.all([this.loadUsersList(), this.loadRolesList(), this.loadDepartmentsList()]);
      });
    },

    async loadUsersList(page) {
      if (page) this.usersPage = page;
      const r = await axios.get('/api/users', { params: { page: this.usersPage, limit: this.usersLimit } });
      this.usersList = r.data.items || [];
      this.usersTotal = r.data.total || 0;
    },

    async handleUsersPageChange(page) {
      this.usersPage = page;
      await this.loadUsersList();
    },

    openUserCreate() {
      this.userDialogMode = 'create';
      this.userForm = { id: null, username: '', password: '', full_name: '', email: '', dept_id: null, role_id: null };
      this.userDialogVisible = true;
    },

    openUserEdit(row) {
      this.userDialogMode = 'edit';
      const role = this.rolesList.find((item) => item.name === row.role);
      this.userForm = {
        id: row.id,
        username: row.username,
        password: '',
        full_name: row.full_name,
        email: row.email,
        dept_id: row.dept_id,
        role_id: role ? role.id : null,
      };
      this.userDialogVisible = true;
    },

    async submitUserForm() {
      if (!this.userForm.full_name || !this.userForm.username) {
        ElementPlus.ElMessage.warning('请填写用户名和姓名');
        return;
      }
      if (this.userForm.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.userForm.email)) {
        ElementPlus.ElMessage.warning('请输入有效邮箱地址');
        return;
      }
      if (this.userDialogMode === 'create' && (!this.userForm.password || this.userForm.password.length < 6)) {
        ElementPlus.ElMessage.warning('初始密码至少 6 位');
        return;
      }
      await this.runConfigAction(async () => {
        if (this.userDialogMode === 'create') {
          await axios.post('/api/users', {
            username: this.userForm.username,
            password: this.userForm.password,
            full_name: this.userForm.full_name,
            email: this.userForm.email,
            dept_id: this.userForm.dept_id,
            role_id: this.userForm.role_id,
          });
        } else {
          await axios.put(`/api/users/${this.userForm.id}`, {
            full_name: this.userForm.full_name,
            email: this.userForm.email,
            dept_id: this.userForm.dept_id,
            role_id: this.userForm.role_id,
          });
        }
        this.userDialogVisible = false;
        await this.loadUsersList();
      }, this.userDialogMode === 'create' ? '用户已创建' : '用户已更新');
    },

    openUserPassword(row) {
      this.userPasswordForm = { id: row.id, old_password: '', new_password: '' };
      this.userPasswordDialogVisible = true;
    },

    async changeUserPassword() {
      if (!this.userPasswordForm.new_password || this.userPasswordForm.new_password.length < 6) {
        ElementPlus.ElMessage.warning('新密码至少 6 位');
        return;
      }
      await this.runConfigAction(async () => {
        await axios.post(`/api/users/${this.userPasswordForm.id}/change-password`, {
          old_password: this.userPasswordForm.old_password || '',
          new_password: this.userPasswordForm.new_password,
        });
        this.userPasswordDialogVisible = false;
        this.userPasswordForm = { id: null, old_password: '', new_password: '' };
      }, '密码已更新');
    },

    async disableUser(row) {
      await this.runConfigAction(async () => {
        await axios.delete(`/api/users/${row.id}`);
        await this.loadUsersList();
      }, '用户已禁用');
    },

    async loadRolesPage() {
      await this.runConfigAction(async () => {
        await Promise.all([this.loadRolesList(), this.loadPermissionsList()]);
      });
    },

    async loadRolesList() {
      const r = await axios.get('/api/roles');
      this.rolesList = r.data || [];
    },

    async openRolePermissions(row) {
      await this.runConfigAction(async () => {
        const r = await axios.get(`/api/roles/${row.id}`);
        this.roleDetail = r.data;
        const permissionsResp = await axios.get('/api/permissions');
        this.permissionsList = permissionsResp.data || [];
        this.roleDialogVisible = true;
      });
    },

    async assignRolePermission(permissionId) {
      await this.runConfigAction(async () => {
        await axios.post(`/api/roles/${this.roleDetail.id}/permissions/${permissionId}`);
        await this.openRolePermissions(this.roleDetail);
        await this.loadRolesList();
      }, '权限已分配');
    },

    async revokeRolePermission(permissionId) {
      await this.runConfigAction(async () => {
        await axios.delete(`/api/roles/${this.roleDetail.id}/permissions/${permissionId}`);
        await this.openRolePermissions(this.roleDetail);
        await this.loadRolesList();
      }, '权限已移除');
    },

    async loadPermissionsPage() {
      await this.runConfigAction(async () => {
        await this.loadPermissionsList();
      });
    },

    async loadPermissionsList() {
      const params = {};
      if (this.permissionFilter.module) params.module = this.permissionFilter.module;
      const r = await axios.get('/api/permissions', { params });
      this.permissionsList = r.data || [];
    },

    resetPermissionFilter() {
      this.permissionFilter = { module: '' };
      this.loadPermissionsList();
    },

    openPermissionCreate() {
      this.permissionDialogMode = 'create';
      this.permissionForm = { id: null, name: '', description: '', module: '' };
      this.permissionDialogVisible = true;
    },

    openPermissionEdit(row) {
      this.permissionDialogMode = 'edit';
      this.permissionForm = { id: row.id, name: row.name, description: row.description, module: row.module };
      this.permissionDialogVisible = true;
    },

    async submitPermissionForm() {
      if (!this.permissionForm.name) {
        ElementPlus.ElMessage.warning('请填写权限名');
        return;
      }
      await this.runConfigAction(async () => {
        if (this.permissionDialogMode === 'create') {
          await axios.post('/api/permissions', this.permissionForm);
        } else {
          await axios.put(`/api/permissions/${this.permissionForm.id}`, {
            description: this.permissionForm.description,
            module: this.permissionForm.module,
          });
        }
        this.permissionDialogVisible = false;
        await this.loadPermissionsList();
        if (this.rolesList.length) await this.loadRolesList();
      }, this.permissionDialogMode === 'create' ? '权限已创建' : '权限已更新');
    },

    async deletePermission(row) {
      await this.runConfigAction(async () => {
        await axios.delete(`/api/permissions/${row.id}`);
        await this.loadPermissionsList();
        if (this.rolesList.length) await this.loadRolesList();
      }, '权限已删除');
    },

    async loadDepartmentsPage() {
      await this.runConfigAction(async () => {
        await Promise.all([this.loadDepartmentsList(), this.loadUsersList(1)]);
      });
    },

    async loadDepartmentsList() {
      const r = await axios.get('/api/departments');
      this.departmentsList = r.data || [];
    },

    openDepartmentCreate() {
      this.departmentDialogMode = 'create';
      this.departmentForm = { id: null, name: '', code: '', manager_id: null };
      this.departmentDialogVisible = true;
    },

    openDepartmentEdit(row) {
      this.departmentDialogMode = 'edit';
      this.departmentForm = { id: row.id, name: row.name, code: row.code, manager_id: row.manager_id };
      this.departmentDialogVisible = true;
    },

    async submitDepartmentForm() {
      if (!this.departmentForm.name) {
        ElementPlus.ElMessage.warning('请填写科室名称');
        return;
      }
      await this.runConfigAction(async () => {
        if (this.departmentDialogMode === 'create') {
          await axios.post('/api/departments', {
            name: this.departmentForm.name,
            code: this.departmentForm.code,
            manager_id: this.departmentForm.manager_id,
          });
        } else {
          await axios.put(`/api/departments/${this.departmentForm.id}`, {
            name: this.departmentForm.name,
            code: this.departmentForm.code,
            manager_id: this.departmentForm.manager_id,
          });
        }
        this.departmentDialogVisible = false;
        await this.loadDepartmentsList();
      }, this.departmentDialogMode === 'create' ? '科室已创建' : '科室已更新');
    },

    async deleteDepartment(row) {
      await this.runConfigAction(async () => {
        await axios.delete(`/api/departments/${row.id}`);
        await this.loadDepartmentsList();
      }, '科室已删除');
    },

    async pingHealthComponent(name) {
      const endpointMap = {
        oracle: '/api/health/oracle',
        postgresql: '/api/health/postgresql',
        dify: '/api/health/dify',
      };
      const endpoint = endpointMap[name];
      if (!endpoint) return;
      const result = await this.runConfigAction(async () => {
        const r = await axios.get(endpoint);
        this.healthComps = { ...this.healthComps, [name]: r.data };
        return r.data;
      }, `${this.cname(name)} 检测已完成`);
      if (result?.status === 'up') ElementPlus.ElMessage.success(`${this.cname(name)} 正常`);
    },

    async runConfigAction(action, successMessage) {
      this.cfgLoading = true;
      try {
        const result = await action();
        if (successMessage) ElementPlus.ElMessage.success(successMessage);
        return result;
      } catch (e) {
        this.showApiError(e);
        throw e;
      } finally {
        this.cfgLoading = false;
      }
    },

    async loadOracleConfig() {
      await this.runConfigAction(async () => {
        const r = await axios.get('/api/config/oracle');
        const data = r.data || {};
        this.oracleForm = {
          host: data.host || '',
          port: data.port || 1521,
          service_name: data.service_name || '',
          username: data.username || '',
          password: '',
          password_masked: data.password_masked || '',
          instant_client_dir: data.instant_client_dir || '',
          query_sql: data.query_sql || '',
          dept_sql: data.dept_sql || '',
          field_mapping: { ...createFieldMapping(), ...(data.field_mapping || {}) },
        };
      });
    },

    async saveOracleConfig() {
      await this.runConfigAction(async () => {
        const body = {
          host: this.oracleForm.host,
          port: Number(this.oracleForm.port),
          service_name: this.oracleForm.service_name,
          username: this.oracleForm.username,
          password: this.oracleForm.password,
          instant_client_dir: this.oracleForm.instant_client_dir,
          query_sql: this.oracleForm.query_sql,
          dept_sql: this.oracleForm.dept_sql,
          field_mapping: { ...this.oracleForm.field_mapping },
        };
        await axios.post('/api/config/oracle', body);
        this.oracleForm.password = '';
        await this.loadOracleConfig();
        await this.loadConfigStatusSummary();
      }, 'Oracle 配置已保存');
    },

    async testOracleConfig() {
      const result = await this.runConfigAction(async () => {
        const r = await axios.post('/api/config/oracle/test');
        this.updateTestResult('oracle', r.data);
        return r.data;
      }, 'Oracle 测试请求已发送');
      if (result?.status === 'up') ElementPlus.ElMessage.success('Oracle 连接成功');
    },

    async loadPostgresqlConfig() {
      await this.runConfigAction(async () => {
        const r = await axios.get('/api/config/postgresql');
        const data = r.data || {};
        this.postgresqlForm = {
          host: data.host || 'localhost',
          port: data.port || 5432,
          database: data.database || '',
          username: data.username || '',
          password: '',
          password_masked: data.password_masked || '',
          query_sql: data.query_sql || '',
          dept_sql: data.dept_sql || '',
          field_mapping: { ...createFieldMapping(), ...(data.field_mapping || {}) },
        };
      });
    },

    async savePostgresqlConfig() {
      await this.runConfigAction(async () => {
        const body = {
          host: this.postgresqlForm.host,
          port: Number(this.postgresqlForm.port),
          database: this.postgresqlForm.database,
          username: this.postgresqlForm.username,
          password: this.postgresqlForm.password,
          query_sql: this.postgresqlForm.query_sql,
          dept_sql: this.postgresqlForm.dept_sql,
          field_mapping: { ...this.postgresqlForm.field_mapping },
        };
        await axios.post('/api/config/postgresql', body);
        this.postgresqlForm.password = '';
        await this.loadPostgresqlConfig();
        await this.loadConfigStatusSummary();
      }, 'PostgreSQL 配置已保存');
    },

    async testPostgresqlConfig() {
      const result = await this.runConfigAction(async () => {
        const r = await axios.post('/api/config/postgresql/test');
        this.updateTestResult('postgresql', r.data);
        return r.data;
      }, 'PostgreSQL 测试请求已发送');
      if (result?.status === 'up') ElementPlus.ElMessage.success('PostgreSQL 连接成功');
    },

    async loadDifyConfig() {
      await this.runConfigAction(async () => {
        const r = await axios.get('/api/config/dify');
        const data = r.data || {};
        this.difyForm = {
          base_url: data.base_url || '',
          api_key: '',
          api_key_masked: data.api_key_masked || '',
          workflow_input_variable: data.workflow_input_variable || 'mr_txt',
          workflow_output_key: data.workflow_output_key || 'aa',
          user_identifier: data.user_identifier || '',
          timeout_seconds: data.timeout_seconds || 90,
          extra_inputs_text: JSON.stringify(data.extra_inputs || {}, null, 2),
        };
        this.onDifyExtraInputsInput();
      });
    },

    async saveDifyConfig() {
      await this.runConfigAction(async () => {
        if (this.jsonErrors.difyExtraInputs) {
          throw new Error(this.jsonErrors.difyExtraInputs);
        }
        const body = {
          base_url: this.difyForm.base_url,
          api_key: this.difyForm.api_key,
          workflow_input_variable: this.difyForm.workflow_input_variable,
          workflow_output_key: this.difyForm.workflow_output_key,
          user_identifier: this.difyForm.user_identifier,
          timeout_seconds: Number(this.difyForm.timeout_seconds),
          extra_inputs: this.parseJsonText(this.difyForm.extra_inputs_text, '额外参数'),
        };
        await axios.post('/api/config/dify', body);
        this.difyForm.api_key = '';
        await this.loadDifyConfig();
        await this.loadConfigStatusSummary();
      }, 'Dify 配置已保存');
    },

    async testDifyConfig() {
      const result = await this.runConfigAction(async () => {
        const r = await axios.post('/api/config/dify/test');
        this.updateTestResult('dify', r.data);
        return r.data;
      }, 'Dify 测试请求已发送');
      if (result?.status === 'up') ElementPlus.ElMessage.success('Dify 连接成功');
    },

    async loadDeptConfig() {
      await this.runConfigAction(async () => {
        const [cfgR, listR] = await Promise.all([
          axios.get('/api/config/departments'),
          axios.get('/api/config/departments/list').catch(() => ({ data: { departments: [] } })),
        ]);
        const data = cfgR.data || {};
        this.deptForm = {
          mode: data.mode || 'include',
          listText: (data.list || []).join('\n'),
        };
        this.deptCandidates = listR.data.departments || [];
      });
    },

    async refreshDeptCandidates() {
      await this.runConfigAction(async () => {
        const r = await axios.get('/api/config/departments/list');
        this.deptCandidates = r.data.departments || [];
      }, '科室列表已刷新');
    },

    async saveDeptConfig() {
      await this.runConfigAction(async () => {
        const body = {
          mode: this.deptForm.mode,
          list: this.normalizeDeptList(this.deptForm.listText),
        };
        await axios.post('/api/config/departments', body);
        await this.loadDeptConfig();
        await this.loadConfigStatusSummary();
      }, '科室配置已保存');
    },

    appendDept(name) {
      const items = this.normalizeDeptList(this.deptForm.listText);
      if (!items.includes(name)) items.push(name);
      this.deptForm.listText = items.join('\n');
    },

    async loadPushSettings() {
      await this.runConfigAction(async () => {
        const r = await axios.get('/api/config/push');
        const data = r.data || {};
        this.pushSettingsForm = {
          interval_ms: data.interval_ms || 500,
          max_retry: data.max_retry || 3,
          batch_size: data.batch_size || 50,
        };
      });
    },

    async savePushSettings() {
      await this.runConfigAction(async () => {
        const body = {
          interval_ms: Number(this.pushSettingsForm.interval_ms),
          max_retry: Number(this.pushSettingsForm.max_retry),
          batch_size: Number(this.pushSettingsForm.batch_size),
        };
        await axios.post('/api/config/push', body);
        await this.loadConfigStatusSummary();
      }, '推送参数已保存');
    },

    async loadNotifyConfig() {
      await this.runConfigAction(async () => {
        const r = await axios.get('/api/config/notify');
        const channels = (r.data.channels || []).map((item) => ({
          ...item,
          configText: JSON.stringify(item.config || {}, null, 2),
        }));
        this.notifyChannels = channels.length ? channels : [createNotifyChannel()];
        this.jsonErrors.notifyConfig = {};
        this.notifyChannels.forEach((_, index) => this.onNotifyConfigInput(index));
      });
    },

    addNotifyChannel() {
      this.notifyChannels.push(createNotifyChannel());
      this.onNotifyConfigInput(this.notifyChannels.length - 1);
    },

    removeNotifyChannel(index) {
      this.notifyChannels.splice(index, 1);
      if (!this.notifyChannels.length) this.notifyChannels.push(createNotifyChannel());
      const next = { ...(this.jsonErrors.notifyConfig || {}) };
      delete next[index];
      this.jsonErrors.notifyConfig = next;
    },

    async saveNotifyConfig() {
      await this.runConfigAction(async () => {
        const notifyErrors = Object.values(this.jsonErrors.notifyConfig || {}).filter(Boolean);
        if (notifyErrors.length) {
          throw new Error(String(notifyErrors[0]));
        }
        const channels = this.notifyChannels.map((item) => ({
          type: item.type,
          enabled: !!item.enabled,
          config: this.parseJsonText(item.configText, `通知渠道${item.type}`),
        }));
        await axios.post('/api/config/notify', { channels });
        await this.loadNotifyConfig();
        await this.loadConfigStatusSummary();
      }, '通知配置已保存');
    },

    async testNotifyChannel(index) {
      const item = this.notifyChannels[index];
      if (this.jsonErrors.notifyConfig?.[index]) {
        throw new Error(this.jsonErrors.notifyConfig[index]);
      }
      const payload = {
        type: item.type,
        enabled: !!item.enabled,
        config: this.parseJsonText(item.configText, `通知渠道${item.type}`),
      };
      const result = await this.runConfigAction(async () => {
        const r = await axios.post('/api/notify/test', payload);
        this.updateTestResult(`notify-${index}`, r.data);
        return r.data;
      }, '通知测试请求已发送');
      if (result?.success) ElementPlus.ElMessage.success('通知测试成功');
    },

    formatTestResult(result) {
      if (!result) return '';
      return JSON.stringify(result, null, 2);
    },

    async loadSchedulerPage() {
      await this.runConfigAction(async () => {
        const [statusR, historyR, configR] = await Promise.all([
          axios.get('/api/scheduler/status'),
          axios.get('/api/scheduler/history', { params: { page: this.schedulerPage, limit: this.schedulerLimit } }),
          axios.get('/api/config/scheduler'),
        ]);
        this.schedulerState = {
          ...(statusR.data || {}),
          ...(configR.data || {}),
        };
        this.schedulerHistory = historyR.data.items || [];
      });
    },

    schedulerModeLabel() {
      const mode = this.schedulerState.schedule_mode;
      if (mode === 'every_n_minutes') return `每 ${this.schedulerState.interval_value || 10} 分钟`;
      if (mode === 'every_n_hours') return `每 ${this.schedulerState.interval_value || 1} 小时`;
      if (mode === 'daily') return `每天 ${this.schedulerState.daily_time || '06:00'}`;
      return 'Cron 自定义';
    },

    async saveSchedulerConfig() {
      await this.runConfigAction(async () => {
        const body = {
          enabled: !!this.schedulerState.enabled,
          cron: this.schedulerState.cron || '0 6 * * *',
          schedule_mode: this.schedulerState.schedule_mode || 'daily',
          daily_time: this.schedulerState.daily_time || '06:00',
          interval_value: Number(this.schedulerState.interval_value || 1),
          interval_unit: this.schedulerState.interval_unit || 'minutes',
        };
        await axios.post('/api/config/scheduler', body);
        await this.loadSchedulerPage();
      }, '定时任务配置已保存');
    },

    async startScheduler() {
      await this.runConfigAction(async () => {
        await axios.post('/api/scheduler/start');
        await this.loadSchedulerPage();
      }, '定时任务已启用');
    },

    async stopScheduler() {
      await this.runConfigAction(async () => {
        await axios.post('/api/scheduler/stop');
        await this.loadSchedulerPage();
      }, '定时任务已停用');
    },

    async triggerSchedulerNow() {
      const result = await this.runConfigAction(async () => {
        const params = {};
        if (this.schedulerTriggerForm.query_date) {
          params.query_date = this.schedulerTriggerForm.query_date;
        }
        const r = await axios.post('/api/scheduler/trigger', null, { params });
        await this.loadSchedulerPage();
        return r.data;
      }, '已触发一次调度任务');
      if (result?.task_id) {
        this.taskId = result.task_id;
      }
    },

    resetDebugPage() {
      this.debugResult = null;
      if (!this.difyForm.workflow_input_variable) {
        this.loadDifyConfig();
      }
      this.debugForm = {
        input_mode: 'json',
        mr_txt: '',
        payload_json_text: JSON.stringify(this.createDebugPayloadTemplate(), null, 2),
        user: 'debug-user',
        workflow_input_variable: this.difyForm.workflow_input_variable || '',
        workflow_output_key: this.difyForm.workflow_output_key || '',
        extra_inputs_text: this.difyForm.extra_inputs_text || '{}',
      };
      this.onDebugExtraInputsInput();
      this.onDebugPayloadInput();
    },

    async runDifyDebug() {
      if (this.debugForm.input_mode === 'text' && !this.debugForm.mr_txt.trim()) {
        ElementPlus.ElMessage.warning('请输入调试文本');
        return;
      }
      const result = await this.runConfigAction(async () => {
        if (this.debugForm.input_mode === 'json' && this.jsonErrors.debugPayload) {
          throw new Error(this.jsonErrors.debugPayload);
        }
        if (this.jsonErrors.debugExtraInputs) {
          throw new Error(this.jsonErrors.debugExtraInputs);
        }
        const payloadJson = this.debugForm.input_mode === 'json'
          ? this.parseJsonText(this.debugForm.payload_json_text, '结构化调试 JSON')
          : undefined;
        const payload = {
          mr_txt: this.debugForm.input_mode === 'text' ? this.debugForm.mr_txt : '',
          payload_json: payloadJson,
          user: this.debugForm.user,
          workflow_input_variable: this.debugForm.workflow_input_variable || undefined,
          workflow_output_key: this.debugForm.workflow_output_key || undefined,
          extra_inputs: this.parseJsonText(this.debugForm.extra_inputs_text, '调试额外参数'),
        };
        const r = await axios.post('/api/config/dify/debug', payload);
        this.debugResult = r.data;
        return r.data;
      }, 'Dify 调试完成');
      if (result?.status === 'success') ElementPlus.ElMessage.success('Dify 调试成功');
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
  if (!v) return '--';
  return String(v).replace('T', ' ').split('.')[0];
};

app.mount('#app');
