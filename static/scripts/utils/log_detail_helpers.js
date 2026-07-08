export function parsePossibleJson(value) {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'object') return value;
  try { return JSON.parse(value); } catch (e) { return null; }
}

export function normalizeAuditStatus(status) {
  const raw = String(status || '').toLowerCase();
  const map = { pass: 'pass', passed: 'pass', success: 'pass', ok: 'pass', fail: 'fail', failed: 'fail', error: 'fail', mismatch: 'fail', inconsistent: 'fail', warn: 'warn', warning: 'warn', medium: 'warn', high: 'fail', low: 'pass' };
  return map[raw] || (raw ? 'unknown' : 'unknown');
}

export function normalizeSeverity(level, fallbackStatus = 'unknown') {
  const raw = String(level || '').toLowerCase();
  if (['high', 'h', '\u4e25\u91cd', '\u9ad8'].includes(raw)) return 'high';
  if (['medium', 'mid', 'm', '\u4e2d'].includes(raw)) return 'medium';
  if (['low', 'l', '\u4f4e'].includes(raw)) return 'low';
  if (fallbackStatus === 'fail') return 'high';
  if (fallbackStatus === 'warn') return 'medium';
  if (fallbackStatus === 'pass') return 'low';
  return 'unknown';
}

export function auditRiskLevel(score) {
  if (score >= 80) return 'high';
  if (score >= 50) return 'medium';
  if (score > 0) return 'low';
  return 'unknown';
}

export function parseAiResultStructured(logDetail) {
  const aiParsed = parsePossibleJson(logDetail?.ai_result);
  const responseParsed = parsePossibleJson(logDetail?.response_json);
  const root = aiParsed || responseParsed || {};
  const structuredRoot = root.result && typeof root.result === 'object' ? root.result : root;
  const summary = structuredRoot.audit_summary && typeof structuredRoot.audit_summary === 'object' ? structuredRoot.audit_summary : {};
  const sourceDimensions = Array.isArray(structuredRoot.dimensions) ? structuredRoot.dimensions : Array.isArray(structuredRoot['\u6838\u67e5\u7ed3\u679c']) ? structuredRoot['\u6838\u67e5\u7ed3\u679c'] : [];
  const dimensions = sourceDimensions.map(function(item, index) {
    var status = normalizeAuditStatus(item?.status || item?.['\u72b6\u6001']);
    return {
      key: (item?.dimension || item?.['\u7ef4\u5ea6'] || item?.name || 'dimension') + '-' + index,
      dimension: item?.dimension || item?.['\u7ef4\u5ea6'] || item?.name || '\u7ef4\u5ea6' + (index + 1),
      status: status,
      severity: normalizeSeverity(item?.severity || item?.['\u4e25\u91cd\u5ea6'], status),
      explanation: item?.explanation || item?.['\u8bf4\u660e'] || ''
    };
  });
  var focusItemsRaw = summary.focus_items || summary['\u91cd\u70b9\u5173\u6ce8\u9879'] || structuredRoot.focus_items || structuredRoot['\u91cd\u70b9\u5173\u6ce8\u9879'] || [];
  var focusItems = Array.isArray(focusItemsRaw) ? focusItemsRaw.map(function(item) { return String(item || '').trim(); }).filter(Boolean) : [];
  var overallConclusion = summary.overall_conclusion || summary['\u603b\u4f53\u7ed3\u8bba'] || structuredRoot.overall_conclusion || structuredRoot['\u603b\u4f53\u7ed3\u8bba'] || '';
  var qualitySummary = structuredRoot.reasoning_brief || summary.reasoning_brief || structuredRoot['\u6574\u4f53\u8d28\u63a7\u63cf\u8ff0'] || structuredRoot.quality_summary || '';
  var riskScore = Number(summary.risk_score ?? summary['\u98ce\u9669\u5206\u503c'] ?? structuredRoot.risk_score ?? structuredRoot['\u98ce\u9669\u5206\u503c'] ?? logDetail?.risk_score ?? 0) || 0;
  return { dimensions: dimensions, focusItems: focusItems, overallConclusion: overallConclusion, qualitySummary: qualitySummary, riskScore: riskScore, riskLevel: auditRiskLevel(riskScore) };
}

export function prettyJson(value) {
  if (!value) return '';
  if (typeof value === 'object') { try { return JSON.stringify(value, null, 2); } catch (e) { return String(value); } }
  if (typeof value !== 'string') return String(value);
  try { return JSON.stringify(JSON.parse(value), null, 2); } catch (e) { return value; }
}

export function logAuditTypeLabel(row) {
  return row?.audit_type_name || row?.audit_type_code || '\u9ed8\u8ba4\u75c5\u7a0b\u62a4\u7406\u6838\u67e5';
}

export function logFailureReason(row) {
  return row?.failure_reason || row?.error_msg || row?.skip_reason_label || row?.skip_reason || '';
}

export function logAlertLevelLabel(level) {
  var labels = { red: '\u7ea2\u706f', yellow: '\u9ec4\u706f', blue: '\u84dd\u706f', gray: '\u7070\u706f' };
  return labels[String(level || '').toLowerCase()] || level || '--';
}

export function logAlertLevelTagType(level) {
  var map = { red: 'danger', yellow: 'warning', blue: 'primary', gray: 'info' };
  return map[String(level || '').toLowerCase()] || 'info';
}

export function logPushStrategyLabel(strategy) {
  var labels = { immediate: '\u7acb\u5373\u63a8\u9001', batch: '\u6279\u91cf\u6c47\u603b', shift_summary: '\u4ea4\u73ed\u6c47\u603b', review_only: '\u4ec5\u590d\u6838' };
  return labels[String(strategy || '').toLowerCase()] || strategy || '--';
}

export function logOutcomeBucketLabel(bucket) {
  var labels = { primary: '\u4e3b\u8981\u95ee\u9898', secondary: '\u6b21\u8981\u95ee\u9898', none: '\u65e0\u95ee\u9898' };
  return labels[String(bucket || '').toLowerCase()] || bucket || '--';
}

export function logClosureHoursLabel(hours) {
  var value = Number(hours || 0);
  return value > 0 ? value + ' \u5c0f\u65f6' : '--';
}

export function logEvidenceTitle(detail) {
  var code = String(detail?.audit_type_code || '').toLowerCase();
  var name = String(detail?.audit_type_name || '');
  if (code.includes('lab') || code.includes('exam') || name.includes('\u68c0\u9a8c') || name.includes('\u68c0\u67e5')) return '\u68c0\u9a8c\u68c0\u67e5\u4e0e\u75c5\u7a0b/\u62a4\u7406\u8bc1\u636e';
  if (code.includes('frontpage') || code.includes('surgery') || name.includes('\u9996\u9875') || name.includes('\u624b\u672f')) return '\u9996\u9875\u624b\u672f\u4e0e\u9996\u6b21\u75c5\u7a0b\u8bc1\u636e';
  if (code.includes('progress') || code.includes('nursing') || name.includes('\u75c5\u7a0b') || name.includes('\u62a4\u7406')) return '\u75c5\u7a0b\u8bb0\u5f55\u4e0e\u62a4\u7406\u8bb0\u5f55\u8bc1\u636e';
  return '\u63a8\u9001\u8bc1\u636e';
}

function _asLogEvidenceArray(value) {
  if (Array.isArray(value)) return value.filter(function(item) { return item !== null && item !== undefined && String(item).trim() !== ''; });
  if (value && typeof value === 'object') return [value];
  if (String(value || '').trim()) return [String(value).trim()];
  return [];
}

function _collectLogExtraEvidence(extra, keys) {
  var source = extra && typeof extra === 'object' && !Array.isArray(extra) ? extra : {};
  var items = [];
  keys.forEach(function(key) { _asLogEvidenceArray(source[key]).forEach(function(item) { items.push(item); }); });
  return items;
}

function _logStructuredMrText(detail) {
  var parsed = parsePossibleJson(detail?.mr_text);
  return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
}

function _extractLogTextSection(text, startMarkers, endMarkers) {
  var source = String(text || '');
  if (!source) return '';
  var start = -1, startLength = 0;
  (startMarkers || []).some(function(marker) { var idx = source.indexOf(marker); if (idx >= 0) { start = idx; startLength = marker.length; return true; } return false; });
  if (start < 0) return '';
  var contentStart = start + startLength;
  var end = source.length;
  (endMarkers || []).forEach(function(marker) { var idx = source.indexOf(marker, contentStart); if (idx >= 0 && idx < end) end = idx; });
  return source.substring(contentStart, end).trim();
}

export function logOriginalEvidenceSections(detail) {
  var code = String(detail?.audit_type_code || '').toLowerCase();
  var name = String(detail?.audit_type_name || '');
  var structured = _logStructuredMrText(detail);
  var isLabExam = code.includes('lab') || code.includes('exam') || name.includes('\u68c0\u9a8c') || name.includes('\u68c0\u67e5');
  var isFrontpage = code.includes('frontpage') || code.includes('surgery') || name.includes('\u9996\u9875') || name.includes('\u624b\u672f');
  if (isLabExam) {
    var progressRoot = structured['\u75c5\u7a0b'] || structured.progress || {};
    var nursingRoot = structured['\u62a4\u7406'] || structured.nursing || {};
    return [
      { title: '\u68c0\u9a8c\u68c0\u67e5', items: _asLogEvidenceArray(structured['\u68c0\u9a8c\u68c0\u67e5'] || structured.lab_exam || structured.labs || structured.exams), text: '' },
      { title: '\u75c5\u7a0b\u8bb0\u5f55', items: _asLogEvidenceArray(structured['\u75c5\u7a0b\u8bb0\u5f55'] || progressRoot['\u75c5\u7a0b\u8bb0\u5f55'] || structured.progress_notes), text: detail?.medical_documents_text || _extractLogTextSection(detail?.mr_text, ['[\u75c5\u7a0b\u8bb0\u5f55]'], ['[\u62a4\u7406\u8bb0\u5f55]']) },
      { title: '\u62a4\u7406\u8bb0\u5f55', items: _asLogEvidenceArray(structured['\u62a4\u7406\u8bb0\u5f55'] || nursingRoot['\u62a4\u7406\u8bb0\u5f55'] || structured.nursing_records), text: detail?.nursing_records_text || _extractLogTextSection(detail?.mr_text, ['[\u62a4\u7406\u8bb0\u5f55]'], []) }
    ];
  }
  if (isFrontpage) {
    var frontpageText = _extractLogTextSection(detail?.mr_text, ['[\u9996\u9875\u624b\u672f\u4e0e\u8bca\u65ad]'], ['[\u9996\u6b21\u75c5\u7a0b\u8bb0\u5f55]']);
    var firstProgressText = _extractLogTextSection(detail?.mr_text, ['[\u9996\u6b21\u75c5\u7a0b\u8bb0\u5f55]'], ['[\u6838\u67e5\u89c4\u5219]', '[\u6ce8\u610f\u4e8b\u9879]']);
    return [
      { title: '\u9996\u9875/\u624b\u672f\u4fe1\u606f', items: _asLogEvidenceArray(structured['\u9996\u9875\u624b\u672f'] || structured['\u9996\u9875\u4fe1\u606f'] || structured.frontpage || structured.surgeries), text: frontpageText },
      { title: '\u9996\u6b21\u75c5\u7a0b\u8bb0\u5f55', items: _asLogEvidenceArray(structured['\u9996\u6b21\u75c5\u7a0b'] || structured.first_progress), text: detail?.medical_documents_text || firstProgressText }
    ];
  }
  return [
    { title: '\u75c5\u7a0b\u8bb0\u5f55', items: [], text: detail?.medical_documents_text || _extractLogTextSection(detail?.mr_text, ['[\u75c5\u5386\u6587\u4e66]'], ['[\u62a4\u7406\u8bb0\u5f55]']) || detail?.mr_text || '' },
    { title: '\u62a4\u7406\u8bb0\u5f55', items: [], text: detail?.nursing_records_text || _extractLogTextSection(detail?.mr_text, ['[\u62a4\u7406\u8bb0\u5f55]'], []) }
  ];
}

export function logDimensionEvidenceSections(detail, row) {
  var code = String(detail?.audit_type_code || '').toLowerCase();
  var name = String(detail?.audit_type_name || '');
  var extra = row?.extra && typeof row.extra === 'object' ? row.extra : {};
  var isLabExam = code.includes('lab') || code.includes('exam') || name.includes('\u68c0\u9a8c') || name.includes('\u68c0\u67e5');
  var isFrontpage = code.includes('frontpage') || code.includes('surgery') || name.includes('\u9996\u9875') || name.includes('\u624b\u672f');
  if (isLabExam) {
    return [
      { title: '\u68c0\u9a8c\u68c0\u67e5\u8bc1\u636e', items: _collectLogExtraEvidence(extra, ['evidence_lab', 'evidence_exam', 'lab_evidence', 'exam_evidence', 'abnormal_labs', 'abnormal_exams']), text: '' },
      { title: '\u75c5\u7a0b\u54cd\u5e94', items: _asLogEvidenceArray(row?.medical_evidence), text: row?.medical_content || '' },
      { title: '\u62a4\u7406\u54cd\u5e94', items: _asLogEvidenceArray(row?.nursing_evidence), text: row?.nursing_content || '' }
    ];
  }
  if (isFrontpage) {
    return [
      { title: '\u9996\u9875/\u624b\u672f\u4fe1\u606f', items: _collectLogExtraEvidence(extra, ['evidence_frontpage', 'frontpage_evidence', 'surgery_evidence', 'diagnosis_evidence']), text: row?.medical_content || '' },
      { title: '\u9996\u6b21\u75c5\u7a0b\u8bb0\u5f55', items: _collectLogExtraEvidence(extra, ['evidence_first_progress', 'first_progress_evidence']), text: row?.nursing_content || '' }
    ];
  }
  return [
    { title: '\u75c5\u7a0b\u8bb0\u5f55', items: _asLogEvidenceArray(row?.medical_evidence), text: row?.medical_content || '' },
    { title: '\u62a4\u7406\u8bb0\u5f55', items: _asLogEvidenceArray(row?.nursing_evidence), text: row?.nursing_content || '' }
  ];
}

export function formatLogEvidenceItem(item) {
  if (typeof item === 'string') return item;
  try { return JSON.stringify(item, null, 2); } catch (e) { return String(item || ''); }
}

export function hasLogEvidenceSectionContent(section) {
  return !!((section?.items || []).length || String(section?.text || '').trim());
}
