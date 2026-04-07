import { apiGet, apiPost } from '../utils/api.js';

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
      const [statusR, historyR, configR] = await Promise.all([
        apiGet('/api/scheduler/status'),
        apiGet('/api/scheduler/history', { params: { page: this.schedulerPage, limit: this.schedulerLimit } }),
        apiGet('/api/config/scheduler'),
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
      await apiPost('/api/config/scheduler', body);
      await this.loadSchedulerPage();
    }, '定时任务配置已保存');
  },

  async startScheduler() {
    await this.runConfigAction(async () => {
      await apiPost('/api/scheduler/start');
      await this.loadSchedulerPage();
    }, '定时任务已启用');
  },

  async stopScheduler() {
    await this.runConfigAction(async () => {
      await apiPost('/api/scheduler/stop');
      await this.loadSchedulerPage();
    }, '定时任务已停用');
  },

  async triggerSchedulerNow() {
    const result = await this.runConfigAction(async () => {
      const params = {};
      if (this.schedulerTriggerForm.query_date) {
        params.query_date = this.schedulerTriggerForm.query_date;
      }
      const r = await apiPost('/api/scheduler/trigger', null, { params });
      await this.loadSchedulerPage();
      return r.data;
    }, '已触发一次调度任务');
    if (result?.task_id) {
      this.taskId = result.task_id;
    }
  },
};
