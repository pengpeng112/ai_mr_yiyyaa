import { apiGet, apiPost } from '../utils/api.js';

export const feedbackMethods = {
  normalizeFeedbackStatus(status) {
    const value = String(status || '').toLowerCase();
    if (['pending', '待处理'].includes(value)) return 'pending';
    if (['acknowledged', 'confirmed', '已确认'].includes(value)) return 'acknowledged';
    if (['rectified', 'fixed', '已整改'].includes(value)) return 'rectified';
    if (['closed', 'done', '已关闭'].includes(value)) return 'closed';
    // DEF-02 修复：未知状态不再静默降级为 pending，保留原始值供调用方判断
    // 若确实无法识别，返回 'unknown' 而非 'pending'
    return value || 'unknown';
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

  onFeedbackSearchInput() {
    if (!this.debouncedLoadFeedbackFn) {
      this.debouncedLoadFeedbackFn = this.debounce(() => this.loadFeedbackList(1), 500);
    }
    this.feedbackPage = 1;
    this.debouncedLoadFeedbackFn();
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
      apiGet('/api/departments').catch(() => ({ data: [] })),
      apiGet('/api/users', { params: { page: 1, limit: 100 } }).catch(() => ({ data: { items: [] } })),
    ]);
    this.feedbackDepartments = Array.isArray(deptResp.data) ? deptResp.data : [];
    this.feedbackUsers = userResp.data.items || [];
  },

  async loadFeedbackList(page) {
    if (page) this.feedbackPage = page;

    // DEF-06 修复：看板模式需要加载全量数据（不受分页截断）
    // 看板展示各状态全部病例，分页 20 条会导致各列数量不准确
    const isKanban = this.feedbackViewType === 'kanban';
      const params = {
        page: this.feedbackPage,
        limit: isKanban ? 100 : this.feedbackLimit,
      };
    Object.entries(this.feedbackFilter).forEach(([k, v]) => {
      if (v !== '' && v !== null && v !== undefined) params[k] = v;
    });
    // 看板模式不按单一状态过滤，展示所有状态
    if (isKanban && params.status) delete params.status;

    try {
      const r = await apiGet('/api/qc/feedback/cases', { params });
      this.feedbackList = r.data.items || [];
      this.feedbackTotal = r.data.total || 0;
      this.feedbackStats = r.data.stats || {};
    } catch (e) {
      this.showApiError(e, '加载质控反馈列表失败');
    }
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

  _parseRawRecordItems(text) {
    if (!text || !text.trim()) return [];
    // 按空行分块，再识别以 "数字." 开头的块作为一条记录
    const blocks = text.split(/\n{2,}/);
    const items = [];
    let current = null;
    for (const block of blocks) {
      const trimmed = block.trim();
      if (!trimmed) continue;
      const headerMatch = trimmed.match(/^(\d+)\.\s([\s\S]*)/);
      if (headerMatch) {
        if (current) items.push(current);
        current = { index: parseInt(headerMatch[1], 10), text: trimmed };
      } else {
        if (current) {
          current.text += '\n\n' + trimmed;
        } else {
          current = { index: items.length + 1, text: trimmed };
        }
      }
    }
    if (current) items.push(current);
    return items;
  },

  async viewFeedbackDetail(logId) {
    await this.runConfigAction(async () => {
      this.feedbackDetailLoading = true;
      const r = await apiGet(`/api/qc/feedback/cases/${logId}`);
      this.feedbackDetail = r.data;
      // 将原始文书文本解析成条目数组，便于前端逐条展示
      if (this.feedbackDetail) {
        this.feedbackDetail._medical_items = this._parseRawRecordItems(this.feedbackDetail.medical_documents_text);
        this.feedbackDetail._nursing_items = this._parseRawRecordItems(this.feedbackDetail.nursing_records_text);
      }
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
      await apiPost(`/api/qc/feedback/cases/${this.feedbackDetail.log_id}/confirm`, {
        action,
        review_comment: this.feedbackConfirmForm.review_comment || '',
      });
      await this.viewFeedbackDetail(this.feedbackDetail.log_id);
      await this.loadFeedbackList(this.feedbackPage);
    }, action === 'closed' ? '已确认无问题并关闭' : '已确认并反馈');
  },

  async exportFeedbackExcel() {
    await this.runConfigAction(async () => {
      const params = {};
      Object.entries(this.feedbackFilter || {}).forEach(([k, v]) => {
        if (v !== '' && v !== null && v !== undefined) params[k] = v;
      });
      if (this.feedbackViewType === 'kanban' && params.status) delete params.status;

      const resp = await apiGet('/api/qc/feedback/export/excel', { params, responseType: 'blob' });
      const blob = new Blob([resp.data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      const disposition = resp.headers?.['content-disposition'] || '';
      const matched = disposition.match(/filename=([^;]+)/i);
      const filename = matched ? decodeURIComponent(matched[1].replace(/"/g, '')) : `feedback_${Date.now()}.xlsx`;

      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    }, 'Excel 导出已开始');
  },
};
