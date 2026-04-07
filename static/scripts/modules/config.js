import { apiGet, apiPost } from '../utils/api.js';

function createFieldMapping() {
  return {
    patient_id: '患者ID',
    visit_number: '次数',
    patient_name: '患者姓名',
    dept: '所在科室名称',
    admission_no: '住院号',
  };
}

function createNotifyChannel() {
  return {
    type: 'webhook',
    enabled: true,
    config: {},
    configText: '{}',
  };
}

export const configMethods = {
  async onDataSourceChange(newType) {
    const previous = this.dataSourceTypeBeforeSwitch || this.dataSourceType;
    try {
      await ElementPlus.ElMessageBox.confirm(
        `确认将数据源切换为 ${newType === 'postgresql' ? 'PostgreSQL' : 'Oracle'}？`,
        '切换数据源',
        {
          confirmButtonText: '确认切换',
          cancelButtonText: '取消',
          type: 'warning',
        },
      );
      await this.saveDataSource();
      this.dataSourceTypeBeforeSwitch = this.dataSourceType;
    } catch (e) {
      this.dataSourceType = previous;
    }
  },

  parseJsonText(text, fieldName) {
    const raw = (text || '').trim();
    if (!raw) return {};
    try {
      return JSON.parse(raw);
    } catch (e) {
      throw new Error(`${fieldName} 不是合法 JSON`);
    }
  },

  validateJsonRealtime(text, targetKey, label, allowEmpty = true) {
    const raw = String(text || '').trim();
    if (!raw) {
      this.jsonErrors[targetKey] = allowEmpty ? '' : `${label}不能为空`;
      return;
    }
    try {
      JSON.parse(raw);
      this.jsonErrors[targetKey] = '';
    } catch (e) {
      this.jsonErrors[targetKey] = `${label} JSON 格式错误: ${e.message}`;
    }
  },

  validateNotifyJsonRealtime(index, text) {
    const raw = String(text || '').trim();
    const next = { ...(this.jsonErrors.notifyConfig || {}) };
    if (!raw) {
      next[index] = '';
    } else {
      try {
        JSON.parse(raw);
        next[index] = '';
      } catch (e) {
        next[index] = `通知渠道 JSON 格式错误: ${e.message}`;
      }
    }
    this.jsonErrors.notifyConfig = next;
  },

  onDifyExtraInputsInput() {
    this.validateJsonRealtime(this.difyForm.extra_inputs_text, 'difyExtraInputs', '额外参数');
  },

  onDebugExtraInputsInput() {
    this.validateJsonRealtime(this.debugForm.extra_inputs_text, 'debugExtraInputs', '调试额外参数');
  },

  onDebugPayloadInput() {
    this.validateJsonRealtime(this.debugForm.payload_json_text, 'debugPayload', '结构化调试 JSON');
  },

  onNotifyConfigInput(index) {
    const item = this.notifyChannels[index] || {};
    this.validateNotifyJsonRealtime(index, item.configText || '');
  },

  normalizeDeptList(text) {
    return (text || '')
      .split(/\r?\n|,|，/)
      .map((item) => item.trim())
      .filter(Boolean);
  },

  updateTestResult(key, payload) {
    this.configTestResult = { ...this.configTestResult, [key]: payload };
  },

  switchConfigTab(tab) {
    this.configTab = tab;
    const loaders = {
      oracle: () => this.loadOracleConfig(),
      postgresql: () => this.loadPostgresqlConfig(),
      dify: () => this.loadDifyConfig(),
      dept: () => this.loadDeptConfig(),
      push: () => this.loadPushSettings(),
      privacy: () => this.loadPrivacyMaskingConfig(),
      notify: () => this.loadNotifyConfig(),
    };
    if (loaders[tab]) loaders[tab]();
  },

  normalizeConfigTabName(name) {
    if (name === 'data-source') return this.dataSourceType === 'postgresql' ? 'postgresql' : 'oracle';
    return String(name || '');
  },

  configTabStatus(tabName) {
    const tab = this.normalizeConfigTabName(tabName);
    const configured = !!this.configStatusConfigured[tab];
    if (!configured) return 'missing';
    if (this.configTabTested(tab)) return 'ready';
    return 'untested';
  },

  configTabTested(tab) {
    if (tab === 'oracle') return this.configTestResult?.oracle?.status === 'up';
    if (tab === 'postgresql') return this.configTestResult?.postgresql?.status === 'up';
    if (tab === 'dify') return this.configTestResult?.dify?.status === 'up';
    if (tab === 'notify') {
      const keys = Object.keys(this.configTestResult || {}).filter((key) => key.startsWith('notify-'));
      return keys.some((key) => this.configTestResult?.[key]?.success);
    }
    if (tab === 'dept' || tab === 'push' || tab === 'privacy') return false;
    return false;
  },

  configStatusText(tabName) {
    const state = this.configTabStatus(tabName);
    if (state === 'ready') return '已配置并测试通过';
    if (state === 'untested') return '已配置未测试';
    return '未配置';
  },

  configStatusTagType(tabName) {
    const state = this.configTabStatus(tabName);
    if (state === 'ready') return 'success';
    if (state === 'untested') return 'warning';
    return 'danger';
  },

  isOracleConfigured(data) {
    return !!(data?.host && data?.service_name && data?.username && (data?.password_masked || data?.password));
  },

  isPostgresqlConfigured(data) {
    return !!(data?.host && data?.database && data?.username && (data?.password_masked || data?.password));
  },

  isDifyConfigured(data) {
    return !!(data?.base_url && (data?.api_key_masked || data?.api_key) && data?.workflow_input_variable && data?.workflow_output_key);
  },

  isDeptConfigured(data) {
    return Array.isArray(data?.list) && data.list.length > 0;
  },

  isPushConfigured(data) {
    return Number(data?.interval_ms) > 0 && Number(data?.max_retry) >= 0 && Number(data?.batch_size) > 0;
  },

  isPrivacyConfigured(data) {
    return data && typeof data === 'object' && Object.prototype.hasOwnProperty.call(data, 'enabled');
  },

  isNotifyConfigured(data) {
    return Array.isArray(data?.channels) && data.channels.length > 0;
  },

  async loadConfigStatusSummary() {
    try {
      const [oracleR, postgresqlR, difyR, deptR, pushR, privacyR, notifyR] = await Promise.all([
        apiGet('/api/config/oracle').catch(() => ({ data: {} })),
        apiGet('/api/config/postgresql').catch(() => ({ data: {} })),
        apiGet('/api/config/dify').catch(() => ({ data: {} })),
        apiGet('/api/config/departments').catch(() => ({ data: {} })),
        apiGet('/api/config/push').catch(() => ({ data: {} })),
        apiGet('/api/config/privacy-masking').catch(() => ({ data: {} })),
        apiGet('/api/config/notify').catch(() => ({ data: {} })),
      ]);
      this.configStatusConfigured = {
        oracle: this.isOracleConfigured(oracleR.data || {}),
        postgresql: this.isPostgresqlConfigured(postgresqlR.data || {}),
        dify: this.isDifyConfigured(difyR.data || {}),
        dept: this.isDeptConfigured(deptR.data || {}),
        push: this.isPushConfigured(pushR.data || {}),
        privacy: this.isPrivacyConfigured(privacyR.data || {}),
        notify: this.isNotifyConfigured(notifyR.data || {}),
      };
    } catch (e) {
      this.showApiError(e, '加载配置状态失败');
    }
  },

  async loadDataSource() {
    try {
      const r = await apiGet('/api/config/data-source');
      this.dataSourceType = r.data.type || 'oracle';
      this.dataSourceTypeBeforeSwitch = this.dataSourceType;
    } catch (e) {
      this.showApiError(e, '加载数据源失败');
    }
  },

  async saveDataSource() {
    try {
      await apiPost('/api/config/data-source', { type: this.dataSourceType });
      ElementPlus.ElMessage.success('数据源已切换');
    } catch (e) {
      this.showApiError(e, '切换数据源失败');
    }
  },

  async runConfigAction(action, successMessage) {
    this.cfgLoading = true;
    try {
      const result = await action();
      if (successMessage) ElementPlus.ElMessage.success(successMessage);
      return result;
    } catch (e) {
      this.showApiError(e);
      throw e;
    } finally {
      this.cfgLoading = false;
    }
  },

  async loadOracleConfig() {
    await this.runConfigAction(async () => {
      const r = await apiGet('/api/config/oracle');
      const data = r.data || {};
      this.oracleForm = {
        host: data.host || '',
        port: data.port || 1521,
        service_name: data.service_name || '',
        username: data.username || '',
        password: '',
        password_masked: data.password_masked || '',
        instant_client_dir: data.instant_client_dir || '',
        query_sql: data.query_sql || '',
        dept_sql: data.dept_sql || '',
        field_mapping: { ...createFieldMapping(), ...(data.field_mapping || {}) },
      };
    });
  },

  async saveOracleConfig() {
    await this.runConfigAction(async () => {
      const body = {
        host: this.oracleForm.host,
        port: Number(this.oracleForm.port),
        service_name: this.oracleForm.service_name,
        username: this.oracleForm.username,
        password: this.oracleForm.password,
        instant_client_dir: this.oracleForm.instant_client_dir,
        query_sql: this.oracleForm.query_sql,
        dept_sql: this.oracleForm.dept_sql,
        field_mapping: { ...this.oracleForm.field_mapping },
      };
      await apiPost('/api/config/oracle', body);
      this.oracleForm.password = '';
      await this.loadOracleConfig();
      await this.loadConfigStatusSummary();
    }, 'Oracle 配置已保存');
  },

  async testOracleConfig() {
    const result = await this.runConfigAction(async () => {
      const r = await apiPost('/api/config/oracle/test');
      this.updateTestResult('oracle', r.data);
      return r.data;
    }, 'Oracle 测试请求已发送');
    if (result?.status === 'up') ElementPlus.ElMessage.success('Oracle 连接成功');
  },

  async loadPostgresqlConfig() {
    await this.runConfigAction(async () => {
      const r = await apiGet('/api/config/postgresql');
      const data = r.data || {};
      this.postgresqlForm = {
        host: data.host || 'localhost',
        port: data.port || 5432,
        database: data.database || '',
        username: data.username || '',
        password: '',
        password_masked: data.password_masked || '',
        query_sql: data.query_sql || '',
        dept_sql: data.dept_sql || '',
        field_mapping: { ...createFieldMapping(), ...(data.field_mapping || {}) },
      };
    });
  },

  async savePostgresqlConfig() {
    await this.runConfigAction(async () => {
      const body = {
        host: this.postgresqlForm.host,
        port: Number(this.postgresqlForm.port),
        database: this.postgresqlForm.database,
        username: this.postgresqlForm.username,
        password: this.postgresqlForm.password,
        query_sql: this.postgresqlForm.query_sql,
        dept_sql: this.postgresqlForm.dept_sql,
        field_mapping: { ...this.postgresqlForm.field_mapping },
      };
      await apiPost('/api/config/postgresql', body);
      this.postgresqlForm.password = '';
      await this.loadPostgresqlConfig();
      await this.loadConfigStatusSummary();
    }, 'PostgreSQL 配置已保存');
  },

  async testPostgresqlConfig() {
    const result = await this.runConfigAction(async () => {
      const r = await apiPost('/api/config/postgresql/test');
      this.updateTestResult('postgresql', r.data);
      return r.data;
    }, 'PostgreSQL 测试请求已发送');
    if (result?.status === 'up') ElementPlus.ElMessage.success('PostgreSQL 连接成功');
  },

  async loadDifyConfig() {
    await this.runConfigAction(async () => {
      const r = await apiGet('/api/config/dify');
      const data = r.data || {};
      this.difyForm = {
        base_url: data.base_url || '',
        api_key: '',
        api_key_masked: data.api_key_masked || '',
        workflow_input_variable: data.workflow_input_variable || 'mr_txt',
        workflow_output_key: data.workflow_output_key || 'aa',
        user_identifier: data.user_identifier || '',
        timeout_seconds: data.timeout_seconds || 90,
        extra_inputs_text: JSON.stringify(data.extra_inputs || {}, null, 2),
      };
      this.onDifyExtraInputsInput();
    });
  },

  async saveDifyConfig() {
    await this.runConfigAction(async () => {
      if (this.jsonErrors.difyExtraInputs) {
        throw new Error(this.jsonErrors.difyExtraInputs);
      }
      const body = {
        base_url: this.difyForm.base_url,
        api_key: this.difyForm.api_key,
        workflow_input_variable: this.difyForm.workflow_input_variable,
        workflow_output_key: this.difyForm.workflow_output_key,
        user_identifier: this.difyForm.user_identifier,
        timeout_seconds: Number(this.difyForm.timeout_seconds),
        extra_inputs: this.parseJsonText(this.difyForm.extra_inputs_text, '额外参数'),
      };
      await apiPost('/api/config/dify', body);
      this.difyForm.api_key = '';
      await this.loadDifyConfig();
      await this.loadConfigStatusSummary();
    }, 'Dify 配置已保存');
  },

  async testDifyConfig() {
    const result = await this.runConfigAction(async () => {
      const r = await apiPost('/api/config/dify/test');
      this.updateTestResult('dify', r.data);
      return r.data;
    }, 'Dify 测试请求已发送');
    if (result?.status === 'up') ElementPlus.ElMessage.success('Dify 连接成功');
  },

  async loadDeptConfig() {
    await this.runConfigAction(async () => {
      const [cfgR, listR] = await Promise.all([
        apiGet('/api/config/departments'),
        apiGet('/api/config/departments/list').catch(() => ({ data: { departments: [] } })),
      ]);
      const data = cfgR.data || {};
      this.deptForm = {
        mode: data.mode || 'include',
        listText: (data.list || []).join('\n'),
      };
      this.deptCandidates = listR.data.departments || [];
    });
  },

  async refreshDeptCandidates() {
    await this.runConfigAction(async () => {
      const r = await apiGet('/api/config/departments/list');
      this.deptCandidates = r.data.departments || [];
    }, '科室列表已刷新');
  },

  async saveDeptConfig() {
    await this.runConfigAction(async () => {
      const body = {
        mode: this.deptForm.mode,
        list: this.normalizeDeptList(this.deptForm.listText),
      };
      await apiPost('/api/config/departments', body);
      await this.loadDeptConfig();
      await this.loadConfigStatusSummary();
    }, '科室配置已保存');
  },

  appendDept(name) {
    const items = this.normalizeDeptList(this.deptForm.listText);
    if (!items.includes(name)) items.push(name);
    this.deptForm.listText = items.join('\n');
  },

  async loadPushSettings() {
    await this.runConfigAction(async () => {
      const r = await apiGet('/api/config/push');
      const data = r.data || {};
      this.pushSettingsForm = {
        interval_ms: data.interval_ms || 500,
        max_retry: data.max_retry || 3,
        batch_size: data.batch_size || 50,
      };
    });
  },

  async savePushSettings() {
    await this.runConfigAction(async () => {
      const body = {
        interval_ms: Number(this.pushSettingsForm.interval_ms),
        max_retry: Number(this.pushSettingsForm.max_retry),
        batch_size: Number(this.pushSettingsForm.batch_size),
      };
      await apiPost('/api/config/push', body);
      await this.loadConfigStatusSummary();
    }, '推送参数已保存');
  },

  async loadPrivacyMaskingConfig() {
    await this.runConfigAction(async () => {
      const r = await apiGet('/api/config/privacy-masking');
      const data = r.data || {};
      this.privacyMaskingForm = {
        enabled: !!data.enabled,
        mask_name: data.mask_name !== false,
        mask_id_card: data.mask_id_card !== false,
        mask_address: data.mask_address !== false,
        mask_phone: data.mask_phone !== false,
      };
    });
  },

  async savePrivacyMaskingConfig() {
    await this.runConfigAction(async () => {
      await apiPost('/api/config/privacy-masking', {
        enabled: !!this.privacyMaskingForm.enabled,
        mask_name: !!this.privacyMaskingForm.mask_name,
        mask_id_card: !!this.privacyMaskingForm.mask_id_card,
        mask_address: !!this.privacyMaskingForm.mask_address,
        mask_phone: !!this.privacyMaskingForm.mask_phone,
      });
      await this.loadConfigStatusSummary();
    }, '隐私脱敏配置已保存');
  },

  async loadNotifyConfig() {
    await this.runConfigAction(async () => {
      const r = await apiGet('/api/config/notify');
      const channels = (r.data.channels || []).map((item) => ({
        ...item,
        configText: JSON.stringify(item.config || {}, null, 2),
      }));
      this.notifyChannels = channels.length ? channels : [createNotifyChannel()];
      this.jsonErrors.notifyConfig = {};
      this.notifyChannels.forEach((_, index) => this.onNotifyConfigInput(index));
    });
  },

  addNotifyChannel() {
    this.notifyChannels.push(createNotifyChannel());
    this.onNotifyConfigInput(this.notifyChannels.length - 1);
  },

  removeNotifyChannel(index) {
    this.notifyChannels.splice(index, 1);
    if (!this.notifyChannels.length) this.notifyChannels.push(createNotifyChannel());
    const next = { ...(this.jsonErrors.notifyConfig || {}) };
    delete next[index];
    this.jsonErrors.notifyConfig = next;
  },

  async saveNotifyConfig() {
    await this.runConfigAction(async () => {
      const notifyErrors = Object.values(this.jsonErrors.notifyConfig || {}).filter(Boolean);
      if (notifyErrors.length) {
        throw new Error(String(notifyErrors[0]));
      }
      const channels = this.notifyChannels.map((item) => ({
        type: item.type,
        enabled: !!item.enabled,
        config: this.parseJsonText(item.configText, `通知渠道${item.type}`),
      }));
      await apiPost('/api/config/notify', { channels });
      await this.loadNotifyConfig();
      await this.loadConfigStatusSummary();
    }, '通知配置已保存');
  },

  async testNotifyChannel(index) {
    const item = this.notifyChannels[index];
    if (this.jsonErrors.notifyConfig?.[index]) {
      throw new Error(this.jsonErrors.notifyConfig[index]);
    }
    const payload = {
      type: item.type,
      enabled: !!item.enabled,
      config: this.parseJsonText(item.configText, `通知渠道${item.type}`),
    };
    const result = await this.runConfigAction(async () => {
      const r = await apiPost('/api/notify/test', payload);
      this.updateTestResult(`notify-${index}`, r.data);
      return r.data;
    }, '通知测试请求已发送');
    if (result?.success) ElementPlus.ElMessage.success('通知测试成功');
  },

  debugParseSuccess(result) {
    return !!(result && result.parsed_output && result.parsed_output.parse_success);
  },

  debugValidationType(result) {
    if (!result) return 'info';
    if (this.debugParseSuccess(result)) return 'success';
    if (result.parse_error || result.parsed_output?.parse_error) return 'error';
    return 'warning';
  },

  debugValidationText(result) {
    if (!result) return '未执行调试';
    if (this.debugParseSuccess(result)) return 'JSON 合法，已成功解析为结构化结果';
    if (result.parse_error || result.parsed_output?.parse_error) return 'JSON 解析失败，已进入兼容兜底逻辑';
    return '未解析出标准 JSON，结果可能仅完成了部分兼容处理';
  },

  debugParseError(result) {
    return result?.parse_error || result?.parsed_output?.parse_error || '';
  },

  debugRawOutput(result) {
    return this.prettyJson(result?.result || result?.raw_text || '');
  },

  debugParsedPreview(result) {
    return this.prettyJson(result?.parsed_output || '');
  },

  createDebugPayloadTemplate() {
    return {
      request_id: 'demo_patient_1_2026-04-02',
      audit_date: '2026-04-02',
      match_rule: 'patient_id + visit_number + date',
      patient_info: {
        patient_id: 'demo_patient_1',
        visit_number: '1',
        admission_no: 'demo001',
        patient_name: '测试患者',
        gender: '男',
        birth_date: '1970-01-01',
        admission_date: '2026-04-02 08:00:00',
        bed_no: '01',
        admission_diagnosis: '双侧感音神经性耳聋',
        admission_condition: '一般',
        nursing_level_order: '一级护理',
        department: '听觉植入科',
        attending_doctor: '测试医生',
      },
      medical_documents: [
        {
          document_time: '2026-04-02 09:00:00',
          document_name: '首次病程记录',
          signed_doctor: '测试医生',
          content: '患者因双耳听力下降入院，精神状态尚可，拟完善术前检查。',
        },
      ],
      nursing_records: [
        {
          record_time: '2026-04-02 09:10:00',
          record_type: '一般患者护理记录单',
          recorder: '测试护士',
          content: '患者神志清，已完成入科宣教，嘱留陪人。',
          vitals: {
            temperature: '36.6',
            heart_rate_pulse: '80',
            respiratory_rate: '20',
            blood_pressure: '116/74',
            oxygen_saturation: '',
            blood_glucose: '',
          },
          assessment: {
            consciousness: '清醒',
            skin_condition: '完好',
            wound_condition: '',
            tube_care: '',
            high_risk: '',
          },
          supportive_care: {
            oxygen_nasal_cannula: '',
            oxygen_mask: '',
            intake: '',
            output: '',
            urine_volume: '',
          },
        },
      ],
    };
  },

  fillDebugPayloadTemplate() {
    this.debugForm.payload_json_text = JSON.stringify(this.createDebugPayloadTemplate(), null, 2);
  },

  async loadHealth() {
    try {
      const r = await apiGet('/api/health');
      this.healthComps = r.data.components || {};
      this.overallHealth = r.data.status || 'healthy';
      this.healthTime = new Date().toLocaleString('zh-CN');
    } catch (e) {
      this.overallHealth = 'unhealthy';
    }
  },

  async pingHealthComponent(name) {
    const endpointMap = {
      oracle: '/api/health/oracle',
      postgresql: '/api/health/postgresql',
      dify: '/api/health/dify',
    };
    const endpoint = endpointMap[name];
    if (!endpoint) return;
    const result = await this.runConfigAction(async () => {
      const r = await apiGet(endpoint);
      this.healthComps = { ...this.healthComps, [name]: r.data };
      return r.data;
    }, `${this.cname(name)} 检测已完成`);
    if (result?.status === 'up') ElementPlus.ElMessage.success(`${this.cname(name)} 正常`);
  },

  resetDebugPage() {
    this.debugResult = null;
    if (!this.difyForm.workflow_input_variable) {
      this.loadDifyConfig();
    }
    this.debugForm = {
      input_mode: 'json',
      mr_txt: '',
      payload_json_text: JSON.stringify(this.createDebugPayloadTemplate(), null, 2),
      user: 'debug-user',
      workflow_input_variable: this.difyForm.workflow_input_variable || '',
      workflow_output_key: this.difyForm.workflow_output_key || '',
      extra_inputs_text: this.difyForm.extra_inputs_text || '{}',
    };
    this.onDebugExtraInputsInput();
    this.onDebugPayloadInput();
  },

  async runDifyDebug() {
    if (this.debugForm.input_mode === 'text' && !this.debugForm.mr_txt.trim()) {
      ElementPlus.ElMessage.warning('请输入调试文本');
      return;
    }
    const result = await this.runConfigAction(async () => {
      if (this.debugForm.input_mode === 'json' && this.jsonErrors.debugPayload) {
        throw new Error(this.jsonErrors.debugPayload);
      }
      if (this.jsonErrors.debugExtraInputs) {
        throw new Error(this.jsonErrors.debugExtraInputs);
      }
      const payloadJson = this.debugForm.input_mode === 'json'
        ? this.parseJsonText(this.debugForm.payload_json_text, '结构化调试 JSON')
        : undefined;
      const payload = {
        mr_txt: this.debugForm.input_mode === 'text' ? this.debugForm.mr_txt : '',
        payload_json: payloadJson,
        user: this.debugForm.user,
        workflow_input_variable: this.debugForm.workflow_input_variable || undefined,
        workflow_output_key: this.debugForm.workflow_output_key || undefined,
        extra_inputs: this.parseJsonText(this.debugForm.extra_inputs_text, '调试额外参数'),
      };
      const r = await apiPost('/api/config/dify/debug', payload);
      this.debugResult = r.data;
      return r.data;
    }, 'Dify 调试完成');
    if (result?.status === 'success') ElementPlus.ElMessage.success('Dify 调试成功');
  },

  formatTestResult(result) {
    if (!result) return '';
    return JSON.stringify(result, null, 2);
  },
};
