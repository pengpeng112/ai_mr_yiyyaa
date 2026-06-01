import { apiDelete, apiGet, apiPost, downloadBlobResponse } from '../utils/api.js?v=20260524-download-blob';

export const feedbackMethods = {
  normalizeFeedbackStatus(status) {
    const value = String(status || '').toLowerCase();
    if (['pending', '待处理'].includes(value)) return 'pending';
    if (['acknowledged', 'confirmed', '已确认'].includes(value)) return 'acknowledged';
    if (['rectified', 'fixed', '已整改'].includes(value)) return 'rectified';
    if (['closed', 'done', '已关闭'].includes(value)) return 'closed';
    // DEF-02 修复：未知状态不再静默降级为 pending，保留原始值供调用方判断
    // 若确实无法识别，返回 'unknown' 而非 'pending'
    return value || 'unknown';
  },

  switchFeedbackViewType(type) {
    this.feedbackViewType = type === 'kanban' ? 'kanban' : 'list';
  },

  feedbackKanbanCount(status) {
    return (this.feedbackKanbanGroups?.[status] || []).length;
  },

  feedbackKanbanTime(row) {
    return this.formatDateTime(row?.reviewed_at || row?.push_time || row?.query_date);
  },

  feedbackAuditTypeLabel(row) {
    return row?.audit_type_name || row?.audit_type_code || '默认病程护理核查';
  },

  alertLevelLabel(level) {
    return { red: '红灯', yellow: '黄灯', blue: '蓝灯', gray: '灰灯' }[level] || level || '--';
  },

  alertLevelTagType(level) {
    return { red: 'danger', yellow: 'warning', blue: 'primary', gray: 'info' }[level] || 'info';
  },

  pushStrategyLabel(strategy) {
    return {
      immediate: '立即推送',
      batch: '批量汇总',
      shift_summary: '交班汇总',
      review_only: '仅复核',
    }[strategy] || strategy || '--';
  },

  outcomeBucketLabel(bucket) {
    return { primary: '主要问题', secondary: '次要问题', none: '无问题' }[bucket] || bucket || '--';
  },

  closureHoursLabel(hours) {
    const value = Number(hours || 0);
    return value > 0 ? `${value} 小时` : '--';
  },

  feedbackScenarioKey(detail) {
    const code = String(detail?.audit_type_code || '').toLowerCase();
    const name = String(detail?.audit_type_name || '');
    if (code.includes('lab_exam') || code.includes('jyjc') || (name.includes('检验') && name.includes('检查'))) return 'labExam';
    if (code.includes('frontpage') || name.includes('首页') || name.includes('首次病程')) return 'frontpage';
    if (code.includes('progress') && code.includes('nursing')) return 'progressNursing';
    if (name.includes('病程') && name.includes('护理')) return 'progressNursing';
    return 'generic';
  },

  feedbackScenarioConfig(detail) {
    const key = this.feedbackScenarioKey(detail);
    const configs = {
      labExam: {
        key,
        label: '检验检查响应质控',
        hint: '重点核查检验检查异常、危急值或检查结论是否在病程记录中评估，并在护理记录中体现观察、执行与闭环。',
        evidenceTitle: '检验检查异常与病程/护理响应',
        evidenceSubtitle: '先看异常发现，再看病程处置和护理闭环；通过项默认压缩，避免空证据干扰阅读。',
        issueLabel: '核查项',
        primaryRawLabel: '病程记录',
        secondaryRawLabel: '护理记录',
        focusTitle: '本类型核查重点',
        focusCards: [
          { label: '检查/检验发现', desc: '异常值、危急值、检查结论、报告时间' },
          { label: '病程响应', desc: '是否评估异常、记录处置、安排复查' },
          { label: '护理响应', desc: '是否观察执行、记录变化、形成闭环' },
        ],
        groupRules: [
          { label: '异常结果响应', keywords: ['异常', '危急', '检验', '检查', '结果'] },
          { label: '病程处理', keywords: ['病程', '评估', '处置', '复查'] },
          { label: '护理闭环', keywords: ['护理', '观察', '执行', '闭环'] },
          { label: '时间线', keywords: ['时间', '报告', '记录'] },
        ],
      },
      progressNursing: {
        key,
        label: '病程护理一致性质控',
        hint: '重点核查病程记录与护理记录在诊断、病情变化、护理级别、措施执行和时间线上的一致性。',
        evidenceTitle: '病程记录与护理记录一致性判断',
        evidenceSubtitle: '优先展示不一致或需复核维度；通过项压缩为清单，展开后再查看原始依据。',
        issueLabel: '核查项',
        primaryRawLabel: '病程记录',
        secondaryRawLabel: '护理记录',
        focusTitle: '本类型核查重点',
        focusCards: [
          { label: '病程依据', desc: '诊断、病情变化、治疗计划与时间记录' },
          { label: '护理依据', desc: '护理级别、生命体征、护理措施与执行记录' },
          { label: '差异维度', desc: '优先查看不一致说明和整改建议' },
        ],
        groupRules: [
          { label: '诊断一致性', keywords: ['诊断'] },
          { label: '护理级别', keywords: ['护理级别', '级别'] },
          { label: '生命体征', keywords: ['生命体征', '体征'] },
          { label: '病情描述', keywords: ['病情', '描述'] },
          { label: '治疗措施', keywords: ['治疗', '措施', '执行'] },
          { label: '时间线', keywords: ['时间', '时间线'] },
        ],
      },
      frontpage: {
        key,
        label: '首页手术与首次病程质控',
        hint: '重点核查首页诊断、手术信息与首次病程记录是否相互印证，减少首页与病程首记不一致。',
        evidenceTitle: '首页手术与首次病程对照',
        evidenceSubtitle: '围绕首页诊断、手术名称、手术时间和首次病程描述进行对照。',
        issueLabel: '核查项',
        primaryRawLabel: '首页/首次病程',
        secondaryRawLabel: '补充记录',
        focusTitle: '本类型核查重点',
        focusCards: [
          { label: '首页信息', desc: '首页诊断、手术名称、手术时间' },
          { label: '首次病程', desc: '首记诊断、拟诊依据、手术相关描述' },
          { label: '对照差异', desc: '名称、时间、诊断和术前术后逻辑' },
        ],
        groupRules: [
          { label: '手术信息', keywords: ['手术', '操作'] },
          { label: '诊断信息', keywords: ['诊断'] },
          { label: '首次病程', keywords: ['首次', '首记', '病程'] },
          { label: '时间线', keywords: ['时间', '日期'] },
        ],
      },
      generic: {
        key,
        label: '病例质控反馈',
        hint: '重点核查结构化质控结论、证据来源和科室闭环处理是否清晰可追踪。',
        evidenceTitle: '核查证据对照',
        evidenceSubtitle: '按分类判断展示问题说明、整改建议和相关证据。',
        issueLabel: '判断项',
        primaryRawLabel: '主要记录',
        secondaryRawLabel: '辅助记录',
        focusTitle: '核查重点',
        focusCards: [
          { label: '质控结论', desc: '总体结论、风险等级和问题说明' },
          { label: '证据来源', desc: '结构化证据与原始推送内容' },
          { label: '闭环处理', desc: '科室确认、整改和状态留痕' },
        ],
        groupRules: [],
      },
    };
    return configs[key] || configs.generic;
  },

  feedbackScenarioClass(detail) {
    return `feedback-scenario-${this.feedbackScenarioKey(detail)}`;
  },

  feedbackOverallConclusionLabel(detail) {
    const text = `${detail?.overall_conclusion || ''} ${detail?.overall_qc_summary || ''}`;
    if (text.includes('不通过')) return '不通过';
    if (text.includes('预警')) return '预警';
    if (text.includes('无法判断')) return '无法判断';
    if (text.includes('通过')) return '通过';
    return detail?.overall_conclusion || '暂无结论';
  },

  feedbackOverallToneClass(detail) {
    const label = this.feedbackOverallConclusionLabel(detail);
    if (label.includes('不通过')) return 'is-danger';
    if (label.includes('预警')) return 'is-warning';
    if (label.includes('无法判断')) return 'is-neutral';
    if (label.includes('通过')) return 'is-pass';
    return 'is-neutral';
  },

  feedbackOverallSummary(detail) {
    return detail?.overall_qc_summary || detail?.overall_conclusion || '暂无整体质控描述';
  },

  feedbackScenarioLabel(detail) {
    return this.feedbackScenarioConfig(detail).label;
  },

  feedbackScenarioHint(detail) {
    return this.feedbackScenarioConfig(detail).hint;
  },

  feedbackEvidenceTitle(detail) {
    return this.feedbackScenarioConfig(detail).evidenceTitle;
  },

  feedbackEvidenceSubtitle(detail) {
    return this.feedbackScenarioConfig(detail).evidenceSubtitle;
  },

  feedbackPatientMeta(detail) {
    const item = detail || {};
    return [
      { label: '日志ID', value: item.log_id },
      { label: '患者ID', value: item.patient_id },
      { label: '住院号', value: item.admission_no },
      { label: '身份证号', value: item.id_card },
      { label: '联系电话', value: item.phone },
      { label: '在院科室', value: item.dept_name || this.deptNameById(item.dept_id) },
      { label: '入院日期', value: item.admission_date },
      { label: '出院日期', value: item.discharge_date },
      { label: '入院科室', value: item.admission_dept_name },
      { label: '出院科室', value: item.discharge_dept_name },
      { label: '入院诊断', value: item.admission_diagnosis, wide: true },
      { label: '出院主诊断', value: item.discharge_main_diagnosis, wide: true },
      { label: '手术', value: item.surgery, wide: true },
      { label: '住址', value: item.address, wide: true },
    ];
  },

  feedbackNonEmptyPatientMeta(detail) {
    return this.feedbackPatientMeta(detail).filter((item) => {
      const value = item?.value;
      return value !== null && value !== undefined && String(value).trim() !== '' && String(value).trim() !== '--';
    });
  },

  feedbackScenarioFocusCards(detail) {
    return this.feedbackScenarioConfig(detail).focusCards || [];
  },

  feedbackDimensionGroupLabel(detail, row) {
    const name = `${row?.dimension || ''} ${row?.dimension_code || ''}`;
    const rules = this.feedbackScenarioConfig(detail).groupRules || [];
    const matched = rules.find((rule) => (rule.keywords || []).some((keyword) => name.includes(keyword)));
    return matched?.label || '综合判断';
  },

  feedbackIsPassedDimension(row) {
    const status = String(row?.status || '').toLowerCase();
    const severity = String(row?.severity || '').toLowerCase();
    const alert = String(row?.alert_level || '').toLowerCase();
    const issueText = `${row?.issue_summary || ''} ${row?.explanation || ''} ${row?.recommendation || ''}`;
    const normalizedIssueText = issueText.replace(/无实质性矛盾|未见异常|无异常|无不一致|未发现问题|未见明确问题|无明确问题|未发现明显不一致|未见明显不一致|处理合理/g, '');
    const hasRiskText = /不一致|异常|缺失|未|建议|整改|风险|问题|疑似|矛盾/.test(normalizedIssueText);
    const negativeStatus = status.includes('不一致') || status.includes('不通过') || status.includes('fail') || status.includes('异常');
    const passedStatus = status.includes('pass') || status.includes('一致') || status.includes('通过') || status.includes('normal');
    const lowRisk = !severity || severity.includes('low') || row?.severity === '低';
    const calmAlert = !alert || alert === 'blue' || alert === 'gray';
    return passedStatus && !negativeStatus && lowRisk && calmAlert && !hasRiskText;
  },

  feedbackRiskDimensions(detail) {
    return (detail?.dimensions || []).filter((row) => !this.feedbackIsPassedDimension(row));
  },

  feedbackPassedDimensions(detail) {
    return (detail?.dimensions || []).filter((row) => this.feedbackIsPassedDimension(row));
  },

  feedbackDimensionSummary(row) {
    const statusText = this.auditStatusLabel ? this.auditStatusLabel(row?.status) : (row?.status || '');
    return row?.issue_summary || row?.explanation || row?.recommendation || statusText || '暂无补充说明';
  },

  feedbackDimensionToneClass(row) {
    const severity = String(row?.severity || '').toLowerCase();
    const alert = String(row?.alert_level || '').toLowerCase();
    const status = String(row?.status || '').toLowerCase();
    if (severity.includes('high') || row?.severity === '高' || alert === 'red' || status.includes('fail') || status.includes('不一致')) return 'is-danger';
    if (severity.includes('medium') || row?.severity === '中' || alert === 'yellow' || status.includes('warn') || status.includes('疑')) return 'is-warning';
    if (severity.includes('low') || row?.severity === '低' || alert === 'blue') return 'is-info';
    return 'is-neutral';
  },

  feedbackRawPrimaryLabel(detail) {
    return this.feedbackScenarioConfig(detail).primaryRawLabel;
  },

  feedbackRawSecondaryLabel(detail) {
    return this.feedbackScenarioConfig(detail).secondaryRawLabel;
  },

  _asEvidenceArray(value) {
    if (Array.isArray(value)) return value.filter((item) => item !== null && item !== undefined && item !== '');
    if (value === null || value === undefined || value === '') return [];
    return [value];
  },

  _collectExtraEvidence(extra, keys) {
    const items = [];
    const source = extra && typeof extra === 'object' ? extra : {};
    keys.forEach((key) => {
      items.push(...this._asEvidenceArray(source[key]));
    });
    return items;
  },

  feedbackDimensionEvidenceSections(detail, row) {
    const scenario = this.feedbackScenarioKey(detail);
    const extra = row?.extra || {};
    const medicalEvidence = this._asEvidenceArray(row?.medical_evidence);
    const nursingEvidence = this._asEvidenceArray(row?.nursing_evidence);

    if (scenario === 'labExam') {
      return [
        {
          key: 'lab-exam',
          title: '检验/检查异常依据',
          items: this._collectExtraEvidence(extra, ['evidence_lab', 'evidence_exam', 'lab_evidence', 'exam_evidence', 'abnormal_labs', 'abnormal_exams']),
          text: extra.evidence_text || extra.lab_exam_evidence || '',
        },
        { key: 'progress', title: '病程评估/处置响应', items: medicalEvidence, text: row?.medical_content || '' },
        { key: 'nursing', title: '护理观察/执行响应', items: nursingEvidence, text: row?.nursing_content || '' },
      ];
    }

    if (scenario === 'frontpage') {
      return [
        {
          key: 'frontpage',
          title: '首页/手术信息',
          items: this._collectExtraEvidence(extra, ['evidence_frontpage', 'frontpage_evidence', 'surgery_evidence', 'diagnosis_evidence']),
          text: row?.medical_content || extra.frontpage_text || '',
        },
        {
          key: 'first-progress',
          title: '首次病程记录',
          items: this._collectExtraEvidence(extra, ['evidence_first_progress', 'first_progress_evidence']),
          text: row?.nursing_content || extra.first_progress_text || '',
        },
      ];
    }

    return [
      { key: 'medical', title: '病程记录依据', items: medicalEvidence, text: row?.medical_content || '' },
      { key: 'nursing', title: '护理记录依据', items: nursingEvidence, text: row?.nursing_content || '' },
    ];
  },

  formatEvidenceItem(item) {
    if (item === null || item === undefined || item === '') return '--';
    if (typeof item === 'string') return item;
    try {
      return JSON.stringify(item, null, 2);
    } catch (_) {
      return String(item);
    }
  },

  hasEvidenceSectionContent(section) {
    return !!((section?.items || []).length || String(section?.text || '').trim());
  },

  feedbackVisibleEvidenceSections(detail, row) {
    return this.feedbackDimensionEvidenceSections(detail, row).filter((section) => this.hasEvidenceSectionContent(section));
  },

  onFeedbackSearchInput() {
    if (!this.debouncedLoadFeedbackFn) {
      this.debouncedLoadFeedbackFn = this.debounce(() => this.loadFeedbackList(1), 500);
    }
    this.feedbackPage = 1;
    this.debouncedLoadFeedbackFn();
  },

  async loadFeedbackPage() {
    await this.runConfigAction(async () => {
      if (!this.feedbackFilter.status) {
        this.feedbackViewMode = 'pending';
        this.feedbackFilter.status = 'pending';
      }
      await this.loadFeedbackAuxData();
      await this.loadFeedbackList();
    });
  },

  switchFeedbackView(mode) {
    this.feedbackViewMode = mode;
    this.feedbackSelectedRows = [];
    this.feedbackFilter.status = mode === 'pending' ? 'pending' : '';
    this.loadFeedbackList(1);
  },

  handleFeedbackSelectionChange(rows) {
    this.feedbackSelectedRows = Array.isArray(rows) ? rows : [];
  },

  async loadFeedbackAuxData() {
    const [deptResp, userResp, auditTypeResp] = await Promise.all([
      apiGet('/api/departments').catch(() => ({ data: [] })),
      apiGet('/api/users', { params: { page: 1, limit: 100 } }).catch(() => ({ data: { items: [] } })),
      apiGet('/api/audit-types/options').catch(() => ({ data: { items: [] } })),
    ]);
    this.feedbackDepartments = Array.isArray(deptResp.data) ? deptResp.data : [];
    this.feedbackUsers = userResp.data.items || [];
    const auditTypeItems = Array.isArray(auditTypeResp.data?.items) ? auditTypeResp.data.items : [];
    this.auditTypeOptions = auditTypeItems.map((item) => ({
      value: item.code,
      label: item.name,
      default_for_schedule: !!item.default_for_schedule,
    }));
  },

  async loadFeedbackList(page) {
    if (page) this.feedbackPage = page;

    // DEF-06 修复：看板模式需要加载全量数据（不受分页截断）
    // 看板展示各状态全部病例，分页 20 条会导致各列数量不准确
    const isKanban = this.feedbackViewType === 'kanban';
      const params = {
        page: this.feedbackPage,
        limit: isKanban ? 100 : this.feedbackLimit,
      };
    Object.entries(this.feedbackFilter).forEach(([k, v]) => {
      if (v !== '' && v !== null && v !== undefined) params[k] = v;
    });
    // 看板模式不按单一状态过滤，展示所有状态
    if (isKanban && params.status) delete params.status;

    try {
      const r = await apiGet('/api/qc/feedback/cases', { params });
      this.feedbackList = r.data.items || [];
      this.feedbackSelectedRows = [];
      this.feedbackTotal = r.data.total || 0;
      this.feedbackStats = r.data.stats || {};
    } catch (e) {
      this.showApiError(e, '加载质控反馈列表失败');
    }
  },

  async handleFeedbackPageChange(page) {
    this.feedbackPage = page;
    await this.loadFeedbackList();
  },

  resetFeedbackFilter() {
    this.feedbackViewMode = 'pending';
    this.feedbackFilter = { status: 'pending', severity: '', audit_type_code: '', dept_id: null, days: 30, keyword: '' };
    this.loadFeedbackList(1);
  },

  closeFeedbackDetail() {
    this.feedbackDetailVisible = false;
  },

  onFeedbackDetailClosed() {
    this.feedbackDetail = null;
    this.feedbackConfirmForm = { log_id: null, action: 'acknowledged', review_comment: '' };
  },

  async loadFeedbackStatsView() {
    return;
  },

  _parseRawRecordItems(text) {
    if (!text || !text.trim()) return [];
    // 按空行分块，再识别以 "数字." 开头的块作为一条记录
    const blocks = text.split(/\n{2,}/);
    const items = [];
    let current = null;
    for (const block of blocks) {
      const trimmed = block.trim();
      if (!trimmed) continue;
      const headerMatch = trimmed.match(/^(\d+)\.\s([\s\S]*)/);
      if (headerMatch) {
        if (current) items.push(current);
        current = { index: parseInt(headerMatch[1], 10), text: trimmed };
      } else {
        if (current) {
          current.text += '\n\n' + trimmed;
        } else {
          current = { index: items.length + 1, text: trimmed };
        }
      }
    }
    if (current) items.push(current);
    return items;
  },

  async viewFeedbackDetail(logId) {
    await this.runConfigAction(async () => {
      this.feedbackDetailLoading = true;
      const r = await apiGet(`/api/qc/feedback/cases/${logId}`);
      this.feedbackDetail = r.data;
      // 将原始文书文本解析成条目数组，便于前端逐条展示
      if (this.feedbackDetail) {
        this.feedbackDetail._medical_items = this._parseRawRecordItems(this.feedbackDetail.medical_documents_text);
        this.feedbackDetail._nursing_items = this._parseRawRecordItems(this.feedbackDetail.nursing_records_text);
      }
      this.feedbackConfirmForm = {
        log_id: r.data.log_id,
        action: r.data.feedback_status === 'closed' ? 'closed' : 'acknowledged',
        review_comment: r.data.feedback?.feedback_text || r.data.feedback_text || '',
      };
      this.feedbackDetailVisible = true;
      await this.loadFeedbackList(this.feedbackPage);
    }).finally(() => {
      this.feedbackDetailLoading = false;
    });
  },

  async submitFeedbackConfirm(action = 'acknowledged') {
    if (!this.feedbackDetail?.log_id) return;
    await this.runConfigAction(async () => {
      await apiPost(`/api/qc/feedback/cases/${this.feedbackDetail.log_id}/confirm`, {
        action,
        review_comment: this.feedbackConfirmForm.review_comment || '',
      });
      await this.viewFeedbackDetail(this.feedbackDetail.log_id);
      await this.loadFeedbackList(this.feedbackPage);
    }, action === 'closed' ? '已确认无问题并关闭' : '已确认并反馈');
  },

  async deleteFeedbackCase(rowOrLogId) {
    const logId = typeof rowOrLogId === 'object' ? rowOrLogId?.log_id : rowOrLogId;
    if (!logId) return;
    try {
      await ElementPlus.ElMessageBox.confirm(
        '确认从质控反馈中删除该病例吗？原始推送日志和审计结果会保留。',
        '删除质控反馈',
        { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
      );
    } catch {
      return;
    }
    await this.runConfigAction(async () => {
      await apiDelete(`/api/qc/feedback/cases/${logId}`);
      if (this.feedbackDetail?.log_id === logId) {
        this.closeFeedbackDetail();
      }
      await this.loadFeedbackList(this.feedbackPage);
    }, '质控反馈已删除');
  },

  async deleteSelectedFeedbackCases() {
    const logIds = Array.from(new Set(
      (this.feedbackSelectedRows || [])
        .map((row) => Number(row?.log_id || 0))
        .filter((value) => value > 0),
    ));
    if (!logIds.length) {
      ElementPlus.ElMessage.warning('请先勾选需要删除的质控反馈');
      return;
    }
    try {
      await ElementPlus.ElMessageBox.confirm(
        `确认从质控反馈中批量删除 ${logIds.length} 条病例吗？原始推送日志和审计结果会保留。`,
        '批量删除质控反馈',
        { confirmButtonText: '批量删除', cancelButtonText: '取消', type: 'warning' },
      );
    } catch {
      return;
    }
    await this.runConfigAction(async () => {
      const resp = await apiDelete('/api/qc/feedback/cases/bulk', { data: { log_ids: logIds } });
      const deleted = Number(resp.data?.data?.deleted ?? logIds.length);
      this.feedbackSelectedRows = [];
      await this.loadFeedbackList(this.feedbackPage);
      if (this.feedbackList.length === 0 && this.feedbackPage > 1) {
        await this.loadFeedbackList(this.feedbackPage - 1);
      }
      ElementPlus.ElMessage.success(`已删除 ${deleted} 条质控反馈`);
    });
  },

  async exportFeedbackExcel() {
    const params = {};
    Object.entries(this.feedbackFilter || {}).forEach(([k, v]) => {
      if (v !== '' && v !== null && v !== undefined) params[k] = v;
    });
    if (this.feedbackViewType === 'kanban' && params.status) delete params.status;

    params.audit_type_code = String(params.audit_type_code || '').trim();
    if (!params.audit_type_code) {
      ElementPlus.ElMessage.warning('请先选择审计类型后再导出 Excel，不同审计类型的质控维度不同，不能混在同一个表中。');
      return;
    }

    await this.runConfigAction(async () => {
      const resp = await apiGet('/api/qc/feedback/export/excel', { params, responseType: 'blob' });
      const contentType = resp.headers?.['content-type'] || '';
      const fallbackExt = contentType.includes('csv') ? 'csv' : 'xlsx';
      await downloadBlobResponse(resp, `feedback_${Date.now()}.${fallbackExt}`);
    }, '导出文件已生成，请查看浏览器下载记录');
  },
};
