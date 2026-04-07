import { apiGet } from '../utils/api.js';

export const statsMethods = {
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

  async loadStats() {
    try {
      const s = await apiGet('/api/stats/summary');
      this.summary = s.data || {};
    } catch (e) {
      this.showApiError(e, '加载统计摘要失败');
    }

    this.$nextTick(async () => {
      // BUG-07 修复：并行拉取全部数据，图表独立渲染，单个失败不中断其余
      let dr, sr, br, dimR, monthlyR, anomalyDeptR, anomalyPatientR;
      try {
        [dr, sr, br, dimR, monthlyR, anomalyDeptR, anomalyPatientR] = await Promise.all([
          apiGet('/api/stats/daily', { params: { days: 30 } }),
          apiGet('/api/stats/severity'),
          apiGet('/api/stats/dept'),
          apiGet('/api/stats/dimensions'),
          apiGet('/api/stats/monthly'),
          apiGet('/api/stats/anomaly-top', { params: { group_by: 'dept' } }),
          apiGet('/api/stats/anomaly-top', { params: { group_by: 'patient' } }),
        ]);
      } catch (e) {
        this.showApiError(e, '加载图表数据失败');
        return;
      }

      // 每个图表独立渲染，失败只打 warn，不中断其余
      this._renderTrendChart(dr);
      this._renderPieChart(sr);
      this._renderBarChart(br);
      this._renderDimChart(dimR);
      this._renderMonthlyChart(monthlyR);
      this._renderAnomalyDeptChart(anomalyDeptR);
      this._renderAnomalyPatientChart(anomalyPatientR);
    });
  },

  _renderTrendChart(dr) {
    try {
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
    } catch (e) { console.warn('trendChart 渲染失败', e); }
  },

  _renderPieChart(sr) {
    try {
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
    } catch (e) { console.warn('pieChart 渲染失败', e); }
  },

  _renderBarChart(br) {
    try {
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
    } catch (e) { console.warn('barChart 渲染失败', e); }
  },

  _renderDimChart(dimR) {
    try {
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
    } catch (e) { console.warn('dimChart 渲染失败', e); }
  },

  _renderMonthlyChart(monthlyR) {
    try {
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
    } catch (e) { console.warn('monthlyChart 渲染失败', e); }
  },

  _renderAnomalyDeptChart(anomalyDeptR) {
    try {
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
    } catch (e) { console.warn('anomalyDeptChart 渲染失败', e); }
  },

  _renderAnomalyPatientChart(anomalyPatientR) {
    try {
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
    } catch (e) { console.warn('anomalyPatientChart 渲染失败', e); }
  },

  // BUG-07 修复：复用已有实例而非每次 dispose+重建，避免图表闪烁
  // 只有当容器 DOM 真正变化（或首次）时才新建实例
  getChart(elId) {
    const el = document.getElementById(elId);
    if (!el) return null;
    const existing = echarts.getInstanceByDom(el);
    if (existing) {
      this.chartInstances[elId] = existing;
      return existing;
    }
    const chart = echarts.init(el);
    this.chartInstances[elId] = chart;
    return chart;
  },
};
