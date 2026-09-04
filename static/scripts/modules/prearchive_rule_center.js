// 归档前规则中心（039 T7）：在 legacy 质控类型页内增量建设。
// 全部经主服务白名单 BFF（/api/prearchive-admin/*）调用预检管理 API；
// BFF 关闭（默认）或预检服务不可用时显示降级提示，不影响六类审计类型 CRUD。
import { apiGet, apiPost, apiPut } from '../utils/api.js?v=20260708-stage3-v1';

export function createPrearchiveRuleCenterState() {
  return {
    prcAvailable: null,        // null=未探测 true/false
    prcDisabledReason: '',
    prcSettings: null,         // {mode, require_separate_approver, governance}
    prcRules: [],
    prcRulesLoading: false,
    prcFilterDomain: '',
    prcFilterStatus: '',
    // 编辑抽屉
    prcDrawerVisible: false,
    prcEditing: null,          // 当前规则行（或 null=新建）
    prcForm: createRuleForm(),
    prcFormJsonMode: false,
    prcSubmitting: false,
    // 版本/diff
    prcVersionsVisible: false,
    prcVersions: [],
    prcVersionsRuleKey: '',
    prcDiffVisible: false,
    prcDiffResult: null,
    // 目标 / Outbox
    prcDestinations: [],
    prcOutbox: [],
    prcOutboxLoading: false,
    prcActiveTab: 'rules',
  };
}

function createRuleForm() {
  return {
    rule_id: '',
    name: '',
    message: '',
    type: 'empty_field',
    severity: 'medium',
    version: '',
    enabled: true,
    mark_item_fid: null,
    deduct_ref: 0,
    dept_codes_text: '',
    fields_text: '',           // empty_field
    doc_name: '', event: 'admission', threshold_hours: 24, // time_limit
    list_field: 'diagnoses',   // duplicate
    trigger_json: '{}',
    expect_text: '',
    match_json: '{}',
    _domain: 'medical_record',
    _origin: 'manual',
  };
}

export const prearchiveRuleCenterMethods = {
  async loadPrearchiveRuleCenter() {
    this.prcRulesLoading = true;
    try {
      const response = await apiGet('/api/prearchive-admin/settings');
      this.prcSettings = response.data || null;
      this.prcAvailable = true;
      this.prcDisabledReason = '';
      await this.loadPrcRules();
      this.loadPrcDestinations().catch(() => {});
      this.loadPrcOutbox().catch(() => {});
    } catch (error) {
      this.prcAvailable = false;
      const status = error?.response?.status;
      // 041 T3：403=权限问题（不是服务故障）；502/503=服务不可用/未启用
      this.prcDisabledReason = status === 403
        ? '无访问权限（缺少 prearchive_rule_view 权限，请联系管理员开通）'
        : (status === 502 || status === 503)
          ? '规则中心不可用（BFF 未启用：PREARCHIVE_ADMIN_ENABLED=false，或预检服务未启动）'
          : (error?.response?.data?.detail || '预检管理服务不可用');
      this.prcRules = [];
    } finally {
      this.prcRulesLoading = false;
    }
  },

  prcDisabledTitle() {
    // 403 不套「规则中心不可用」前缀，避免把权限问题写成服务故障
    const reason = this.prcDisabledReason || '';
    const suffix = '。上方六类审计类型与本页其他区域不受影响。';
    return reason.startsWith('无访问权限') ? reason + suffix : `规则中心不可用：${reason}${suffix}`;
  },

  async loadPrcRules() {
    const params = new URLSearchParams();
    if (this.prcFilterDomain) params.set('domain', this.prcFilterDomain);
    if (this.prcFilterStatus) params.set('status', this.prcFilterStatus);
    const response = await apiGet(`/api/prearchive-admin/rules?${params.toString()}`);
    this.prcRules = response.data?.items || [];
  },

  async loadPrcDestinations() {
    const response = await apiGet('/api/prearchive-admin/destinations');
    this.prcDestinations = response.data?.items || [];
  },

  async loadPrcOutbox() {
    this.prcOutboxLoading = true;
    try {
      const response = await apiGet('/api/prearchive-admin/outbox');
      this.prcOutbox = response.data?.items || [];
    } finally {
      this.prcOutboxLoading = false;
    }
  },

  prcModeBanner() {
    const mode = this.prcSettings?.mode || 'file';
    const labels = { file: '文件规则（现状）', compare: '影子比对（file 结果为准）', registry: '规则仓（已发布版本）' };
    return labels[mode] || mode;
  },

  prcDeliveryBanner() {
    // 阶段 A 固定关闭；真实开启状态由预检服务配置决定，此处按目标 enabled 汇总提示
    const enabledCount = (this.prcDestinations || []).filter((d) => d.enabled).length;
    return enabledCount === 0 ? '对外推送关闭' : `对外推送：${enabledCount} 个目标启用`;
  },

  prcCan(perm) {
    const perms = this.currentUser?.permissions || [];
    return perms.includes(perm) || perms.includes('*');
  },

  openPrcCreate() {
    this.prcEditing = null;
    this.prcForm = createRuleForm();
    this.prcFormJsonMode = false;
    this.prcDrawerVisible = true;
  },

  openPrcEdit(row) {
    this.prcEditing = row;
    const content = row.content || {};
    this.prcForm = {
      rule_id: content.rule_id || row.rule_key,
      name: content.name || '',
      message: content.message || '',
      type: content.type || 'empty_field',
      severity: content.severity || 'medium',
      version: content.rule_version || row.rule_version,
      enabled: content.enabled !== false,
      mark_item_fid: content.mark_item_fid ?? null,
      deduct_ref: content.deduct_ref || 0,
      dept_codes_text: (content.dept_codes || []).join(','),
      fields_text: (content.fields || []).join(','),
      doc_name: content.doc_name || '',
      event: content.event || 'admission',
      threshold_hours: content.threshold_hours || 24,
      list_field: content.list_field || 'diagnoses',
      trigger_json: JSON.stringify(content.trigger || {}, null, 2),
      expect_text: (content.expect || []).join(','),
      match_json: JSON.stringify(content.match || {}, null, 2),
      _domain: row.domain || 'medical_record',
      _origin: row.origin || 'manual',
    };
    this.prcFormJsonMode = false;
    this.prcDrawerVisible = true;
  },

  prcBuildContentFromForm() {
    const f = this.prcForm;
    const content = {
      rule_id: String(f.rule_id || '').trim(),
      name: String(f.name || '').trim(),
      message: String(f.message || '').trim(),
      type: f.type,
      severity: f.severity,
      version: String(f.version || '').trim(),
      enabled: !!f.enabled,
      mark_item_fid: f.mark_item_fid === '' || f.mark_item_fid === null ? null : Number(f.mark_item_fid),
      deduct_ref: Number(f.deduct_ref || 0),
      dept_codes: String(f.dept_codes_text || '').split(',').map((s) => s.trim()).filter(Boolean),
    };
    if (f.type === 'empty_field') {
      content.fields = String(f.fields_text || '').split(',').map((s) => s.trim()).filter(Boolean);
    }
    if (f.type === 'time_limit') {
      content.doc_name = String(f.doc_name || '').trim();
      content.event = f.event;
      content.threshold_hours = Number(f.threshold_hours || 0);
    }
    if (f.type === 'duplicate') {
      content.list_field = f.list_field;
    }
    if (f.type === 'missing_doc') {
      try { content.trigger = JSON.parse(f.trigger_json || '{}'); } catch { content.trigger = {}; }
      content.expect = String(f.expect_text || '').split(',').map((s) => s.trim()).filter(Boolean);
      try { content.match = JSON.parse(f.match_json || '{}'); } catch { content.match = {}; }
    }
    return content;
  },

  async submitPrcForm() {
    if (!this.prcEditing) return this.createPrcRule();
    return this.updatePrcDraft();
  },

  async createPrcRule() {
    const content = this.prcBuildContentFromForm();
    this.prcSubmitting = true;
    try {
      await apiPost('/api/prearchive-admin/rules', {
        ...content, _domain: this.prcForm._domain, _origin: this.prcForm._origin,
      });
      ElementPlus.ElMessage.success('草稿已创建');
      this.prcDrawerVisible = false;
      await this.loadPrcRules();
    } catch (error) {
      this.showApiError(error, '创建草稿失败');
    } finally {
      this.prcSubmitting = false;
    }
  },

  async updatePrcDraft() {
    const content = this.prcBuildContentFromForm();
    this.prcSubmitting = true;
    try {
      await apiPut(`/api/prearchive-admin/rules/${encodeURIComponent(this.prcEditing.rule_key)}/draft`, {
        rule_version: this.prcEditing.rule_version,
        expect_edit_version: this.prcEditing.draft_edit_version,
        content,
      });
      ElementPlus.ElMessage.success('草稿已保存');
      this.prcDrawerVisible = false;
      await this.loadPrcRules();
    } catch (error) {
      this.showApiError(error, '保存草稿失败（可能存在并发编辑冲突）');
    } finally {
      this.prcSubmitting = false;
    }
  },

  async prcValidate(row) {
    try {
      const response = await apiPost(
        `/api/prearchive-admin/rules/${encodeURIComponent(row.rule_key)}/validate`,
        { rule_version: row.rule_version });
      if (response.data?.valid) {
        ElementPlus.ElMessage.success('校验通过，状态已置为 validated');
      } else {
        ElementPlus.ElMessageBox.alert((response.data?.errors || []).join('；') || '校验失败', '规则校验', { type: 'warning' });
      }
      await this.loadPrcRules();
    } catch (error) {
      this.showApiError(error, '校验失败');
    }
  },

  async prcDryRun(row) {
    try {
      const response = await apiPost(
        `/api/prearchive-admin/rules/${encodeURIComponent(row.rule_key)}/dry-run`,
        { rule_version: row.rule_version });
      const results = response.data?.fixture_results || [];
      const summary = results.map((r) => `${r.patient_id}/${r.visit_id}: ${r.problem_count} 问题`).join('\n');
      ElementPlus.ElMessageBox.alert(summary || response.data?.reason || '无 fixture 结果', '试运行（demo 虚构数据）', { type: 'info' });
    } catch (error) {
      this.showApiError(error, '试运行失败');
    }
  },

  async prcApprove(row) {
    try {
      await ElementPlus.ElMessageBox.prompt('审批意见（可选）', '审批规则', { inputPlaceholder: '同意' });
    } catch { return; }
    try {
      await apiPost(`/api/prearchive-admin/rules/${encodeURIComponent(row.rule_key)}/approve`,
        { rule_version: row.rule_version });
      ElementPlus.ElMessage.success('已审批');
      await this.loadPrcRules();
    } catch (error) {
      this.showApiError(error, '审批失败');
    }
  },

  async prcPublish(row) {
    try {
      await ElementPlus.ElMessageBox.confirm(
        `发布 ${row.rule_key} @ ${row.rule_version}\nSHA-256: ${row.content_sha256 || '-'}\n发布后旧版本自动退役，可用回滚恢复。`,
        '确认发布（危险操作）', { type: 'warning', confirmButtonText: '发布' });
    } catch { return; }
    try {
      await apiPost(`/api/prearchive-admin/rules/${encodeURIComponent(row.rule_key)}/publish`,
        { rule_version: row.rule_version });
      ElementPlus.ElMessage.success('已发布并更新指针');
      await this.loadPrcRules();
    } catch (error) {
      this.showApiError(error, '发布失败');
    }
  },

  async prcRollback(row) {
    try {
      const { value } = await ElementPlus.ElMessageBox.prompt('回滚到的已发布版本号', '回滚指针', { inputPlaceholder: '如 2026.09.02.1' });
      await apiPost(`/api/prearchive-admin/rules/${encodeURIComponent(row.rule_key)}/rollback`,
        { to_version: String(value || '').trim(), reason: '页面回滚' });
      ElementPlus.ElMessage.success('已回滚');
      await this.loadPrcRules();
    } catch (error) {
      if (error === 'cancel' || error?.toString?.().includes('cancel')) return;
      this.showApiError(error, '回滚失败');
    }
  },

  async prcRetire(row) {
    try {
      await ElementPlus.ElMessageBox.confirm(`退役 ${row.rule_key} @ ${row.rule_version}？`, '确认退役', { type: 'warning' });
    } catch { return; }
    try {
      await apiPost(`/api/prearchive-admin/rules/${encodeURIComponent(row.rule_key)}/retire`,
        { rule_version: row.rule_version });
      ElementPlus.ElMessage.success('已退役');
      await this.loadPrcRules();
    } catch (error) {
      this.showApiError(error, '退役失败');
    }
  },

  async openPrcVersions(row) {
    this.prcVersionsRuleKey = row.rule_key;
    try {
      const response = await apiGet(`/api/prearchive-admin/rules/${encodeURIComponent(row.rule_key)}/versions`);
      this.prcVersions = response.data?.items || [];
      this.prcVersionsVisible = true;
    } catch (error) {
      this.showApiError(error, '加载版本历史失败');
    }
  },

  async openPrcDiff(row, versionA, versionB) {
    try {
      const params = new URLSearchParams({ version_a: versionA, version_b: versionB });
      const response = await apiGet(
        `/api/prearchive-admin/rules/${encodeURIComponent(row.rule_key || row)}/diff?${params.toString()}`);
      this.prcDiffResult = response.data || null;
      this.prcDiffVisible = true;
    } catch (error) {
      this.showApiError(error, '加载版本差异失败');
    }
  },

  prcStatusTag(status) {
    return ({ draft: 'info', validated: '', approved: 'warning', published: 'success', retired: 'danger' })[status] || 'info';
  },

  prcDomainLabel(domain) {
    return ({ medical_record: '病历质控', medical_quality: '医疗质量', insurance: '医保', system_push: '系统推送' })[domain] || domain;
  },

  async prcContractTest(code) {
    try {
      await ElementPlus.ElMessageBox.confirm(
        `向 ${code} 发送合成契约测试事件（不含任何真实患者数据；阶段 A 只构造请求不实际外发）？`,
        '契约测试', { type: 'info' });
      const response = await apiPost(`/api/prearchive-admin/destinations/${encodeURIComponent(code)}/contract-test`);
      ElementPlus.ElMessage.success(`契约测试请求已构造（event=${response.data?.event_id || '-'}，preview 模式）`);
      this.loadPrcDestinations().catch(() => {});
    } catch (error) {
      if (error === 'cancel') return;
      this.showApiError(error, '契约测试失败');
    }
  },

  async prcToggleDestination(row) {
    try {
      await apiPost('/api/prearchive-admin/destinations', { code: row.code, enabled: !row.enabled });
      ElementPlus.ElMessage.success(row.enabled ? '目标已停用' : '目标已启用（真实外发仍受 delivery 总开关控制）');
      await this.loadPrcDestinations();
    } catch (error) {
      this.showApiError(error, '目标更新失败');
    }
  },

  async prcRetryOutbox(row) {
    try {
      await apiPost(`/api/prearchive-admin/outbox/${encodeURIComponent(row.id)}/retry`);
      ElementPlus.ElMessage.success('已重新入队');
      await this.loadPrcOutbox();
    } catch (error) {
      this.showApiError(error, '重试失败（仅 dead/disabled 状态可重试）');
    }
  },

  prcOutboxStatusTag(status) {
    return ({ pending: 'info', sending: '', sent: 'success', retry: 'warning', dead: 'danger', disabled: 'info' })[status] || 'info';
  },
};
