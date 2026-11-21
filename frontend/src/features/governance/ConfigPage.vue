<template>
  <div class="page-config">
    <PageHeader
      title="数据源与系统配置"
      description="按页签管理数据源、Dify、360 全息视图与推送脱敏通知；密钥留空表示保留原密文；每页签独立测试与保存。"
    >
      <template #actions>
        <el-button :loading="loading" @click="loadAll">刷新</el-button>
      </template>
    </PageHeader>

    <el-alert type="info" :closable="false" class="relay-jump-alert">
      <template #title>企微前置机配置不在本页：按科室/护士长/管床医生三档接收人及测试预览，请前往【企微接收人配置】专页。</template>
      <el-button size="small" type="primary" plain data-testid="goto-relay-page" @click="router.push('/governance/relay')">前往企微接收人配置 -&gt;</el-button>
    </el-alert>

    <el-alert v-for="(warning, i) in loadingWarnings" :key="i" type="warning" :closable="false" class="section-warning">{{ warning }}</el-alert>

    <el-tabs v-model="active" tab-position="left" class="config-tabs" v-loading="loading">
      <!-- ── 页签 1：临床业务库（Oracle） ── -->
      <el-tab-pane label="临床业务库(Oracle)" name="oracle">
        <h2 class="tab-title">临床业务库（Oracle）连接与只读 SQL</h2>
        <el-form label-position="top" class="cfg-form">
          <div class="cfg-grid">
            <label class="cfg-field"><span class="cfg-label">主机地址</span>
              <el-input v-model="oracle.host" />
            </label>
            <label class="cfg-field"><span class="cfg-label">端口</span>
              <el-input-number v-model="oracle.port" :min="1" :max="65535" style="width: 100%" />
            </label>
            <label class="cfg-field"><span class="cfg-label">服务名</span>
              <el-input v-model="oracle.service_name" />
            </label>
            <label class="cfg-field"><span class="cfg-label">账号</span>
              <el-input v-model="oracle.username" />
            </label>
            <label class="cfg-field"><span class="cfg-label">密码</span>
              <el-input v-model="oracle.password" type="password" show-password placeholder="留空表示不修改" />
            </label>
            <label class="cfg-field"><span class="cfg-label">客户端目录（Instant Client）</span>
              <el-input v-model="oracle.instant_client_dir" />
            </label>
          </div>
          <el-collapse class="cfg-advanced">
            <el-collapse-item name="pool">
              <template #title><span class="cfg-advanced-title">高级参数（连接池与只读查询）</span></template>
              <div class="cfg-grid">
                <label class="cfg-field"><span class="cfg-label">最小连接数</span>
                  <el-input-number v-model="oracle.pool_min" :min="1" :max="50" style="width: 100%" />
                </label>
                <label class="cfg-field"><span class="cfg-label">最大连接数</span>
                  <el-input-number v-model="oracle.pool_max" :min="1" :max="200" style="width: 100%" />
                </label>
                <label class="cfg-field"><span class="cfg-label">连接步进</span>
                  <el-input-number v-model="oracle.pool_increment" :min="1" :max="20" style="width: 100%" />
                </label>
                <label class="cfg-field"><span class="cfg-label">空闲回收秒数</span>
                  <el-input-number v-model="oracle.pool_timeout_seconds" :min="10" style="width: 100%" />
                </label>
                <label class="cfg-field"><span class="cfg-label">获取连接超时(秒)</span>
                  <el-input-number v-model="oracle.acquire_timeout_seconds" :min="1" style="width: 100%" />
                </label>
                <div class="cfg-field"><span class="cfg-label">池满允许直连回退</span>
                  <el-switch v-model="oracle.pool_fallback_direct" />
                </div>
                <label class="cfg-field cfg-field--full"><span class="cfg-label">只读查询 SQL</span>
                  <el-input v-model="oracle.query_sql" type="textarea" :rows="3" placeholder="SELECT 只读语句（用于连通性验证）" />
                </label>
                <label class="cfg-field cfg-field--full"><span class="cfg-label">科室 SQL</span>
                  <el-input v-model="oracle.dept_sql" type="textarea" :rows="2" />
                </label>
                <label class="cfg-field"><span class="cfg-label">单次查询行数上限</span>
                  <el-input-number v-model="oracle.queryLimit" :min="1" :max="200" style="width: 100%" />
                </label>
              </div>
            </el-collapse-item>
          </el-collapse>
        </el-form>
        <div class="cfg-actions">
          <el-button :loading="saving['test-oracle']" @click="connection('oracle')">测试连接</el-button>
          <el-input-number v-model="oracle.queryLimit" :min="1" :max="200" size="small" style="width: 110px" />
          <el-input v-model="oracle.queryParams" size="small" placeholder="查询参数 JSON（可选）" style="width: 200px" />
          <el-button :loading="saving['query-oracle']" @click="query('oracle')">执行只读 SQL</el-button>
          <el-button type="primary" :loading="saving['Oracle']" @click="saveOracle">保存本页</el-button>
        </div>
        <TestResultCard :result="testResults.oracle" title="Oracle 连接测试" />
        <QueryResultPanel v-if="queryResults.oracle" :data="queryResults.oracle" />
      </el-tab-pane>

      <!-- ── 页签 2：业务库（PostgreSQL）+ 数据源切换 ── -->
      <el-tab-pane label="业务库(PostgreSQL)" name="postgresql">
        <h2 class="tab-title">业务库（PostgreSQL，如启用）</h2>
        <div class="ds-switch">
          <span class="cfg-label">数据源类型切换（影响后续质控读取）</span>
          <div class="ds-switch-row">
            <el-radio-group v-model="dataSourceType">
              <el-radio value="oracle">Oracle</el-radio>
              <el-radio value="postgresql">PostgreSQL</el-radio>
            </el-radio-group>
            <el-button type="warning" size="small" :loading="saving['数据源']" @click="saveDataSource">确认切换</el-button>
          </div>
        </div>
        <el-form label-position="top" class="cfg-form">
          <div class="cfg-grid">
            <label class="cfg-field"><span class="cfg-label">主机地址</span>
              <el-input v-model="pg.host" />
            </label>
            <label class="cfg-field"><span class="cfg-label">端口</span>
              <el-input-number v-model="pg.port" :min="1" :max="65535" style="width: 100%" />
            </label>
            <label class="cfg-field"><span class="cfg-label">数据库名</span>
              <el-input v-model="pg.database" />
            </label>
            <label class="cfg-field"><span class="cfg-label">账号</span>
              <el-input v-model="pg.username" />
            </label>
            <label class="cfg-field"><span class="cfg-label">密码</span>
              <el-input v-model="pg.password" type="password" show-password placeholder="留空表示不修改" />
            </label>
          </div>
          <el-collapse class="cfg-advanced">
            <el-collapse-item name="pgsql">
              <template #title><span class="cfg-advanced-title">高级参数（只读查询）</span></template>
              <div class="cfg-grid">
                <label class="cfg-field cfg-field--full"><span class="cfg-label">只读查询 SQL</span>
                  <el-input v-model="pg.query_sql" type="textarea" :rows="3" />
                </label>
                <label class="cfg-field cfg-field--full"><span class="cfg-label">科室 SQL</span>
                  <el-input v-model="pg.dept_sql" type="textarea" :rows="2" />
                </label>
                <label class="cfg-field"><span class="cfg-label">单次查询行数上限</span>
                  <el-input-number v-model="pg.queryLimit" :min="1" :max="200" style="width: 100%" />
                </label>
              </div>
            </el-collapse-item>
          </el-collapse>
        </el-form>
        <div class="cfg-actions">
          <el-button :loading="saving['test-postgresql']" @click="connection('postgresql')">测试连接</el-button>
          <el-button :loading="saving['query-postgresql']" @click="query('postgresql')">执行只读 SQL</el-button>
          <el-button type="primary" :loading="saving['PostgreSQL']" @click="savePg">保存本页</el-button>
        </div>
        <TestResultCard :result="testResults.postgresql" title="PostgreSQL 连接测试" />
        <QueryResultPanel v-if="queryResults.postgresql" :data="queryResults.postgresql" />
      </el-tab-pane>

      <!-- ── 页签 3：电子病历库（Vastbase） ── -->
      <el-tab-pane label="电子病历库(Vastbase)" name="emr">
        <h2 class="tab-title">电子病历库（Vastbase）字段映射</h2>
        <p class="cfg-hint">字段严格对应 EmrVastbaseConfig；SSL 模式留空时不传该参数。</p>
        <el-form label-position="top" class="cfg-form">
          <div class="cfg-grid">
            <label class="cfg-field"><span class="cfg-label">主机地址</span>
              <el-input v-model="emr.host" />
            </label>
            <label class="cfg-field"><span class="cfg-label">端口</span>
              <el-input-number v-model="emr.port" :min="1" :max="65535" style="width: 100%" />
            </label>
            <label class="cfg-field"><span class="cfg-label">数据库名</span>
              <el-input v-model="emr.database" />
            </label>
            <label class="cfg-field"><span class="cfg-label">账号</span>
              <el-input v-model="emr.username" />
            </label>
            <label class="cfg-field"><span class="cfg-label">密码</span>
              <el-input v-model="emr.password" type="password" show-password placeholder="留空表示不修改" />
            </label>
            <label class="cfg-field"><span class="cfg-label">SSL 模式（可选，留空不传）</span>
              <el-input v-model="emr.sslmode" placeholder="如 require / disable" />
            </label>
            <label class="cfg-field"><span class="cfg-label">模式（schema）</span>
              <el-input v-model="emr.db_schema" />
            </label>
            <label class="cfg-field"><span class="cfg-label">文书视图</span>
              <el-input v-model="emr.view" />
            </label>
            <label v-for="key in EMR_FIELD_KEYS" :key="key" class="cfg-field"><span class="cfg-label">{{ emrFieldLabel(key) }}</span>
              <el-input-number
                v-if="['connect_timeout_seconds', 'statement_timeout_ms', 'max_records'].includes(key)"
                v-model="emr[key]"
                :min="key === 'max_records' ? 100 : key === 'statement_timeout_ms' ? 1000 : 1"
                style="width: 100%"
              />
              <el-input v-else v-model="emr[key]" />
            </label>
          </div>
          <div class="cfg-grid">
            <div class="cfg-field"><span class="cfg-label">启用电子病历库</span>
              <el-switch v-model="emr.enabled" />
            </div>
            <div class="cfg-field"><span class="cfg-label">病程导出使用本库</span>
              <el-switch v-model="emr.use_for_export_progress" />
            </div>
            <div class="cfg-field"><span class="cfg-label">出院记录导出使用本库</span>
              <el-switch v-model="emr.use_for_export_discharge" />
            </div>
            <div class="cfg-field"><span class="cfg-label">失败回退 Oracle</span>
              <el-switch v-model="emr.fallback_to_oracle" />
            </div>
          </div>
        </el-form>
        <div class="cfg-actions">
          <el-button :loading="saving['test-emr']" @click="connection('emr', '/config/emr-vastbase/test')">测试连接</el-button>
          <el-button type="primary" :loading="saving['EMR Vastbase']" @click="saveEmr">保存本页</el-button>
        </div>
        <TestResultCard :result="testResults.emr" title="电子病历库连接测试" />
      </el-tab-pane>

      <!-- ── 页签 4：AI 引擎（Dify） ── -->
      <el-tab-pane label="AI 引擎(Dify)" name="dify">
        <h2 class="tab-title">AI 引擎（Dify）与目标节点</h2>
        <p class="cfg-hint">builder 输出统一为 <code>mr_text</code>；Dify 默认输入变量 <code>mr_txt</code> 仅由 dify_pusher 映射。</p>
        <el-form label-position="top" class="cfg-form">
          <div class="cfg-grid">
            <label class="cfg-field cfg-field--full"><span class="cfg-label">默认地址（只填基础地址，不要带 /workflows/run）</span>
              <el-input v-model="dify.base_url" placeholder="http://host:port/v1" />
            </label>
            <label class="cfg-field"><span class="cfg-label">API 密钥</span>
              <el-input v-model="dify.api_key" type="password" show-password placeholder="留空表示不修改" />
            </label>
            <label class="cfg-field"><span class="cfg-label">工作流输入变量名</span>
              <el-input v-model="dify.workflow_input_variable" placeholder="默认 mr_txt" />
            </label>
            <label class="cfg-field"><span class="cfg-label">工作流输出变量名</span>
              <el-input v-model="dify.workflow_output_key" />
            </label>
            <label class="cfg-field"><span class="cfg-label">调用标识</span>
              <el-input v-model="dify.user_identifier" />
            </label>
            <label class="cfg-field"><span class="cfg-label">超时秒数</span>
              <el-input-number v-model="dify.timeout_seconds" :min="1" :max="300" style="width: 100%" />
            </label>
            <label class="cfg-field cfg-field--full"><span class="cfg-label">额外静态输入（JSON 对象）</span>
              <el-input v-model="dify.extra_inputs_text" type="textarea" :rows="3" placeholder='{"hospital_id": "..."}' />
            </label>
            <div class="cfg-field"><span class="cfg-label">开启完整调试日志</span>
              <el-switch v-model="dify.full_debug_log" />
            </div>
          </div>
          <el-divider content-position="left">目标节点池（最多 10 个）</el-divider>
          <div class="cfg-grid">
            <label class="cfg-field"><span class="cfg-label">调度策略</span>
              <el-select v-model="pool.target_strategy">
                <el-option label="轮询" value="round_robin" />
                <el-option label="权重随机" value="weighted_random" />
              </el-select>
            </label>
            <label class="cfg-field"><span class="cfg-label">熔断失败次数</span>
              <el-input-number v-model="pool.circuit_breaker_failures" :min="1" :max="20" style="width: 100%" />
            </label>
            <label class="cfg-field"><span class="cfg-label">熔断冷却秒数</span>
              <el-input-number v-model="pool.circuit_breaker_seconds" :min="1" style="width: 100%" />
            </label>
          </div>
          <div v-for="(target, i) in pool.targets" :key="i" class="target-row">
            <el-switch v-model="target.enabled" />
            <el-input v-model="target.name" placeholder="节点名" style="width: 140px" />
            <el-input v-model="target.base_url" placeholder="节点基础地址" style="flex: 1" />
            <el-input v-model="target.api_key" type="password" show-password placeholder="密钥留空保留" style="width: 180px" />
            <el-input-number v-model="target.timeout_seconds" :min="1" :max="300" style="width: 100px" />
            <el-input-number v-model="target.weight" :min="1" :max="100" style="width: 90px" />
            <el-button type="danger" text @click="pool.targets.splice(i, 1)">删除</el-button>
          </div>
          <el-button size="small" @click="addTarget">添加节点</el-button>
        </el-form>
        <div class="cfg-actions">
          <el-button :loading="saving['test-dify']" @click="connection('dify', '/config/dify/test')">测试 Dify</el-button>
          <el-button type="primary" :loading="saving['Dify']" @click="saveDify">保存 AI 引擎</el-button>
          <el-button type="primary" plain :loading="saving['节点池']" @click="savePool">保存节点池</el-button>
        </div>
        <TestResultCard :result="testResults.dify" title="Dify 连接测试" />
      </el-tab-pane>

      <!-- ── 页签 5：360 全息视图 ── -->
      <el-tab-pane label="360 全息视图" name="holography">
        <h2 class="tab-title">360 全息视图对接配置（S28 / wfy）</h2>
        <p class="cfg-hint">userCode 由后端统一计算（登录账号命中工号格式即直传，否则回退兜底工号）；本页保存仅写入 360 配置节。</p>
        <el-form label-position="top" class="cfg-form">
          <div class="cfg-grid">
            <div class="cfg-field"><span class="cfg-label">启用 360 全息视图</span>
              <el-switch v-model="holography.enabled" />
            </div>
            <label class="cfg-field cfg-field--full"><span class="cfg-label">基础地址</span>
              <el-input v-model="holography.base_url" placeholder="http://..." />
            </label>
            <label class="cfg-field"><span class="cfg-label">系统编码</span>
              <el-input v-model="holography.sys_code" placeholder="默认 S28" />
            </label>
            <label class="cfg-field"><span class="cfg-label">非工号账号兜底工号</span>
              <el-input v-model="holography.fallback_user_code" placeholder="默认 wfy" />
            </label>
            <label class="cfg-field cfg-field--full"><span class="cfg-label">员工工号格式（正则）</span>
              <el-input v-model="holography.employee_code_pattern" placeholder="默认 ^[0-9]{4,10}$" />
              <span class="cfg-hint">符合此格式的登录账号直接作为工号传给 360。</span>
            </label>
            <label class="cfg-field cfg-field--full"><span class="cfg-label">非员工账号列表（这些账号使用兜底工号）</span>
              <el-select v-model="holography.non_employee_accounts" multiple allow-create filterable default-first-option placeholder="输入账号后回车，默认 admin" style="width: 100%" />
            </label>
            <div class="cfg-field"><span class="cfg-label">企微手机端显示 360 入口</span>
              <el-switch v-model="holography.enable_on_mobile" />
            </div>
          </div>
          <el-divider content-position="left">预览工具（本地拼接，不发起请求）</el-divider>
          <div class="preview-row">
            <label class="cfg-field"><span class="cfg-label">测试患者号</span>
              <el-input v-model="previewPatientId" placeholder="如 00985003" style="width: 220px" />
            </label>
            <div class="preview-box" data-testid="holography-preview-url">{{ previewUrl || '（填写启用状态/基础地址/患者号后生成预览链接）' }}</div>
            <el-button :disabled="!previewUrl" @click="openPreview">新窗口试打开</el-button>
          </div>
          <p class="cfg-hint">当前登录人 user_code（后端计算）：{{ holography.user_code || '—' }}</p>
        </el-form>
        <div class="cfg-actions">
          <el-button type="primary" :loading="saving['holography']" data-testid="save-holography" @click="saveHolography">保存本页</el-button>
        </div>
      </el-tab-pane>

      <!-- ── 页签 6：推送、脱敏与通知 ── -->
      <el-tab-pane label="推送/脱敏/通知" name="push_privacy_notify">
        <h2 class="tab-title">推送、脱敏与通知渠道</h2>
        <el-card shadow="never" class="sub-card">
          <template #header>推送参数</template>
          <div class="cfg-grid">
            <label class="cfg-field"><span class="cfg-label">推送间隔毫秒</span>
              <el-input-number v-model="push.interval_ms" :min="100" style="width: 100%" />
            </label>
            <label class="cfg-field"><span class="cfg-label">最大重试次数</span>
              <el-input-number v-model="push.max_retry" :min="0" :max="10" style="width: 100%" />
            </label>
            <label class="cfg-field"><span class="cfg-label">批量大小</span>
              <el-input-number v-model="push.batch_size" :min="1" :max="100" style="width: 100%" />
            </label>
            <label class="cfg-field"><span class="cfg-label">并发工作线程</span>
              <el-input-number v-model="push.parallel_workers" :min="1" :max="32" style="width: 100%" />
            </label>
          </div>
          <el-button type="primary" :loading="saving['推送参数']" @click="savePush">保存推送参数</el-button>
        </el-card>
        <el-card shadow="never" class="sub-card">
          <template #header>隐私脱敏</template>
          <div class="cfg-grid">
            <div class="cfg-field"><span class="cfg-label">启用脱敏</span>
              <el-switch v-model="privacy.enabled" />
            </div>
            <div class="cfg-field"><span class="cfg-label">姓名脱敏</span>
              <el-switch v-model="privacy.mask_name" />
            </div>
            <div class="cfg-field"><span class="cfg-label">身份证脱敏</span>
              <el-switch v-model="privacy.mask_id_card" />
            </div>
            <div class="cfg-field"><span class="cfg-label">地址脱敏</span>
              <el-switch v-model="privacy.mask_address" />
            </div>
            <div class="cfg-field"><span class="cfg-label">联系电话脱敏</span>
              <el-switch v-model="privacy.mask_phone" />
            </div>
          </div>
          <el-button type="primary" :loading="saving['隐私脱敏']" @click="savePrivacy">保存脱敏设置</el-button>
        </el-card>
        <el-card shadow="never" class="sub-card">
          <template #header>通知渠道（config 必须为 JSON 对象；测试会真实发送）</template>
          <div v-for="(channel, i) in notify.channels" :key="i" class="channel-row">
            <el-select v-model="channel.type" style="width: 130px">
              <el-option v-for="type in ['wechat', 'dingtalk', 'email', 'webhook']" :key="type" :label="channelTypeLabel(type)" :value="type" />
            </el-select>
            <el-switch v-model="channel.enabled" />
            <el-input v-model="channel.configText" type="textarea" :rows="2" placeholder="config JSON 对象" style="flex: 1" />
            <el-button type="danger" text @click="notify.channels.splice(i, 1)">删除</el-button>
            <el-button type="warning" :loading="saving[`test-notify-${i}`]" @click="testNotify(i)">测试</el-button>
          </div>
          <el-button size="small" @click="addChannel">添加渠道</el-button>
          <el-button type="primary" :loading="saving['通知']" @click="saveNotify">保存通知渠道</el-button>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
// WP08（064 总计划）：数据源与系统配置页重构——左侧竖向 6 页签，每页签独立
// 「测试连接 + 保存本页」；新增「360 全息视图」页签（GET/POST /api/config/holography，
// S28/wfy 默认值 + 本地拼接预览工具，userCode 用后端返回的本人 user_code）；
// 全部端点与「密码/Key 留空不覆盖」语义原样保留（omitBlankSecret/局部提交）；
// 连接池等高级参数默认折叠且标签全中文（禁 pool_min 等英文键）；
// 原始 JSON 一律折叠展示；企微前置机指引跳 /governance/relay（WP-09 处理）。
import { computed, defineComponent, h, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/base/PageHeader.vue'
import { apiGet, apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { ElMessage, ElMessageBox } from 'element-plus'
import { loadHolographyConfig } from '@/utils/holography'
import {
  buildDifyTargetPayload,
  omitBlankSecret,
  parseDeptCandidates,
  parseNotifyConfig,
} from '@/utils/config-contracts'

const router = useRouter()

type AnyRecord = Record<string, any>

const EMR_FIELD_KEYS = [
  'db_schema', 'view', 'patient_id_field', 'visit_id_field', 'dept_field',
  'content_field', 'title_field', 'type_field', 'template_field',
  'record_time_field', 'finish_time_field', 'first_save_time_field',
  'create_date_field', 'doctor_field', 'status_field',
  'connect_timeout_seconds', 'statement_timeout_ms', 'max_records',
] as const

const active = ref('oracle')
const loading = ref(false)
const loadingWarnings = ref<string[]>([])
const saving = ref<Record<string, boolean>>({})
const dataSourceType = ref<'oracle' | 'postgresql'>('oracle')
const testResults = reactive<AnyRecord>({})
const queryResults = reactive<AnyRecord>({})

const oracle = reactive<AnyRecord>({ host: '', port: 1521, service_name: '', username: '', password: '', password_masked: '', instant_client_dir: '', query_sql: '', dept_sql: '', field_mapping: {}, pool_min: 1, pool_max: 8, pool_increment: 1, pool_timeout_seconds: 60, acquire_timeout_seconds: 15, pool_fallback_direct: false, queryParams: '{}', queryLimit: 20 })
const pg = reactive<AnyRecord>({ host: 'localhost', port: 5432, database: '', username: '', password: '', password_masked: '', query_sql: '', dept_sql: '', field_mapping: {}, queryLimit: 20 })
const emr = reactive<AnyRecord>({ enabled: false, host: '', port: 5432, database: '', username: '', password: '', password_masked: '', sslmode: '', db_schema: 'jhemr', view: 'v_blws', patient_id_field: 'patient_id', visit_id_field: 'visit_id', dept_field: 'dept_name', content_field: 'progress_message', title_field: 'progress_title_name', type_field: 'progress_type_name', template_field: 'progress_template_name', record_time_field: 'record_time_format', finish_time_field: 'finish_time_format', first_save_time_field: 'first_save_time', create_date_field: 'create_date', doctor_field: 'doctor_name', status_field: 'progress_status', connect_timeout_seconds: 10, statement_timeout_ms: 60000, max_records: 50000, use_for_export_progress: true, use_for_export_discharge: true, fallback_to_oracle: true })
const dify = reactive<AnyRecord>({ base_url: '', api_key: '', api_key_masked: '', workflow_input_variable: 'mr_txt', workflow_output_key: 'aa', user_identifier: 'med-audit-system', timeout_seconds: 90, extra_inputs_text: '', full_debug_log: false })
const pool = reactive<AnyRecord>({ target_strategy: 'round_robin', circuit_breaker_failures: 3, circuit_breaker_seconds: 60, targets: [] as AnyRecord[] })
const push = reactive({ interval_ms: 500, max_retry: 3, batch_size: 50, parallel_workers: 4 })
const privacy = reactive({ enabled: false, mask_name: true, mask_id_card: true, mask_address: true, mask_phone: true })
const notify = reactive({ channels: [] as Array<{ type: string; enabled: boolean; configText: string }> })
const relay = reactive({ enabled: false, base_url: '', endpoint: '/qc-record-alert', secret_key: '', secret_key_masked: '', timeout_seconds: 10, severity_levels: ['high'], source: '病历质控系统', max_retry: 3, retry_backoff_seconds: 5, alert_dept_filter: [] as string[] })
const deptCandidates = ref<string[]>([])

const holography = reactive<AnyRecord>({
  enabled: false, base_url: '', sys_code: 'S28', fallback_user_code: 'wfy',
  employee_code_pattern: '^[0-9]{4,10}$', non_employee_accounts: [] as string[],
  enable_on_mobile: false, user_code: '',
})
const previewPatientId = ref('')

/** 预览 URL：表单本地拼接（与 utils/holography.buildHolographyUrl 同语义）。 */
const previewUrl = computed(() => {
  if (!holography.enabled) return ''
  const base = String(holography.base_url || '').trim()
  const pid = String(previewPatientId.value || '').trim()
  if (!base || !pid) return ''
  try {
    const url = new URL(base)
    url.searchParams.set('patientId', pid)
    // userCode：命中工号正则用表单值直传，否则兜底工号（与后端 resolve_holography_user_code 同语义）
    const uname = String(holography.user_code || '').trim()
    const pattern = String(holography.employee_code_pattern || '^[0-9]{4,10}$')
    let userCode = String(holography.fallback_user_code || 'wfy')
    try {
      if (uname && new RegExp(pattern).test(uname)) userCode = uname
    } catch { /* 非法正则走兜底 */ }
    url.searchParams.set('userCode', userCode)
    url.searchParams.set('sysCode', String(holography.sys_code || 'S28'))
    return url.toString()
  } catch {
    return ''
  }
})

function openPreview(): void {
  if (!previewUrl.value) return
  window.open(previewUrl.value, '_blank', 'noopener,noreferrer')
}

function setSaving(key: string, value: boolean): void { saving.value[key] = value }
async function confirm(message: string, title = '请确认'): Promise<boolean> {
  try { await ElMessageBox.confirm(message, title, { type: 'warning' }); return true } catch { return false }
}

function assignConfig(target: AnyRecord, data: AnyRecord): void {
  Object.keys(target).forEach((key) => {
    if (key in data && key !== 'password' && !key.endsWith('_masked')) target[key] = data[key]
  })
  if ('password_masked' in data) target.password_masked = data.password_masked || ''
}
function applyDify(data: AnyRecord): void {
  assignConfig(dify, data); dify.api_key = ''
  dify.extra_inputs_text = data.extra_inputs ? JSON.stringify(data.extra_inputs, null, 2) : ''
}
function applyPool(data: AnyRecord): void {
  pool.target_strategy = data.target_strategy || 'round_robin'
  pool.circuit_breaker_failures = data.circuit_breaker_failures || 3
  pool.circuit_breaker_seconds = data.circuit_breaker_seconds || 60
  pool.targets = (data.targets || []).map((t: AnyRecord) => ({
    ...t,
    original_name: String(t.name || ''),
    api_key: '',
    api_key_masked: t.api_key_masked || '',
    has_secret: !!t.has_secret || !!t.api_key_masked,
  }))
}
function applyNotify(data: AnyRecord): void {
  notify.channels = (data.channels || []).map((c: AnyRecord) => ({
    type: c.type, enabled: c.enabled !== false,
    configText: JSON.stringify(c.config || {}, null, 2),
  }))
}

async function loadAll(): Promise<void> {
  loading.value = true
  loadingWarnings.value = []
  const jobs: Record<string, Promise<unknown>> = {
    ds: apiGet('/config/data-source'),
    oracle: apiGet('/config/oracle'),
    pg: apiGet('/config/postgresql'),
    emr: apiGet('/config/emr-vastbase'),
    dify: apiGet('/config/dify'),
    targets: apiGet('/config/dify/targets'),
    push: apiGet('/config/push'),
    privacy: apiGet('/config/privacy-masking'),
    notify: apiGet('/config/notify'),
    relay: apiGet('/config/relay-alert'),
    holography: apiGet('/config/holography'),
  }
  const entries = await Promise.all(Object.entries(jobs).map(async ([key, promise]) => {
    try { return [key, await promise] as const }
    catch (e) {
      loadingWarnings.value.push(`${key}：${toUserMessage(e, '加载失败')}`)
      return [key, null] as const
    }
  }))
  const data = Object.fromEntries(entries) as AnyRecord
  if (data.ds) dataSourceType.value = data.ds.type === 'postgresql' ? 'postgresql' : 'oracle'
  if (data.oracle) { assignConfig(oracle, data.oracle); oracle.password = '' }
  if (data.pg) { assignConfig(pg, data.pg); pg.password = '' }
  if (data.emr) { assignConfig(emr, data.emr); emr.password = '' }
  if (data.dify) applyDify(data.dify)
  if (data.targets) applyPool(data.targets)
  if (data.push) Object.assign(push, data.push)
  if (data.privacy) Object.assign(privacy, data.privacy)
  if (data.notify) applyNotify(data.notify)
  if (data.relay) { assignConfig(relay, data.relay); relay.secret_key = '' }
  if (data.holography) {
    Object.keys(holography).forEach((key) => {
      if (key in data.holography && key !== 'user_code') holography[key] = data.holography[key]
    })
    holography.user_code = data.holography.user_code || ''
    holography.non_employee_accounts = (data.holography.non_employee_accounts || []).map(String)
  }
  try {
    deptCandidates.value = parseDeptCandidates(await apiGet('/config/departments/list'))
  } catch (e) {
    loadingWarnings.value.push(`科室候选：${toUserMessage(e, '加载失败')}`)
  }
  loading.value = false
}

async function saveSection(key: string, url: string, body: AnyRecord): Promise<boolean> {
  if (saving.value[key]) return false
  setSaving(key, true)
  try {
    await apiPost(url, body)
    ElMessage.success(`${key}已保存`)
    return true
  } catch (e) {
    ElMessage.error(toUserMessage(e, `${key}保存失败`))
    return false
  } finally {
    setSaving(key, false)
  }
}

async function saveDataSource(): Promise<void> {
  if (!(await confirm(`确认切换数据源到 ${dataSourceType.value}？`))) return
  await saveSection('数据源', '/config/data-source', { type: dataSourceType.value })
}

function connection(type: string, url = `/config/${type}/test`): void {
  if (saving.value[`test-${type}`]) return
  setSaving(`test-${type}`, true)
  void apiPost<AnyRecord>(url).then((r) => {
    testResults[type] = r
    const ok = r?.status === 'up' || r?.status === 'success' || r?.success === true
    if (ok) ElMessage.success(`${type} 测试成功${r.latency_ms ? `（${r.latency_ms}ms）` : ''}`)
    else ElMessage.error(`${type} 测试失败：${r.message || r.status || 'unknown'}`)
  }).catch((e) => ElMessage.error(toUserMessage(e, `${type} 测试失败`))).finally(() => setSaving(`test-${type}`, false))
}

async function saveOracle(): Promise<void> {
  const body = omitBlankSecret({ ...oracle, field_mapping: oracle.field_mapping }, 'password')
  delete body.password_masked; delete body.queryParams; delete body.queryLimit
  if (await saveSection('Oracle', '/config/oracle', body)) oracle.password = ''
}
async function savePg(): Promise<void> {
  const body = omitBlankSecret({ ...pg, field_mapping: pg.field_mapping }, 'password')
  delete body.password_masked; delete body.queryLimit
  if (await saveSection('PostgreSQL', '/config/postgresql', body)) pg.password = ''
}
async function saveEmr(): Promise<void> {
  const body = omitBlankSecret({ ...emr }, 'password')
  delete body.password_masked
  if (await saveSection('EMR Vastbase', '/config/emr-vastbase', body)) emr.password = ''
}
async function saveDify(): Promise<void> {
  let extra: AnyRecord = {}
  if (dify.extra_inputs_text.trim()) {
    try { extra = parseNotifyConfig(dify.extra_inputs_text) }
    catch { ElMessage.error('额外输入必须是非数组 JSON 对象'); return }
  }
  const body = omitBlankSecret({
    base_url: dify.base_url, workflow_input_variable: dify.workflow_input_variable,
    workflow_output_key: dify.workflow_output_key, user_identifier: dify.user_identifier,
    timeout_seconds: dify.timeout_seconds, extra_inputs: extra,
    full_debug_log: dify.full_debug_log, api_key: dify.api_key,
  }, 'api_key')
  if (await saveSection('Dify', '/config/dify', body)) dify.api_key = ''
}
function addTarget(): void {
  if (pool.targets.length >= 10) { ElMessage.warning('最多 10 个节点'); return }
  pool.targets.push({ name: '', base_url: '', api_key: '', api_key_masked: '', has_secret: false, timeout_seconds: 90, weight: 1, enabled: true })
}
async function savePool(): Promise<void> {
  try {
    const original = pool.targets.map((t: AnyRecord) => t.original_name)
    const targets = pool.targets.map((t: AnyRecord, i: number) => buildDifyTargetPayload(t, original[i]))
    if (await saveSection('节点池', '/config/dify/targets', {
      target_strategy: pool.target_strategy,
      circuit_breaker_failures: pool.circuit_breaker_failures,
      circuit_breaker_seconds: pool.circuit_breaker_seconds,
      targets,
    })) {
      pool.targets.forEach((t: AnyRecord) => {
        t.original_name = t.name; t.has_secret = t.has_secret || !!t.api_key; t.api_key = ''
      })
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '节点池配置无效')
  }
}
function savePush(): void { void saveSection('推送参数', '/config/push', { ...push }) }
function savePrivacy(): void { void saveSection('隐私脱敏', '/config/privacy-masking', { ...privacy }) }
function saveNotify(): void {
  try {
    const channels = notify.channels.map((c) => ({
      type: c.type, enabled: c.enabled, config: parseNotifyConfig(c.configText),
    }))
    void saveSection('通知', '/config/notify', { channels })
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '通知配置无效')
  }
}
function addChannel(): void {
  notify.channels.push({ type: 'webhook', enabled: true, configText: '{}' })
}
async function testNotify(index: number): Promise<void> {
  const channel = notify.channels[index]
  if (!channel || saving.value[`test-notify-${index}`]) return
  let config: AnyRecord
  try { config = parseNotifyConfig(channel.configText) }
  catch { ElMessage.error('通知 config 必须是非数组 JSON 对象'); return }
  if (!(await confirm('通知测试会真实发送消息，确认继续？'))) return
  setSaving(`test-notify-${index}`, true)
  try {
    const result = await apiPost<AnyRecord>('/notify/test', { type: channel.type, enabled: channel.enabled, config })
    testResults[`notify-${index}`] = result
    if (result?.status === 'success' || result?.success === true) ElMessage.success('通知测试成功')
    else ElMessage.error(`通知测试失败：${result?.message || result?.status || 'unknown'}`)
  } catch (e) {
    ElMessage.error(toUserMessage(e, '通知测试失败'))
  } finally {
    setSaving(`test-notify-${index}`, false)
  }
}

/** WP08 新增：保存 360 全息配置（只提交 holography 节；POST /config/holography）。 */
async function saveHolography(): Promise<void> {
  const body = {
    enabled: holography.enabled,
    base_url: String(holography.base_url || '').trim(),
    sys_code: String(holography.sys_code || '').trim(),
    fallback_user_code: String(holography.fallback_user_code || '').trim() || 'wfy',
    employee_code_pattern: String(holography.employee_code_pattern || '^[0-9]{4,10}$'),
    non_employee_accounts: (holography.non_employee_accounts || []).map((s: unknown) => String(s).trim()).filter(Boolean),
    enable_on_mobile: holography.enable_on_mobile,
  }
  if (body.enabled && !/^https?:\/\//.test(body.base_url)) {
    ElMessage.error('启用状态下基础地址必须以 http:// 或 https:// 开头')
    return
  }
  if (!body.sys_code) { ElMessage.error('请填写系统编码（如 S28）'); return }
  if (await saveSection('holography', '/config/holography', body)) {
    void loadHolographyConfig(true)
  }
}

async function query(kind: 'oracle' | 'postgresql'): Promise<void> {
  const form = kind === 'oracle' ? oracle : pg
  if (!String(form.query_sql).trim()) { ElMessage.warning('请输入只读 SQL'); return }
  let params: AnyRecord = {}
  if (kind === 'oracle' && String(form.queryParams).trim()) {
    try { params = parseNotifyConfig(form.queryParams) }
    catch { ElMessage.error('params 必须是非数组 JSON 对象'); return }
  }
  const body = kind === 'oracle'
    ? { sql: form.query_sql, limit: form.queryLimit, params }
    : { sql: form.query_sql, limit: form.queryLimit }
  setSaving(`query-${kind}`, true)
  try { queryResults[kind] = await apiPost(`/config/${kind}/query`, body) }
  catch (e) { ElMessage.error(toUserMessage(e, 'SQL 测试失败')) }
  finally { setSaving(`query-${kind}`, false) }
}

/** EMR Vastbase 字段键中文名（未映射的键原样展示）。 */
function emrFieldLabel(key: string): string {
  const map: Record<string, string> = {
    host: '主机地址', port: '端口', database: '数据库', username: '用户名',
    db_schema: '模式（schema）', view: '文书视图', patient_id_field: '患者ID字段',
    visit_id_field: '住院次字段', dept_field: '科室字段', content_field: '内容字段',
    title_field: '标题字段', type_field: '类型字段', template_field: '模板名字段',
    record_time_field: '记录时间字段', finish_time_field: '完成时间字段',
    first_save_time_field: '首次保存时间字段', create_date_field: '创建日期字段',
    doctor_field: '医生字段', status_field: '状态字段',
    connect_timeout_seconds: '连接超时秒数', statement_timeout_ms: 'SQL 执行超时（毫秒）',
    max_records: '单次最大记录数', sslmode: 'SSL 模式',
  }
  return map[key] || key
}

function channelTypeLabel(type: string): string {
  const map: Record<string, string> = {
    wechat: '企业微信', dingtalk: '钉钉', email: '邮件', webhook: 'Webhook',
  }
  return map[type] || type
}

/**
 * 中文结构化测试结果卡（成功/失败、耗时、错误信息；原始 JSON 折叠）。
 * 内联定义（仅本页使用的极小组件，避免散文件）。
 */
const TestResultCard = defineComponent({
  name: 'TestResultCard',
  props: { result: { type: Object as () => AnyRecord | undefined, default: undefined }, title: { type: String, default: '' } },
  setup(props) {
    return () => {
      if (!props.result || typeof props.result !== 'object') return null as any
      const item = props.result as AnyRecord
      const ok = item.status === 'up' || item.status === 'success' || item.success === true
      return h('div', { class: 'test-card' }, [
        h('div', { class: 'test-card-head' }, [
          h('span', { class: ok ? 'test-ok' : 'test-fail' }, ok ? '✓ 连接成功' : '✗ 连接失败'),
          item.latency_ms ? h('span', { class: 'cfg-label' }, `耗时 ${item.latency_ms}ms`) : null,
        ]),
        item.message ? h('div', { class: 'test-msg' }, String(item.message)) : null,
        h('div', { class: 'test-raw' }, [
          h('details', null, [
            h('summary', null, '查看原始响应'),
            h('pre', { class: 'raw-json' }, JSON.stringify(item, null, 2)),
          ]),
        ]),
      ])
    }
  },
})

/** 只读 SQL 结果面板（表格 + 原始 JSON 折叠）。 */
const QueryResultPanel = defineComponent({
  name: 'QueryResultPanel',
  props: { data: { type: Object as () => AnyRecord, required: true } },
  setup(props) {
    const rows = computed(() => (Array.isArray(props.data.rows) ? props.data.rows : []))
    const columns = computed(() =>
      Array.isArray(props.data.columns) ? props.data.columns : Object.keys(rows.value[0] || {}))
    return () => h('div', { class: 'query-panel' }, [
      h('div', { class: 'cfg-hint' },
        `SQL 状态：${props.data.status || 'unknown'} · 耗时 ${props.data.elapsed_ms || 0}ms · 返回 ${props.data.row_count ?? rows.value.length} 行`),
      rows.value.length
        ? h('el-table', { data: rows.value, maxHeight: 260, size: 'small' },
          () => columns.value.map((column: string) => h('el-table-column', {
            prop: column, label: column, showOverflowTooltip: true,
          })))
        : null,
      h('details', { style: 'margin-top: 6px' }, [
        h('summary', null, '查看原始响应'),
        h('pre', { class: 'raw-json' }, JSON.stringify(props.data, null, 2)),
      ]),
    ])
  },
})

onMounted(() => { void loadAll() })
</script>

<style scoped>
.page-config { padding: 4px; }
.relay-jump-alert { margin-bottom: 10px; }
.section-warning { margin-bottom: 8px; }
.config-tabs { margin-top: 4px; min-height: 420px; }
.config-tabs :deep(.el-tabs__content) { padding: 4px 8px 12px; }
.tab-title { margin: 0 0 10px; font-size: 16px; }
.cfg-form { display: grid; gap: 10px; }
.cfg-grid { display: grid; grid-template-columns: repeat(2, minmax(260px, 1fr)); gap: 12px 24px; align-items: end; }
.cfg-field { display: grid; gap: 4px; min-width: 0; }
.cfg-field--full { grid-column: 1 / -1; }
.cfg-label { font-size: 12px; color: var(--el-text-color-secondary); }
.cfg-hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.6; margin: 0; }
.cfg-advanced { margin-top: 4px; }
.cfg-advanced-title { font-size: 13px; font-weight: 600; }
.cfg-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--el-border-color-lighter); }
.sub-card { margin-bottom: 14px; }
.target-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 8px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; margin-bottom: 8px; }
.channel-row { display: flex; gap: 8px; align-items: flex-start; flex-wrap: wrap; margin-bottom: 10px; }
.ds-switch { display: grid; gap: 6px; padding: 10px 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; margin-bottom: 12px; }
.ds-switch-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.preview-row { display: flex; gap: 12px; align-items: flex-start; flex-wrap: wrap; }
.preview-box {
  flex: 1; min-width: 280px; padding: 9px 12px; border-radius: 8px;
  background: var(--el-fill-color-light); border: 1px dashed var(--el-border-color);
  font-size: 12px; word-break: break-all; min-height: 36px; color: var(--el-text-color-regular);
}
.test-card { margin-top: 10px; padding: 10px 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; }
.test-card-head { display: flex; gap: 12px; align-items: center; }
.test-ok { color: var(--el-color-success); font-weight: 700; }
.test-fail { color: var(--el-color-danger); font-weight: 700; }
.test-msg { margin-top: 4px; font-size: 12px; color: var(--el-text-color-secondary); word-break: break-all; }
.test-raw, .query-panel { margin-top: 8px; }
.raw-json {
  margin: 6px 0 0; max-height: 240px; overflow: auto; padding: 8px 10px; border-radius: 8px;
  background: #0f172a; color: #e2e8f0; font-size: 12px; line-height: 1.5;
  white-space: pre-wrap; word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
@media (max-width: 900px) {
  .cfg-grid { grid-template-columns: 1fr; }
  .target-row, .channel-row { grid-template-columns: 1fr; }
}
</style>
