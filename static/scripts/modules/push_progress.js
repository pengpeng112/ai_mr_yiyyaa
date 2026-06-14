import { apiGet } from '../utils/api.js';

export const pushProgressMethods = {
  async loadPushProgressPage() {
    this.ppFilter = { status: '', trigger_type: '', date_range: [] };
    this.ppPage = 1;
    await this.loadPushProgressList(1);
  },

  async loadPushProgressList(page) {
    if (page) this.ppPage = page;
    this.ppLoading = true;
    this.ppList = [];
    try {
      const f = this.ppFilter || {};
      const params = { page: this.ppPage, limit: this.ppPageSize };
      if (f.status) params.status = f.status;
      if (f.trigger_type) params.trigger_type = f.trigger_type;
      if (Array.isArray(f.date_range) && f.date_range.length === 2) {
        params.date_from = this._pfDate(f.date_range[0]);
        params.date_to = this._pfDate(f.date_range[1]);
      }

      const [histR, currentR] = await Promise.all([
        apiGet('/api/scheduler/history', { params }).catch(() => ({ data: { items: [], total: 0 } })),
        apiGet('/api/push/tasks/latest').catch(() => ({ data: null })),
      ]);

      const items = histR.data?.items || [];
      this.ppList = items;
      this.ppTotal = histR.data?.total || 0;

      const allItems = items;
      this.ppStats = {
        total: this.ppTotal,
        running: allItems.filter((i) => i.status === 'running').length,
        completed: allItems.filter((i) => i.status === 'completed').length,
        failed: allItems.filter((i) => i.status === 'failed').length,
        avgDuration: allItems.length
          ? Math.round(allItems.reduce((s, i) => s + (Number(i.duration_seconds) || 0), 0) / allItems.length)
          : null,
        statsScope: 'page',
      };

      if (currentR.data && currentR.data.task_id) {
        const cur = currentR.data;
        if (!this.ppList.find((i) => i.task_id === cur.task_id)) {
          this.ppList.unshift({ ...cur, trigger_type: 'manual' });
          if (cur.status === 'running') this.ppStats.running++;
          this.ppTotal++;
        }
      }
    } catch (e) {
      this.showApiError(e, '加载推送进度失败');
    } finally {
      this.ppLoading = false;
    }
  },

  _pfDate(d) {
    if (!d) return '';
    if (typeof d === 'string') return d.substring(0, 10);
    const dt = new Date(d);
    const y = dt.getFullYear();
    const m = String(dt.getMonth() + 1).padStart(2, '0');
    const day = String(dt.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  },

  resetPPFilter() {
    this.ppFilter = { status: '', trigger_type: '', date_range: [] };
    this.loadPushProgressList(1);
  },

  selectPPTask(row) {
    this.ppDetail = row || null;
  },

  ppStatusLabel(status) {
    return { running: '运行中', completed: '已完成', failed: '失败', cancelled: '已取消' }[status] || status || '--';
  },

  ppStatusTagType(status) {
    return { running: 'warning', completed: 'success', failed: 'danger', cancelled: 'info' }[status] || 'info';
  },

  ppSuccessLabel(row) {
    const total = Number(row?.total_records || 0);
    const success = Number(row?.success_count || 0);
    if (!total) return '--';
    return (success / total * 100).toFixed(1) + '%';
  },

  ppSuccessTagType(row) {
    const total = Number(row?.total_records || 0);
    const success = Number(row?.success_count || 0);
    if (!total) return 'info';
    const rate = success / total;
    return rate >= 0.95 ? 'success' : rate >= 0.8 ? 'warning' : 'danger';
  },
};
