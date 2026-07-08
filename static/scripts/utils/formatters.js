export function severityLabel(severity) {
  return { high: '高', medium: '中', low: '低' }[severity] || severity || '--';
}

export function pushStatusLabel(status) {
  return { success: '成功', failed: '失败', skipped: '跳过', pending: '待处理', error: '错误' }[status] || status || '--';
}

export function feedbackStatusLabel(status) {
  return { pending: '待处理', acknowledged: '已确认', rectified: '已整改', closed: '已关闭' }[status] || status || '--';
}

export function feedbackStatusTagType(status) {
  return { pending: 'warning', acknowledged: 'primary', rectified: 'success', closed: 'info' }[status] || 'info';
}

export function statusTagType(status) {
  return { success: 'success', failed: 'danger', skipped: 'info', pending: 'warning', error: 'danger' }[status] || 'info';
}

export function severityTagType(severity) {
  return { high: 'danger', medium: 'warning', low: 'success' }[severity] || 'info';
}

export function auditStatusLabel(status) {
  return { pass: '通过', fail: '不一致', warn: '警告', unknown: '未知' }[status] || status || '--';
}

export function relayAlertStatusLabel(status) {
  return { success: '成功', failed: '失败', pending: '待发送', suppressed: '已抑制' }[status] || status || '--';
}

export function relayAlertStatusTag(status) {
  return { success: 'success', failed: 'danger', pending: 'warning', suppressed: 'info' }[status] || 'info';
}

export function relayAlertSeverityLabel(severity) {
  return { high: '高', medium: '中', low: '低' }[severity] || severity || '--';
}

export function relayAlertSeverityTag(severity) {
  return { high: 'danger', medium: 'warning', low: 'info' }[severity] || 'info';
}

export function relayAlertViewedLabel(row) {
  return Number(row?.viewed_flag || 0) ? '已查看' : '未查看';
}

export function relayAlertViewedTag(row) {
  return Number(row?.viewed_flag || 0) ? 'success' : 'info';
}

export function relayAlertFeedbackLabel(action) {
  return { acknowledged: '已知晓', rectified: '已处理', other: '其他原因' }[action] || '';
}

export function relayAlertFeedbackTag(action) {
  return { acknowledged: 'success', rectified: 'warning', other: 'info' }[action] || 'info';
}

export function relayAlertFeedbackIcon(action) {
  return { acknowledged: '✓', rectified: '🔧', other: '📝' }[action] || '?';
}

export function formatDateTimeFallback(value) {
  if (!value) return '--';
  if (typeof dayjs === 'function') {
    const d = dayjs(value);
    if (d?.isValid && d.isValid()) return d.format('YYYY-MM-DD HH:mm:ss');
  }
  return String(value).replace('T', ' ').split('.')[0];
}
