import { apiDelete, apiGet, apiPost } from '../utils/api.js?v=20260524-download-blob';
import { buildRenderBlocks } from './render_engine.js';

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
      if (!Array.isArray(this.auditTypeOptions) || !this.auditTypeOptions.length) {
        const optionsResp = await apiGet('/api/logs/filters/options');
        this.auditTypeOptions = Array.isArray(optionsResp.data?.audit_type_options) ? optionsResp.data.audit_type_options : [];
      }
      const params = { page: this.logPage, limit: this.logLimit };
      Object.entries(this.lf).forEach(([k, v]) => { if (v) params[k] = v; });

      // DEF-01 修复：时间窗口直接作为服务端过滤参数传入，不在客户端过滤当前页
      // 客户端过滤只能覆盖已加载的分页数据，跨页记录会被漏掉
      if (this.logTimeWindow) {
        if (!params.date_from) params.date_from = this.logTimeWindow.dateFrom;
        if (!params.date_to) params.date_to = this.logTimeWindow.dateTo;
      }

      const [logsResp, statsResp] = await Promise.all([
        apiGet('/api/logs', { params }),
        apiGet('/api/logs/skip-reasons/stats', { params: { date_from: params.date_from, date_to: params.date_to, push_time_from: params.push_time_from, push_time_to: params.push_time_to, dept: params.dept, audit_type_code: params.audit_type_code } }),
      ]);
      this.logs = logsResp.data.items || [];
      this.logTotal = logsResp.data.total || 0;
      this.selectedLogIds = [];
      this.skipReasonStats = statsResp.data || { total_skipped: 0, items: [] };
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

  logAuditTypeLabel(row) {
    return row?.audit_type_name || row?.audit_type_code || '默认病程护理核查';
  },

  logFailureReason(row) {
    return row?.failure_reason || row?.error_msg || row?.skip_reason_label || row?.skip_reason || '';
  },

  logAlertLevelLabel(level) {
    const labels = { red: '红灯', yellow: '黄灯', blue: '蓝灯', gray: '灰灯' };
    return labels[String(level || '').toLowerCase()] || level || '--';
  },

  logAlertLevelTagType(level) {
    const map = { red: 'danger', yellow: 'warning', blue: 'primary', gray: 'info' };
    return map[String(level || '').toLowerCase()] || 'info';
  },

  logPushStrategyLabel(strategy) {
    const labels = { immediate: '立即推送', batch: '批量汇总', shift_summary: '交班汇总', review_only: '仅复核' };
    return labels[String(strategy || '').toLowerCase()] || strategy || '--';
  },

  logOutcomeBucketLabel(bucket) {
    const labels = { primary: '主要问题', secondary: '次要问题', none: '无问题' };
    return labels[String(bucket || '').toLowerCase()] || bucket || '--';
  },

  logClosureHoursLabel(hours) {
    const value = Number(hours || 0);
    return value > 0 ? `${value} 小时` : '--';
  },

  logEvidenceTitle(detail) {
    const code = String(detail?.audit_type_code || '').toLowerCase();
    const name = String(detail?.audit_type_name || '');
    if (code.includes('lab') || code.includes('exam') || name.includes('检验') || name.includes('检查')) return '检验检查与病程/护理证据';
    if (code.includes('frontpage') || code.includes('surgery') || name.includes('首页') || name.includes('手术')) return '首页手术与首次病程证据';
    if (code.includes('progress') || code.includes('nursing') || name.includes('病程') || name.includes('护理')) return '病程记录与护理记录证据';
    return '推送证据';
  },

  _asLogEvidenceArray(value) {
    if (Array.isArray(value)) return value.filter((item) => item !== null && item !== undefined && String(item).trim() !== '');
    if (value && typeof value === 'object') return [value];
    if (String(value || '').trim()) return [String(value).trim()];
    return [];
  },

  _collectLogExtraEvidence(extra, keys) {
    const source = extra && typeof extra === 'object' && !Array.isArray(extra) ? extra : {};
    const items = [];
    keys.forEach((key) => {
      this._asLogEvidenceArray(source[key]).forEach((item) => items.push(item));
    });
    return items;
  },

  _logStructuredMrText(detail) {
    const parsed = this.parsePossibleJson(detail?.mr_text);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  },

  _extractLogTextSection(text, startMarkers, endMarkers = []) {
    const source = String(text || '');
    if (!source) return '';
    let start = -1;
    let startLength = 0;
    (startMarkers || []).some((marker) => {
      const idx = source.indexOf(marker);
      if (idx >= 0) {
        start = idx;
        startLength = marker.length;
        return true;
      }
      return false;
    });
    if (start < 0) return '';
    const contentStart = start + startLength;
    let end = source.length;
    (endMarkers || []).forEach((marker) => {
      const idx = source.indexOf(marker, contentStart);
      if (idx >= 0 && idx < end) end = idx;
    });
    return source.substring(contentStart, end).trim();
  },

  logOriginalEvidenceSections(detail) {
    const code = String(detail?.audit_type_code || '').toLowerCase();
    const name = String(detail?.audit_type_name || '');
    const structured = this._logStructuredMrText(detail);
    const isLabExam = code.includes('lab') || code.includes('exam') || name.includes('检验') || name.includes('检查');
    const isFrontpage = code.includes('frontpage') || code.includes('surgery') || name.includes('首页') || name.includes('手术');

    if (isLabExam) {
      const progressRoot = structured['病程'] || structured.progress || {};
      const nursingRoot = structured['护理'] || structured.nursing || {};
      return [
        { title: '检验检查', items: this._asLogEvidenceArray(structured['检验检查'] || structured.lab_exam || structured.labs || structured.exams), text: '' },
        { title: '病程记录', items: this._asLogEvidenceArray(structured['病程记录'] || progressRoot['病程记录'] || structured.progress_notes), text: detail?.medical_documents_text || this._extractLogTextSection(detail?.mr_text, ['[病程记录]'], ['[护理记录]']) },
        { title: '护理记录', items: this._asLogEvidenceArray(structured['护理记录'] || nursingRoot['护理记录'] || structured.nursing_records), text: detail?.nursing_records_text || this._extractLogTextSection(detail?.mr_text, ['[护理记录]'], []) },
      ];
    }
    if (isFrontpage) {
      const frontpageText = this._extractLogTextSection(detail?.mr_text, ['[首页手术与诊断]'], ['[首次病程记录]']);
      const firstProgressText = this._extractLogTextSection(detail?.mr_text, ['[首次病程记录]'], ['[核查规则]', '[注意事项]']);
      return [
        { title: '首页/手术信息', items: this._asLogEvidenceArray(structured['首页手术'] || structured['首页信息'] || structured.frontpage || structured.surgeries), text: frontpageText },
        { title: '首次病程记录', items: this._asLogEvidenceArray(structured['首次病程'] || structured.first_progress), text: detail?.medical_documents_text || firstProgressText },
      ];
    }
    return [
      { title: '病程记录', items: [], text: detail?.medical_documents_text || this._extractLogTextSection(detail?.mr_text, ['[病历文书]'], ['[护理记录]']) || detail?.mr_text || '' },
      { title: '护理记录', items: [], text: detail?.nursing_records_text || this._extractLogTextSection(detail?.mr_text, ['[护理记录]'], []) },
    ];
  },

  logDimensionEvidenceSections(detail, row) {
    const code = String(detail?.audit_type_code || '').toLowerCase();
    const name = String(detail?.audit_type_name || '');
    const extra = row?.extra && typeof row.extra === 'object' ? row.extra : {};
    const isLabExam = code.includes('lab') || code.includes('exam') || name.includes('检验') || name.includes('检查');
    const isFrontpage = code.includes('frontpage') || code.includes('surgery') || name.includes('首页') || name.includes('手术');

    if (isLabExam) {
      return [
        { title: '检验检查证据', items: this._collectLogExtraEvidence(extra, ['evidence_lab', 'evidence_exam', 'lab_evidence', 'exam_evidence', 'abnormal_labs', 'abnormal_exams']), text: '' },
        { title: '病程响应', items: this._asLogEvidenceArray(row?.medical_evidence), text: row?.medical_content || '' },
        { title: '护理响应', items: this._asLogEvidenceArray(row?.nursing_evidence), text: row?.nursing_content || '' },
      ];
    }
    if (isFrontpage) {
      return [
        { title: '首页/手术信息', items: this._collectLogExtraEvidence(extra, ['evidence_frontpage', 'frontpage_evidence', 'surgery_evidence', 'diagnosis_evidence']), text: row?.medical_content || '' },
        { title: '首次病程记录', items: this._collectLogExtraEvidence(extra, ['evidence_first_progress', 'first_progress_evidence']), text: row?.nursing_content || '' },
      ];
    }
    return [
      { title: '病程记录', items: this._asLogEvidenceArray(row?.medical_evidence), text: row?.medical_content || '' },
      { title: '护理记录', items: this._asLogEvidenceArray(row?.nursing_evidence), text: row?.nursing_content || '' },
    ];
  },

  formatLogEvidenceItem(item) {
    if (typeof item === 'string') return item;
    try {
      return JSON.stringify(item, null, 2);
    } catch (e) {
      return String(item || '');
    }
  },

  hasLogEvidenceSectionContent(section) {
    return !!((section?.items || []).length || String(section?.text || '').trim());
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
      const parsedResponse = this.parsePossibleJson(detail.response_json) || this.parsePossibleJson(detail.ai_result) || {};
      const auditResult = (detail.audit_result && typeof detail.audit_result === 'object') ? detail.audit_result : {};
      const storedAudit = Object.keys(auditResult).length
        ? auditResult
        : ((detail.stored_audit && typeof detail.stored_audit === 'object') ? detail.stored_audit : {});
      const storedDimensions = Array.isArray(storedAudit.dimensions) ? storedAudit.dimensions : [];
      const storedConclusion = storedAudit.conclusion && typeof storedAudit.conclusion === 'object' ? storedAudit.conclusion : {};
      const renderContext = {
        ...(parsedResponse && typeof parsedResponse === 'object' && !Array.isArray(parsedResponse) ? parsedResponse : {}),
        audit_result: storedAudit,
        stored_audit: storedAudit,
        stored_dimensions: storedDimensions,
        stored_conclusion: storedConclusion,
      };
      // 兼容旧版纯文本 mr_text：新版结构化 mr_text 由展示 helper 直接识别。
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
        raw_debug_pretty: this.prettyJson(detail.raw_debug || parsedResponse),
        ai_result_pretty: this.prettyJson(detail.ai_result),
        ai_structured: aiStructured,
        medical_documents_text: medicalDocumentsText,
        nursing_records_text: nursingRecordsText,
        audit_result: storedAudit,
        stored_dimensions: storedDimensions,
        stored_conclusion: storedConclusion,
        raw_response_json: detail.raw_debug || {
          dify_result: parsedResponse,
          parse_status: detail.parse_status,
          parse_error: detail.parse_error,
          workflow_run_id: detail.workflow_run_id,
          task_id: detail.task_id,
        },
        ...buildRenderBlocks(
          detail.audit_type_display,
          renderContext,
        ),
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
    if (command === 'delete') return this.deleteSingleLog(row.id);
  },

  async deleteSingleLog(logId) {
    try {
      await ElementPlus.ElMessageBox.confirm('删除后该推送日志及关联审计结果、质控反馈将不可恢复，确定删除吗？', '删除推送日志', { type: 'warning' });
    } catch (e) {
      return;
    }
    await this.runConfigAction(async () => {
      await apiDelete(`/api/logs/${logId}`);
      if (this.logDetail && this.logDetail.id === logId) {
        this.closeLogDetail();
      }
      await this.loadLogs();
    }, '推送日志已删除');
  },

  async deleteSelectedLogs() {
    if (!this.selectedLogIds.length) {
      ElementPlus.ElMessage.warning('请先选择需要删除的日志');
      return;
    }
    try {
      await ElementPlus.ElMessageBox.confirm(`将删除 ${this.selectedLogIds.length} 条推送日志及关联审计结果、质控反馈，确定删除吗？`, '批量删除推送日志', { type: 'warning' });
    } catch (e) {
      return;
    }
    await this.runConfigAction(async () => {
      await apiDelete('/api/logs/bulk/delete', { data: { log_ids: this.selectedLogIds } });
      await this.loadLogs();
    }, '推送日志已删除');
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
    this.lf = { status: '', dept: '', date_from: '', date_to: '', patient_id: '', patient_name: '', audit_type_code: '' };
    this.logTimeWindow = null;
    this.loadLogs(1);
  },

  logHasActiveFilters() {
    const f = this.lf || {};
    return Object.entries(f).some(([, v]) => v !== null && v !== undefined && String(v).trim() !== '');
  },

  async exportCsv() {
    const params = { ...this.lf };
    if (this.logTimeWindow?.dateFrom || this.logTimeWindow?.date_from) params.date_from = this.logTimeWindow.dateFrom || this.logTimeWindow.date_from;
    if (this.logTimeWindow?.dateTo || this.logTimeWindow?.date_to) params.date_to = this.logTimeWindow.dateTo || this.logTimeWindow.date_to;
    Object.keys(params).forEach((key) => {
      if (params[key] === '' || params[key] === null || params[key] === undefined) delete params[key];
    });
    try {
      const resp = await apiGet('/api/logs/export/csv', { params, responseType: 'blob' });
      const blob = new Blob([resp.data], { type: resp.headers?.['content-type'] || 'text/csv;charset=utf-8' });
      const disposition = resp.headers?.['content-disposition'] || '';
      const match = disposition.match(/filename="?([^";]+)"?/i);
      const filename = match?.[1] || `push_log_${Date.now()}.csv`;
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (e) {
      this.showApiError(e, '导出 CSV 失败');
    }
  },
};
