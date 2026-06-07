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
      if (f.viewed_flag !== '' && f.viewed_flag !== null && f.viewed_flag !== undefined) {
        params.viewed_flag = f.viewed_flag;
      }
      const r = await apiGet('/api/patient-qc/relay-alert/logs', { params });
      this.relayAlertList = r.data.items || [];
      this.relayAlertTotal = r.data.total || 0;
    } catch (e) {
      this.showApiError(e, '加载前置机告警日志失败');
    } finally {
      this.relayAlertLoading = false;
    }
  },

  async queryRelayAlertLogs() {
    this.relayAlertPage = 1;
    await this.loadRelayAlertLogs(1);
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
        if (v !== null && v !== undefined && v !== '') params[k] = v;
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

  async openPatientQcDetail(row) {
    if (!row || !row.patient_id) return;
    this.pqDetailVisible = true;
    this.pqDetailLoading = true;
    this.pqDetail = null;
    this.pqExpandedGroups = [];
    try {
      const r = await apiGet('/api/patient-qc/patient-detail', {
        params: { patient_id: row.patient_id, visit_number: row.visit_number, dept: row.dept || '' },
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
