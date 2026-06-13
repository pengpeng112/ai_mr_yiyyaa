import { apiGet, apiPost, downloadBlobResponse } from '../utils/api.js';

export const patientQcMethods = {
  switchPatientQcTab(tab) {
    this.patientQcTab = tab || 'patients';
    if (tab === 'relay-alerts') {
      this.loadRelayAlertLogs();
    } else {
      this.loadPatientQcList();
    }
  },

  relayAlertStatusLabel(status) {
    return {
      success: '成功',
      failed: '失败',
      pending: '待发送',
      suppressed: '已抑制',
    }[status] || status || '--';
  },

  relayAlertStatusTag(status) {
    return {
      success: 'success',
      failed: 'danger',
      pending: 'warning',
      suppressed: 'info',
    }[status] || 'info';
  },

  relayAlertSeverityLabel(severity) {
    return { high: '高', medium: '中', low: '低' }[severity] || severity || '--';
  },

  relayAlertSeverityTag(severity) {
    return { high: 'danger', medium: 'warning', low: 'info' }[severity] || 'info';
  },

  relayAlertViewedLabel(row) {
    return Number(row?.viewed_flag || 0) ? '已查看' : '未查看';
  },

  relayAlertViewedTag(row) {
    return Number(row?.viewed_flag || 0) ? 'success' : 'info';
  },

  defaultRelayAlertSummary() {
    return {
      total: 0,
      success: 0,
      failed: 0,
      pending: 0,
      suppressed: 0,
      viewed: 0,
      unviewed: 0,
      success_rate: null,
      view_rate: null,
    };
  },

  async loadRelayAlertLogs(page) {
    if (page) this.relayAlertPage = page;
    this.relayAlertLoading = true;
    this.relayAlertList = [];
    try {
      const params = {
        page: this.relayAlertPage,
        limit: this.relayAlertPageSize,
      };
      const f = this.relayAlertFilter || {};
      if (f.patient_id) params.patient_id = f.patient_id;
      if (f.status) params.status = f.status;
      if (f.dept) params.dept = f.dept;
      if (f.severity) params.severity = f.severity;
      if (f.viewed_flag !== '' && f.viewed_flag !== null && f.viewed_flag !== undefined) {
        params.viewed_flag = f.viewed_flag;
      }
      if (Array.isArray(f.date_range) && f.date_range.length === 2) {
        params.date_from = this._fmtLocalDate(f.date_range[0]);
        params.date_to = this._fmtLocalDate(f.date_range[1]);
      }
      const [r, summaryR] = await Promise.all([
        apiGet('/api/patient-qc/relay-alert/logs', { params }),
        apiGet('/api/patient-qc/relay-alert/summary', { params }).catch(() => ({ data: this.defaultRelayAlertSummary() })),
      ]);
      this.relayAlertList = r.data.items || [];
      this.relayAlertTotal = r.data.total || 0;
      this.relayAlertSummary = {
        ...this.defaultRelayAlertSummary(),
        ...(summaryR.data || {}),
      };
    } catch (e) {
      this.showApiError(e, '加载前置机告警日志失败');
    } finally {
      this.relayAlertLoading = false;
    }
  },

  _fmtLocalDate(d) {
    if (!d) return '';
    if (typeof d === 'string') return d.substring(0, 10);
    const dt = new Date(d);
    const y = dt.getFullYear();
    const m = String(dt.getMonth() + 1).padStart(2, '0');
    const day = String(dt.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  },

  async queryRelayAlertLogs() {
    this.relayAlertPage = 1;
    await this.loadRelayAlertLogs(1);
  },

  resetRelayAlertFilter() {
    this.relayAlertFilter = { patient_id: '', status: '', viewed_flag: '', dept: '', severity: '', date_range: [] };
    this.queryRelayAlertLogs();
  },

  relayAlertHasFilters() {
    const f = this.relayAlertFilter || {};
    return Object.entries(f).some(([k, v]) => {
      if (k === 'date_range') return Array.isArray(v) && v.length === 2;
      return v !== null && v !== undefined && String(v).trim() !== '';
    });
  },

  openRelayAlertDetail(row) {
    this.relayAlertDetail = row || null;
    this.relayAlertDetailVisible = !!row;
  },

  async retryRelayAlert(alertId) {
    if (!alertId) return;
    try {
      const r = await apiPost(`/api/patient-qc/relay-alert/retry/${alertId}`);
      ElementPlus.ElMessage.success(r.data?.message || '重试已提交');
      await this.loadRelayAlertLogs();
    } catch (e) {
      this.showApiError(e, '重试失败');
    }
  },

  async loadPatientQcList(page) {
    if (page) this.pqPage = page;
    this.pqLoading = true;
    this.pqList = [];
    try {
      const params = {
        page: this.pqPage,
        limit: this.pqPageSize,
      };
      Object.entries(this.pqFilter || {}).forEach(([k, v]) => {
        if (k === 'date_range') return;
        const value = typeof v === 'string' ? v.trim() : v;
        if (value !== null && value !== undefined && value !== '') params[k] = value;
      });
      if (Array.isArray(this.pqFilter.date_range) && this.pqFilter.date_range.length === 2) {
        const fmtLocal = (d) => {
          if (!d) return '';
          if (typeof d === 'string') return d.substring(0, 10);
          const dt = new Date(d);
          const y = dt.getFullYear();
          const m = String(dt.getMonth() + 1).padStart(2, '0');
          const day = String(dt.getDate()).padStart(2, '0');
          return `${y}-${m}-${day}`;
        };
        params.date_from = fmtLocal(this.pqFilter.date_range[0]);
        params.date_to = fmtLocal(this.pqFilter.date_range[1]);
      }
      const r = await apiGet('/api/patient-qc/patients', { params });
      this.pqList = r.data.items || [];
      this.pqTotal = r.data.total || 0;
    } catch (e) {
      this.showApiError(e, '加载患者质控列表失败');
    } finally {
      this.pqLoading = false;
    }
  },

  async queryPatientQcList() {
    this.pqPage = 1;
    await this.loadPatientQcList(1);
  },

  resetPatientQcFilter() {
    this.pqFilter = { patient_id: '', patient_name: '', admission_no: '', visit_number: '', dept: '', severity: '', status: '', date_range: [] };
    this.queryPatientQcList();
  },

  hasPatientQcFilters() {
    const f = this.pqFilter || {};
    return Object.entries(f).some(([k, v]) => {
      if (k === 'date_range') return Array.isArray(v) && v.length === 2;
      return v !== null && v !== undefined && String(v).trim() !== '';
    });
  },

  qcText(value) {
    const text = value === null || value === undefined ? '' : String(value).trim();
    return text || '--';
  },

  async openPatientQcDetail(row) {
    if (!row || !row.patient_id) return;
    this.pqDetailVisible = true;
    this.pqDetailLoading = true;
    this.pqDetail = null;
    this.pqExpandedGroups = [];
    this.pqDetailSection = 'overview';
    this.pqEvidenceTab = 'medical';
    this.pqSelectedPushLogId = '';
    try {
      const r = await apiGet('/api/patient-qc/patient-detail', {
        params: { patient_id: row.patient_id, visit_number: row.visit_number || '', dept: row.dept || '' },
      });
      this.pqDetail = r.data;
      if (this.pqDetail?.audit_groups?.length) {
        this.pqExpandedGroups = [this.pqDetail.audit_groups[0].audit_type_code];
      }
    } catch (e) {
      this.showApiError(e, '加载患者详情失败');
    } finally {
      this.pqDetailLoading = false;
    }
  },

  async pqQuickAction(pushLogId, action) {
    if (!pushLogId) return;
    this.pqActionLoading = { ...this.pqActionLoading, [pushLogId]: true };
    try {
      await apiPost('/api/patient-qc/feedback/quick-action', { push_log_id: pushLogId, action });
      const label = { rectified: '已整改', pending: '已标记未处理' }[action] || action;
      ElementPlus.ElMessage.success(label);
      await this._pqRefreshDetail();
    } catch (e) {
      this.showApiError(e, '操作失败');
    } finally {
      this.pqActionLoading = { ...this.pqActionLoading, [pushLogId]: false };
    }
  },

  pqOpenOtherReason(pushLogId) {
    this.pqOtherReasonLogId = pushLogId;
    this.pqOtherReasonText = '';
    this.pqOtherReasonVisible = true;
  },

  async pqSubmitOtherReason() {
    const text = (this.pqOtherReasonText || '').trim();
    if (!text) {
      ElementPlus.ElMessage.warning('请填写具体原因');
      return;
    }
    const logId = this.pqOtherReasonLogId;
    this.pqActionLoading = { ...this.pqActionLoading, [logId]: true };
    try {
      await apiPost('/api/patient-qc/feedback/quick-action', { push_log_id: logId, action: 'other', reason: text });
      ElementPlus.ElMessage.success('已记录其他原因');
      this.pqOtherReasonVisible = false;
      await this._pqRefreshDetail();
    } catch (e) {
      this.showApiError(e, '操作失败');
    } finally {
      this.pqActionLoading = { ...this.pqActionLoading, [logId]: false };
    }
  },

  async _pqRefreshDetail() {
    if (!this.pqDetail?.patient) return;
    const p = this.pqDetail.patient;
    try {
      const r = await apiGet('/api/patient-qc/patient-detail', {
        params: { patient_id: p.patient_id, visit_number: p.visit_number, dept: p.dept || '' },
      });
      this.pqDetail = r.data;
    } catch (_) {}
  },

  pqDetailRiskLevel() {
    const s = this.pqDetail?.summary || {};
    if (Number(s.high_count || 0) > 0) return 'high';
    if (Number(s.medium_count || 0) > 0) return 'medium';
    if (Number(s.issue_count || 0) > 0) return 'low';
    return 'none';
  },

  pqDetailIssueList() {
    const groups = this.pqDetail?.audit_groups || [];
    const list = [];
    groups.forEach((group) => {
      (group.logs || []).forEach((log) => {
        (log.dimensions || []).forEach((dim) => {
          const isIssue = ['fail', 'risk', 'warning'].includes(dim.status) || dim.issue_summary;
          if (!isIssue) return;
          list.push({
            audit_type_code: group.audit_type_code,
            audit_type_name: group.audit_type_name || group.audit_type_code,
            push_log_id: log.push_log_id,
            push_time: log.push_time,
            feedback: log.feedback || {},
            dimension_name: dim.dimension_name || dim.dimension_code,
            dimension_code: dim.dimension_code,
            status: dim.status,
            severity: dim.severity || log.severity || group.severity,
            issue_summary: dim.issue_summary || '',
            recommendation: dim.recommendation || '',
            medical_evidence: dim.medical_evidence || [],
            nursing_evidence: dim.nursing_evidence || [],
          });
        });
      });
    });
    const severityRank = { high: 1, medium: 2, low: 3 };
    return list.sort((a, b) => (severityRank[a.severity] || 9) - (severityRank[b.severity] || 9));
  },

  pqDetailPendingIssues() {
    return this.pqDetailIssueList().filter((item) => {
      const status = item.feedback?.status || 'pending';
      return status !== 'rectified' && status !== 'closed';
    });
  },

  pqDetailEvidenceGroups() {
    const issues = this.pqDetailIssueList();
    const medical = [];
    const nursing = [];
    const recommendations = [];
    issues.forEach((item) => {
      (item.medical_evidence || []).forEach((ev) => {
        medical.push({ title: item.dimension_name, audit_type_name: item.audit_type_name, push_time: item.push_time, text: ev, severity: item.severity });
      });
      (item.nursing_evidence || []).forEach((ev) => {
        nursing.push({ title: item.dimension_name, audit_type_name: item.audit_type_name, push_time: item.push_time, text: ev, severity: item.severity });
      });
      if (item.recommendation) {
        recommendations.push({ title: item.dimension_name, audit_type_name: item.audit_type_name, push_time: item.push_time, text: item.recommendation, severity: item.severity });
      }
    });
    return { medical, nursing, recommendations };
  },

  pqDetailTimeline() {
    const groups = this.pqDetail?.audit_groups || [];
    const list = [];
    groups.forEach((group) => {
      (group.logs || []).forEach((log) => {
        list.push({
          ...log,
          audit_type_code: group.audit_type_code,
          audit_type_name: group.audit_type_name || group.audit_type_code,
        });
      });
    });
    return list.sort((a, b) => String(b.push_time || '').localeCompare(String(a.push_time || '')));
  },

  async pqExportSummary() {
    this.pqExportLoading = true;
    try {
      const resp = await apiGet('/api/patient-qc/export/patient-visit-summary', { responseType: 'blob' });
      await downloadBlobResponse(resp, `patient_visit_summary_${Date.now()}.xlsx`);
      ElementPlus.ElMessage.success('导出成功');
    } catch (e) {
      this.showApiError(e, '导出失败');
    } finally {
      this.pqExportLoading = false;
    }
  },
};
