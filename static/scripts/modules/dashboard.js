import { createLineSeries } from '../utils/chart-helpers.js';
import { apiGet } from '../utils/api.js';

export const dashboardMethods = {
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
    // PERF-02 修复：防重入，快速多次切换菜单不发起多批并发请求
    if (this._dashboardLoading) return;
    this._dashboardLoading = true;
    try {
      const today = this.todayDateString();
      // BUG-06 修复：合并原来两次日志请求为一次
      // 原来同时发 todayLogs(limit=300) + recentLogs(limit=120)，数据重叠浪费请求
      // 改为：只拉今日日志，告警优先从今日筛选；今日无高风险时才补一次近期查询
      const [s, h, todayLogsR, pendingFeedbackR, schedulerStatusR] = await Promise.all([
        apiGet('/api/stats/summary'),
        apiGet('/api/health'),
        apiGet('/api/logs', { params: { page: 1, limit: 200, push_time_from: today, push_time_to: today } }).catch(() => ({ data: { items: [] } })),
        apiGet('/api/qc/feedback/cases', { params: { page: 1, limit: 1, status: 'pending', days: 30 } }).catch(() => ({ data: { total: 0 } })),
        apiGet('/api/scheduler/status').catch(() => ({ data: {} })),
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

      // 从今日日志中筛选高风险告警
      let highRiskLogs = todayLogs.filter(
        (item) => Number(item.inconsistency || 0) === 1
          && (item.severity === 'high' || Number(item.risk_score || 0) >= 80),
      );

      // 若今日无高风险记录，补充查最近记录（只在需要时才额外发请求）
      if (highRiskLogs.length === 0) {
        try {
          const recentR = await apiGet('/api/logs', { params: { page: 1, limit: 50 } });
          const recentItems = recentR.data?.items || [];
          highRiskLogs = recentItems.filter(
            (item) => Number(item.inconsistency || 0) === 1
              && (item.severity === 'high' || Number(item.risk_score || 0) >= 80),
          );
        } catch (_) { /* 告警加载失败不影响主流程 */ }
      }

      const alerts = highRiskLogs
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
    } finally {
      this._dashboardLoading = false;
    }
    this.$nextTick(() => this.renderDash());
  },

  async renderDash() {
    try {
      const r = await apiGet('/api/stats/daily', { params: { days: 30 } });
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
          createLineSeries('总数', d.map((i) => i.total), '#1677ff'),
          createLineSeries('成功', d.map((i) => i.success), '#52c41a'),
          createLineSeries('失败', d.map((i) => i.failed), '#ff4d4f'),
        ],
      });
    } catch (e) {
      this.showApiError(e, '加载趋势图失败');
    }
  },
};
