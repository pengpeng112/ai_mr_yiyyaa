"""
Pydantic Schemas —— 驱动 Swagger 文档 & 请求/响应校验
"""
from pydantic import BaseModel, Field, constr
from typing import Optional, List
from datetime import datetime


# ---- 配置相关 ----
class OracleConfig(BaseModel):
    host: str = Field("10.255.255.20", description="Oracle 主机地址")
    port: int = Field(1521, description="Oracle 端口")
    service_name: str = Field("orcl", description="Oracle 服务名")
    username: str = Field("", description="用户名")
    password: str = Field("", description="密码（传入明文，存储加密）")


class OracleConfigResponse(BaseModel):
    host: str
    port: int
    service_name: str
    username: str
    password_masked: str = Field("", description="脱敏后的密码")


class DifyConfig(BaseModel):
    base_url: str = Field("http://10.255.255.10/v1", description="Dify API 基础地址")
    api_key: str = Field("", description="Dify API Key（传入明文，存储加密）")
    workflow_input_variable: str = Field("mr_txt", description="Workflow 输入变量名")
    workflow_output_key: str = Field("aa", description="Dify Workflow 输出变量名")
    user_identifier: str = Field("med-audit-system", description="调用者标识")
    timeout_seconds: int = Field(90, description="请求超时秒数")
    extra_inputs: dict = Field(default_factory=dict, description="额外静态输入变量（合并到每次 Dify 调用的 inputs 中）")


class DifyConfigResponse(BaseModel):
    base_url: str
    api_key_masked: str
    workflow_input_variable: str
    workflow_output_key: str
    user_identifier: str
    timeout_seconds: int
    extra_inputs: dict = Field(default_factory=dict)


# ---- SQL 配置 ----
class SqlConfig(BaseModel):
    main_query: str = Field(..., description="Oracle 查询 SQL 模板，包含 {dept_filter} 和 :query_date 占位符")
    dept_column: str = Field("所在科室名称", description="科室列名，用于 exclude 模式过滤")


class DeptConfig(BaseModel):
    mode: str = Field("include", description="include=仅推送列表中科室 | exclude=排除列表中科室")
    list: List[str] = Field(default_factory=list, description="科室名称列表")


class SchedulerConfig(BaseModel):
    enabled: bool = Field(True, description="是否启用定时任务")
    cron: str = Field("0 6 * * *", description="Cron 表达式")


class PushSettings(BaseModel):
    interval_ms: int = Field(500, description="批量推送间隔(ms)")
    max_retry: int = Field(3, description="失败最大重试次数")
    batch_size: int = Field(50, description="每批推送数量")


# ---- 通知渠道 ----
class NotifyChannel(BaseModel):
    type: str = Field(..., description="wechat | dingtalk | email | webhook")
    enabled: bool = Field(True)
    config: dict = Field(default_factory=dict, description="渠道配置（如 webhook_url, smtp 等）")


class NotifyConfig(BaseModel):
    channels: List[NotifyChannel] = Field(default_factory=list)


# ---- 推送相关 ----
class ManualPushRequest(BaseModel):
    query_date: str = Field(..., description="查询日期 yyyy-mm-dd")
    dept_filter: Optional[List[str]] = Field(None, description="科室过滤（空=用配置中的科室）")
    dry_run: bool = Field(False, description="True=仅预览不推送")
    async_mode: bool = Field(False, description="True=异步执行返回 task_id")


class RetryRequest(BaseModel):
    log_ids: List[int] = Field(..., description="需要重推的日志 ID 列表")


class PushProgress(BaseModel):
    task_id: str
    status: str  # running | completed | failed
    total: int = 0
    processed: int = 0
    success: int = 0
    failed: int = 0


# ---- 日志查询 ----
class PushLogQuery(BaseModel):
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=200)
    status: Optional[str] = None
    dept: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    patient_id: Optional[str] = None


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

    class Config:
        from_attributes = True


class PaginatedLogs(BaseModel):
    total: int
    page: int
    limit: int
    items: List[PushLogItem]


# ---- 审计报告 ----
class AuditDimensionItem(BaseModel):
    dimension: str
    status: str          # ✅❌⚠️❓
    medical_content: str = ""
    nursing_content: str = ""
    explanation: str = ""


class AuditReportResponse(BaseModel):
    log_id: int
    patient_id: str
    patient_name: str
    admission_no: str
    dept: str
    query_date: str
    push_time: datetime
    dimensions: List[AuditDimensionItem]
    overall_conclusion: str
    focus_items: List[str]
    status: str


class DimensionStatsItem(BaseModel):
    dimension: str
    total: int
    pass_count: int       # ✅
    fail_count: int       # ❌
    warn_count: int       # ⚠️
    unknown_count: int    # ❓
    pass_rate: float


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


# ---- 通用 ----
class MessageResponse(BaseModel):
    message: str
    success: bool = True
    data: Optional[dict] = None
