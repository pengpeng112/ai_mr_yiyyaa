import { apiGet, apiPost } from '../utils/api.js';

export const logsMethods = {
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

  async loadLogs(page) {
    if (page) this.logPage = page;
    try {
      const params = { page: this.logPage, limit: this.logLimit };
      Object.entries(this.lf).forEach(([k, v]) => { if (v) params[k] = v; });

      // DEF-01 修复：时间窗口直接作为服务端过滤参数传入，不在客户端过滤当前页
      // 客户端过滤只能覆盖已加载的分页数据，跨页记录会被漏掉
      if (this.logTimeWindow) {
        if (!params.date_from) params.date_from = this.logTimeWindow.dateFrom;
        if (!params.date_to) params.date_to = this.logTimeWindow.dateTo;
      }

      const r = await apiGet('/api/logs', { params });
      this.logs = r.data.items || [];
      this.logTotal = r.data.total || 0;
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
      const r = await apiGet(`/api/logs/${logId}`);
      const detail = r.data || {};
      const aiStructured = this.parseAiResultStructured(detail);
      // 拆分 mr_text 为病历文书 / 护理记录两部分
      let medicalDocumentsText = '';
      let nursingRecordsText = '';
      if (detail.mr_text) {
        const nursingIdx = detail.mr_text.indexOf('\n[护理记录]');
        if (nursingIdx >= 0) {
          const medicalIdx = detail.mr_text.indexOf('[病历文书]');
          medicalDocumentsText = medicalIdx >= 0
            ? detail.mr_text.substring(medicalIdx + '[病历文书]'.length, nursingIdx).trim()
            : detail.mr_text.substring(0, nursingIdx).trim();
          nursingRecordsText = detail.mr_text.substring(nursingIdx + '\n[护理记录]'.length).trim();
        }
      }
      this.logDetail = {
        ...detail,
        request_json_pretty: this.prettyJson(detail.request_json),
        response_json_pretty: this.prettyJson(detail.response_json || detail.ai_result),
        ai_result_pretty: this.prettyJson(detail.ai_result),
        ai_structured: aiStructured,
        medical_documents_text: medicalDocumentsText,
        nursing_records_text: nursingRecordsText,
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
      await apiPost(`/api/logs/${logId}/retry`);
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
      await apiPost('/api/push/retry', { log_ids: this.selectedLogIds });
      await this.loadLogs();
    }, `已提交 ${this.selectedLogIds.length} 条日志重推`);
  },

  async viewReport(logId) {
    await this.runConfigAction(async () => {
      const r = await apiGet(`/api/report/${logId}/data`);
      this.reportData = r.data;
      this.reportVisible = true;
    });
  },

  openPrintableReport(logId) {
    window.open(`/report/${logId}`, '_blank');
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
};
