import { severityLabel, pushStatusLabel, statusTagType, severityTagType } from '../utils/formatters.js?v=20260624-batch0';
import {
  parseAiResultStructured,
  parsePossibleJson,
  prettyJson,
  logAuditTypeLabel,
  logAlertLevelLabel,
  logAlertLevelTagType,
  logPushStrategyLabel,
  logOutcomeBucketLabel,
  logClosureHoursLabel,
  logOriginalEvidenceSections,
  logDimensionEvidenceSections,
  formatLogEvidenceItem,
  hasLogEvidenceSectionContent,
} from '../utils/log_detail_helpers.js?v=20260629-log-detail-fix';

var currentLogId = parseInt(new URLSearchParams(location.search).get('id') || '0') || 0;
var listData = [];
var listIndex = -1;

var token = localStorage.getItem('auth_token');
if (!token) location.href = '/';
axios.interceptors.request.use(function(config) {
  config.headers.Authorization = 'Bearer ' + token;
  return config;
});
axios.interceptors.response.use(function(r) { return r; }, function(err) {
  if (err.response && err.response.status === 401) location.href = '/';
  return Promise.reject(err);
});

function fmt(val) {
  if (!val) return '--';
  if (typeof dayjs === 'function') { var d = dayjs(val); if (d && d.isValid && d.isValid()) return d.format('YYYY-MM-DD HH:mm:ss'); }
  return String(val).replace('T', ' ').split('.')[0];
}

function renderBlockValue(block) {
  var value = block && block.value;
  if (value === null || value === undefined || value === '') return '\u65e0';
  if (Array.isArray(value)) return value.length ? value.join('\uff0c') : '\u65e0';
  if (typeof value === 'object') return prettyJson(value);
  return String(value);
}

function buildDetail(detail) {
  var aiStructured = parseAiResultStructured(detail);
  var parsedResponse = parsePossibleJson(detail.response_json) || parsePossibleJson(detail.ai_result) || {};
  var auditResult = (detail.audit_result && typeof detail.audit_result === 'object') ? detail.audit_result : {};
  var storedAudit = Object.keys(auditResult).length ? auditResult : ((detail.stored_audit && typeof detail.stored_audit === 'object') ? detail.stored_audit : {});
  var storedDimensions = Array.isArray(storedAudit.dimensions) ? storedAudit.dimensions : [];
  var storedConclusion = storedAudit.conclusion && typeof storedAudit.conclusion === 'object' ? storedAudit.conclusion : {};
  var medicalDocumentsText = '';
  var nursingRecordsText = '';
  if (detail.mr_text) {
    var nursingIdx = detail.mr_text.indexOf('\n[\u62a4\u7406\u8bb0\u5f55]');
    if (nursingIdx >= 0) {
      var medicalIdx = detail.mr_text.indexOf('[\u75c5\u5386\u6587\u4e66]');
      medicalDocumentsText = medicalIdx >= 0 ? detail.mr_text.substring(medicalIdx + '[\u75c5\u5386\u6587\u4e66]'.length, nursingIdx).trim() : detail.mr_text.substring(0, nursingIdx).trim();
      nursingRecordsText = detail.mr_text.substring(nursingIdx + '\n[\u62a4\u7406\u8bb0\u5f55]'.length).trim();
    }
  }
  return Object.assign({}, detail, {
    request_json_pretty: prettyJson(detail.request_json),
    response_json_pretty: prettyJson(detail.response_json || detail.ai_result),
    ai_structured: aiStructured,
    medical_documents_text: medicalDocumentsText,
    nursing_records_text: nursingRecordsText,
    audit_result: storedAudit,
    stored_dimensions: storedDimensions,
    stored_conclusion: storedConclusion
  });
}

function loadDetail(id) {
  return axios.get('/api/logs/' + id).then(function(r) { return buildDetail(r.data); });
}

function loadList() {
  return axios.get('/api/logs', { params: { page: 1, limit: 200 } }).then(function(r) {
    listData = (r.data && r.data.items) || [];
    listIndex = listData.findIndex(function(item) { return item.id === currentLogId; });
  }).catch(function() { listData = []; listIndex = -1; });
}

var app = Vue.createApp({
  data: function() {
    return {
      loading: true,
      error: '',
      logDetail: null,
      activeTab: 'ai',
      listTotal: 0,
      listIndex: -1,
      evidenceSections: [],
      dimensionEvidenceSectionsMap: {}
    };
  },
  computed: {
    hasPrev: function() { return this.listIndex > 0; },
    hasNext: function() { return this.listIndex >= 0 && this.listIndex < listData.length - 1; }
  },
  methods: {
    fmt: fmt,
    severityLabel: severityLabel,
    pushStatusLabel: pushStatusLabel,
    statusTagType: statusTagType,
    severityTagType: severityTagType,
    logAuditTypeLabel: logAuditTypeLabel,
    logAlertLevelLabel: logAlertLevelLabel,
    logAlertLevelTagType: logAlertLevelTagType,
    logPushStrategyLabel: logPushStrategyLabel,
    logOutcomeBucketLabel: logOutcomeBucketLabel,
    logClosureHoursLabel: logClosureHoursLabel,
    formatLogEvidenceItem: formatLogEvidenceItem,
    hasLogEvidenceSectionContent: hasLogEvidenceSectionContent,
    prettyJson: prettyJson,
    renderBlockValue: renderBlockValue,
    goBack: function() { if (window.opener) { window.close(); } else { location.href = '/'; } },
    prevLog: function() {
      if (!this.hasPrev) return;
      currentLogId = listData[this.listIndex - 1].id;
      location.search = '?id=' + currentLogId;
    },
    nextLog: function() {
      if (!this.hasNext) return;
      currentLogId = listData[this.listIndex + 1].id;
      location.search = '?id=' + currentLogId;
    },
    doPrint: function() {
      var id = currentLogId;
      axios.post('/api/report/' + id + '/print-token').then(function(r) {
        var t = r.data && r.data.token;
        if (t) window.open('/report/' + id + '?token=' + encodeURIComponent(t), '_blank');
      }).catch(function(err) {
        var msg = (err.response && err.response.data && err.response.data.detail) || err.message || '\u6253\u5370\u5931\u8d25';
        ElementPlus.ElMessage.error(msg);
      });
    },
    dimensionEvidenceSections: function(row) {
      if (!this.logDetail) return [];
      return logDimensionEvidenceSections(this.logDetail, row);
    },
    refresh: function() {
      this.loading = true;
      this.error = '';
      var self = this;
      loadDetail(currentLogId).then(function(detail) {
        self.logDetail = detail;
        self.evidenceSections = detail ? logOriginalEvidenceSections(detail) : [];
        self.loading = false;
      }).catch(function(err) {
        self.error = (err.response && err.response.data && err.response.data.detail) || err.message || '\u52a0\u8f7d\u8be6\u60c5\u5931\u8d25';
        self.loading = false;
      });
      loadList().then(function() {
        self.listTotal = listData.length;
        self.listIndex = listIndex;
      });
    }
  },
  mounted: function() {
    this.refresh();
  }
});

app.use(ElementPlus);
app.mount('#app');
