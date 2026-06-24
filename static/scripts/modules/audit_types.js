import { apiDelete, apiGet, apiPost, apiPut } from '../utils/api.js?v=20260524-download-blob';

function prettyJson(value, fallback) {
  const data = value === undefined ? fallback : value;
  return JSON.stringify(data, null, 2);
}

const MR_TYPE_OPTIONS = [
  '检验检查与病历护理核查',
  '首页手术与首次病程',
  '医嘱与病程及护理核查',
];

const SOURCE_LABELS = {
  primary: '主数据源',
  patient: '患者信息',
  lab: '检验',
  exam: '检查',
  progress: '病程',
  nursing: '护理',
  frontpage: '首页/手术',
  first_progress: '首次病程',
};

const BUILDER_LABELS = {
  legacy_progress_nursing: '旧版病程-护理核查',
  generic_multi_source: '通用多源核查',
  lab_exam_progress_nursing: '检验/检查-病程/护理核查',
  lab_exam_structured_progress_nursing: '结构化检验/检查核查',
  frontpage_surgery_first_progress: '首页手术-首次病程核查',
  orders_vs_progress_stub: '医嘱-病程占位模板',
};

function inferMrType(source = {}) {
  const extraInputs = source?.dify?.extra_inputs || source?.extra_inputs || {};
  const configured = String(extraInputs.mr_type || '').trim();
  if (configured) return configured;

  const code = String(source.code || '').trim();
  const name = String(source.name || '').trim();
  const builder = String(source?.payload?.builder || '').trim();
  if (code === 'lab_exam_vs_progress_nursing' || builder === 'lab_exam_progress_nursing') return '检验检查与病历护理核查';
  if (code === 'frontpage_surgery_diagnosis_vs_first_progress' || builder === 'frontpage_surgery_first_progress') return '首页手术与首次病程';
  if (code === 'progress_vs_nursing' || builder === 'legacy_progress_nursing') return '医嘱与病程及护理核查';
  if (code === 'orders_vs_progress' || builder === 'orders_progress_stub') return '医嘱与病程及护理核查';
  if (name.includes('检验') && name.includes('检查')) return '检验检查与病历护理核查';
  if (name.includes('首页') && name.includes('首次病程')) return '首页手术与首次病程';
  if (name.includes('医嘱')) return '医嘱与病程及护理核查';
  return '';
}

function parseObjectJsonSafe(text) {
  try {
    const parsed = JSON.parse(String(text || '{}'));
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function sourcesJsonToCards(sources) {
  const sourceObj = sources && typeof sources === 'object' && !Array.isArray(sources) ? sources : {};
  return Object.entries(sourceObj).map(([name, cfg]) => {
    const item = cfg && typeof cfg === 'object' && !Array.isArray(cfg) ? cfg : {};
    const mapping = item.field_mapping && typeof item.field_mapping === 'object' && !Array.isArray(item.field_mapping) ? item.field_mapping : {};
    return {
      name,
      label: SOURCE_LABELS[name] || name,
      type: item.type || 'sql',
      required: item.required === true,
      query_sql: String(item.query_sql || ''),
      field_mapping_rows: Object.entries(mapping).map(([key, value]) => ({ key, value: String(value || '') })),
      collapsed: false,
    };
  });
}

function sourceCardsToSourcesJson(cards) {
  const result = {};
  (cards || []).forEach((card) => {
    const name = String(card.name || '').trim();
    if (!name) return;
    const fieldMapping = {};
    (card.field_mapping_rows || []).forEach((row) => {
      const key = String(row.key || '').trim();
      const value = String(row.value || '').trim();
      if (key) fieldMapping[key] = value;
    });
    result[name] = {
      type: card.type || 'sql',
      query_sql: String(card.query_sql || ''),
      field_mapping: fieldMapping,
      required: card.required === true,
    };
  });
  return result;
}

function parseJsonFallback(text, fallback) {
  try {
    const parsed = JSON.parse(String(text || ''));
    return parsed === null || parsed === undefined ? fallback : parsed;
  } catch {
    return fallback;
  }
}

function sourceRowsFromObject(sources) {
  const sourceObj = sources && typeof sources === 'object' && !Array.isArray(sources) ? sources : {};
  return Object.entries(sourceObj).map(([name, cfg]) => {
    const item = cfg && typeof cfg === 'object' && !Array.isArray(cfg) ? cfg : {};
    const mapping = item.field_mapping && typeof item.field_mapping === 'object' && !Array.isArray(item.field_mapping) ? item.field_mapping : {};
    const querySql = String(item.query_sql || '');
    const mappingKeys = Object.keys(mapping);
    return {
      name,
      label: SOURCE_LABELS[name] || name,
      type: item.type || 'sql',
      required: item.required === true,
      mappingCount: mappingKeys.length,
      mappingPreview: mappingKeys.slice(0, 8).map((key) => `${key}->${mapping[key]}`).join('，'),
      hasSql: !!querySql.trim(),
      hasQueryDate: querySql.includes(':query_date') || querySql.includes(':date_from') || querySql.includes(':date_to'),
      hasDeptFilter: querySql.includes('{dept_filter}'),
    };
  });
}

export function createAuditTypeEditorState() {
  const payloadDefault = { builder: 'generic_multi_source', extra_fields: {} };
  return {
    code: '',
    name: '',
    description: '',
    enabled: true,
    sort_order: 100,
    default_for_schedule: false,
    group_key_text: 'patient_id, visit_number',
    sources_visual_mode: 'cards',
    source_cards: [],
    sources_text: prettyJson(
      {
        primary: {
          type: 'sql',
          query_sql: 'SELECT * FROM your_source_table WHERE 1 = 1',
          field_mapping: {},
          required: true,
        },
      },
      {},
    ),
    join_rules: [],
    join_rules_text: '[]',
    join_rules_json_dirty: false,
    payload_text: prettyJson(payloadDefault, {}),
    payload_quick: {
      builder: 'generic_multi_source',
      date_window_days: 0,
      progress_followup_days: 1,
      max_lab_items: 30,
      max_exam_reports: 10,
      include_normal_summary: false,
      retention_l3_days: 30,
      max_progress_records: 20,
      max_nursing_records: 20,
      max_progress_chars: 4000,
      max_nursing_chars: 4000,
    },
    dify: {
      base_url: '',
      api_key: '',
      workflow_input_variable: 'mr_txt',
      mr_type: '',
      workflow_output_key: 'aa',
      user_identifier: 'med-audit-system',
      timeout_seconds: 90,
      extra_inputs_text: '{}',
      targets_text: '[]',
    },
    response_text: prettyJson(
      {
        parse_strategy: 'hybrid',
        dimension_path: '$.dimensions',
        conclusion_path: '$.overall_conclusion',
        severity_path: '$.severity',
        risk_score_path: '$.risk_score',
        inconsistency_path: '$.inconsistency',
      },
      {},
    ),
    summary_blocks_text: '[]',
    detail_blocks_text: '[]',
  };
}

function parsePayloadJsonSafe(text) {
  try {
    const parsed = JSON.parse(String(text || '{}'));
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}


function joinRuleDisplayText(joinRules) {
  const rules = Array.isArray(joinRules) ? joinRules : [];
  if (!rules.length) return '未配置额外关联规则，仅使用默认 group_key 合并';
  return rules.map((rule) => {
    const name = String(rule?.name || '未命名规则').trim();
    const left = String(rule?.left_source || '').trim() || '左侧数据源';
    const right = String(rule?.right_source || '').trim() || '右侧数据源';
    const joinType = rule?.join_type === 'left' ? '左连接' : '内连接';
    const keys = Array.isArray(rule?.join_keys) ? rule.join_keys : [];
    const keyText = keys.map((item) => `${item?.left || '--'}=${item?.right || '--'}`).join(' + ') || '未配置关联键';
    return `${name}: ${left} ${joinType} ${right} (${keyText})`;
  }).join('；');
}

function extractPayloadQuick(payload) {
  const source = payload || {};
  return {
    builder: source.builder || 'generic_multi_source',
    date_window_days: Number(source.date_window_days ?? 0) || 0,
    progress_followup_days: Number(source.progress_followup_days ?? 1) || 0,
    max_lab_items: Number(source.max_lab_items ?? 30) || 0,
    max_exam_reports: Number(source.max_exam_reports ?? 10) || 0,
    include_normal_summary: source.include_normal_summary === true,
    retention_l3_days: Number(source?.retention_override?.l3_days ?? 30) || 0,
    max_progress_records: Number(source.max_progress_records ?? 20) || 0,
    max_nursing_records: Number(source.max_nursing_records ?? 20) || 0,
    max_progress_chars: Number(source.max_progress_chars ?? 4000) || 0,
    max_nursing_chars: Number(source.max_nursing_chars ?? 4000) || 0,
  };
}

function mergePayloadQuick(payload, quick) {
  const next = { ...(payload || {}) };
  const q = quick || {};
  next.builder = String(q.builder || next.builder || 'generic_multi_source').trim() || 'generic_multi_source';
  next.date_window_days = Number(q.date_window_days ?? next.date_window_days ?? 0) || 0;
  next.progress_followup_days = Number(q.progress_followup_days ?? next.progress_followup_days ?? 1) || 0;
  next.max_lab_items = Number(q.max_lab_items ?? next.max_lab_items ?? 30) || 0;
  next.max_exam_reports = Number(q.max_exam_reports ?? next.max_exam_reports ?? 10) || 0;
  next.include_normal_summary = q.include_normal_summary === true;
  next.max_progress_records = Number(q.max_progress_records ?? next.max_progress_records ?? 20) || 0;
  next.max_nursing_records = Number(q.max_nursing_records ?? next.max_nursing_records ?? 20) || 0;
  next.max_progress_chars = Number(q.max_progress_chars ?? next.max_progress_chars ?? 4000) || 0;
  next.max_nursing_chars = Number(q.max_nursing_chars ?? next.max_nursing_chars ?? 4000) || 0;
  next.retention_override = {
    ...(next.retention_override || {}),
    l3_days: Number(q.retention_l3_days ?? next?.retention_override?.l3_days ?? 30) || 30,
  };
  return next;
}

function normalizeAuditTypeEditor(data) {
  const next = createAuditTypeEditorState();
  const payload = data || {};
  const dify = payload.dify || {};
  const display = payload.display || {};
  const joinRules = Array.isArray(payload.join_rules) ? payload.join_rules : [];
  return {
    ...next,
    code: payload.code || '',
    name: payload.name || '',
    description: payload.description || '',
    enabled: payload.enabled !== false,
    sort_order: Number(payload.sort_order || 100),
    default_for_schedule: payload.default_for_schedule === true,
    group_key_text: Array.isArray(payload.group_key) && payload.group_key.length ? payload.group_key.join(', ') : next.group_key_text,
    sources_text: prettyJson(payload.sources || {}, {}),
    join_rules: joinRules,
    join_rules_text: prettyJson(joinRules, []),
    join_rules_json_dirty: false,
    payload_text: prettyJson(payload.payload || {}, {}),
    payload_quick: extractPayloadQuick(payload.payload || {}),
    dify: {
      base_url: dify.base_url || '',
      api_key: '',
      workflow_input_variable: dify.workflow_input_variable || 'mr_txt',
      mr_type: inferMrType(payload),
      workflow_output_key: dify.workflow_output_key || 'aa',
      user_identifier: dify.user_identifier || 'med-audit-system',
      timeout_seconds: Number(dify.timeout_seconds || 90),
      extra_inputs_text: prettyJson(dify.extra_inputs || {}, {}),
      targets_text: prettyJson(dify.targets || [], []),
    },
    response_text: prettyJson(payload.response || {}, {}),
    summary_blocks_text: prettyJson(display.summary_blocks || [], []),
    detail_blocks_text: prettyJson(display.detail_blocks || [], []),
  };
}

function buildAuditTypePayload(context) {
  const form = context.auditTypeForm || createAuditTypeEditorState();
  const groupKey = String(form.group_key_text || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
  const extraInputs = context.parseJsonText(form.dify.extra_inputs_text, 'Dify extra_inputs');
  const mrType = String(form.dify.mr_type || '').trim();
  if (mrType) {
    extraInputs.mr_type = mrType;
  } else {
    delete extraInputs.mr_type;
  }
  const dify = {
    base_url: String(form.dify.base_url || '').trim(),
    workflow_input_variable: String(form.dify.workflow_input_variable || 'mr_txt').trim() || 'mr_txt',
    workflow_output_key: String(form.dify.workflow_output_key || 'aa').trim() || 'aa',
    user_identifier: String(form.dify.user_identifier || 'med-audit-system').trim() || 'med-audit-system',
    timeout_seconds: Number(form.dify.timeout_seconds || 90),
    extra_inputs: extraInputs,
    targets: context.parseJsonText(form.dify.targets_text, 'Dify targets'),
  };
  if (String(form.dify.api_key || '').trim()) {
    dify.api_key = String(form.dify.api_key || '').trim();
  }
  const payloadJson = context.parseJsonText(form.payload_text, 'Payload 配置');
  const mergedPayload = mergePayloadQuick(payloadJson, form.payload_quick);
  return {
    code: String(form.code || '').trim(),
    name: String(form.name || '').trim(),
    description: String(form.description || '').trim(),
    enabled: form.enabled !== false,
    sort_order: Number(form.sort_order || 100),
    default_for_schedule: form.default_for_schedule === true,
    group_key: groupKey.length ? groupKey : ['patient_id', 'visit_number'],
    sources: context.parseJsonText(form.sources_text, '数据源配置'),
    join_rules: Array.isArray(form.join_rules) ? form.join_rules : [],
    payload: mergedPayload,
    dify,
    response: context.parseJsonText(form.response_text, '响应解析配置'),
    display: {
      summary_blocks: context.parseJsonText(form.summary_blocks_text, '摘要区块配置'),
      detail_blocks: context.parseJsonText(form.detail_blocks_text, '详情区块配置'),
    },
  };
}

export const auditTypeMethods = {
  selectAuditType(item) {
    this.selectedAuditType = item || null;
    this.auditDetailTab = 'basic';
  },

  handleAuditTypeAction(cmd, item) {
    if (cmd === 'clone') {
      this.openAuditTypeClone(item);
    } else if (cmd === 'test-source') {
      this.openAuditTypeSourceTest(item);
    } else if (cmd === 'test-dify') {
      this.openAuditTypeDifyTest(item);
    } else if (cmd === 'delete') {
      this.deleteAuditType(item);
    }
  },

  // 卡片操作函数
  syncSourcesCardsFromJson() {
    const sources = parseJsonFallback(this.auditTypeForm?.sources_text || '{}', {});
    this.auditTypeForm.source_cards = sourcesJsonToCards(sources);
  },

  applySourcesCardsToJson() {
    const sources = sourceCardsToSourcesJson(this.auditTypeForm?.source_cards || []);
    this.auditTypeForm.sources_text = prettyJson(sources, {});
  },

  addAuditTypeSourceCard() {
    this.auditTypeForm.source_cards.push({
      name: `source_${this.auditTypeForm.source_cards.length + 1}`,
      label: '',
      type: 'sql',
      required: false,
      query_sql: '',
      field_mapping_rows: [
        { key: 'patient_id', value: '患者ID' },
        { key: 'visit_number', value: '次数' },
      ],
      collapsed: false,
    });
  },

  copyAuditTypeSourceCard(index) {
    const card = this.auditTypeForm.source_cards[index];
    if (!card) return;
    this.auditTypeForm.source_cards.splice(index + 1, 0, {
      ...card,
      name: `${card.name}_copy`,
      field_mapping_rows: (card.field_mapping_rows || []).map((row) => ({ ...row })),
    });
  },

  removeAuditTypeSourceCard(index) {
    this.auditTypeForm.source_cards.splice(index, 1);
  },

  addSourceFieldMappingRow(sourceIndex) {
    if (!this.auditTypeForm.source_cards[sourceIndex]) return;
    this.auditTypeForm.source_cards[sourceIndex].field_mapping_rows.push({ key: '', value: '' });
  },

  removeSourceFieldMappingRow(sourceIndex, rowIndex) {
    if (!this.auditTypeForm.source_cards[sourceIndex]) return;
    this.auditTypeForm.source_cards[sourceIndex].field_mapping_rows.splice(rowIndex, 1);
  },

  auditTypeBuilderLabel(builder) {
    const key = String(builder || '').trim();
    return BUILDER_LABELS[key] || key || '未配置';
  },

  auditTypeCurrentSources() {
    return parseJsonFallback(this.auditTypeForm?.sources_text || '{}', {});
  },

  auditTypeCurrentPayload() {
    return parseJsonFallback(this.auditTypeForm?.payload_text || '{}', {});
  },

  auditTypeCurrentResponse() {
    return parseJsonFallback(this.auditTypeForm?.response_text || '{}', {});
  },

  auditTypeSourceRows(sourceOverride) {
    const sources = sourceOverride || this.auditTypeCurrentSources();
    return sourceRowsFromObject(sources);
  },

  auditTypeFlowSteps() {
    const payload = this.auditTypeCurrentPayload();
    const response = this.auditTypeCurrentResponse();
    return [
      { key: 'sources', order: 1, title: '数据源 SQL', desc: `${this.auditTypeSourceRows().length} 个数据源按 group_key 合并。` },
      { key: 'payload', order: 2, title: 'Payload 构建', desc: this.auditTypeBuilderLabel(payload.builder) },
      { key: 'dify', order: 3, title: 'Dify 工作流', desc: `${this.auditTypeForm?.dify?.workflow_input_variable || 'mr_txt'} 输入，${this.auditTypeForm?.dify?.workflow_output_key || 'aa'} 输出。` },
      { key: 'response', order: 4, title: '响应解析', desc: `策略 ${response.parse_strategy || 'hybrid'}，提取维度与结论。` },
      { key: 'display', order: 5, title: '审计展示', desc: 'summary/detail blocks 决定审计中心和报告展示。' },
    ];
  },

  auditTypeVisualDiagnostics() {
    const rows = this.auditTypeSourceRows();
    const payload = this.auditTypeCurrentPayload();
    const response = this.auditTypeCurrentResponse();
    const messages = [];
    if (!rows.length) {
      messages.push({ type: 'warning', message: '未解析出数据源，保存前请检查 sources JSON。' });
    }
    rows.forEach((row) => {
      if (!row.hasSql) messages.push({ type: 'warning', message: `${row.label} 未配置 query_sql。` });
      if (!row.hasDeptFilter) messages.push({ type: 'warning', message: `${row.label} SQL 未包含 {dept_filter}，科室过滤可能不生效。` });
      if (!row.hasQueryDate) messages.push({ type: 'info', message: `${row.label} SQL 未显式包含日期参数，请确认由 SQL 自身控制范围。` });
      if (!row.mappingCount) messages.push({ type: 'warning', message: `${row.label} 未配置 field_mapping，可能无法合并患者/住院次。` });
    });
    if (!payload.builder) messages.push({ type: 'warning', message: 'Payload 未配置 builder，将无法直观看出使用哪个构建器。' });
    if (!this.auditTypeForm?.dify?.workflow_input_variable) messages.push({ type: 'warning', message: 'Dify 主输入变量为空，默认应为 mr_txt。' });
    if (!this.auditTypeForm?.dify?.workflow_output_key) messages.push({ type: 'warning', message: 'Dify 输出变量为空，请与 End 节点输出保持一致。' });
    if (response.dimension_path && !String(response.dimension_path).startsWith('$')) messages.push({ type: 'warning', message: 'response.dimension_path 应以 $ 开头。' });
    if (!messages.length) messages.push({ type: 'success', message: '当前配置摘要未发现明显缺口，仍建议使用“测试数据源”和“测试 Dify”验证。' });
    return messages.slice(0, 8);
  },

  getMrTypeOptions() {
    const values = new Set(MR_TYPE_OPTIONS);
    (this.auditTypesList || []).forEach((item) => {
      const mrType = inferMrType(item);
      if (mrType) values.add(mrType);
    });
    const current = String(this.auditTypeForm?.dify?.mr_type || '').trim();
    if (current) values.add(current);
    return Array.from(values);
  },

  syncAuditTypeMrTypeFromExtraInputs() {
    const extraInputs = parseObjectJsonSafe(this.auditTypeForm?.dify?.extra_inputs_text || '{}');
    this.auditTypeForm.dify.mr_type = String(extraInputs.mr_type || '').trim();
  },

  applyAuditTypeMrTypeToExtraInputs() {
    const extraInputs = parseObjectJsonSafe(this.auditTypeForm?.dify?.extra_inputs_text || '{}');
    const mrType = String(this.auditTypeForm?.dify?.mr_type || '').trim();
    if (mrType) {
      extraInputs.mr_type = mrType;
    } else {
      delete extraInputs.mr_type;
    }
    this.auditTypeForm.dify.extra_inputs_text = prettyJson(extraInputs, {});
  },

  syncAuditTypePayloadQuickFromJson() {
    const parsed = parsePayloadJsonSafe(this.auditTypeForm?.payload_text || '{}');
    this.auditTypeForm.payload_quick = extractPayloadQuick(parsed);
  },

  applyAuditTypePayloadQuickToJson() {
    const parsed = parsePayloadJsonSafe(this.auditTypeForm?.payload_text || '{}');
    const merged = mergePayloadQuick(parsed, this.auditTypeForm?.payload_quick || {});
    this.auditTypeForm.payload_text = prettyJson(merged, {});
  },

  // 关联规则相关函数
  auditTypeSourceNames() {
    const sources = this.auditTypeCurrentSources();
    return Object.keys(sources || {});
  },

  auditTypeSourceOptions() {
    return this.auditTypeSourceNames().map((name) => ({
      value: name,
      label: SOURCE_LABELS[name] ? `${name}（${SOURCE_LABELS[name]}）` : name,
    }));
  },

  auditTypeRuleSummaryRows() {
    const payload = this.auditTypeCurrentPayload();
    const quick = this.auditTypeForm?.payload_quick || {};
    const builder = String(payload.builder || quick.builder || '').trim();
    const groupKey = String(this.auditTypeForm?.group_key_text || '').trim() || 'patient_id, visit_number';
    const followupDays = Number(quick.progress_followup_days ?? payload.progress_followup_days ?? 1) || 0;
    const maxLabItems = Number(quick.max_lab_items ?? payload.max_lab_items ?? 30) || 0;
    const maxExamReports = Number(quick.max_exam_reports ?? payload.max_exam_reports ?? 10) || 0;
    const maxProgressRecords = Number(quick.max_progress_records ?? payload.max_progress_records ?? 20) || 0;
    const maxNursingRecords = Number(quick.max_nursing_records ?? payload.max_nursing_records ?? 20) || 0;
    const maxProgressChars = Number(quick.max_progress_chars ?? payload.max_progress_chars ?? 4000) || 0;
    const maxNursingChars = Number(quick.max_nursing_chars ?? payload.max_nursing_chars ?? 4000) || 0;
    const rows = [
      {
        key: 'group_key',
        label: '默认分组合并',
        value: groupKey,
        hint: '系统始终先按这些字段把多源记录合并为同一个患者/住院次 bundle。',
      },
      {
        key: 'join_rules',
        label: '额外源间关联',
        value: joinRuleDisplayText(this.auditTypeForm?.join_rules),
        hint: 'join_rules 只在默认 bundle 内进一步要求两个数据源按指定字段匹配。',
      },
    ];
    if (builder === 'lab_exam_progress_nursing' || builder === 'lab_exam_structured_progress_nursing') {
      rows.push(
        {
          key: 'context_base',
          label: '病程/护理匹配基准',
          value: '异常检验 result_time + is_abnormal=true 的异常检查 report_time/exam_time',
          hint: '正常检查报告即使有描述也不参与上下文关联；出院日期/query_date 只负责 SQL 圈定患者。',
        },
        {
          key: 'progress_window',
          label: '病程窗口',
          value: '报告同一天，且病程时间晚于报告时间',
          hint: `按 event_time/record_time/title_time/create_time/sign_time 解析病程时间；未取到报告时间时才回退随访 ${followupDays} 天。`,
        },
        {
          key: 'nursing_window',
          label: '护理窗口',
          value: '报告同一天，且护理时间晚于报告时间',
          hint: '按 event_time/record_time/nurse_time 解析护理时间；没有报告时间时回退 query_date/出院日期。',
        },
        {
          key: 'limits',
          label: '载荷限制',
          value: `检验 ${maxLabItems} 条，检查 ${maxExamReports} 份，病程 ${maxProgressRecords} 条/${maxProgressChars} 字，护理 ${maxNursingRecords} 条/${maxNursingChars} 字`,
          hint: quick.include_normal_summary ? '包含正常检验/检查摘要。' : '默认只纳入异常或关键信息摘要。',
        },
      );
    } else {
      rows.push({
        key: 'payload_builder',
        label: 'Payload 构建规则',
        value: this.auditTypeBuilderLabel(builder),
        hint: '该构建器没有独立的检验检查事件时间窗口，按对应 builder 内置规则构建 mr_text。',
      });
    }
    return rows;
  },

  addJoinRule() {
    const sourceNames = this.auditTypeSourceNames();
    this.auditTypeForm.join_rules.push({
      name: `join_${this.auditTypeForm.join_rules.length + 1}`,
      description: '额外关联规则，不配置时仍按 group_key 默认合并',
      left_source: sourceNames[0] || '',
      right_source: sourceNames[1] || '',
      join_keys: [{ left: 'patient_id', right: 'patient_id' }, { left: 'visit_number', right: 'visit_number' }],
      join_type: 'inner',
    });
  },

  removeJoinRule(index) {
    this.auditTypeForm.join_rules.splice(index, 1);
  },

  addJoinKey(ruleIndex) {
    if (!this.auditTypeForm.join_rules[ruleIndex]) return;
    this.auditTypeForm.join_rules[ruleIndex].join_keys.push({ left: '', right: '' });
  },

  removeJoinKey(ruleIndex, keyIndex) {
    if (!this.auditTypeForm.join_rules[ruleIndex]) return;
    this.auditTypeForm.join_rules[ruleIndex].join_keys.splice(keyIndex, 1);
  },

  syncJoinRulesFromJson() {
    const text = String(this.auditTypeForm?.join_rules_text || '[]').trim();
    try {
      const parsed = JSON.parse(text);
      if (!Array.isArray(parsed)) {
        ElementPlus.ElMessage.error('关联规则 JSON 必须是数组格式');
        return false;
      }
      this.auditTypeForm.join_rules = parsed;
      this.auditTypeForm.join_rules_json_dirty = false;
      return true;
    } catch (e) {
      ElementPlus.ElMessage.error('关联规则 JSON 格式错误，请检查后重试');
      return false;
    }
  },

  applyJoinRulesToJson() {
    this.auditTypeForm.join_rules_text = prettyJson(this.auditTypeForm.join_rules || [], []);
    this.auditTypeForm.join_rules_json_dirty = false;
  },

  markJoinRulesJsonDirty() {
    this.auditTypeForm.join_rules_json_dirty = true;
  },

  async loadAuditTypesPage() {
    await this.runConfigAction(async () => {
      await this.loadAuditTypesList();
    });
    this.loadAuditTypeRuntimeSummary().catch(() => {});
  },

  async loadAuditTypesList() {
    try {
      const response = await apiGet('/api/audit-types');
      this.auditTypesList = response.data?.items || [];
      if (!this.selectedAuditType && this.auditTypesList.length) {
        this.selectAuditType(this.auditTypesList[0]);
      }
    } catch (error) {
      this.showApiError(error, '加载审计类型列表失败');
    }
  },

  openAuditTypeCreate() {
    this.auditTypeDialogMode = 'create';
    this.auditTypeEditorTab = 'overview';
    this.auditTypeForm = createAuditTypeEditorState();
    this.syncAuditTypePayloadQuickFromJson();
    this.syncSourcesCardsFromJson();
    this.auditTypeDialogVisible = true;
  },

  async openAuditTypeEdit(row) {
    try {
      const response = await apiGet(`/api/audit-types/${row.code}`);
      this.auditTypeDialogMode = 'edit';
      this.auditTypeEditorTab = 'overview';
      this.auditTypeForm = normalizeAuditTypeEditor(response.data || {});
      this.syncAuditTypePayloadQuickFromJson();
      this.syncSourcesCardsFromJson();
      this.auditTypeDialogVisible = true;
    } catch (error) {
      this.showApiError(error, '加载审计类型详情失败');
    }
  },

  async submitAuditTypeForm() {
    // 如果是卡片模式，先应用卡片到 JSON
    if (this.auditTypeForm?.sources_visual_mode === 'cards') {
      this.applySourcesCardsToJson();
    }
    // JSON 文本被直接编辑时优先解析 JSON；否则以表单数据为权威。
    if (this.auditTypeForm?.join_rules_json_dirty) {
      if (!this.syncJoinRulesFromJson()) {
        return;
      }
    } else {
      this.applyJoinRulesToJson();
    }
    this.applyAuditTypePayloadQuickToJson();
    this.applyAuditTypeMrTypeToExtraInputs();
    const payload = buildAuditTypePayload(this);
    if (!payload.code || !payload.name) {
      ElementPlus.ElMessage.warning('请填写编码和名称');
      return;
    }
    await this.runConfigAction(async () => {
      if (this.auditTypeDialogMode === 'create') {
        await apiPost('/api/audit-types', payload);
      } else {
        await apiPut(`/api/audit-types/${this.auditTypeForm.code}`, payload);
      }
      this.auditTypeDialogVisible = false;
      await Promise.all([this.loadAuditTypesList(), this.loadAuditTypeOptions()]);
    }, this.auditTypeDialogMode === 'create' ? '审计类型已创建' : '审计类型已更新');
  },

  async deleteAuditType(row) {
    try {
      await ElementPlus.ElMessageBox.confirm(
        `确认删除审计类型“${row.name || row.code}”吗？此操作会移除配置。`,
        '删除审计类型',
        { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
      );
    } catch {
      return;
    }
    await this.runConfigAction(async () => {
      await apiDelete(`/api/audit-types/${row.code}`);
      await Promise.all([this.loadAuditTypesList(), this.loadAuditTypeOptions()]);
    }, '审计类型已删除');
  },

  openAuditTypeClone(row) {
    this.auditTypeCloneForm = {
      source_code: row.code,
      new_code: `${row.code}_copy`,
      new_name: `${row.name} - 副本`,
    };
    this.auditTypeCloneDialogVisible = true;
  },

  async submitAuditTypeClone() {
    if (!this.auditTypeCloneForm.source_code || !this.auditTypeCloneForm.new_code || !this.auditTypeCloneForm.new_name) {
      ElementPlus.ElMessage.warning('请填写克隆编码和名称');
      return;
    }
    await this.runConfigAction(async () => {
      await apiPost(`/api/audit-types/${this.auditTypeCloneForm.source_code}/clone`, {
        new_code: this.auditTypeCloneForm.new_code,
        new_name: this.auditTypeCloneForm.new_name,
      });
      this.auditTypeCloneDialogVisible = false;
      await Promise.all([this.loadAuditTypesList(), this.loadAuditTypeOptions()]);
    }, '审计类型已克隆');
  },

  openAuditTypeSourceTest(row) {
    this.auditTypeSourceTestForm = {
      code: row.code,
      query_date: this.auditTypeSourceTestForm.query_date || '',
      date_dimension: this.auditTypeSourceTestForm.date_dimension || 'query_date',
      dept_filter_text: '',
    };
    this.auditTypeSourceTestResult = null;
    this.auditTypeSourceTestDialogVisible = true;
  },

  async submitAuditTypeSourceTest() {
    const code = this.auditTypeSourceTestForm.code;
    if (!code || !this.auditTypeSourceTestForm.query_date) {
      ElementPlus.ElMessage.warning('请填写测试日期');
      return;
    }
    const deptList = String(this.auditTypeSourceTestForm.dept_filter_text || '')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
    await this.runConfigAction(async () => {
      const response = await apiPost(`/api/audit-types/${code}/test-source`, {
        query_date: this.auditTypeSourceTestForm.query_date,
        date_dimension: this.auditTypeSourceTestForm.date_dimension,
        dept_filter: deptList.length ? deptList : null,
      });
      this.auditTypeSourceTestResult = response.data || {};
    });
  },

  auditTestSkipReasonRows() {
    const counts = this.auditTypeSourceTestResult?.precheck?.skip_reason_counts || {};
    const labels = {
      empty_lab_exam: '检验检查数据为空',
      empty_progress_nursing: '病程护理记录为空',
      empty_both_sides: '检验检查和病程护理均为空',
    };
    return Object.entries(counts).map(([reason, count]) => ({
      reason,
      label: labels[reason] || reason,
      count,
    }));
  },

  openAuditTypeDifyTest(row) {
    this.auditTypeDifyTestForm = {
      code: row.code,
      mr_txt_sample: this.auditTypeDifyTestForm.mr_txt_sample || '',
    };
    this.auditTypeDifyTestResult = null;
    this.auditTypeDifyTestDialogVisible = true;
  },

  // ── 审计类型页 Runtime Summary 只读提示 ────────────────────────────────────

  async loadAuditTypeRuntimeSummary() {
    this.auditTypeRuntimeSummaryLoading = true;
    this.auditTypeRuntimeSummaryError = '';
    try {
      const r = await apiGet('/api/config/runtime-summary');
      this.auditTypeRuntimeSummary = r.data || {};
    } catch (e) {
      this.auditTypeRuntimeSummaryError = this.getErrorMessage
        ? this.getErrorMessage(e, '审计类型配置风险提示加载失败')
        : String(e?.message || e || '');
    } finally {
      this.auditTypeRuntimeSummaryLoading = false;
    }
  },

  auditTypeRuntimeWarnings() {
    const summary = this.auditTypeRuntimeSummary;
    if (!summary) return [];
    const all = summary.warnings || [];
    return all.filter((w) => {
      const p = w.path || '';
      return p.startsWith('audit_types.');
    });
  },

  auditTypeWarningsByLevel(level) {
    return this.auditTypeRuntimeWarnings().filter((w) => w.level === level);
  },

  auditTypeWarningTagType(level) {
    if (level === 'error') return 'danger';
    if (level === 'warning') return 'warning';
    return 'info';
  },

  auditTypeRuntimeSummaries() {
    const summary = this.auditTypeRuntimeSummary;
    if (!summary) return [];
    return summary.audit_types || [];
  },

  auditTypeRuntimeSourceRows(at) {
    if (!at || !Array.isArray(at.sources)) return [];
    return at.sources.map((s) => ({
      key: s.key || '--',
      type: s.type || '--',
      backend: s.backend || '--',
      required: s.required === true,
      hasQuerySql: s.has_query_sql === true,
    }));
  },

  auditTypeRuntimeDifyTarget(at) {
    if (!at || !at.dify_target) return {};
    return at.dify_target;
  },

  auditTypeRuntimeTargetSource(at) {
    const dt = this.auditTypeRuntimeDifyTarget(at);
    return dt.target_source || '--';
  },

  auditTypeRuntimeWorkflowInput(at) {
    const dt = this.auditTypeRuntimeDifyTarget(at);
    return dt.workflow_input_variable || '--';
  },

  auditTypeRuntimeHasApiKey(at) {
    const dt = this.auditTypeRuntimeDifyTarget(at);
    return dt.has_api_key === true;
  },

  auditTypeRuntimeHasBaseUrl(at) {
    const dt = this.auditTypeRuntimeDifyTarget(at);
    return !!(dt.base_url);
  },

  auditTypeRuntimeFlagType(value) {
    if (value) return 'success';
    return 'info';
  },

  async submitAuditTypeDifyTest() {
    const code = this.auditTypeDifyTestForm.code;
    if (!code || !String(this.auditTypeDifyTestForm.mr_txt_sample || '').trim()) {
      ElementPlus.ElMessage.warning('请填写 Dify 测试文本');
      return;
    }
    await this.runConfigAction(async () => {
      const response = await apiPost(`/api/audit-types/${code}/test-dify`, {
        mr_txt_sample: this.auditTypeDifyTestForm.mr_txt_sample,
      });
      this.auditTypeDifyTestResult = response.data || {};
    });
  },
};
