"""
Pydantic Schemas —— 驱动 Swagger 文档 & 请求/响应校验
"""
from pydantic import BaseModel, Field, field_validator, model_validator, constr
from typing import Any, Dict, Optional, List, Literal
from datetime import datetime, timedelta


# ---- 配置相关 ----
# ---- PostgreSQL 配置 ----
class PostgreSQLConfig(BaseModel):
    host: str = Field("localhost", description="PostgreSQL 主机地址")
    port: int = Field(5432, ge=1, le=65535, description="PostgreSQL 端口")
    database: str = Field("ai_hms_db", description="数据库名称")
    username: str = Field("", description="用户名")
    password: str = Field("", description="密码（传入明文，存储加密）")
    query_sql: str = Field("", description="自定义查询SQL，须包含 {dept_filter} 和 %s 参数（日期在最后一个参数）")
    dept_sql: str = Field("", description="科室查询SQL（留空使用默认SQL）")
    field_mapping: Optional["OracleFieldMapping"] = Field(None, description="字段映射配置")


class PostgreSQLConfigResponse(BaseModel):
    host: str
    port: int
    database: str
    username: str
    password_masked: str = Field("", description="脱敏后的密码")
    query_sql: str = Field("", description="当前查询SQL")
    dept_sql: str = Field("", description="当前科室查询SQL")
    field_mapping: Optional["OracleFieldMapping"] = None


class OracleFieldMapping(BaseModel):
    patient_id: str = Field("患者ID", description="患者ID字段名")
    visit_number: str = Field("次数", description="住院次数字段名")
    patient_name: str = Field("患者姓名", description="患者姓名字段名")
    dept: str = Field("所在科室名称", description="科室字段名")
    admission_no: str = Field("住院号", description="住院号字段名")


class OracleConfig(BaseModel):
    host: constr(min_length=1, max_length=255) = Field("10.255.255.20", description="Oracle 主机地址")
    port: int = Field(1521, ge=1, le=65535, description="Oracle 端口")
    service_name: constr(min_length=1, max_length=64) = Field("orcl", description="Oracle 服务名")
    username: constr(min_length=0, max_length=50) = Field("", description="用户名")
    password: constr(min_length=0, max_length=128) = Field("", description="密码（传入明文，存储加密）")
    instant_client_dir: str = Field("", description="Oracle Instant Client 目录路径（如 C:/oracle/instantclient_21_9）")
    query_sql: str = Field("", description="自定义查询SQL（留空使用默认SQL；支持 {dept_filter}，未提供时系统会在有科室筛选时自动注入）")
    dept_sql: str = Field("", description="科室查询SQL（留空使用默认SQL）")
    field_mapping: Optional[OracleFieldMapping] = Field(None, description="字段映射配置")
    pool_min: int = Field(1, ge=1, le=50, description="Oracle 连接池最小连接数")
    pool_max: int = Field(8, ge=1, le=200, description="Oracle 连接池最大连接数")
    pool_increment: int = Field(1, ge=1, le=20, description="连接池扩容步长")
    pool_timeout_seconds: int = Field(60, ge=10, le=3600, description="连接池空闲连接超时秒数")
    acquire_timeout_seconds: int = Field(15, ge=1, le=300, description="连接池获取连接等待超时秒数")
    pool_fallback_direct: bool = Field(False, description="连接池获取失败时是否回退到直连（默认关闭）")

    @field_validator("pool_max")
    @classmethod
    def validate_pool_max(cls, v, info):
        pool_min = info.data.get("pool_min", 1)
        if v < pool_min:
            raise ValueError("pool_max 不能小于 pool_min")
        return v


class OracleConfigResponse(BaseModel):
    host: str
    port: int
    service_name: str
    username: str
    password_masked: str = Field("", description="脱敏后的密码")
    instant_client_dir: str = Field("", description="Oracle Instant Client 目录路径")
    query_sql: str = Field("", description="当前查询SQL")
    dept_sql: str = Field("", description="当前科室查询SQL")
    field_mapping: Optional[OracleFieldMapping] = None
    pool_min: int = 1
    pool_max: int = 8
    pool_increment: int = 1
    pool_timeout_seconds: int = 60
    acquire_timeout_seconds: int = 15
    pool_fallback_direct: bool = False


class DataSourceConfig(BaseModel):
    type: constr(pattern=r"^(oracle|postgresql)$") = Field("oracle", description="当前使用的数据源类型")


class DifyConfig(BaseModel):
    base_url: constr(min_length=1, max_length=255) = Field("http://10.255.255.10/v1", description="Dify API 基础地址")
    api_key: constr(min_length=0, max_length=256) = Field("", description="Dify API Key（传入明文，存储加密）")
    workflow_input_variable: constr(min_length=1, max_length=50) = Field("mr_txt", description="Workflow 主输入变量名（病历文本）")
    workflow_output_key: constr(min_length=1, max_length=50) = Field("aa", description="Workflow 输出变量名")
    user_identifier: constr(min_length=1, max_length=50) = Field("med-audit-system", description="调用者标识")
    timeout_seconds: int = Field(90, ge=1, le=300, description="请求超时秒数")
    extra_inputs: dict = Field(default_factory=dict, description="额外静态参数，随每次请求一并传入 Dify（如 hospital_id、audit_mode 等）")
    full_debug_log: bool = Field(False, description="是否记录完整 Dify 请求/响应日志；默认关闭，仅记录脱敏摘要")


class DifyConfigResponse(BaseModel):
    base_url: str
    api_key_masked: str
    workflow_input_variable: str
    workflow_output_key: str = "aa"
    user_identifier: str
    timeout_seconds: int
    extra_inputs: dict = Field(default_factory=dict)
    full_debug_log: bool = False


class DeptConfig(BaseModel):
    mode: constr(pattern=r"^(include|exclude)$") = Field("include", description="include=仅推送列表中科室 | exclude=排除列表中科室")
    list: List[constr(min_length=1, max_length=50)] = Field(default_factory=list, description="科室名称列表")

    @field_validator('list')
    @classmethod
    def validate_dept_list(cls, v):
        """验证科室列表"""
        if len(v) > 200:
            raise ValueError("科室列表不能超过200个")
        return v


class SchedulerConfig(BaseModel):
    enabled: bool = Field(True, description="是否启用定时任务")
    cron: constr(min_length=9, max_length=50) = Field("0 6 * * *", description="Cron 表达式")
    schedule_mode: constr(pattern=r"^(cron|every_n_minutes|every_n_hours|daily)$") = Field("daily", description="调度模式")
    daily_time: constr(pattern=r"^\d{2}:\d{2}$") = Field("06:00", description="每日执行时间 HH:MM")
    interval_value: int = Field(10, ge=1, le=1440, description="灵活间隔值")
    interval_unit: constr(pattern=r"^(minutes|hours)$") = Field("minutes", description="灵活间隔单位")
    audit_type_codes: Optional[List[constr(pattern=r"^[a-z][a-z0-9_]{2,63}$")]] = Field(
        None,
        description="定时任务指定审计类型编码集合；为空时使用 default_for_schedule",
    )

    @field_validator('cron')
    @classmethod
    def validate_cron(cls, v):
        """验证Cron表达式格式"""
        parts = v.strip().split()
        if len(parts) != 5:
            raise ValueError("Cron表达式必须包含5个部分: 分 时 日 月 周")
        return v

    @field_validator('daily_time')
    @classmethod
    def validate_daily_time(cls, v):
        hour, minute = v.split(":")
        if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
            raise ValueError("daily_time 必须是有效时间，格式 HH:MM")
        return v

    @field_validator("audit_type_codes")
    @classmethod
    def validate_scheduler_audit_type_codes(cls, v):
        if v is None:
            return v
        values = [str(item or "").strip() for item in v if str(item or "").strip()]
        if len(values) > 20:
            raise ValueError("audit_type_codes cannot exceed 20")
        return list(dict.fromkeys(values))


class PushSettings(BaseModel):
    interval_ms: int = Field(500, ge=100, le=10000, description="批量推送间隔(ms)")
    max_retry: int = Field(3, ge=0, le=10, description="失败最大重试次数")
    batch_size: int = Field(50, ge=1, le=100, description="每批推送数量")


class PrivacyMaskingConfig(BaseModel):
    enabled: bool = Field(False, description="是否启用敏感字段脱敏")
    mask_name: bool = Field(True, description="是否脱敏姓名")
    mask_id_card: bool = Field(True, description="是否脱敏身份证号")
    mask_address: bool = Field(True, description="是否脱敏住址")
    mask_phone: bool = Field(True, description="是否脱敏联系电话")


# ---- 通知渠道 ----
class NotifyChannel(BaseModel):
    type: Literal["wechat", "dingtalk", "email", "webhook"] = Field(..., description="通知渠道类型")
    enabled: bool = Field(True)
    config: dict = Field(default_factory=dict, description="渠道配置（如 webhook_url, smtp 等）")


class NotifyConfig(BaseModel):
    channels: List[NotifyChannel] = Field(default_factory=list)


# ---- 前置机推送配置 ----
class PayloadField(BaseModel):
    key: str = Field("", description="输出 JSON 键名")
    source: str = Field("", description="数据源路径，如 patient_info.doctor_name，__static__ 表示静态值")
    static_value: str = Field("", description="source=__static__ 时的固定值")
    enabled: bool = Field(True, description="是否启用")
    label: str = Field("", description="前端显示名称")
    group: str = Field("custom", description="分组：patient/dimension/conclusion/meta/custom")


class RelayAlertConfig(BaseModel):
    enabled: bool = Field(False, description="是否启用前置机推送")
    base_url: str = Field("", description="前置机地址")
    endpoint: str = Field("/qc-record-alert", description="推送接口路径")
    secret_key: str = Field("", description="签名密钥（明文，保存时加密）")
    timeout_seconds: int = Field(10, ge=1, le=120, description="超时秒数")
    severity_levels: List[str] = Field(default_factory=lambda: ["high"], description="推送严重度")
    source: str = Field("病历质控系统", description="来源标识")
    max_retry: int = Field(3, ge=0, le=10, description="最大重试次数")
    retry_backoff_seconds: int = Field(5, ge=1, le=300, description="重试间隔秒数")
    payload_fields: List[PayloadField] = Field(default_factory=list, description="推送字段配置")


class RelayAlertConfigResponse(BaseModel):
    enabled: bool = Field(False)
    base_url: str = Field("")
    endpoint: str = Field("/qc-record-alert")
    secret_key_masked: str = Field("", description="脱敏后的签名密钥")
    timeout_seconds: int = Field(10)
    severity_levels: List[str] = Field(default_factory=lambda: ["high"])
    source: str = Field("病历质控系统")
    max_retry: int = Field(3)
    retry_backoff_seconds: int = Field(5)
    payload_fields: List[PayloadField] = Field(default_factory=list, description="推送字段配置")
    available_sources: List[dict] = Field(default_factory=list, description="可用数据源列表")


class QuickActionRequest(BaseModel):
    push_log_id: int = Field(..., description="推送日志ID")
    action: constr(pattern=r"^(rectified|pending|other)$") = Field(..., description="操作：rectified/pending/other")
    reason: str = Field("", description="其他原因说明（action=other 时必填）")


# ---- 推送相关 ----


class DifyTargetRequest(BaseModel):
    """Manual push target endpoint config."""
    name: constr(min_length=1, max_length=50) = Field("default", description="Target name")
    base_url: constr(min_length=1, max_length=255) = Field(..., description="Dify base url")
    api_key: constr(min_length=1, max_length=256) = Field(..., description="Dify api key")
    timeout_seconds: int = Field(90, ge=1, le=300, description="Timeout seconds")
    weight: int = Field(1, ge=1, le=100, description="Load balancing weight")
    enabled: bool = Field(True, description="Enable current target")


class DifyTargetSave(BaseModel):
    """持久化保存的 Dify 目标节点（api_key 存明文，服务端加密存储）。"""
    name: constr(min_length=1, max_length=50) = Field("default", description="目标节点名称")
    base_url: constr(min_length=1, max_length=255) = Field(..., description="Dify API 基础地址")
    api_key: constr(min_length=0, max_length=256) = Field("", description="Dify API Key（明文传入，服务端加密存储）")
    timeout_seconds: int = Field(90, ge=1, le=300, description="请求超时秒数")
    weight: int = Field(1, ge=1, le=100, description="负载均衡权重")
    enabled: bool = Field(True, description="是否启用")


class DifyTargetsResponse(BaseModel):
    """Dify 目标节点列表响应（包含 api_key 明文与脱敏字段）。"""
    targets: List[dict] = Field(default_factory=list, description="节点列表，含 api_key 与 api_key_masked")


class EmrVastbaseConfig(BaseModel):
    """电子病历海量库配置（请求体）"""

    enabled: bool = Field(False, description="是否启用")
    host: str = Field("", description="海量库主机地址")
    port: int = Field(5432, ge=1, le=65535, description="端口")
    database: str = Field("", description="数据库名称")
    username: str = Field("", description="用户名")
    password: str = Field("", description="密码（传入明文，存储加密）")
    db_schema: str = Field("jhemr", description="Schema 名称")
    view: str = Field("v_blws", description="视图名称")
    patient_id_field: str = Field("patient_id", description="患者 ID 字段名")
    visit_id_field: str = Field("visit_id", description="住院次字段名")
    dept_field: str = Field("dept_name", description="科室字段名")
    content_field: str = Field("progress_message", description="文书内容字段名")
    title_field: str = Field("progress_title_name", description="文书标题字段名")
    type_field: str = Field("progress_type_name", description="文书类型字段名")
    template_field: str = Field("progress_template_name", description="模板名称字段名")
    record_time_field: str = Field("record_time_format", description="记录时间字段名")
    finish_time_field: str = Field("finish_time_format", description="完成时间字段名")
    first_save_time_field: str = Field("first_save_time", description="首次保存时间字段名")
    create_date_field: str = Field("create_date", description="创建日期字段名")
    doctor_field: str = Field("doctor_name", description="医生姓名字段名")
    status_field: str = Field("progress_status", description="文书状态字段名")
    connect_timeout_seconds: int = Field(10, ge=1, le=60, description="连接超时秒数")
    statement_timeout_ms: int = Field(60000, ge=1000, le=600000, description="SQL 执行超时毫秒数")
    max_records: int = Field(50000, ge=100, le=500000, description="单次查询最大记录数")
    use_for_export_progress: bool = Field(True, description="导出汇总病程是否使用海量库")
    use_for_export_discharge: bool = Field(True, description="导出汇总出院记录是否使用海量库")
    fallback_to_oracle: bool = Field(True, description="海量库异常时是否回退 Oracle")


class EmrVastbaseConfigResponse(BaseModel):
    """电子病历海量库配置（响应体）"""

    enabled: bool = Field(False)
    host: str = Field("")
    port: int = Field(5432)
    database: str = Field("")
    username: str = Field("")
    password_masked: str = Field("", description="脱敏后的密码")
    db_schema: str = Field("jhemr")
    view: str = Field("v_blws")
    patient_id_field: str = Field("patient_id")
    visit_id_field: str = Field("visit_id")
    dept_field: str = Field("dept_name")
    content_field: str = Field("progress_message")
    title_field: str = Field("progress_title_name")
    type_field: str = Field("progress_type_name")
    template_field: str = Field("progress_template_name")
    record_time_field: str = Field("record_time_format")
    finish_time_field: str = Field("finish_time_format")
    first_save_time_field: str = Field("first_save_time")
    create_date_field: str = Field("create_date")
    doctor_field: str = Field("doctor_name")
    status_field: str = Field("progress_status")
    connect_timeout_seconds: int = Field(10)
    statement_timeout_ms: int = Field(60000)
    max_records: int = Field(50000)
    use_for_export_progress: bool = Field(True)
    use_for_export_discharge: bool = Field(True)
    fallback_to_oracle: bool = Field(True)


class AuditTypeSource(BaseModel):
    """审计类型数据源配置"""

    type: Literal["sql"] = Field("sql", description="数据源类型")
    backend: Literal["default", "oracle", "postgresql", "emr_vastbase"] = Field("default", description="后端数据源路由：default 使用全局 data_source.type，其余强制指定")
    document_kind: Literal["", "all", "progress", "first_progress", "discharge"] = Field("", description="海量库文书类型过滤：空字符串时按 source_name 自动推断，其余显式指定")
    query_sql: str = Field("", description="查询 SQL")
    field_mapping: Dict[str, str] = Field(default_factory=dict, description="字段映射")
    required: bool = Field(True, description="是否必需")


class AuditTypeDify(BaseModel):
    """审计类型专属 Dify 配置"""

    base_url: str = Field("", description="Dify API 基础地址")
    api_key_enc: Optional[str] = Field(None, description="已加密 API Key")
    api_key: Optional[str] = Field(None, description="明文 API Key，仅写入时使用")
    workflow_input_variable: str = Field("mr_txt", description="Workflow 主输入变量名")
    workflow_output_key: str = Field("aa", description="Workflow 输出变量名")
    user_identifier: str = Field("med-audit-system", description="调用者标识")
    timeout_seconds: int = Field(90, ge=1, le=300, description="请求超时秒数")
    extra_inputs: Dict[str, Any] = Field(default_factory=dict, description="额外静态输入")
    targets: List[Dict[str, Any]] = Field(default_factory=list, description="扩展 Dify 目标节点")


class AuditTypeDisplayColumn(BaseModel):
    """展示规则中的表格列定义"""

    label: str = Field(..., description="列标题")
    path: str = Field(..., description="列 JSONPath")
    renderer: str = Field("", description="可选渲染器")


class AuditTypeDisplayBlock(BaseModel):
    """展示规则块"""

    label: str = Field(..., description="区块标题")
    path: str = Field(..., description="JSONPath")
    type: Literal["text_block", "kv_list", "table", "bool_tag", "severity_badge", "dimension_grid", "raw_json", "tag_list"] = Field(
        "text_block",
        description="渲染器类型",
    )
    columns: List[AuditTypeDisplayColumn] = Field(default_factory=list, description="表格列配置")
    collapsed: bool = Field(False, description="是否默认折叠")


class AuditTypeDisplay(BaseModel):
    """审计类型展示规则"""

    summary_blocks: List[AuditTypeDisplayBlock] = Field(default_factory=list, description="摘要区块")
    detail_blocks: List[AuditTypeDisplayBlock] = Field(default_factory=list, description="详情区块")


class JoinKey(BaseModel):
    """关联键配置"""

    left: str = Field(..., description="左侧数据源字段")
    right: str = Field(..., description="右侧数据源字段")


class JoinRule(BaseModel):
    """数据源关联规则"""

    name: str = Field(..., description="规则名称")
    description: str = Field("", description="规则描述")
    left_source: str = Field(..., description="左侧数据源名称")
    right_source: str = Field(..., description="右侧数据源名称")
    join_keys: List[JoinKey] = Field(..., description="关联键列表")
    join_type: Literal["inner", "left"] = Field("inner", description="关联类型")


class AuditTypeConfig(BaseModel):
    """审计类型配置"""

    code: constr(pattern=r"^[a-z][a-z0-9_]{2,63}$") = Field(..., description="类型编码")
    name: str = Field(..., description="类型名称")
    description: str = Field("", description="类型描述")
    enabled: bool = Field(True, description="是否启用")
    sort_order: int = Field(100, description="排序值")
    default_for_schedule: bool = Field(False, description="是否默认参与调度")
    sources: Dict[str, AuditTypeSource] = Field(default_factory=dict, description="命名数据源")
    group_key: List[str] = Field(default_factory=lambda: ["patient_id", "visit_number"], description="分组键")
    join_rules: List[JoinRule] = Field(default_factory=list, description="数据源关联规则")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Payload 构造配置")
    dify: AuditTypeDify = Field(default_factory=AuditTypeDify, description="Dify 配置")
    response: Dict[str, Any] = Field(default_factory=dict, description="响应解析配置")
    display: AuditTypeDisplay = Field(default_factory=AuditTypeDisplay, description="展示配置")

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, v):
        if not v:
            raise ValueError("sources 不能为空")
        return v

    @field_validator("group_key")
    @classmethod
    def validate_group_key(cls, v):
        return v or ["patient_id", "visit_number"]

    @model_validator(mode="after")
    def validate_multi_source_contract(self):
        payload = self.payload or {}
        builder = str(payload.get("builder") or "").strip()

        numeric_keys = ("date_window_days", "progress_followup_days", "max_lab_items", "max_exam_reports")
        for key in numeric_keys:
            if key not in payload:
                continue
            value = payload.get(key)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"payload.{key} must be non-negative integer")
            if key in {"max_lab_items", "max_exam_reports"} and value == 0:
                raise ValueError(f"payload.{key} must be greater than 0")

        if "include_normal_summary" in payload and not isinstance(payload.get("include_normal_summary"), bool):
            raise ValueError("payload.include_normal_summary must be bool")

        if self.code == "lab_exam_vs_progress_nursing":
            required_sources = {"lab", "exam", "progress", "nursing"}
            missing = sorted(required_sources - set(self.sources.keys()))
            if missing:
                raise ValueError(f"lab_exam_vs_progress_nursing missing sources: {', '.join(missing)}")
            allowed_builders = {"lab_exam_progress_nursing", "lab_exam_structured_progress_nursing"}
            if builder not in allowed_builders:
                raise ValueError(
                    "lab_exam_vs_progress_nursing payload.builder must be lab_exam_progress_nursing "
                    "or lab_exam_structured_progress_nursing"
                )
            required_group_keys = {"patient_id", "visit_number", "audit_date"}
            if not required_group_keys.issubset(set(self.group_key)):
                raise ValueError("lab_exam_vs_progress_nursing group_key must include patient_id/visit_number/audit_date")

        if self.code == "frontpage_surgery_diagnosis_vs_first_progress":
            required_sources = {"frontpage", "first_progress"}
            missing = sorted(required_sources - set(self.sources.keys()))
            if missing:
                raise ValueError(f"frontpage_surgery_diagnosis_vs_first_progress missing sources: {', '.join(missing)}")
            if builder != "frontpage_surgery_first_progress":
                raise ValueError("frontpage_surgery_diagnosis_vs_first_progress payload.builder must be frontpage_surgery_first_progress")
            required_group_keys = {"patient_id", "visit_number"}
            if not required_group_keys.issubset(set(self.group_key)):
                raise ValueError("frontpage_surgery_diagnosis_vs_first_progress group_key must include patient_id/visit_number")

        return self


class AuditTypeListResponse(BaseModel):
    items: List[AuditTypeConfig] = Field(default_factory=list, description="审计类型列表")


class AuditTypeCloneRequest(BaseModel):
    new_code: constr(pattern=r"^[a-z][a-z0-9_]{2,63}$") = Field(..., description="新类型编码")
    new_name: str = Field(..., description="新类型名称")


class AuditTypeTestSourceRequest(BaseModel):
    query_date: constr(pattern=r"^\d{4}-\d{2}-\d{2}$", min_length=10, max_length=10) = Field(..., description="测试日期")
    date_dimension: constr(pattern=r"^(query_date|record_create_date|admission_date|discharge_date)$") = Field(
        "query_date",
        description="日期维度",
    )
    dept_filter: Optional[List[constr(min_length=1, max_length=50)]] = Field(None, description="科室筛选")


class AuditTypeTestDifyRequest(BaseModel):
    mr_txt_sample: str = Field(..., description="Dify 测试文本")


class ManualPushRequest(BaseModel):
    """Manual push request with range/date-dimension and bulk options."""
    query_date: Optional[constr(pattern=r"^\d{4}-\d{2}-\d{2}$", min_length=10, max_length=10)] = None
    date_from: Optional[constr(pattern=r"^\d{4}-\d{2}-\d{2}$", min_length=10, max_length=10)] = None
    date_to: Optional[constr(pattern=r"^\d{4}-\d{2}-\d{2}$", min_length=10, max_length=10)] = None
    date_dimension: constr(pattern=r"^(query_date|record_create_date|admission_date|discharge_date)$") = "query_date"
    dept_filter: Optional[List[constr(min_length=1, max_length=50)]] = None
    dry_run: bool = False
    async_mode: bool = False
    parallel_workers: int = Field(1, ge=1, le=64, description="Parallel workers for manual push")
    empty_retry_max: int = Field(0, ge=0, le=10, description="Max retries for empty Dify output")
    empty_retry_backoff_ms: int = Field(1000, ge=0, le=60000, description="Backoff milliseconds for empty retry")
    target_strategy: constr(pattern=r"^(round_robin|weighted_random)$") = Field(
        "round_robin",
        description="Target strategy",
    )
    dify_targets: Optional[List[DifyTargetRequest]] = Field(
        None,
        description="Optional multi Dify targets for manual push only",
    )
    audit_type_codes: Optional[List[constr(pattern=r"^[a-z][a-z0-9_]{2,63}$")]] = Field(
        None,
        description="指定的审计类型编码集合；为空时使用默认调度集合",
    )
    parallel_audit_types: bool = Field(False, description="是否并行执行多个审计类型")
    selected_record_keys: Optional[List[constr(min_length=1, max_length=255)]] = Field(
        None,
        description="Optional selected single-record keys from manual preview",
    )
    skip_already_succeeded: bool = Field(
        False,
        description="断点续推：跳过 push_log 中已有成功记录的条目，用于大批量任务中断后继续推送",
    )
    page: Optional[int] = Field(None, ge=1, description="Query preview page number")
    page_size: Optional[int] = Field(None, ge=1, le=500, description="Query preview page size")

    @field_validator('query_date', 'date_from', 'date_to')
    @classmethod
    def validate_date_format(cls, v):
        if v is None:
            return v
        try:
            d = datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("date must be yyyy-mm-dd")
        now = datetime.now()
        if d.date() > now.date():
            raise ValueError("date cannot be in the future")
        if d.date() < (now - timedelta(days=365)).date():
            raise ValueError("date cannot be older than 365 days")
        return v

    @field_validator('date_to')
    @classmethod
    def validate_date_order(cls, v, info):
        if not v:
            return v
        date_from = info.data.get('date_from')
        if date_from and v < date_from:
            raise ValueError("date_to must be >= date_from")
        return v

    @field_validator('dept_filter')
    @classmethod
    def validate_dept_filter(cls, v):
        if v is not None and len(v) > 100:
            raise ValueError("dept_filter cannot exceed 100")
        return v

    @field_validator('dify_targets')
    @classmethod
    def validate_dify_targets(cls, v):
        if v is None:
            return v
        if len(v) > 10:
            raise ValueError("dify_targets cannot exceed 10")
        if not any(bool(t.enabled) for t in v):
            raise ValueError("at least one enabled target is required")
        return v

    @field_validator('selected_record_keys')
    @classmethod
    def validate_selected_record_keys(cls, v):
        if v is None:
            return v
        if len(v) > 5000:
            raise ValueError("selected_record_keys cannot exceed 5000")
        return v

    @field_validator("audit_type_codes")
    @classmethod
    def validate_audit_type_codes(cls, v):
        if v is None:
            return v
        values = [str(item or "").strip() for item in v if str(item or "").strip()]
        if len(values) > 20:
            raise ValueError("audit_type_codes cannot exceed 20")
        return list(dict.fromkeys(values))


class RetryRequest(BaseModel):
    log_ids: List[int] = Field(..., description="需要重推的日志 ID 列表")

    @field_validator('log_ids')
    @classmethod
    def validate_log_ids(cls, v):
        """验证日志ID列表"""
        if not v:
            raise ValueError("日志ID列表不能为空")
        if len(v) > 50:
            raise ValueError("单次重推的日志数量不能超过50条")
        if any(log_id <= 0 for log_id in v):
            raise ValueError("日志ID必须为正整数")
        return v


class PushProgress(BaseModel):
    task_id: str
    status: str  # running | completed | failed | cancelled
    total: int = 0
    processed: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled: bool = False


# ---- 日志查询 ----
class PushLogQuery(BaseModel):
    page: int = Field(1, ge=1, description="页码")
    limit: int = Field(20, ge=1, le=200, description="每页数量")
    status: Optional[constr(pattern=r"^(success|failed|skipped|pending)$")] = Field(None, description="状态筛选")
    dept: Optional[constr(max_length=50)] = Field(None, description="科室筛选")
    date_from: Optional[constr(pattern=r"^\d{4}-\d{2}-\d{2}$")] = Field(None, description="开始日期")
    date_to: Optional[constr(pattern=r"^\d{4}-\d{2}-\d{2}$")] = Field(None, description="结束日期")
    patient_id: Optional[constr(max_length=50)] = Field(None, description="患者ID")
    audit_type_code: Optional[constr(max_length=64)] = Field(None, description="核查类型编码")
    reviewed_flag: Optional[int] = Field(None, ge=0, le=1, description="人工复核标记：0未复核/1已复核")
    manual_override: Optional[int] = Field(None, ge=0, le=1, description="手动覆盖标记：0否/1是")
    skip_reason: Optional[constr(max_length=200)] = Field(None, description="跳过原因")

    @field_validator('date_to')
    @classmethod
    def validate_date_range(cls, v, info):
        """验证日期范围"""
        date_from = info.data.get('date_from')
        if v and date_from:
            try:
                if datetime.strptime(v, "%Y-%m-%d") < datetime.strptime(date_from, "%Y-%m-%d"):
                    raise ValueError("结束日期不能早于开始日期")
            except ValueError:
                pass
        return v


class PushLogItem(BaseModel):
    id: int
    push_time: datetime
    trigger_type: str
    query_date: str
    patient_id: str
    patient_name: Optional[str] = ""
    dept: Optional[str] = ""
    audit_type_code: Optional[str] = ""
    audit_type_name: Optional[str] = ""
    status: str
    inconsistency: int
    severity: Optional[str] = ""
    risk_score: int = 0
    elapsed_ms: int
    retry_count: int
    pushed_flag: int = 0
    reviewed_flag: int = 0
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = ""
    manual_override: int = 0
    skip_reason: Optional[str] = ""
    skip_reason_label: Optional[str] = ""
    error_msg: Optional[str] = ""
    failure_reason: Optional[str] = ""
    alert_level: Optional[str] = ""

    @field_validator(
        'trigger_type',
        'query_date',
        'patient_id',
        'patient_name',
        'dept',
        'audit_type_code',
        'audit_type_name',
        'status',
        'severity',
        'reviewed_by',
        'skip_reason',
        'skip_reason_label',
        'error_msg',
        'failure_reason',
        'alert_level',
        mode='before'
    )
    @classmethod
    def normalize_nullable_text_fields(cls, v):
        """统一将 None 归一化为空字符串，避免日志历史数据触发校验错误。"""
        return "" if v is None else str(v)

    class Config:
        from_attributes = True


class PushLogDetail(PushLogItem):
    workflow_run_id: Optional[str] = ""
    task_id: Optional[str] = ""
    ai_result: Optional[str] = ""
    mr_text: Optional[str] = ""
    request_json: Optional[str] = ""
    response_json: Optional[str] = ""
    parse_status: Optional[str] = ""
    parse_error: Optional[str] = ""
    ai_version: Optional[str] = "1.0"
    audit_type_display: Optional[AuditTypeDisplay] = None
    stored_audit: Optional[Dict[str, Any]] = None
    audit_result: Optional[Dict[str, Any]] = None
    raw_debug: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class PaginatedLogs(BaseModel):
    total: int
    page: int
    limit: int
    items: List[PushLogItem]


# ---- 统计 ----
class StatsSummary(BaseModel):
    total_pushes: int
    success_count: int
    failed_count: int
    success_rate: float
    inconsistency_count: int
    inconsistency_rate: float


class DailyTrend(BaseModel):
    date: str
    total: int
    success: int
    failed: int
    inconsistency: int


class DeptDistribution(BaseModel):
    dept: str
    total: int
    inconsistency: int


class SeverityDistribution(BaseModel):
    severity: str
    count: int


# ---- 健康检查 ----
class ComponentHealth(BaseModel):
    status: str  # up | down
    latency_ms: Optional[int] = None
    message: Optional[str] = None


class HealthResponse(BaseModel):
    status: str  # healthy | degraded | unhealthy
    timestamp: datetime
    components: dict


# ---- 审计报告 ----
class AuditDimensionItem(BaseModel):
    dimension: str
    dimension_code: str = ""
    status: str = ""        # ✅ ❌ ⚠️ ❓
    severity: str = ""
    confidence: float = 0
    medical_content: str = ""
    nursing_content: str = ""
    explanation: str = ""
    issue_summary: str = ""
    recommendation: str = ""
    alert_level: str = ""           # red | yellow | blue | gray
    closure_hours: int = 0
    push_strategy: str = ""         # immediate | batch | shift_summary | review_only
    outcome_bucket: str = ""        # primary | secondary | none
    extra_json: str = "{}"
    medical_evidence: List[Any] = Field(default_factory=list)
    nursing_evidence: List[Any] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)


class AuditReportResponse(BaseModel):
    log_id: int
    patient_id: str
    patient_name: str
    admission_no: str = ""
    dept: str
    query_date: str
    push_time: datetime
    dimensions: List[AuditDimensionItem] = Field(default_factory=list)
    overall_conclusion: str = ""
    overall_qc_summary: str = ""
    focus_items: List[str] = Field(default_factory=list)
    status: str
    alert_level: str = ""
    severity: str = ""


class DimensionStatsItem(BaseModel):
    dimension: str
    total: int = 0
    pass_count: int = 0       # ✅
    fail_count: int = 0       # ❌
    warn_count: int = 0       # ⚠️
    unknown_count: int = 0    # ❓
    pass_rate: float = 0.0


# ---- 通用 ----
class MessageResponse(BaseModel):
    message: str
    success: bool = True
    data: Optional[dict] = None


# ============ RBAC 认证与授权 ============

class LoginRequest(BaseModel):
    username: constr(min_length=1, max_length=50) = Field(..., description="用户名")
    password: constr(min_length=1, max_length=128) = Field(..., description="密码")


class UserInfo(BaseModel):
    id: int
    username: str
    full_name: str
    email: str
    dept_id: Optional[int] = None
    dept_name: Optional[str] = None
    role: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserInfo


class PermissionInfo(BaseModel):
    id: int
    name: str
    description: str
    module: str

    class Config:
        from_attributes = True


class RoleMenuInfo(BaseModel):
    id: str
    label: str = ""
    icon: str = ""
    path: str = ""


class RoleDepartmentInfo(BaseModel):
    id: int
    name: str
    code: str = ""
    manager_id: Optional[int] = None


class RoleInfo(BaseModel):
    id: int
    name: str
    description: str
    permissions: List[PermissionInfo] = Field(default_factory=list)
    menus: List[RoleMenuInfo] = Field(default_factory=list)
    departments: List[RoleDepartmentInfo] = Field(default_factory=list)

    class Config:
        from_attributes = True


class DepartmentInfo(BaseModel):
    id: int
    name: str
    code: str = ""
    manager_id: Optional[int] = None

    @field_validator('code', mode='before')
    @classmethod
    def normalize_code(cls, v):
        return "" if v is None else str(v)

    class Config:
        from_attributes = True


class UserCreateRequest(BaseModel):
    username: constr(min_length=1, max_length=50) = Field(..., description="用户名")
    password: constr(min_length=6, max_length=128) = Field(..., description="密码（至少6位）")
    full_name: constr(min_length=1, max_length=100) = Field(..., description="姓名")
    email: Optional[str] = Field(None, description="邮箱")
    dept_id: Optional[int] = Field(None, description="科室ID")
    role_id: Optional[int] = Field(None, description="角色ID")


class UserUpdateRequest(BaseModel):
    full_name: Optional[str] = Field(None, description="姓名")
    email: Optional[str] = Field(None, description="邮箱")
    dept_id: Optional[int] = Field(None, description="科室ID")
    role_id: Optional[int] = Field(None, description="角色ID")
    is_active: Optional[bool] = Field(None, description="是否激活")


class ChangePasswordRequest(BaseModel):
    old_password: constr(min_length=1, max_length=128) = Field(..., description="旧密码")
    new_password: constr(min_length=6, max_length=128) = Field(..., description="新密码（至少6位）")


class UserListResponse(BaseModel):
    total: int
    page: int
    limit: int
    items: List[UserInfo]


# ============ 质控反馈 ============

class QCFeedbackCreateRequest(BaseModel):
    push_log_id: int = Field(..., description="关联的推送日志ID")
    dept_id: int = Field(..., description="科室ID")
    severity: constr(pattern=r"^(high|medium|low)$") = Field(..., description="严重程度：high/medium/low")
    feedback_text: str = Field(..., description="反馈内容")
    assigned_to: Optional[int] = Field(None, description="分配给谁（用户ID）")


class QCFeedbackUpdateRequest(BaseModel):
    status: Optional[constr(pattern=r"^(pending|acknowledged|rectified|closed)$")] = Field(None, description="状态")
    assigned_to: Optional[int] = Field(None, description="分配给谁")
    feedback_text: Optional[str] = Field(None, description="反馈内容")


class QCFeedbackRectifyRequest(BaseModel):
    rectification_text: str = Field(..., description="整改说明")


class QCFeedbackHistoryItem(BaseModel):
    id: int
    old_status: str
    new_status: str
    changed_by: int
    change_reason: str
    changed_at: datetime

    class Config:
        from_attributes = True


class QCFeedbackItem(BaseModel):
    id: int
    push_log_id: int
    dept_id: int
    severity: str
    status: str
    assigned_to: Optional[int] = None
    feedback_text: str
    is_viewed: bool = False
    viewed_at: Optional[datetime] = None
    view_count: int = 0
    rectification_clicked: bool = False
    rectification_clicked_at: Optional[datetime] = None
    suppress_ai_push: bool = False
    rectification_text: str = ""
    rectification_date: Optional[datetime] = None
    created_by: int
    created_at: datetime
    updated_at: datetime

    @field_validator('rectification_text', mode='before')
    @classmethod
    def normalize_rectification_text(cls, v):
        return "" if v is None else str(v)

    class Config:
        from_attributes = True


class QCFeedbackDetail(QCFeedbackItem):
    history: List[QCFeedbackHistoryItem] = Field(default_factory=list)


class QCFeedbackListResponse(BaseModel):
    total: int
    page: int
    limit: int
    items: List[QCFeedbackItem]
    stats: Optional[dict] = None  # 统计信息


class QCFeedbackStats(BaseModel):
    total: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    viewed: int = 0
    rectification_clicked: int = 0
    suppressed: int = 0
    pending: int = 0
    acknowledged: int = 0
    rectified: int = 0
    closed: int = 0


class QCFeedbackConfirmRequest(BaseModel):
    action: constr(pattern=r"^(acknowledged|closed)$") = Field("acknowledged", description="确认动作：acknowledged=确认待跟进，closed=确认无问题并关闭")
    review_comment: str = Field("", description="科室反馈/确认说明")


class QCFeedbackBulkDeleteRequest(BaseModel):
    log_ids: List[int] = Field(..., min_length=1, max_length=1000, description="待从质控反馈中心删除的日志ID")


class QCFeedbackCaseItem(BaseModel):
    log_id: int
    feedback_id: Optional[int] = None
    dept_id: Optional[int] = None
    dept_name: str = ""
    audit_type_code: str = ""
    audit_type_name: str = ""
    patient_id: str
    patient_name: str = ""
    admission_no: str = ""
    query_date: str
    push_time: datetime
    severity: str = ""
    risk_score: int = 0
    overall_conclusion: str = ""
    overall_qc_summary: str = ""
    alert_level: str = ""
    closure_hours: int = 0
    push_strategy: str = ""
    outcome_bucket: str = ""
    issue_count: int = 0
    focus_items: List[str] = Field(default_factory=list)
    feedback_status: str = "pending"
    feedback_text: str = ""
    reviewed_by: Optional[str] = ""
    reviewed_at: Optional[datetime] = None
    admission_date: str = ""
    discharge_date: str = ""
    admission_diagnosis: str = ""
    is_discharged: str = ""
    admission_dept_name: str = ""
    discharge_dept_name: str = ""
    discharge_main_diagnosis: str = ""
    surgery: str = ""
    id_card: str = ""
    address: str = ""
    phone: str = ""


class QCFeedbackCaseDetail(QCFeedbackCaseItem):
    dimensions: List[AuditDimensionItem] = Field(default_factory=list)
    feedback: Optional[QCFeedbackDetail] = None
    mr_text: Optional[str] = ""          # 推送的原始病历文书与护理记录
    medical_documents_text: Optional[str] = ""
    nursing_records_text: Optional[str] = ""


class QCFeedbackCaseListResponse(BaseModel):
    total: int
    page: int
    limit: int
    items: List[QCFeedbackCaseItem]
    stats: Optional[dict] = None


# ---- 导出审计日志 ----
class ExportAuditLogItem(BaseModel):
    """导出审计日志条目"""
    id: int
    export_time: datetime
    user_id: int
    username: str
    export_type: str
    export_format: str
    filter_criteria: str = ""
    record_count: int = 0
    ip_address: str = ""
    user_agent: str = ""
    status: str
    error_msg: str = ""

    class Config:
        from_attributes = True


class ExportAuditLogListResponse(BaseModel):
    """导出审计日志列表响应"""
    total: int
    page: int
    limit: int
    items: List[ExportAuditLogItem]
