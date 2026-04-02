const { createApp } = Vue;

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
      summary: {},
      healthComps: {},
      healthTime: '',
      pushForm: { query_date: '', dept_filter: '', dry_run: false, async_mode: false },
      pushLoading: false,
      pushResult: null,
      taskId: null,
      taskProg: null,
      taskPoller: null,
      logs: [],
      logTotal: 0,
      logPage: 1,
      logLimit: 20,
      selectedLogIds: [],
      lf: { status: '', dept: '', date_from: '', date_to: '', patient_id: '' },
      logDetailVisible: false,
      logDetail: null,
      reportVisible: false,
      reportData: null,
      feedbackStats: {},
      feedbackList: [],
      feedbackPage: 1,
      feedbackLimit: 20,
      feedbackTotal: 0,
      feedbackFilter: { status: '', severity: '', dept_id: null },
      feedbackDepartments: [],
      feedbackUsers: [],
      feedbackCreateVisible: false,
      feedbackUpdateVisible: false,
      feedbackRectifyVisible: false,
      feedbackDetailVisible: false,
      feedbackCreateForm: { push_log_id: null, dept_id: null, severity: 'medium', feedback_text: '', assigned_to: null },
      feedbackUpdateForm: { id: null, status: 'pending', feedback_text: '', assigned_to: null },
      feedbackRectifyForm: { id: null, rectification_text: '' },
      feedbackDetail: null,
      usersList: [],
      usersPage: 1,
      usersLimit: 20,
      usersTotal: 0,
      userDialogVisible: false,
      userDialogMode: 'create',
      userForm: { id: null, username: '', password: '', full_name: '', email: '', dept_id: null, role_id: null },
      userPasswordDialogVisible: false,
      userPasswordForm: { id: null, new_password: '' },
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
      schedulerState: { running: false, enabled: false, cron: '', next_run: '', last_run: null },
      schedulerHistory: [],
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
    };
  },

  computed: {
    pageTitle() {
      const m = {
        dashboard: '🏠 仪表盘',
        push: '🚀 数据推送',
        logs: '📋 推送日志',
        stats: '📊 数据统计',
        feedback: '💬 质控反馈',
        users: '👥 用户管理',
        roles: '🧩 角色管理',
        permissions: '🔐 权限管理',
        departments: '🏥 科室管理',
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

    availableRolePermissions() {
      if (!this.roleDetail) return [];
      const assigned = new Set((this.roleDetail.permissions || []).map((item) => item.id));
      return this.permissionsList.filter((item) => !assigned.has(item.id));
    },
  },

  methods: {
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
          if (error?.response?.status === 401) {
            this.clearAuthState();
            this.loginHint = '登录已失效，请重新登录。';
          }
          return Promise.reject(error);
        },
      );
    },

    clearAuthState() {
      this.isAuthenticated = false;
      this.authToken = '';
      this.currentUser = {};
      localStorage.removeItem('auth_token');
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
      if (!this.authToken) return;
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
      } catch (e) {}
      this.clearAuthState();
      this.loginHint = '已退出，请重新登录。';
      this.activeMenu = 'dashboard';
    },

    async bootstrapApp() {
      await this.loadDataSource();
      await this.loadDashboard();
    },

    pct(v) {
      return v !== undefined ? (v * 100).toFixed(1) + '%' : '--';
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

    feedbackStatusLabel(status) {
      return {
        pending: '待处理',
        acknowledged: '已确认',
        rectified: '已整改',
        closed: '已关闭',
      }[status] || status || '--';
    },

    feedbackStatusTagType(status) {
      return {
        pending: 'warning',
        acknowledged: 'primary',
        rectified: 'success',
        closed: 'info',
      }[status] || 'info';
    },

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

    parseJsonText(text, fieldName) {
      const raw = (text || '').trim();
      if (!raw) return {};
      try {
        return JSON.parse(raw);
      } catch (e) {
        throw new Error(`${fieldName} 不是合法 JSON`);
      }
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

    switchMenu(key) {
      this.activeMenu = key;
      const loaders = {
        dashboard: () => this.loadDashboard(),
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
      if (loaders[key]) loaders[key]();
    },

    async loadDataSource() {
      try {
        const r = await axios.get('/api/config/data-source');
        this.dataSourceType = r.data.type || 'oracle';
      } catch (e) {}
    },

    async saveDataSource() {
      try {
        await axios.post('/api/config/data-source', { type: this.dataSourceType });
        ElementPlus.ElMessage.success('数据源已切换');
      } catch (e) {
        ElementPlus.ElMessage.error('切换失败: ' + this.getErrorMessage(e));
      }
    },

    async loadDashboard() {
      try {
        const [s, h] = await Promise.all([
          axios.get('/api/stats/summary'),
          axios.get('/api/health'),
        ]);
        this.summary = s.data || {};
        this.healthComps = h.data.components || {};
        this.overallHealth = h.data.status || 'healthy';
      } catch (e) {
        console.error(e);
      }
      this.$nextTick(() => this.renderDash());
    },

    async renderDash() {
      try {
        const r = await axios.get('/api/stats/daily', { params: { days: 30 } });
        const el = document.getElementById('dashChart');
        if (!el) return;
        const chart = echarts.init(el);
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
      } catch (e) {}
    },

    async loadStats() {
      try {
        const s = await axios.get('/api/stats/summary');
        this.summary = s.data || {};
      } catch (e) {}

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
            const chart = echarts.init(trendEl);
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
            const chart = echarts.init(pieEl);
            const items = sr.data.items || sr.data || [];
            chart.setOption({
              tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
              legend: { orient: 'vertical', left: 'left' },
              series: [{
                type: 'pie',
                radius: ['40%', '70%'],
                data: items.map((i) => ({ name: i.severity || '未知', value: i.count })),
                color: ['#ff4d4f', '#fa8c16', '#52c41a', '#8c8c8c'],
              }],
            });
          }

          const barEl = document.getElementById('barChart');
          if (barEl) {
            const chart = echarts.init(barEl);
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
            const chart = echarts.init(dimEl);
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
            const chart = echarts.init(monthlyEl);
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
            const chart = echarts.init(anomalyDeptEl);
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
            const chart = echarts.init(anomalyPatientEl);
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
          console.error('charts', e);
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
          this.startTaskPolling();
          ElementPlus.ElMessage.success('异步任务已提交');
        } else {
          this.pushResult = res.data;
          ElementPlus.ElMessage.success('完成');
        }
      } catch (e) {
        ElementPlus.ElMessage.error('推送失败: ' + this.getErrorMessage(e));
      } finally {
        this.pushLoading = false;
      }
    },

    async queryProgress() {
      if (!this.taskId) return;
      const r = await axios.get('/api/push/status/' + this.taskId);
      this.taskProg = r.data;
      if (['completed', 'failed', 'not_found'].includes(r.data.status)) {
        this.stopTaskPolling();
        this.loadLogs(1);
      }
    },

    startTaskPolling() {
      this.stopTaskPolling();
      this.queryProgress();
      this.taskPoller = setInterval(() => this.queryProgress(), 3000);
    },

    stopTaskPolling() {
      if (this.taskPoller) {
        clearInterval(this.taskPoller);
        this.taskPoller = null;
      }
    },

    async loadLogs(page) {
      if (page) this.logPage = page;
      try {
        const params = { page: this.logPage, limit: this.logLimit };
        Object.entries(this.lf).forEach(([k, v]) => { if (v) params[k] = v; });
        const r = await axios.get('/api/logs', { params });
        this.logs = r.data.items || [];
        this.logTotal = r.data.total || 0;
        this.selectedLogIds = [];
      } catch (e) {
        ElementPlus.ElMessage.error('加载日志失败');
      }
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
        this.logDetail = {
          ...detail,
          request_json_pretty: this.prettyJson(detail.request_json),
          response_json_pretty: this.prettyJson(detail.response_json || detail.ai_result),
          ai_result_pretty: this.prettyJson(detail.ai_result),
        };
        this.logDetailVisible = true;
      });
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

    statusTagType(status) {
      return {
        success: 'success',
        failed: 'danger',
        skipped: 'info',
        pending: 'warning',
        error: 'danger',
      }[status] || 'info';
    },

    severityTagType(severity) {
      return {
        high: 'danger',
        medium: 'warning',
        low: 'success',
      }[severity] || 'info';
    },

    auditStatusLabel(status) {
      return {
        pass: '通过',
        fail: '不一致',
        warn: '警告',
        unknown: '未知',
      }[status] || status || '--';
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
        await this.loadFeedbackAuxData();
        await this.loadFeedbackList();
        await this.loadFeedbackStatsView();
      });
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
      const r = await axios.get('/api/qc/feedback', { params });
      this.feedbackList = r.data.items || [];
      this.feedbackTotal = r.data.total || 0;
      this.feedbackStats = r.data.stats || {};
    },

    async handleFeedbackPageChange(page) {
      this.feedbackPage = page;
      await this.loadFeedbackList();
    },

    resetFeedbackFilter() {
      this.feedbackFilter = { status: '', severity: '', dept_id: null };
      this.loadFeedbackList(1);
    },

    async loadFeedbackStatsView() {
      this.$nextTick(async () => {
        try {
          const [severityR, statusR] = await Promise.all([
            axios.get('/api/qc/feedback/stats/severity'),
            axios.get('/api/qc/feedback/stats/status'),
          ]);

          const sevEl = document.getElementById('feedbackSeverityChart');
          if (sevEl) {
            const chart = echarts.init(sevEl);
            const items = severityR.data.severity_distribution || [];
            chart.setOption({
              tooltip: { trigger: 'item' },
              legend: { bottom: 0 },
              series: [{
                type: 'pie',
                radius: ['35%', '70%'],
                data: items.map((i) => ({ name: i.label || i.severity || i.name, value: i.count || i.value || 0 })),
                color: ['#ff4d4f', '#fa8c16', '#52c41a'],
              }],
            });
          }

          const statusEl = document.getElementById('feedbackStatusChart');
          if (statusEl) {
            const chart = echarts.init(statusEl);
            const items = statusR.data.status_distribution || [];
            chart.setOption({
              tooltip: { trigger: 'axis' },
              grid: { left: 40, right: 20, top: 10, bottom: 30 },
              xAxis: { type: 'category', data: items.map((i) => i.label || this.feedbackStatusLabel(i.status || i.name)) },
              yAxis: { type: 'value' },
              series: [{ type: 'bar', data: items.map((i) => i.count || i.value || 0), itemStyle: { color: '#1677ff' } }],
            });
          }
        } catch (e) {
          console.error('feedback charts', e);
        }
      });
    },

    async createFeedback() {
      if (!this.feedbackCreateForm.push_log_id || !this.feedbackCreateForm.dept_id || !this.feedbackCreateForm.feedback_text.trim()) {
        ElementPlus.ElMessage.warning('请填写日志ID、科室和反馈内容');
        return;
      }
      await this.runConfigAction(async () => {
        await axios.post('/api/qc/feedback', this.feedbackCreateForm);
        this.feedbackCreateVisible = false;
        this.feedbackCreateForm = { push_log_id: null, dept_id: null, severity: 'medium', feedback_text: '', assigned_to: null };
        await this.loadFeedbackPage();
      }, '反馈已创建');
    },

    openFeedbackUpdate(row) {
      this.feedbackUpdateForm = {
        id: row.id,
        status: row.status,
        feedback_text: row.feedback_text,
        assigned_to: row.assigned_to,
      };
      this.feedbackUpdateVisible = true;
    },

    async updateFeedback() {
      await this.runConfigAction(async () => {
        await axios.put(`/api/qc/feedback/${this.feedbackUpdateForm.id}`, {
          status: this.feedbackUpdateForm.status,
          assigned_to: this.feedbackUpdateForm.assigned_to,
          feedback_text: this.feedbackUpdateForm.feedback_text,
        });
        this.feedbackUpdateVisible = false;
        await this.loadFeedbackPage();
        if (this.feedbackDetail?.id === this.feedbackUpdateForm.id) {
          await this.viewFeedbackDetail(this.feedbackUpdateForm.id);
        }
      }, '反馈已更新');
    },

    openFeedbackRectify(row) {
      this.runConfigAction(async () => {
        await axios.post(`/api/qc/feedback/${row.id}/mark-rectify-clicked`);
        this.feedbackRectifyForm = { id: row.id, rectification_text: row.rectification_text || '' };
        this.feedbackRectifyVisible = true;
        await this.loadFeedbackList(this.feedbackPage);
      });
    },

    async submitFeedbackRectification() {
      if (!this.feedbackRectifyForm.rectification_text.trim()) {
        ElementPlus.ElMessage.warning('请输入整改说明');
        return;
      }
      await this.runConfigAction(async () => {
        await axios.post(`/api/qc/feedback/${this.feedbackRectifyForm.id}/rectify`, {
          rectification_text: this.feedbackRectifyForm.rectification_text,
        });
        this.feedbackRectifyVisible = false;
        await this.loadFeedbackPage();
        if (this.feedbackDetail?.id === this.feedbackRectifyForm.id) {
          await this.viewFeedbackDetail(this.feedbackRectifyForm.id);
        }
      }, '整改说明已提交');
    },

    async viewFeedbackDetail(feedbackId) {
      await this.runConfigAction(async () => {
        const r = await axios.get(`/api/qc/feedback/${feedbackId}`);
        this.feedbackDetail = r.data;
        this.feedbackDetailVisible = true;
        await this.loadFeedbackList(this.feedbackPage);
      });
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
      this.userPasswordForm = { id: row.id, new_password: '' };
      this.userPasswordDialogVisible = true;
    },

    async changeUserPassword() {
      if (!this.userPasswordForm.new_password || this.userPasswordForm.new_password.length < 6) {
        ElementPlus.ElMessage.warning('新密码至少 6 位');
        return;
      }
      await this.runConfigAction(async () => {
        const params = new URLSearchParams({ old_password: 'admin', new_password: this.userPasswordForm.new_password });
        await axios.post(`/api/users/${this.userPasswordForm.id}/change-password?${params.toString()}`);
        this.userPasswordDialogVisible = false;
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
        ElementPlus.ElMessage.error(this.getErrorMessage(e));
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
      });
    },

    async saveDifyConfig() {
      await this.runConfigAction(async () => {
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
      });
    },

    addNotifyChannel() {
      this.notifyChannels.push(createNotifyChannel());
    },

    removeNotifyChannel(index) {
      this.notifyChannels.splice(index, 1);
      if (!this.notifyChannels.length) this.notifyChannels.push(createNotifyChannel());
    },

    async saveNotifyConfig() {
      await this.runConfigAction(async () => {
        const channels = this.notifyChannels.map((item) => ({
          type: item.type,
          enabled: !!item.enabled,
          config: this.parseJsonText(item.configText, `通知渠道${item.type}`),
        }));
        await axios.post('/api/config/notify', { channels });
        await this.loadNotifyConfig();
      }, '通知配置已保存');
    },

    async testNotifyChannel(index) {
      const item = this.notifyChannels[index];
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
        const [statusR, historyR] = await Promise.all([
          axios.get('/api/scheduler/status'),
          axios.get('/api/scheduler/history', { params: { page: this.schedulerPage, limit: this.schedulerLimit } }),
        ]);
        this.schedulerState = statusR.data || {};
        this.schedulerHistory = historyR.data.items || [];
      });
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
        const r = await axios.post('/api/scheduler/trigger');
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
    },

    async runDifyDebug() {
      if (this.debugForm.input_mode === 'text' && !this.debugForm.mr_txt.trim()) {
        ElementPlus.ElMessage.warning('请输入调试文本');
        return;
      }
      const result = await this.runConfigAction(async () => {
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
    setInterval(() => {
      this.currentTime = new Date().toLocaleString('zh-CN');
    }, 1000);
    this.restoreSession();
    window.addEventListener('resize', () => {
      document.querySelectorAll('[id$="Chart"]').forEach((el) => {
        try { echarts.getInstanceByDom(el)?.resize(); } catch (e) {}
      });
    });
  },

  beforeUnmount() {
    this.stopTaskPolling();
  },
});

app.use(ElementPlus);
app.mount('#app');
