import { apiGet, apiPost } from '../utils/api.js?v=20260628-scheduler-v1';

export const schedulerMethods = {
  schedulerSuccessRate(row) {
    const total = Number(row?.total_records || 0);
    const success = Number(row?.success_count || 0);
    if (!total) return null;
    return (success / total) * 100;
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

  async loadSchedulerPage() {
    await this.runConfigAction(async () => {
      const [statusR, historyR, dailyConfigR, dischargeConfigR] = await Promise.all([
        apiGet('/api/scheduler/status'),
        apiGet('/api/scheduler/history', { params: { page: this.schedulerPage, limit: this.schedulerLimit } }),
        apiGet('/api/config/scheduler-daily'),
        apiGet('/api/config/scheduler-discharge'),
      ]);
      const statusData = statusR.data || {};
      const dailyConfig = dailyConfigR.data || {};
      const dischargeConfig = dischargeConfigR.data || {};

      this.hasDualScheduler = !!statusData.has_dual;

      if (statusData.has_dual && statusData.daily) {
        this.schedulerState = {
          ...this.schedulerState,
          ...dailyConfig,
          ...statusData.daily,
          running: statusData.running,
        };
        if (!Array.isArray(this.schedulerState.audit_type_codes)) {
          this.schedulerState.audit_type_codes = [];
        }
        if (!Array.isArray(this.schedulerState.dept_filter)) {
          this.schedulerState.dept_filter = [];
        }

        this.schedulerDischargeState = {
          ...this.schedulerDischargeState,
          ...dischargeConfig,
          ...(statusData.discharge || {}),
          running: statusData.running,
        };
        if (!Array.isArray(this.schedulerDischargeState.audit_type_codes)) {
          this.schedulerDischargeState.audit_type_codes = [];
        }
        if (!Array.isArray(this.schedulerDischargeState.dept_filter)) {
          this.schedulerDischargeState.dept_filter = [];
        }
      } else {
        const legacy = statusData.legacy || {};
        this.schedulerState = {
          ...this.schedulerState,
          running: statusData.running,
          enabled: legacy.enabled !== undefined ? legacy.enabled : dailyConfig.enabled,
          cron: legacy.cron || dailyConfig.cron || '',
          schedule_mode: legacy.schedule_mode || dailyConfig.schedule_mode || 'daily',
          daily_time: legacy.daily_time || dailyConfig.daily_time || '06:00',
          audit_run_mode: legacy.audit_run_mode || dailyConfig.audit_run_mode || 'daily_increment',
          audit_type_codes: legacy.audit_type_codes || dailyConfig.audit_type_codes || [],
          dept_filter: legacy.dept_filter || dailyConfig.dept_filter,
        };
        if (!Array.isArray(this.schedulerState.audit_type_codes)) {
          this.schedulerState.audit_type_codes = [];
        }
        if (!Array.isArray(this.schedulerState.dept_filter)) {
          this.schedulerState.dept_filter = [];
        }
      }
      if (!Array.isArray(this.schedulerTriggerForm.dept_filter)) {
        this.schedulerTriggerForm.dept_filter = [];
      }
      this.schedulerDeptFilterText = (this.schedulerState.dept_filter || []).join(',');
      this.schedulerDischargeDeptFilterText = (this.schedulerDischargeState.dept_filter || []).join(',');
      this.schedulerTriggerDeptFilterText = (this.schedulerTriggerForm.dept_filter || []).join(',');
      if (!Array.isArray(this.schedulerDeptCandidates) || !this.schedulerDeptCandidates.length) {
        const deptR = await apiGet('/api/config/departments/list').catch(() => ({ data: { departments: [] } }));
        this.schedulerDeptCandidates = deptR.data.departments || [];
      }
      this.schedulerHistory = historyR.data.items || [];
      // failure-isolated: runtime-summary load does not block scheduler
      this.loadSchedulerRuntimeSummary().catch(() => {});
      this.loadAlertDeptFilter().catch(() => {});
    });
  },

  schedulerModeLabel(stateOverride) {
    const state = stateOverride || this.schedulerState;
    const mode = state.schedule_mode;
    if (mode === 'every_n_minutes') return `每 ${state.interval_value || 10} 分钟`;
    if (mode === 'every_n_hours') return `每 ${state.interval_value || 1} 小时`;
    if (mode === 'daily') return `每天 ${state.daily_time || '06:00'}`;
    return 'Cron 自定义';
  },

  dischargeModeLabel() {
    return this.schedulerModeLabel(this.schedulerDischargeState);
  },

  buildSchedulerConfigPayload(overrideEnabled, stateOverride, deptTextOverride) {
    const state = stateOverride || this.schedulerState;
    const selectedDepts = Array.isArray(state.dept_filter)
      ? state.dept_filter
      : [];
    const deptText = deptTextOverride !== undefined ? deptTextOverride : this.schedulerDeptFilterText;
    const typedDepts = this.normalizeDeptList ? this.normalizeDeptList(deptText || '') : [];
    const deptFilter = Array.from(new Set([...selectedDepts, ...typedDepts].map((item) => String(item || '').trim()).filter(Boolean)));
    return {
      enabled: overrideEnabled !== undefined ? !!overrideEnabled : !!state.enabled,
      cron: state.cron || '0 6 * * *',
      schedule_mode: state.schedule_mode || 'daily',
      daily_time: state.daily_time || '06:00',
      interval_value: Number(state.interval_value || 1),
      interval_unit: state.interval_unit || 'minutes',
      audit_run_mode: state.audit_run_mode || 'daily_increment',
      audit_type_codes: Array.isArray(state.audit_type_codes)
        ? state.audit_type_codes.map((item) => String(item || '').trim()).filter(Boolean)
        : [],
      dept_filter: deptFilter,
    };
  },

  buildDischargeConfigPayload(overrideEnabled) {
    const payload = this.buildSchedulerConfigPayload(overrideEnabled, this.schedulerDischargeState, this.schedulerDischargeDeptFilterText || '');
    payload.audit_run_mode = 'discharge_final';
    return payload;
  },

  async saveSchedulerConfig() {
    await this.runConfigAction(async () => {
      const body = this.buildSchedulerConfigPayload();
      await apiPost('/api/config/scheduler-daily', body);
      await this.loadSchedulerPage();
    }, '定时任务配置已保存');
  },

  async saveDischargeSchedulerConfig() {
    await this.runConfigAction(async () => {
      const body = this.buildDischargeConfigPayload();
      await apiPost('/api/config/scheduler-discharge', body);
      await this.loadSchedulerPage();
    }, '出院终末调度配置已保存');
  },

  async startScheduler() {
    await this.runConfigAction(async () => {
      const body = this.buildSchedulerConfigPayload(true);
      await apiPost('/api/config/scheduler-daily', body);
      await apiPost('/api/scheduler/start', null, { params: { job_id: 'daily_push' } });
      await this.loadSchedulerPage();
    }, '每日增量调度已启用');
  },

  async startDischargeScheduler() {
    await this.runConfigAction(async () => {
      const body = this.buildDischargeConfigPayload(true);
      await apiPost('/api/config/scheduler-discharge', body);
      await apiPost('/api/scheduler/start', null, { params: { job_id: 'discharge_push' } });
      await this.loadSchedulerPage();
    }, '出院终末调度已启用');
  },

  async stopScheduler() {
    await this.runConfigAction(async () => {
      await apiPost('/api/scheduler/stop', null, { params: { job_id: 'daily_push' } });
      await this.loadSchedulerPage();
    }, '每日增量调度已停用');
  },

  async stopDischargeScheduler() {
    await this.runConfigAction(async () => {
      await apiPost('/api/scheduler/stop', null, { params: { job_id: 'discharge_push' } });
      await this.loadSchedulerPage();
    }, '出院终末调度已停用');
  },

  async triggerSchedulerNow() {
    const result = await this.runConfigAction(async () => {
      const params = {};
      if (this.schedulerTriggerForm.query_date) {
        params.query_date = this.schedulerTriggerForm.query_date;
      }
      if (Array.isArray(this.schedulerTriggerForm.audit_type_codes) && this.schedulerTriggerForm.audit_type_codes.length) {
        params.audit_type_codes = this.schedulerTriggerForm.audit_type_codes.map((item) => String(item || '').trim()).filter(Boolean).join(',');
      }
      if (Array.isArray(this.schedulerTriggerForm.dept_filter) && this.schedulerTriggerForm.dept_filter.length) {
        params.dept_filter = this.schedulerTriggerForm.dept_filter.map((item) => String(item || '').trim()).filter(Boolean).join(',');
      }
      const typedDepts = this.normalizeDeptList ? this.normalizeDeptList(this.schedulerTriggerDeptFilterText || '') : [];
      if (typedDepts.length) {
        const selected = Array.isArray(this.schedulerTriggerForm.dept_filter) ? this.schedulerTriggerForm.dept_filter : [];
        params.dept_filter = Array.from(new Set([...selected, ...typedDepts].map((item) => String(item || '').trim()).filter(Boolean))).join(',');
      }
      if (this.schedulerTriggerForm.audit_run_mode) {
        params.audit_run_mode = this.schedulerTriggerForm.audit_run_mode;
      }
      const r = await apiPost('/api/scheduler/trigger', null, { params });
      await this.loadSchedulerPage();
      return r.data;
    }, '已触发一次调度任务');
    if (result?.task_id) {
      this.taskId = result.task_id;
    }
  },

  // ── 调度页 Runtime Summary 只读提示 ────────────────────────────────────

  async loadSchedulerRuntimeSummary() {
    this.schedulerRuntimeSummaryLoading = true;
    this.schedulerRuntimeSummaryError = '';
    try {
      const r = await apiGet('/api/config/runtime-summary');
      this.schedulerRuntimeSummary = r.data || {};
    } catch (e) {
      this.schedulerRuntimeSummaryError = this.getErrorMessage
        ? this.getErrorMessage(e, '配置风险提示加载失败')
        : String(e?.message || e || '');
    } finally {
      this.schedulerRuntimeSummaryLoading = false;
    }
  },

  schedulerRuntimeWarnings() {
    const summary = this.schedulerRuntimeSummary;
    if (!summary) return [];
    const all = summary.warnings || [];
    return all.filter((w) => {
      const p = w.path || '';
      const c = w.code || '';
      return p.startsWith('scheduler_daily.')
        || p.startsWith('scheduler_discharge.')
        || c.startsWith('scheduler_daily')
        || c.startsWith('scheduler_discharge')
        || c === 'dept_filter_mismatch';
    });
  },

  schedulerWarningsByLevel(level) {
    return this.schedulerRuntimeWarnings().filter((w) => w.level === level);
  },

  schedulerWarningTagType(level) {
    if (level === 'error') return 'danger';
    if (level === 'warning') return 'warning';
    return 'info';
  },

  schedulerAuditTypeStats() {
    const summary = this.schedulerRuntimeSummary;
    if (!summary) return { total: 0, defaultSchedule: 0 };
    const atList = summary.audit_types || [];
    return {
      total: atList.length,
      defaultSchedule: atList.filter((at) => at.default_for_schedule).length,
    };
  },

  schedulerStatusTagType(status) {
    if (status === 'running' || status === 'success') return 'success';
    if (status === 'enabled' || status === 'warning' || status === 'partial') return 'warning';
    if (status === 'failed' || status === 'error') return 'danger';
    return 'info';
  },

  schedulerLatestHistory() {
    return (this.schedulerHistory || [])[0] || null;
  },

  resetSchedulerTriggerForm() {
    this.schedulerTriggerForm = {
      audit_run_mode: 'daily_increment',
      query_date: '',
      audit_type_codes: [],
      dept_filter: [],
    };
    this.schedulerTriggerDeptFilterText = '';
  },

  async loadAlertDeptFilter() {
    try {
      const r = await apiGet('/api/config/relay-alert');
      const data = r.data || {};
      const deptFilter = Array.isArray(data.alert_dept_filter) ? data.alert_dept_filter : [];
      this.alertDeptFilterForm = {
        dept_filter: deptFilter,
        dept_text: deptFilter.join(','),
      };
    } catch (_) {
      this.alertDeptFilterForm = { dept_filter: [], dept_text: '' };
    }
  },

  async saveAlertDeptFilter() {
    this.alertDeptFilterSaving = true;
    try {
      const selected = Array.isArray(this.alertDeptFilterForm.dept_filter)
        ? this.alertDeptFilterForm.dept_filter.map(d => String(d || '').trim()).filter(Boolean)
        : [];
      const typed = (this.alertDeptFilterForm.dept_text || '').split(/[,;\n]+/).map(d => d.trim()).filter(Boolean);
      const merged = Array.from(new Set([...selected, ...typed])).slice(0, 100);
      await apiPost('/api/config/relay-alert', { alert_dept_filter: merged });
      this.alertDeptFilterForm.dept_filter = merged;
      this.alertDeptFilterForm.dept_text = merged.join(',');
      ElementPlus.ElMessage.success('告警科室过滤已保存');
    } catch (e) {
      this.showApiError(e, '保存告警科室过滤失败');
    } finally {
      this.alertDeptFilterSaving = false;
    }
  },
};
