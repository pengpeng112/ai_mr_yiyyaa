"""
Pydantic Schemas —— 驱动 Swagger 文档 & 请求/响应校验
"""
from pydantic import BaseModel, Field, field_validator, constr
from typing import Optional, List, Literal
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
    query_sql: str = Field("", description="自定义查询SQL（留空使用默认SQL）")
    dept_sql: str = Field("", description="科室查询SQL（留空使用默认SQL）")
    field_mapping: Optional[OracleFieldMapping] = Field(None, description="字段映射配置")


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


class DifyConfigResponse(BaseModel):
    base_url: str
    api_key_masked: str
    workflow_input_variable: str
    workflow_output_key: str = "aa"
    user_identifier: str
    timeout_seconds: int
    extra_inputs: dict = Field(default_factory=dict)


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

    @field_validator('cron')
    @classmethod
    def validate_cron(cls, v):
        """验证Cron表达式格式"""
        parts = v.strip().split()
        if len(parts) != 5:
            raise ValueError("Cron表达式必须包含5个部分: 分 时 日 月 周")
        return v


class PushSettings(BaseModel):
    interval_ms: int = Field(500, ge=100, le=10000, description="批量推送间隔(ms)")
    max_retry: int = Field(3, ge=0, le=10, description="失败最大重试次数")
    batch_size: int = Field(50, ge=1, le=100, description="每批推送数量")


# ---- 通知渠道 ----
class NotifyChannel(BaseModel):
    type: Literal["wechat", "dingtalk", "email", "webhook"] = Field(..., description="通知渠道类型")
    enabled: bool = Field(True)
    config: dict = Field(default_factory=dict, description="渠道配置（如 webhook_url, smtp 等）")


class NotifyConfig(BaseModel):
    channels: List[NotifyChannel] = Field(default_factory=list)


# ---- 推送相关 ----
class ManualPushRequest(BaseModel):
    query_date: constr(
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        min_length=10,
        max_length=10
    ) = Field(..., description="查询日期 yyyy-mm-dd")
    dept_filter: Optional[List[constr(min_length=1, max_length=50)]] = Field(
        None,
        description="科室过滤（空=用配置中的科室）"
    )
    dry_run: bool = Field(False, description="True=仅预览不推送")
    async_mode: bool = Field(False, description="True=异步执行返回 task_id")

    @field_validator('query_date')
    @classmethod
    def validate_date_format(cls, v):
        """验证日期格式、有效性和范围"""
        try:
            d = datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("日期格式必须为 yyyy-mm-dd，且必须是有效日期")
        
        now = datetime.now()
        if d.date() > now.date():
            raise ValueError("查询日期不能是未来日期")
        if d.date() < (now - timedelta(days=365)).date():
            raise ValueError("查询日期不能超过1年前")
        return v

    @field_validator('dept_filter')
    @classmethod
    def validate_dept_filter(cls, v):
        """验证科室过滤列表"""
        if v is not None and len(v) > 100:
            raise ValueError("科室过滤列表不能超过100个科室")
        return v


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
    status: str  # running | completed | failed
    total: int = 0
    processed: int = 0
    success: int = 0
    failed: int = 0


# ---- 日志查询 ----
class PushLogQuery(BaseModel):
    page: int = Field(1, ge=1, description="页码")
    limit: int = Field(20, ge=1, le=200, description="每页数量")
    status: Optional[constr(pattern=r"^(success|failed|skipped|pending)$")] = Field(None, description="状态筛选")
    dept: Optional[constr(max_length=50)] = Field(None, description="科室筛选")
    date_from: Optional[constr(pattern=r"^\d{4}-\d{2}-\d{2}$")] = Field(None, description="开始日期")
    date_to: Optional[constr(pattern=r"^\d{4}-\d{2}-\d{2}$")] = Field(None, description="结束日期")
    patient_id: Optional[constr(max_length=50)] = Field(None, description="患者ID")

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
    patient_name: str
    dept: str
    status: str
    inconsistency: int
    severity: str
    risk_score: int = 0
    elapsed_ms: int
    retry_count: int
    error_msg: str

    class Config:
        from_attributes = True


class PushLogDetail(PushLogItem):
    workflow_run_id: str
    task_id: str
    ai_result: str
    mr_text: str
    request_json: str = ""
    response_json: str = ""
    parse_status: str = ""
    parse_error: str = ""
    ai_version: str = "1.0"

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
    status: str = ""        # ✅ ❌ ⚠️ ❓
    medical_content: str = ""
    nursing_content: str = ""
    explanation: str = ""


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
    focus_items: List[str] = Field(default_factory=list)
    status: str


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


class RoleInfo(BaseModel):
    id: int
    name: str
    description: str
    permissions: List[PermissionInfo] = Field(default_factory=list)

    class Config:
        from_attributes = True


class DepartmentInfo(BaseModel):
    id: int
    name: str
    code: str
    manager_id: Optional[int] = None

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
    rectification_text: str
    rectification_date: Optional[datetime] = None
    created_by: int
    created_at: datetime
    updated_at: datetime

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
