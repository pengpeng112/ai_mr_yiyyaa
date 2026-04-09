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

function buildPushRequestBody(vm, extra = {}) {
  const isRangeMode = vm.pushForm.date_mode === 'range';
  const dateRange = Array.isArray(vm.pushForm.date_range) ? vm.pushForm.date_range : [];
  const dateFrom = dateRange[0] || '';
  const dateTo = dateRange[1] || '';
  const difyTargets = vm.normalizePushTargets();
  return {
    query_date: isRangeMode ? null : vm.pushForm.query_date,
    date_from: isRangeMode ? dateFrom : null,
    date_to: isRangeMode ? dateTo : null,
    date_dimension: vm.pushForm.date_dimension || 'record_create_date',
    dept_filter: vm.pushForm.dept_filter
      ? vm.pushForm.dept_filter.split(',').map((s) => s.trim()).filter(Boolean)
      : null,
    dry_run: vm.pushForm.dry_run,
    async_mode: vm.pushForm.async_mode && !vm.pushForm.dry_run,
    parallel_workers: Number(vm.pushForm.parallel_workers || 1),
    empty_retry_max: Number(vm.pushForm.empty_retry_max || 0),
    empty_retry_backoff_ms: Number(vm.pushForm.empty_retry_backoff_ms || 1000),
    target_strategy: vm.pushForm.target_strategy || 'round_robin',
    dify_targets: difyTargets.length ? difyTargets : null,
    selected_record_keys: extra.selected_record_keys || null,
    page: extra.page ?? null,
    page_size: extra.page_size ?? null,
  };
}

export const pushMethods = {
  getPushErrorMessage(error, fallback = '推送失败') {
    const baseMessage = this.getErrorMessage(error, fallback);
    if (baseMessage.includes('多个已启用的 Dify 目标必须配置为不同的 base_url')) {
      return `${baseMessage} 请在下方 Dify 节点列表中为每个启用节点配置不同地址后重试。`;
    }
    return baseMessage;
  },

  showPushApiError(error, fallback = '推送失败') {
    const message = this.getPushErrorMessage(error, fallback);
    ElementPlus.ElMessage.error(message);
    console.error(error);
    return message;
  },

  handlePushRequestError(error, fallback = '推送失败') {
    const message = this.showPushApiError(error, fallback);
    this.markPushIndicatorFailed({ message });
    if (message.includes('多个已启用的 Dify 目标必须配置为不同的 base_url')) {
      this.$nextTick(() => this.focusPushDifyTargetsSection());
    }
    return message;
  },

  enabledDifyTargetCount() {
    return (this.pushForm.dify_targets || []).filter(function(t) { return t.enabled; }).length;
  },

  targetMetricsRows() {
    var m = this.pushResult && this.pushResult.target_metrics;
    if (!m) return [];
    return Object.keys(m).map(function(name) {
      var v = m[name] || {};
      return { name: name, selected: v.selected || 0, success: v.success || 0, failed: v.failed || 0, empty: v.empty || 0 };
    });
  },

  focusPushDifyTargetsSection() {
    const anchor = document.getElementById('push-dify-targets');
    if (!anchor) return;
    anchor.scrollIntoView({ behavior: 'smooth', block: 'start' });
  },

  syncPushTableSelection() {
    const table = this.$refs.pushQueryTableRef;
    if (!table) return;
    const selected = new Set((this.selectedPushRecordKeys || []).map((k) => String(k || '')));
    const visibleRows = this.filteredPushQueryRows();
    this.syncingPushTableSelection = true;
    table.clearSelection();
    visibleRows.forEach((row) => {
      const key = String(row?.record_key || '');
      if (key && selected.has(key)) {
        table.toggleRowSelection(row, true);
      }
    });
    this.$nextTick(() => {
      this.syncingPushTableSelection = false;
    });
  },

  async loadPushCandidatesPage({ showMessage = true } = {}) {
    const res = await apiPost('/api/push/query-preview', buildPushRequestBody(this, {
      page: Number(this.pushQueryPage || 1),
      page_size: Number(this.pushQueryPageSize || 50),
    }));
    this.pushQuerySummary = res.data || {};
    this.pushQueryRows = Array.isArray(res.data?.rows) ? res.data.rows : [];
    this.pushQueryTotal = Number(res.data?.total_rows ?? this.pushQueryRows.length ?? 0);
    this.pushQueryPage = Number(res.data?.page ?? this.pushQueryPage ?? 1);
    this.pushQueryPageSize = Number(res.data?.page_size ?? this.pushQueryPageSize ?? 50);
    if (showMessage) {
      ElementPlus.ElMessage.success(`查询完成，共 ${this.pushQueryTotal} 条可选记录`);
    }
    this.$nextTick(() => this.syncPushTableSelection());
  },

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
      message: payload.message || '推送任务失败',
    };
    this.taskId = null;
    this.taskProg = null;
  },

  markPushIndicatorCancelled(payload = {}) {
    this.clearPushIndicatorTimer();
    this.pushIndicator = {
      visible: true,
      status: 'cancelled',
      processed: Number(payload.processed || 0),
      total: Number(payload.total || 0),
      success: Number(payload.success || 0),
      failed: Number(payload.failed || 0),
      task_id: payload.task_id || this.taskId || '',
      message: payload.message || '推送已停止',
    };
    this.taskId = null;
    this.taskProg = null;
    this.stopTaskPolling();
  },

  async stopPush() {
    const taskId = this.taskId || this.pushIndicator.task_id;
    if (!taskId) {
      ElementPlus.ElMessage.warning('没有正在运行的任务');
      return;
    }
    try {
      await apiPost(`/api/push/cancel/${taskId}`, {});
      this.markPushIndicatorCancelled({
        task_id: taskId,
        processed: this.pushIndicator.processed || this.taskProg?.processed || 0,
        total: this.pushIndicator.total || this.taskProg?.total || 0,
        success: this.pushIndicator.success || this.taskProg?.success || 0,
        failed: this.pushIndicator.failed || this.taskProg?.failed || 0,
        message: '推送已停止',
      });
      ElementPlus.ElMessage.success('推送已停止');
    } catch (e) {
      this.showApiError(e, '停止推送失败');
    }
  },

  syncPushIndicatorWithTask(taskData = {}) {
    const status = String(taskData.status || '').toLowerCase();
    if (status === 'completed') {
      this.markPushIndicatorCompleted(taskData);
      return;
    }
    if (status === 'cancelled') {
      this.markPushIndicatorCancelled(taskData);
      return;
    }
    if (status === 'failed' || status === 'not_found') {
      this.markPushIndicatorFailed({
        ...taskData,
        message: status === 'not_found' ? '任务状态不存在' : '推送任务失败',
      });
      return;
    }
    this.markPushIndicatorRunning(taskData);
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

  async loadSavedDifyTargets() {
    try {
      const resp = await apiGet('/api/config/dify/targets');
      const targets = (resp.data || {}).targets || [];
      if (!targets.length) {
        ElementPlus.ElMessage.warning('尚未保存任何 Dify 节点配置');
        return;
      }
      this.pushForm.dify_targets = targets.map((item) => createPushTarget({
        ...item,
      }));
      ElementPlus.ElMessage.success(`已载入 ${targets.length} 个已保存节点`);
    } catch (e) {
      this.showApiError(e, '加载已保存 Dify 节点失败');
    }
  },

  async saveDifyTargetsToPersist() {
    const targets = this.normalizePushTargets();
    if (!targets.length) {
      ElementPlus.ElMessage.warning('没有可保存的有效 Dify 节点');
      return;
    }
    try {
      await apiPost('/api/config/dify/targets', targets);
      ElementPlus.ElMessage.success(`已保存 ${targets.length} 个 Dify 节点配置`);
    } catch (e) {
      this.showApiError(e, '保存 Dify 节点失败');
    }
  },

  normalizePushTargets() {
    const items = Array.isArray(this.pushForm.dify_targets) ? this.pushForm.dify_targets : [];
    return items
      .map((item) => createPushTarget(item))
      .filter((item) => item.enabled && item.base_url && item.api_key);
  },

  validatePushDateRange() {
    const isRangeMode = this.pushForm.date_mode === 'range';
    const dateRange = Array.isArray(this.pushForm.date_range) ? this.pushForm.date_range : [];
    const dateFrom = dateRange[0] || '';
    const dateTo = dateRange[1] || '';
    if (isRangeMode && (!dateFrom || !dateTo)) {
      ElementPlus.ElMessage.warning('请选择开始日期和结束日期');
      return false;
    }
    return true;
  },

  async queryPushCandidates() {
    if (!this.validatePushDateRange()) return;
    this.pushQueryLoading = true;
    this.pushQueryPage = 1;
    this.pushQueryRows = [];
    this.pushQuerySummary = null;
    this.pushQueryTotal = 0;
    this.selectedPushRecordKeys = [];
    try {
      await this.loadPushCandidatesPage({ showMessage: true });
    } catch (e) {
      this.showApiError(e, '查询 SQL 结果失败');
    } finally {
      this.pushQueryLoading = false;
    }
  },

  async changePushQueryPage(page) {
    this.pushQueryPage = Number(page || 1);
    this.pushQueryLoading = true;
    try {
      await this.loadPushCandidatesPage({ showMessage: false });
    } catch (e) {
      this.showApiError(e, '切换页码失败');
    } finally {
      this.pushQueryLoading = false;
    }
  },

  async changePushQueryPageSize(pageSize) {
    this.pushQueryPageSize = Number(pageSize || 50);
    this.pushQueryPage = 1;
    this.pushQueryLoading = true;
    try {
      await this.loadPushCandidatesPage({ showMessage: false });
    } catch (e) {
      this.showApiError(e, '切换分页大小失败');
    } finally {
      this.pushQueryLoading = false;
    }
  },

  handlePushQuerySelectionChange(rows) {
    if (this.syncingPushTableSelection) {
      return;
    }
    const currentVisibleKeys = new Set(
      (this.filteredPushQueryRows() || []).map((item) => String(item?.record_key || '')).filter(Boolean),
    );
    const selectedOnVisible = new Set(
      (rows || []).map((item) => String(item?.record_key || '')).filter(Boolean),
    );
    const merged = (this.selectedPushRecordKeys || []).filter((key) => !currentVisibleKeys.has(String(key || '')));
    selectedOnVisible.forEach((key) => merged.push(key));
    this.selectedPushRecordKeys = Array.from(new Set(merged));
  },

  filteredPushQueryRows() {
    const keyword = String(this.pushQueryKeyword || '').trim().toLowerCase();
    return (this.pushQueryRows || []).filter((row) => {
      if (this.pushQueryOnlyUnpushed && row.pushed_before) {
        return false;
      }
      if (!keyword) return true;
      return [
        row.patient_id,
        row.patient_name,
        row.admission_no,
        row.dept,
        row.mrid,
        row.medical_document_name,
      ].some((value) => String(value || '').toLowerCase().includes(keyword));
    });
  },

  async pushSelectedCandidates() {
    if (!this.selectedPushRecordKeys.length) {
      ElementPlus.ElMessage.warning('请先勾选需要推送的记录');
      return;
    }
    if (!this.validatePushDateRange()) return;

    this.pushLoading = true;
    this.pushResult = null;
    try {
      const res = await apiPost(
        '/api/push/manual',
        buildPushRequestBody(this, { selected_record_keys: this.selectedPushRecordKeys }),
      );
      if (res.data.task_id) {
        this.taskId = res.data.task_id;
        this.taskProg = null;
        this.pushResult = res.data;
        this.markPushIndicatorRunning({ task_id: this.taskId });
        this.startTaskPolling();
        ElementPlus.ElMessage.success(`已提交 ${this.selectedPushRecordKeys.length} 条勾选记录的推送任务`);
      } else {
        this.pushResult = res.data;
        const results = res.data.results || [];
        const total = Number(res.data.total ?? results.length ?? 0);
        const success = Number(res.data.success ?? results.filter((item) => item.status === 'success').length);
        const failed = Number(res.data.failed ?? results.filter((item) => item.status === 'failed').length);
        this.markPushIndicatorCompleted({ total, success, failed, processed: total });
        ElementPlus.ElMessage.success('勾选记录推送完成');
        await this.queryPushCandidates();
      }
    } catch (e) {
      this.handlePushRequestError(e, '勾选推送失败');
    } finally {
      this.pushLoading = false;
    }
  },

  async doPush() {
    if (!this.validatePushDateRange()) return;

    this.pushLoading = true;
    this.pushResult = null;
    try {
      const res = await apiPost('/api/push/manual', buildPushRequestBody(this));
      if (res.data.task_id) {
        this.taskId = res.data.task_id;
        this.taskProg = null;
        this.pushResult = res.data;
        this.markPushIndicatorRunning({ task_id: this.taskId });
        this.startTaskPolling();
        ElementPlus.ElMessage.success('已提交批量推送任务');
      } else {
        this.pushResult = res.data;
        const results = res.data.results || [];
        const total = Number(res.data.total ?? results.length ?? 0);
        const success = Number(res.data.success ?? results.filter((item) => item.status === 'success').length);
        const failed = Number(res.data.failed ?? results.filter((item) => item.status === 'failed').length);
        this.markPushIndicatorCompleted({ total, success, failed, processed: total });
        ElementPlus.ElMessage.success(this.pushForm.dry_run ? '预览完成' : '批量推送完成');
        if (this.pushQueryRows.length) {
          await this.queryPushCandidates();
        }
      }
    } catch (e) {
      this.handlePushRequestError(e, '批量推送失败');
    } finally {
      this.pushLoading = false;
    }
  },

  async queryProgress() {
    if (!this.taskId) return;
    const r = await apiGet(`/api/push/status/${this.taskId}`);
    this.taskProg = r.data;
    this.syncPushIndicatorWithTask(r.data);
    if (['completed', 'failed', 'not_found', 'cancelled'].includes(r.data.status)) {
      this.stopTaskPolling();
      this.loadLogs(1);
      if (this.pushQueryRows.length) {
        this.queryPushCandidates();
      }
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
