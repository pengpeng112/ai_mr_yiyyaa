import { apiGet, apiPost } from '../utils/api.js';

function createPushTarget(source = {}) {
  return {
    name: source.name || '',
    base_url: source.base_url || '',
    api_key: source.api_key || '',
    workflow_input_variable: source.workflow_input_variable || 'mr_txt',
    workflow_output_key: source.workflow_output_key || 'aa',
    user_identifier: source.user_identifier || 'med-audit-system',
    timeout_seconds: Number(source.timeout_seconds || 90),
    weight: Number(source.weight || 1),
    enabled: source.enabled !== false,
  };
}

export const pushMethods = {
  clearPushIndicatorTimer() {
    if (this.pushIndicatorHideTimer) {
      clearTimeout(this.pushIndicatorHideTimer);
      this.pushIndicatorHideTimer = null;
    }
  },

  clearPushIndicator() {
    this.clearPushIndicatorTimer();
    this.pushProgressDrawerVisible = false;
    this.pushIndicator = {
      visible: false,
      status: 'idle',
      processed: 0,
      total: 0,
      success: 0,
      failed: 0,
      task_id: '',
      message: '',
    };
  },

  schedulePushIndicatorHide() {
    this.clearPushIndicatorTimer();
    this.pushIndicatorHideTimer = setTimeout(() => {
      if (this.pushIndicator.status === 'completed') {
        this.clearPushIndicator();
      }
    }, 3000);
  },

  markPushIndicatorRunning(payload = {}) {
    this.clearPushIndicatorTimer();
    this.pushIndicator = {
      visible: true,
      status: 'running',
      processed: Number(payload.processed || 0),
      total: Number(payload.total || 0),
      success: Number(payload.success || 0),
      failed: Number(payload.failed || 0),
      task_id: payload.task_id || this.taskId || '',
      message: payload.message || '',
    };
  },

  markPushIndicatorCompleted(payload = {}) {
    this.pushIndicator = {
      visible: true,
      status: 'completed',
      processed: Number(payload.processed ?? payload.total ?? 0),
      total: Number(payload.total || 0),
      success: Number(payload.success ?? payload.processed ?? payload.total ?? 0),
      failed: Number(payload.failed || 0),
      task_id: payload.task_id || this.taskId || '',
      message: payload.message || '',
    };
    this.taskId = null;
    this.taskProg = null;
    this.schedulePushIndicatorHide();
  },

  markPushIndicatorFailed(payload = {}) {
    this.clearPushIndicatorTimer();
    this.pushIndicator = {
      visible: true,
      status: 'failed',
      processed: Number(payload.processed || 0),
      total: Number(payload.total || 0),
      success: Number(payload.success || 0),
      failed: Number(payload.failed || 0),
      task_id: payload.task_id || this.taskId || '',
      message: payload.message || 'Push task failed',
    };
    this.taskId = null;
    this.taskProg = null;
  },

  syncPushIndicatorWithTask(taskData = {}) {
    const status = String(taskData.status || '').toLowerCase();
    if (status === 'completed') {
      this.markPushIndicatorCompleted({
        processed: taskData.processed,
        total: taskData.total,
        success: taskData.success,
        failed: taskData.failed,
        task_id: taskData.task_id,
      });
      return;
    }
    if (status === 'failed' || status === 'not_found') {
      this.markPushIndicatorFailed({
        processed: taskData.processed,
        total: taskData.total,
        success: taskData.success,
        failed: taskData.failed,
        task_id: taskData.task_id,
        message: status === 'not_found' ? 'Task status not found' : 'Push task failed',
      });
      return;
    }
    this.markPushIndicatorRunning({
      processed: taskData.processed,
      total: taskData.total,
      success: taskData.success,
      failed: taskData.failed,
      task_id: taskData.task_id,
    });
  },

  openPushProgressDrawer() {
    this.pushProgressDrawerVisible = true;
  },

  addEmptyPushTarget() {
    this.pushForm.dify_targets.push(createPushTarget({
      name: `dify-${this.pushForm.dify_targets.length + 1}`,
    }));
  },

  duplicatePushTarget(index) {
    const item = this.pushForm.dify_targets[index];
    if (!item) return;
    this.pushForm.dify_targets.splice(index + 1, 0, createPushTarget({
      ...item,
      name: item.name ? `${item.name}-copy` : `dify-${index + 2}`,
    }));
  },

  removePushTarget(index) {
    this.pushForm.dify_targets.splice(index, 1);
  },

  async appendDefaultDifyTarget() {
    try {
      const resp = await apiGet('/api/config/dify');
      const cfg = resp.data || {};
      if (!cfg.base_url) {
        ElementPlus.ElMessage.warning('默认 Dify 配置未设置');
        return;
      }
      this.pushForm.dify_targets.push(createPushTarget({
        name: cfg.name || `default-${this.pushForm.dify_targets.length + 1}`,
        base_url: cfg.base_url,
        workflow_input_variable: cfg.workflow_input_variable,
        workflow_output_key: cfg.workflow_output_key,
        user_identifier: cfg.user_identifier,
        timeout_seconds: cfg.timeout_seconds,
      }));
      ElementPlus.ElMessage.success('已载入默认 Dify 配置，请补充 API Key');
    } catch (e) {
      this.showApiError(e, '加载默认 Dify 配置失败');
    }
  },

  normalizePushTargets() {
    const items = Array.isArray(this.pushForm.dify_targets) ? this.pushForm.dify_targets : [];
    return items
      .map((item) => createPushTarget(item))
      .filter((item) => item.base_url && item.api_key);
  },

  async doPush() {
    const isRangeMode = this.pushForm.date_mode === 'range';
    const dateRange = Array.isArray(this.pushForm.date_range) ? this.pushForm.date_range : [];
    const dateFrom = dateRange[0] || '';
    const dateTo = dateRange[1] || '';
    if (!isRangeMode && !this.pushForm.query_date) {
      ElementPlus.ElMessage.warning('请选择目标日期');
      return;
    }
    if (isRangeMode && (!dateFrom || !dateTo)) {
      ElementPlus.ElMessage.warning('请选择开始日期和结束日期');
      return;
    }

    this.pushLoading = true;
    this.pushResult = null;
    try {
      const difyTargets = this.normalizePushTargets();
      const body = {
        query_date: isRangeMode ? null : this.pushForm.query_date,
        date_from: isRangeMode ? dateFrom : null,
        date_to: isRangeMode ? dateTo : null,
        date_dimension: this.pushForm.date_dimension || 'record_create_date',
        dept_filter: this.pushForm.dept_filter
          ? this.pushForm.dept_filter.split(',').map((s) => s.trim()).filter(Boolean)
          : null,
        dry_run: this.pushForm.dry_run,
        async_mode: this.pushForm.async_mode && !this.pushForm.dry_run,
        parallel_workers: Number(this.pushForm.parallel_workers || 1),
        empty_retry_max: Number(this.pushForm.empty_retry_max || 0),
        empty_retry_backoff_ms: Number(this.pushForm.empty_retry_backoff_ms || 1000),
        target_strategy: this.pushForm.target_strategy || 'round_robin',
        dify_targets: difyTargets.length ? difyTargets : null,
      };
      const res = await apiPost('/api/push/manual', body);
      if (res.data.task_id) {
        this.taskId = res.data.task_id;
        this.taskProg = null;
        this.markPushIndicatorRunning({ task_id: this.taskId });
        this.startTaskPolling();
        ElementPlus.ElMessage.success('手动推送任务已提交');
      } else {
        this.pushResult = res.data;
        const results = res.data.results || [];
        const total = Number(res.data.total ?? res.data.total_patients ?? results.length ?? 0);
        const success = Number(res.data.success ?? results.filter((item) => item.status === 'success').length);
        const failed = Number(res.data.failed ?? results.filter((item) => item.status === 'failed').length);
        this.markPushIndicatorCompleted({ total, success, failed, processed: total });
        ElementPlus.ElMessage.success(res.data.dry_run ? '预览完成' : '手动推送完成');
      }
    } catch (e) {
      this.markPushIndicatorFailed({ message: this.getErrorMessage(e, 'Push failed') });
      this.showApiError(e, '手动推送失败');
    } finally {
      this.pushLoading = false;
    }
  },

  async queryProgress() {
    if (!this.taskId) return;
    const r = await apiGet('/api/push/status/' + this.taskId);
    this.taskProg = r.data;
    this.syncPushIndicatorWithTask(r.data);
    if (['completed', 'failed', 'not_found'].includes(r.data.status)) {
      this.stopTaskPolling();
      this.loadLogs(1);
    }
  },

  startTaskPolling() {
    this.stopTaskPolling();
    this.taskPollCount = 0;
    this.queryProgress();
    this.taskPoller = setInterval(async () => {
      this.taskPollCount += 1;
      await this.queryProgress();
      if (this.taskPollCount >= this.maxTaskPoll) {
        this.stopTaskPolling();
        ElementPlus.ElMessage.warning('进度轮询超时，请稍后手动查看');
      }
    }, 3000);

    if (!this.visibilityHandlerBound) {
      document.addEventListener('visibilitychange', () => {
        if (document.hidden) this.stopTaskPolling();
      });
      this.visibilityHandlerBound = true;
    }
  },

  stopTaskPolling() {
    if (this.taskPoller) {
      clearInterval(this.taskPoller);
      this.taskPoller = null;
    }
    this.taskPollCount = 0;
  },
};
