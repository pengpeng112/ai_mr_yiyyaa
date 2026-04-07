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

export function formatDateTimeFallback(value) {
  if (!value) return '--';
  if (typeof dayjs === 'function') {
    const d = dayjs(value);
    if (d?.isValid && d.isValid()) return d.format('YYYY-MM-DD HH:mm:ss');
  }
  return String(value).replace('T', ' ').split('.')[0];
}
