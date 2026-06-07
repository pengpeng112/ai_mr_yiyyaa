import { createLineSeries } from '../utils/chart-helpers.js';
import { apiGet } from '../utils/api.js?v=20260524-download-blob';

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
    this.$nextTick(() => this.viewLogDetail(logId));
  },

  openDashboardFeedback(mode = 'all') {
    this.switchMenu('feedback');
    if (mode === 'pending') {
      this.switchFeedbackView('pending');
    } else {
      this.switchFeedbackView('all');
    }
  },

  openDashboardTarget(target) {
    if (target === 'audit') {
      this.switchMenu('audit');
      return;
    }
    if (target === 'patient-qc') {
      this.switchMenu('patient-qc');
      return;
    }
    if (target === 'relay-alerts') {
      this.patientQcTab = 'relay-alerts';
      this.switchMenu('patient-qc');
      return;
    }
  },

  resetDashboardState() {
    this.dashboardKpis = {
      date: this.todayDateString(),
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
    };
    this.dashboardDeptTop = [];
    this.dashboardEvents = [];
    this.dashboardRelay = { total: 0, success: 0, failed: 0, viewed: 0, unviewed: 0 };
    this.dashboardScheduler = { lastRunTime: '', nextRunTime: '' };
  },

  async loadDashboard() {
    if (this._dashboardLoading) return;
    this._dashboardLoading = true;
    this.dashboardLoading = true;
    this.resetDashboardState();
    try {
      const today = this.todayDateString();

      const [
        summaryR, healthR, todayStatsR, dailyR, severityR, todayLogsR,
        deptTopR, pendingFeedbackR, schedulerStatusR, relaySummaryR,
      ] = await Promise.all([
        apiGet('/api/stats/summary').catch(() => ({ data: {} })),
        apiGet('/api/health').catch(() => ({ data: { components: {} } })),
        apiGet('/api/stats/today').catch(() => ({ data: { total: 0, success: 0, inconsistency: 0 } })),
        apiGet('/api/stats/daily', { params: { days: 30 } }).catch(() => ({ data: { items: [] } })),
        apiGet('/api/stats/severity').catch(() => ({ data: { items: [] } })),
        apiGet('/api/logs', { params: { page: 1, limit: 200, push_time_from: today, push_time_to: today } }).catch(() => ({ data: { items: [] } })),
        apiGet('/api/stats/anomaly-top', { params: { group_by: 'dept' } }).catch(() => ({ data: { items: [] } })),
        apiGet('/api/qc/feedback/cases', { params: { page: 1, limit: 1, status: 'pending', days: 30 } }).catch(() => ({ data: { total: 0 } })),
        apiGet('/api/scheduler/status').catch(() => ({ data: {} })),
        apiGet('/api/patient-qc/relay-alert/summary').catch(() => ({ data: {} })),
      ]);

      this.summary = summaryR.data || {};
      this.healthComps = healthR.data?.components || {};
      this.overallHealth = healthR.data?.status || 'healthy';

      const todayTotal = Number(todayStatsR.data?.total || 0);
      const todaySuccess = Number(todayStatsR.data?.success || 0);
      const todayInconsistency = Number(todayStatsR.data?.inconsistency || 0);
      const pendingCases = Number(pendingFeedbackR.data?.total || 0) || 0;

      const successRate = todayTotal ? (todaySuccess / todayTotal) * 100 : 0;

      const schedulerData = schedulerStatusR.data || {};
      const lastRunRaw = this.extractSchedulerLastRun(schedulerData);
      const lastRunTime = lastRunRaw ? this.formatDateTime(lastRunRaw) : '--';
      const nextRunRaw = schedulerData.next_run || '';
      const nextRunTime = nextRunRaw ? this.formatDateTime(nextRunRaw) : '';

      const severityItems = severityR.data?.items || [];
      const highRisk = severityItems.find((i) => i.severity === 'high');
      const highRiskCount = Number(highRisk?.count || 0);

      const relaySummary = relaySummaryR.data || {};
      const relayTotal = Number(relaySummary.total || 0);
      const relaySuccess = Number(relaySummary.success || 0);
      const relayFailed = Number(relaySummary.failed || 0);
      const relayViewed = Number(relaySummary.viewed || 0);
      const relayUnviewed = Number(relaySummary.unviewed || 0);

      const relaySuccessRate = relaySummary.success_rate ?? (relayTotal ? (relaySuccess / relayTotal) * 100 : null);
      const viewRate = relaySummary.view_rate ?? (relayTotal ? (relayViewed / relayTotal) * 100 : null);

      const dailyItems = dailyR.data?.items || [];

      const todayLogs = todayLogsR.data?.items || [];
      let highRiskLogs = todayLogs.filter(
        (item) => Number(item.inconsistency || 0) === 1
          && (item.severity === 'high' || Number(item.risk_score || 0) >= 80),
      );
      if (highRiskLogs.length === 0) {
        try {
          const recentR = await apiGet('/api/logs', { params: { page: 1, limit: 50 } });
          const recentItems = recentR.data?.items || [];
          highRiskLogs = recentItems.filter(
            (item) => Number(item.inconsistency || 0) === 1
              && (item.severity === 'high' || Number(item.risk_score || 0) >= 80),
          );
        } catch (_) {}
      }

      const dashboardEvents = highRiskLogs.slice(0, 5).map((item) => ({
        id: item.id,
        patient_name: item.patient_name || '--',
        patient_id: item.patient_id || '--',
        dept: item.dept || '--',
        risk_score: Number(item.risk_score || 0),
        severity: item.severity || '',
        push_time: this.formatDateTime(item.push_time),
        raw_push_time: item.push_time || '',
      })).sort((a, b) => this.parseTimeValue(b.raw_push_time) - this.parseTimeValue(a.raw_push_time));

      this.dashboardKpis = {
        date: today,
        total: todayTotal,
        todaySuccess,
        successRate,
        inconsistency: todayInconsistency,
        highRisk: highRiskCount,
        pendingFeedback: pendingCases,
        relaySuccessRate,
        relayRecentTotal: relayTotal,
        viewRate,
        relayViewed,
        closureRate: null,
      };

      this.dashboardDeptTop = (deptTopR.data?.items || []).slice(0, 10);
      this.dashboardEvents = dashboardEvents;
      this.dashboardRelay = {
        total: relayTotal,
        success: relaySuccess,
        failed: relayFailed,
        viewed: relayViewed,
        unviewed: relayUnviewed,
      };
      this.dashboardScheduler = { lastRunTime, nextRunTime };

      this.dashboardAlerts = dashboardEvents;
      this.dashboardToday = {
        date: today,
        total: todayTotal,
        success: todaySuccess,
        inconsistency: todayInconsistency,
        newCases: todayInconsistency,
        pendingCases,
        latestRunTime: lastRunTime,
      };

      this.$nextTick(() => this.renderDashboardCharts(dailyItems, severityItems));
    } catch (e) {
      this.showApiError(e, '加载仪表盘失败');
    } finally {
      this._dashboardLoading = false;
      this.dashboardLoading = false;
    }
  },

  renderDashboardCharts(dailyItems, severityItems) {
    this.renderDashTrendChart(dailyItems);
    this.renderDashSeverityChart(severityItems);
  },

  renderDashTrendChart(dailyItems) {
    const el = document.getElementById('dashTrendChart');
    if (!el) return;
    const chart = this.getChart('dashTrendChart');
    if (!chart) return;
    const data = dailyItems || [];
    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['推送总数', '成功', '不一致', '失败'], bottom: 0, textStyle: { color: '#b0c4de' } },
      grid: { left: 36, right: 10, top: 10, bottom: 40 },
      xAxis: { type: 'category', data: data.map((i) => i.date), axisLabel: { rotate: 40, fontSize: 10, color: '#8f9bb0' } },
      yAxis: { type: 'value', axisLabel: { color: '#8f9bb0' } },
      series: [
        createLineSeries('推送总数', data.map((i) => i.total), '#1677ff'),
        createLineSeries('成功', data.map((i) => i.success), '#52c41a'),
        createLineSeries('不一致', data.map((i) => i.inconsistency), '#fa8c16'),
        createLineSeries('失败', data.map((i) => i.failed), '#ff4d4f'),
      ],
    });
  },

  renderDashSeverityChart(severityItems) {
    const el = document.getElementById('dashSeverityChart');
    if (!el) return;
    const chart = this.getChart('dashSeverityChart');
    if (!chart) return;
    const items = severityItems || [];
    const colors = { high: '#ff4d4f', medium: '#fa8c16', low: '#1677ff', unknown: '#8f9bb0' };
    chart.setOption({
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, textStyle: { color: '#b0c4de' } },
      series: [{
        type: 'pie',
        radius: ['45%', '72%'],
        center: ['50%', '48%'],
        label: { color: '#b0c4de' },
        data: items.map((i) => ({
          name: { high: '高危', medium: '中危', low: '低危', unknown: '未知' }[i.severity] || i.severity,
          value: i.count,
          itemStyle: { color: colors[i.severity] || '#8f9bb0' },
        })),
      }],
    });
  },
};
