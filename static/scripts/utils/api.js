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
