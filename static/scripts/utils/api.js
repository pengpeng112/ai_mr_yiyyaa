export function withApiError(context, error, fallback = '请求失败') {
  if (typeof context?.showApiError === 'function') {
    return context.showApiError(error, fallback);
  }
  const message = error?.response?.data?.detail || error?.message || fallback;
  if (globalThis?.ElementPlus?.ElMessage) {
    globalThis.ElementPlus.ElMessage.error(message);
  }
  return message;
}

export function apiGet(url, options) {
  return axios.get(url, options);
}

export function apiPost(url, data, options) {
  return axios.post(url, data, options);
}

export function apiPut(url, data, options) {
  return axios.put(url, data, options);
}

export function apiDelete(url, options) {
  return axios.delete(url, options);
}

export async function downloadBlobResponse(resp, fallbackFilename) {
  const contentType = resp.headers?.['content-type'] || 'application/octet-stream';
  const blob = resp.data instanceof Blob ? resp.data : new Blob([resp.data], { type: contentType });
  if (!blob.size) {
    throw new Error('导出文件为空，请缩小筛选范围后重试');
  }
  if (contentType.includes('application/json')) {
    const text = await blob.text();
    try {
      const data = JSON.parse(text);
      throw new Error(data?.detail || data?.message || text || '导出失败');
    } catch (error) {
      if (error instanceof SyntaxError) throw new Error(text || '导出失败');
      throw error;
    }
  }

  const disposition = resp.headers?.['content-disposition'] || '';
  const encodedMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  const plainMatch = disposition.match(/filename="?([^";]+)"?/i);
  const filename = encodedMatch
    ? decodeURIComponent(encodedMatch[1])
    : (plainMatch?.[1] ? decodeURIComponent(plainMatch[1]) : fallbackFilename);

  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename || `export_${Date.now()}`;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
  window.setTimeout(() => {
    link.remove();
    window.URL.revokeObjectURL(url);
  }, 60000);
  return filename;
}
