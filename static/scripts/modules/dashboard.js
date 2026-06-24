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

  relayAlertStatusLabel(status) {
    return {
      success: '成功',
      failed: '失败',
      pending: '待发送',
      suppressed: '已抑制',
    }[status] || status || '--';
  },

  openDashboardRelayAlert(item) {
    const patientId = item?.patient_id && item.patient_id !== '--' ? item.patient_id : '';
    this.relayAlertFilter = {
      ...(this.relayAlertFilter || {}),
      patient_id: patientId,
      status: '',
      viewed_flag: '',
    };
    this.switchMenu('relay-alert-logs');
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
      this.relayAlertFilter = {
        ...(this.relayAlertFilter || {}),
        patient_id: '',
        status: '',
        viewed_flag: '',
      };
      this.switchMenu('relay-alert-logs');
      return;
    }
  },

  resetDashboardState() {
    this.dashboardKpis = {
      date: this.todayDateString(),
      total: 0,
      todaySuccess: 0,
      todaySkipped: 0,
      successRate: 0,
      effectiveTotal: 0,
      inconsistencyRate: null,
      inconsistency: 0,
      highRisk: 0,
      pendingFeedback: 0,
      relaySuccessRate: null,
      relayRecentTotal: 0,
      relayFailed: 0,
      viewRate: null,
      relayViewed: 0,
      relayUnviewed: 0,
    };
    this.dashboardDeptTop = [];
    this.dashboardEvents = [];
    this.dashboardRelay = { total: 0, success: 0, failed: 0, viewed: 0, unviewed: 0 };
    this.dashboardRelayRecent = [];
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
        deptTopR, dimensionR, pendingFeedbackR, schedulerStatusR, relaySummaryR, relayRecentR,
      ] = await Promise.all([
        apiGet('/api/stats/summary').catch(() => ({ data: {} })),
        apiGet('/api/health').catch(() => ({ data: { components: {} } })),
        apiGet('/api/stats/today').catch(() => ({ data: { total: 0, success: 0, skipped: 0, inconsistency: 0 } })),
        apiGet('/api/stats/daily', { params: { days: 30 } }).catch(() => ({ data: { items: [] } })),
        apiGet('/api/stats/severity').catch(() => ({ data: { items: [] } })),
        apiGet('/api/logs', { params: { page: 1, limit: 200, push_time_from: today, push_time_to: today } }).catch(() => ({ data: { items: [] } })),
        apiGet('/api/stats/anomaly-top', { params: { group_by: 'dept' } }).catch(() => ({ data: { items: [] } })),
        apiGet('/api/stats/dimensions').catch(() => ({ data: { items: [] } })),
        apiGet('/api/qc/feedback/cases', { params: { page: 1, limit: 1, status: 'pending', days: 30 } }).catch(() => ({ data: { total: 0 } })),
        apiGet('/api/scheduler/status').catch(() => ({ data: {} })),
        apiGet('/api/patient-qc/relay-alert/summary').catch(() => ({ data: {} })),
        apiGet('/api/patient-qc/relay-alert/logs', { params: { page: 1, limit: 5 } }).catch(() => ({ data: { items: [] } })),
      ]);

      this.summary = summaryR.data || {};
      const rawHealthComps = healthR.data?.components || {};
      this.healthComps = Object.fromEntries(Object.entries(rawHealthComps).filter(([key]) => key !== 'dify'));
      this.overallHealth = healthR.data?.status || 'healthy';

      const todayTotal = Number(todayStatsR.data?.total || 0);
      const todaySuccess = Number(todayStatsR.data?.success || 0);
      const todaySkipped = Number(todayStatsR.data?.skipped || 0);
      const todayInconsistency = Number(todayStatsR.data?.inconsistency || 0);
      const pendingCases = Number(pendingFeedbackR.data?.total || 0) || 0;

      const effectiveTotal = Math.max(0, todayTotal - todaySkipped);
      const successRate = effectiveTotal ? (todaySuccess / effectiveTotal) * 100 : 0;
      const inconsistencyRate = effectiveTotal ? (todayInconsistency / effectiveTotal) * 100 : null;

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
      const dimensionItems = (dimensionR.data?.items || [])
        .slice()
        .sort((a, b) => {
          const aIssues = Number(a.fail_count || 0) + Number(a.warn_count || 0);
          const bIssues = Number(b.fail_count || 0) + Number(b.warn_count || 0);
          return bIssues - aIssues;
        });

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

      const relayRecentItems = (relayRecentR.data?.items || []).slice(0, 5).map((item) => ({
        id: item.id,
        patient_id: item.patient_id || '--',
        dept: item.dept || '--',
        status: item.status || '',
        severity: item.severity || '',
        viewed_flag: Number(item.viewed_flag || 0),
        evidence_summary: item.evidence_summary || '',
        created_at: item.created_at || '',
      }));

      this.dashboardKpis = {
        date: today,
        total: todayTotal,
        todaySuccess,
        todaySkipped,
        successRate,
        effectiveTotal,
        inconsistencyRate,
        inconsistency: todayInconsistency,
        highRisk: highRiskCount,
        pendingFeedback: pendingCases,
        relaySuccessRate,
        relayRecentTotal: relayTotal,
        relayFailed,
        viewRate,
        relayViewed,
        relayUnviewed,
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
      this.dashboardRelayRecent = relayRecentItems;
      this.dashboardScheduler = { lastRunTime, nextRunTime };

      this.$nextTick(() => this.renderDashboardCharts(dailyItems, severityItems, dimensionItems));
    } catch (e) {
      this.showApiError(e, '加载仪表盘失败');
    } finally {
      this._dashboardLoading = false;
      this.dashboardLoading = false;
    }
  },

  renderDashboardCharts(dailyItems, severityItems, dimensionItems) {
    this.renderDashTrendChart(dailyItems);
    this.renderDashSeverityChart(severityItems);
    this.renderDashDimensionChart(dimensionItems);
  },

  renderDashTrendChart(dailyItems) {
    const el = document.getElementById('dashTrendChart');
    if (!el) return;
    const chart = this.getChart('dashTrendChart');
    if (!chart) return;
    const data = dailyItems || [];
    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['推送总数', '成功', '不一致', '失败'], bottom: 0, textStyle: { color: '#475569' } },
      grid: { left: 44, right: 14, top: 18, bottom: 44 },
      xAxis: { type: 'category', data: data.map((i) => i.date), axisLabel: { rotate: 30, fontSize: 10, color: '#64748b', interval: 'auto' } },
      yAxis: { type: 'value', axisLabel: { color: '#64748b' } },
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
      legend: { bottom: 0, textStyle: { color: '#475569' } },
      series: [{
        type: 'pie',
        radius: ['45%', '72%'],
        center: ['50%', '48%'],
        label: { color: '#475569' },
        data: items.map((i) => ({
          name: { high: '高危', medium: '中危', low: '低危', unknown: '未知' }[i.severity] || i.severity,
          value: i.count,
          itemStyle: { color: colors[i.severity] || '#8f9bb0' },
        })),
      }],
    });
  },

  _dimZhMap: {
    'Diagnosis Consistency': '诊断一致性',
    'Condition Consistency': '病情描述一致性',
    'Nursing Level Consistency': '护理级别一致性',
    'Timeline Consistency': '时间合理性',
    'Treatment Measure Consistency': '诊疗措施一致性',
    'Vital Sign Consistency': '生命体征一致性',
  },

  _dimName(name) {
    return this._dimZhMap[name] || name || '未命名';
  },

  renderDashDimensionChart(dimensionItems) {
    const el = document.getElementById('dashDimensionChart');
    if (!el) return;
    const chart = this.getChart('dashDimensionChart');
    if (!chart) return;
    const items = (dimensionItems || []).slice(0, 8);
    chart.setOption({
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { data: ['不一致', '警告', '通过'], bottom: 0, textStyle: { color: '#475569' } },
      grid: { left: 100, right: 20, top: 10, bottom: 46, containLabel: true },
      xAxis: { type: 'value', axisLabel: { color: '#64748b', fontSize: 10 } },
      yAxis: {
        type: 'category',
        data: items.map((i) => this._dimName(i.dimension)),
        axisLabel: { color: '#475569', fontSize: 11, overflow: 'truncate', width: 80 },
      },
      series: [
        { name: '不一致', type: 'bar', stack: 'total', data: items.map((i) => Number(i.fail_count || 0)), itemStyle: { color: '#dc2626' } },
        { name: '警告', type: 'bar', stack: 'total', data: items.map((i) => Number(i.warn_count || 0)), itemStyle: { color: '#f97316' } },
        { name: '通过', type: 'bar', stack: 'total', data: items.map((i) => Number(i.pass_count || 0)), itemStyle: { color: '#16a34a' } },
      ],
    });
  },
};
