# 医疗记录一致性审计系统 — 全面代码改造与界面优化计划

> 生成日期：2026-04-04
> 审查范围：Python FastAPI 后端 + Vue 3 前端（共约 6,000+ 行代码）
> 总问题数：后端 21 项 + 前端 20 项 = 41 项

---

## 一、问题概览

| 层级 | 严重度 | 数量 | 主要类别 |
|------|--------|------|---------|
| **后端** | P0/P1（高） | 7 | 安全漏洞、并发竞态、连接泄漏 |
| **后端** | P2（中） | 8 | 性能、异常处理、设计缺陷 |
| **后端** | P3（低） | 6 | 重复代码、测试缺失、容器安全 |
| **前端** | P0/P1（高） | 5 | 安全 Bug、内存泄漏、核心 UX 缺陷 |
| **前端** | P2（中） | 10 | 布局、交互体验、错误处理 |
| **前端** | P3（低） | 5 | 可访问性、响应式、性能 |

---

## 二、后端代码改造计划

### 第一阶段：紧急修复（P0/P1）— 预计 3-5 个工作日

---

#### 1.1 移除 docker-compose.yml 中的硬编码密钥 🔴

**文件：** `docker-compose.yml:17-18`

**问题：** `JWT_SECRET_KEY` 和 `SECRET_KEY` 明文写入 YAML，可通过 Git 历史泄露，攻击者可伪造任意用户 JWT。

**修改方案：**
```yaml
# 删除明文值，改为引用环境变量占位符
- JWT_SECRET_KEY=${JWT_SECRET_KEY}
- SECRET_KEY=${SECRET_KEY}
```

同步更新 `.env.example`，补充密钥生成命令提示：
```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

---

#### 1.2 修复 scheduler.py 全局变量竞态条件 🔴

**文件：** `app/scheduler.py:21-22`

**问题：** `_scheduler`、`_last_run_info` 全局变量在多请求并发时无锁保护，APScheduler 后台线程与 API 请求线程并发读写，可能导致调度器重复启动或信息读取损坏。

同步修复 `app/oracle_client.py:29`：`_oracle_pool` / `_oracle_pool_key` 同样缺少锁保护。

**修改方案：**
```python
import threading
_scheduler_lock = threading.Lock()
_info_lock = threading.Lock()

# start_scheduler / shutdown_scheduler 整体包入 with _scheduler_lock:
# _last_run_info 更新改为构建完整 dict 后原子赋值
new_info = {"run_time": ..., "query_date": ..., ...}
with _info_lock:
    _last_run_info = new_info   # 原子替换，消除中间状态

# get_last_run_info() 加锁读取
def get_last_run_info() -> dict:
    with _info_lock:
        return _last_run_info.copy()

# oracle_client.py 同理
_pool_lock = threading.Lock()
# get_oracle_connection() 的检查-赋值段包入 with _pool_lock:
```

---

#### 1.3 修复 oracle_client.py 数据库连接/游标泄漏 🔴

**文件：** `app/oracle_client.py`（`fetch_department_list`、`fetch_records`）

**问题：** 连接获取在 SQL 校验之前，若校验抛异常则连接泄漏；游标未用嵌套 `try-finally` 显式关闭。

**修改方案：**
```python
# 先校验 SQL，再获取连接；游标用嵌套 try-finally
conn = get_oracle_connection(config)
try:
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        result = [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()        # 显式关闭游标（任何路径）
    return result
finally:
    conn.close()              # 任何路径都关闭连接
```

---

#### 1.4 修复不完整事务管理（push_executor.py）🔴

**文件：** `app/services/push_executor.py:115-122`

**问题：** `db.commit()` 成功后若后续统计代码抛出异常，上层 `except` 执行 `db.rollback()`，但数据已 commit 无法撤销，造成状态与预期不符。

**修改方案：**
```python
# commit 单独包裹，与后续业务逻辑严格分离
try:
    db.commit()
except Exception as commit_error:
    logger.error("批量推送数据库提交失败: %s", commit_error, exc_info=True)
    db.rollback()
    raise
# commit 成功后，以下代码不再受事务控制
logger.info("批量推送完成: 成功=%d, 失败=%d", result.success, result.failed)
```

---

#### 1.5 修复 trigger_now daemon 线程异常静默吞没 🔴

**文件：** `app/scheduler.py:255-266`

**问题：** 线程函数 `_run()` 无任何异常捕获；推送失败时用户无感知，`last_error` 永远为空。

**修改方案：**
```python
def _run():
    try:
        _daily_push_job(...)
    except Exception as e:
        logger.error("手动触发推送线程发生未处理异常: %s", e, exc_info=True)
        with _info_lock:
            _last_run_info["last_error"] = f"trigger_thread_crash: {e}"

t = threading.Thread(target=_run, daemon=True, name=f"push-{task_id}")
```

---

#### 1.6 补齐关键操作审计日志 🟡

**文件：** `app/routers/config.py`（所有 POST 路由），`app/routers/users.py`

**问题：** Oracle 配置修改、调度器配置修改等敏感操作无操作人审计日志，不符合医疗系统合规要求。

**修改方案：** 在配置保存路由成功返回前增加 audit_logger 调用：
```python
audit_logger.info(
    "[AUDIT] 用户 %s (id=%s) 修改了 %s 配置",
    current_user.username, current_user.id, "Oracle"
)
```

---

#### 第一阶段验收标准

- `grep "SECRET_KEY=" docker-compose.yml` 无明文密钥
- 并发压测 `/api/scheduler/trigger` 10 并发，无 `dictionary changed size` 错误
- 注入 SQL 校验失败场景，Oracle 连接池 `busy` 不持续增长
- 手动触发推送失败时，`/api/scheduler/status` 返回非空 `last_error`

---

### 第二阶段：质量提升（P2）— 预计 5-8 个工作日

---

#### 2.1 统一错误响应格式

**文件：** `app/schemas.py`、`app/main.py`、所有 `app/routers/*.py`

**问题：** 不同路由混用 `MessageResponse`、`dict`、`HTTPException`，前端需要多套解析逻辑。

**修改方案：**
```python
# main.py 注册全局异常处理器
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": f"HTTP_{exc.status_code}", "message": exc.detail},
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    logger.error("未处理异常: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "服务内部错误"},
    )
```

各路由统一改为 `raise HTTPException`，不再直接 `return {"success": False, ...}`。

---

#### 2.2 修复 async/sync 混用

**文件：** `app/routers/qc_feedback.py`、`app/routers/departments.py`、`app/routers/demo.py`

**问题：** 大量路由声明为 `async def` 但无任何 `await`，同步 DB 操作直接阻塞事件循环。

**修改方案：** 无 `await` 的路由一律改为 `def`（FastAPI 自动放入线程池执行）。

---

#### 2.3 修复 qc_feedback 分页低效

**文件：** `app/routers/qc_feedback.py:254-270`

**问题：** `query.all()` 全量加载后 Python 切片，千条记录时严重低效。

**修改方案：**
```python
# 先聚合统计，再数据库级分页
total = query.count()
rows = (
    query
    .order_by(PushLog.push_time.desc())
    .offset((page - 1) * limit)
    .limit(limit)
    .all()
)
```

---

#### 2.4 补齐 exc_info=True 到所有 error 日志

**文件：** `app/notifier.py`、`app/dify_pusher.py`、`app/services/push_executor.py`

**问题：** 大量 `logger.error(f"...{e}")` 无堆栈跟踪，生产排查困难。

**修改方案：** 批量替换：
```python
# 将 f-string 改为 %s 参数，并添加 exc_info=True
logger.error("操作失败 [%s]: %s", context, e, exc_info=True)
```

---

#### 2.5 Oracle 连接池显式失效机制

**文件：** `app/oracle_client.py`、`app/routers/config.py`

**修改方案：** 新增 `reset_oracle_pool()` 函数，在配置保存路由成功后显式调用：
```python
def reset_oracle_pool():
    global _oracle_pool, _oracle_pool_key
    with _pool_lock:
        if _oracle_pool:
            try: _oracle_pool.close(force=False)
            except: _oracle_pool.close(force=True)
            finally:
                _oracle_pool = None
                _oracle_pool_key = None
```

---

#### 2.6 补齐权限检查（敏感路由）

**文件：** `app/routers/config.py`（Oracle/Dify/调度器配置修改）

确保所有配置修改路由使用 `Depends(require_permission("manage_config"))` 与现有 RBAC 机制保持一致。

---

#### 第二阶段验收标准

- 任意路由返回错误时，响应 body 均含 `code` 和 `message` 字段
- 1000 条 PushLog 下，`/api/qc/feedback/cases` 响应时间 < 500ms
- `logs/app.log` 中任意异常均包含完整堆栈跟踪

---

### 第三阶段：架构优化（P3）— 预计 8-12 个工作日

---

#### 3.1 提取 oracle/postgresql 客户端公共基类（DRY）

**文件：** 新建 `app/db_client_base.py`，改造 `oracle_client.py`、`postgresql_client.py`

**问题：** 两文件重复约 200 行代码（正则、校验函数、字段映射默认值）。

**修改方案：** 将共用逻辑迁移到 `db_client_base.py`，两个客户端改为 `from app.db_client_base import ...` 导入，分三批迁移，每批后确认无回归。

---

#### 3.2 notifier.py 改为策略模式（OCP）

**文件：** 新建 `app/notify_channels.py`，改造 `app/notifier.py`

**问题：** 新增通知渠道需修改 if/elif 主函数，违反开放封闭原则。

**修改方案：**
```python
# 每种渠道一个类，通过注册表分发
_CHANNEL_REGISTRY = {cls.channel_type: cls() for cls in [WeChatChannel, DingTalkChannel, ...]}

def send_notification(...):
    ch = _CHANNEL_REGISTRY.get(ch_type)
    if ch:
        ch.send(patient_id, result, config)
    # 未来新增渠道只需新增类，send_notification 零改动
```

---

#### 3.3 建立 pytest 测试框架

**文件：** `tests/conftest.py`（新建），`requirements.dev.txt`（新建）

最小可用测试基础设施（YAGNI），优先覆盖 P0/P1 修复对应的测试用例（至少 20 个）：
- `test_oracle_client.py`：SQL 校验防注入、连接泄漏场景
- `test_scheduler.py`：并发启动不重复、线程安全读写
- `test_push_executor.py`：commit 失败回滚行为
- `test_notifier.py`：策略模式分发逻辑（mock HTTP）
- `test_qc_feedback_api.py`：API 响应格式 + 分页正确性

---

#### 3.4 SQLite 并发安全 + Docker 安全加固

**文件：** `app/database.py`、`Dockerfile`、`docker-compose.yml`

```python
# database.py：StaticPool 改为 NullPool（配合已有 WAL 模式）
from sqlalchemy.pool import NullPool
return create_engine(url, poolclass=NullPool, connect_args={"check_same_thread": False})
```

```dockerfile
# Dockerfile：添加非 root 运行用户
RUN groupadd -r medaudit && useradd -r -g medaudit medaudit \
    && chown -R medaudit:medaudit /app
USER medaudit
```

```yaml
# docker-compose.yml：添加资源限制
deploy:
  resources:
    limits:
      memory: 1G
      cpus: '2.0'
```

---

#### 第三阶段验收标准

- `pytest tests/` 全部通过，覆盖 20+ 用例
- `oracle_client.py` 和 `postgresql_client.py` 无重复正则/函数定义
- 新增通知渠道类只需改 `notify_channels.py`，`notifier.py` 零改动
- 容器内 `whoami` 返回非 root 用户
- 10 并发 60s 压测，SQLite 模式无 `database is locked`

---

## 三、前端界面优化计划

### 前端功能模块现状

| 模块 | 页面 | 当前问题等级 |
|------|------|------------|
| 仪表盘 | 统计卡片 + ECharts 图表 | 中（图表内存泄漏） |
| 数据推送 | 手动推送 + 进度轮询 | 高（轮询无停止条件） |
| 推送日志 | 分页表格 + 详情 Modal | 中（操作列过多、分页逻辑混乱） |
| 数据统计 | 5 个图表 | 中（图表未销毁） |
| 质控反馈 | 病例表格 + 维度对照 | 中（分页低效、详情可读性差） |
| 用户/角色/权限管理 | CRUD 表格 | 高（密码修改 hardcode） |
| 配置管理 | 多表单 + JSON 预览 | 中（验证不足） |

---

### 前端 P0/P1：安全 Bug 修复

---

#### F-1.1 用户密码修改 hardcode 旧密码 🔴

**文件：** `static/scripts/app.js:1007-1017`

**问题：**
```javascript
// 当前代码：硬编码旧密码为 'admin'
const params = new URLSearchParams({ old_password: 'admin', new_password: ... });
```
管理员无需输入旧密码即可修改任意用户密码，安全风险极高。

**修改方案：**
- 用户管理修改密码 Dialog 添加"当前密码"输入框
- 密码通过 POST body 传输（不放 URL 参数）
- 后端校验旧密码是否正确

---

#### F-1.2 localStorage 存储 JWT Token 🔴

**文件：** `static/scripts/app.js:26,194`

**问题：** JWT Token 明文存储于 localStorage，可被浏览器开发者工具及 XSS 脚本窃取。

**修改方案（渐进式）：**
- 短期：在 Token 写入前验证格式（JWT 应为 `xxx.xxx.xxx`），拒绝非法格式
- 中期：迁移为内存存储（不持久化），配合 refreshToken 机制保持会话
- 长期：后端改为 HttpOnly Cookie 传递 Token

---

#### F-1.3 任务轮询无停止条件（内存泄漏）🔴

**文件：** `static/scripts/app.js:601-612`

**问题：** `setInterval` 无最大次数限制、无页面隐藏检测，长期运行导致内存泄漏。

**修改方案：**
```javascript
startTaskPolling() {
    this.stopTaskPolling();
    let count = 0;
    const MAX_POLL = 120;  // 最多轮询 120 次（6 分钟）

    this.taskPoller = setInterval(async () => {
        count++;
        await this.queryProgress();
        if (count >= MAX_POLL || this.taskDone) {
            this.stopTaskPolling();
            if (count >= MAX_POLL) ElMessage.warning("推送超时，请手动查询结果");
        }
    }, 3000);

    // 页面隐藏时停止轮询
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) this.stopTaskPolling();
    }, { once: true });
}
```

---

#### F-1.4 Chart 实例销毁不彻底 🟠

**文件：** `static/scripts/app.js:401-557`

**问题：** 页面切换时 ECharts 实例未调用 `dispose()`，快速切换会导致同一 DOM 绑定多个实例，内存持续增长。

**修改方案：**
```javascript
// 在 data() 中记录实例引用
chartInstances: {},

// 渲染前先销毁旧实例
renderChart(elId, option) {
    const el = document.getElementById(elId);
    if (!el) return;
    if (this.chartInstances[elId]) {
        this.chartInstances[elId].dispose();
    }
    const chart = echarts.init(el);
    chart.setOption(option);
    this.chartInstances[elId] = chart;
},

// beforeUnmount 统一销毁
beforeUnmount() {
    Object.values(this.chartInstances).forEach(c => c.dispose());
    this.chartInstances = {};
    this.stopTaskPolling();
    clearInterval(this.clockTimer);
}
```

---

#### F-1.5 Axios 拦截器未处理网络错误 🟠

**文件：** `static/scripts/app.js:165-175`

**问题：** 只处理 401，未处理 CORS 错误（`error.response` 为 undefined）、超时、5xx 服务器错误。

**修改方案：**
```javascript
axios.interceptors.response.use(
    (response) => response,
    (error) => {
        if (!error.response) {
            // 网络错误或 CORS 错误
            ElMessage.error("网络连接失败，请检查服务是否可达");
        } else if (error.response.status === 401) {
            this.clearAuthState();
        } else if (error.response.status >= 500) {
            ElMessage.error("服务器内部错误，请联系管理员");
        }
        return Promise.reject(error);
    }
);
```

---

### 前端 P2：交互体验改进

---

#### F-2.1 推送日志详情 Modal 添加前后翻页

**文件：** `static/index.html:263-301`、`static/scripts/app.js`

**问题：** 查看日志详情必须关闭 Modal → 点击下一行 → 再次打开，审查多条失败日志时操作繁琐。

**修改方案：** 在 Modal footer 左侧添加翻页按钮：
```html
<template #footer>
    <div style="display:flex;justify-content:space-between;align-items:center">
        <div>
            <el-button @click="prevLogDetail" :disabled="!hasPrevLog">← 上一条</el-button>
            <span style="margin:0 12px">{{ currentLogIndex + 1 }} / {{ logsList.length }}</span>
            <el-button @click="nextLogDetail" :disabled="!hasNextLog">下一条 →</el-button>
        </div>
        <el-button @click="logDetailVisible = false">关闭</el-button>
    </div>
</template>
```

---

#### F-2.2 数据源切换添加确认对话框

**文件：** `static/scripts/app.js:370-384`

**问题：** 点击 Radio 切换数据源立即触发保存，无确认步骤，容易误操作。

**修改方案：**
```javascript
async onDataSourceChange(newType) {
    try {
        await ElMessageBox.confirm(
            `确认将数据源切换为 ${newType === 'oracle' ? 'Oracle' : 'PostgreSQL'}？`,
            '切换数据源',
            { confirmButtonText: '确认切换', cancelButtonText: '取消', type: 'warning' }
        );
        await this.saveDataSource(newType);
        ElMessage.success('数据源切换成功');
    } catch {
        // 用户取消，恢复原值
        this.currentDataSource = this.originalDataSource;
    }
}
```

---

#### F-2.3 表格筛选变化时自动重置分页

**文件：** `static/scripts/app.js:614-625`

**问题：** 筛选条件变化时不重置分页，导致用户在第 3 页筛选后看不到结果（结果在第 1 页）。

**修改方案：** 所有筛选触发函数统一调用 `loadLogs(1)`（重置到第 1 页）：
```javascript
onFilterChange() {
    this.logsFilter.page = 1;   // 重置分页
    this.loadLogs();
}
```

---

#### F-2.4 质控反馈维度对照表文本截断展开

**文件：** `static/index.html:473-486`

**问题：** 病程记录和护理记录原文可能超过 500 字，表格行高撑开，不可读。

**修改方案：**
```html
<el-table-column label="病程记录内容">
    <template #default="{ row }">
        <div class="text-ellipsis" :title="row.mr_content">
            {{ row.mr_content.slice(0, 60) }}...
            <el-button link @click="showFullText(row.mr_content)">展开</el-button>
        </div>
    </template>
</el-table-column>
```

同时新增纯文本展示 Dialog，避免 Modal 嵌套过深。

---

#### F-2.5 表格操作列合并为"更多"菜单

**文件：** `static/index.html:238-247`

**问题：** 推送日志操作列有 4 个按钮（详情、重推、报告、打印），1600px 以下屏幕触发水平滚动。

**修改方案：** 只展示主操作"详情"，其余收进 Dropdown：
```html
<el-button size="small" @click="viewLogDetail(row)">详情</el-button>
<el-dropdown size="small" @command="handleLogAction($event, row)">
    <el-button size="small">更多 <el-icon><ArrowDown /></el-icon></el-button>
    <template #dropdown>
        <el-dropdown-item command="retry">重推</el-dropdown-item>
        <el-dropdown-item command="report">查看报告</el-dropdown-item>
        <el-dropdown-item command="print">打印</el-dropdown-item>
    </template>
</el-dropdown>
```

---

#### F-2.6 Modal 宽度统一适配

**文件：** `static/index.html:263,447`

**问题：** 反馈详情 Modal 固定宽度 1100px，在小屏幕被截断；JSON 代码块无水平滚动。

**修改方案：**
```html
<!-- 统一改为响应式最大宽度 -->
<el-dialog width="min(92vw, 1100px)" ...>
```

```css
/* JSON 预览区 */
.json-preview {
    overflow-x: auto;
    max-height: 50vh;
    font-size: 12px;
}
```

---

#### F-2.7 表单验证补齐

**文件：** `static/scripts/app.js:970-978` 及各 CRUD 表单

**问题：** 邮箱格式未验证；Oracle/PostgreSQL 端口字段可输入非数字；JSON 配置字段无实时验证。

**修改方案：**
```javascript
// 添加规则
emailRules: [
    { type: 'email', message: '请输入有效邮箱', trigger: 'blur' }
],
portRules: [
    { type: 'number', min: 1, max: 65535, message: '端口号范围 1-65535', trigger: 'blur' }
],
// JSON 字段实时验证
validateJson(rule, value, cb) {
    try { JSON.parse(value); cb(); }
    catch(e) { cb(new Error('JSON 格式错误: ' + e.message)); }
}
```

---

#### F-2.8 筛选/批量操作后主动刷新表格

**文件：** `static/scripts/app.js`（批量重推、批量确认等操作）

**问题：** 批量操作后不自动刷新，用户仍看到旧状态，需要手动刷新。

**修改方案：** 批量操作成功后调用刷新：
```javascript
async batchRetry() {
    await axios.post('/api/logs/batch-retry', { ids: this.selectedLogs });
    ElMessage.success(`已提交 ${this.selectedLogs.length} 条重推任务`);
    this.selectedLogs = [];
    await this.loadLogs();   // 主动刷新
}
```

---

#### F-2.9 Dialog 关闭后清理数据（防止旧数据闪现）

**文件：** `static/scripts/app.js`（所有 closeDialog 方法）

**问题：** Modal 关闭后相关 data 变量未清空，再次打开时会短暂显示旧数据。

**修改方案：**
```javascript
closeLogDetail() {
    this.logDetailVisible = false;
    this.$nextTick(() => {
        this.logDetail = null;
    });
}
```

---

#### F-2.10 全局 API 错误处理一致性

**文件：** `static/scripts/app.js`（所有 catch 块）

**问题：** 部分 catch 只打印 `console.error(e)`，无用户提示；错误消息格式不统一。

**修改方案：** 提取公用错误处理方法：
```javascript
showApiError(e, fallback = '操作失败') {
    const msg = e?.response?.data?.message || e?.message || fallback;
    ElMessage.error(msg);
    console.error(e);
}
// 所有 catch 块统一调用：
} catch (e) {
    this.showApiError(e, '加载数据失败');
}
```

---

### 前端 P3：响应式与可访问性改进

---

#### F-3.1 移动端导航菜单不可用（< 900px）

**文件：** `static/app.css:121-122`

**问题：** 900px 以下将侧边栏高度限制为 280px，15+ 个菜单项无法全部显示。

**修改方案：** 改为 Element Plus Drawer 抽屉式导航，通过汉堡菜单按钮触发，支持滚动。

---

#### F-3.2 表格缺少水平滚动容器

**文件：** `static/app.css`（表格容器）

**修改方案：**
```css
.table-container {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
}
```

---

#### F-3.3 补充 900px ~ 1200px 中间响应式断点

**文件：** `static/app.css`

当前只有 `@media (max-width: 1100px)` 和 `@media (max-width: 900px)` 两个断点，中间段（1000-1100px）显示混乱。

**修改方案：** 补充 `@media (max-width: 1200px)` 断点，统计卡片从 4 列改为 2 列。

---

#### F-3.4 搜索输入框添加防抖

**文件：** `static/scripts/app.js`（表格筛选输入框）

**修改方案：**
```javascript
// 简单防抖实现
debounce(fn, delay = 500) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
},
// 使用
onSearchInput: debounce(function() { this.loadLogs(1); }, 500)
```

---

#### F-3.5 为关键按钮补充 aria-label

**文件：** `static/index.html`（所有图标按钮）

**修改方案：** 为只含图标的按钮添加语义标签：
```html
<!-- 删除按钮示例 -->
<el-button aria-label="删除用户" @click="deleteUser(row)">
    <el-icon><Delete /></el-icon>
</el-button>
```

---

## 四、关键文件改造清单

### 后端文件

| 文件 | 风险评分 | 改造阶段 | 主要问题 |
|------|---------|---------|---------|
| `docker-compose.yml` | 🔴 9/10 | 第一阶段 | 明文密钥 |
| `app/scheduler.py` | 🔴 9/10 | 第一阶段 | 竞态条件、线程安全 |
| `app/oracle_client.py` | 🔴 8/10 | 第一+三阶段 | 连接泄漏、重复代码 |
| `app/services/push_executor.py` | 🔴 8/10 | 第一+二阶段 | 事务管理不完整 |
| `app/routers/qc_feedback.py` | 🟠 7/10 | 第二阶段 | 分页低效、async混用 |
| `app/notifier.py` | 🟠 7/10 | 第一+三阶段 | 审计日志缺失、OCP违反 |
| `app/database.py` | 🟡 6/10 | 第三阶段 | StaticPool并发风险 |
| `app/routers/config.py` | 🟡 6/10 | 第一+二阶段 | 权限检查不一致 |
| `app/main.py` | 🟡 5/10 | 第二阶段 | 缺全局异常处理器 |
| `Dockerfile` | 🟢 4/10 | 第三阶段 | root运行 |

### 前端文件

| 文件 | 风险评分 | 改造阶段 | 主要问题 |
|------|---------|---------|---------|
| `static/scripts/app.js` | 🔴 8/10 | F-1+F-2 | 密码hardcode、内存泄漏 |
| `static/index.html` | 🟠 6/10 | F-2 | Modal宽度、操作列拥挤 |
| `static/app.css` | 🟡 5/10 | F-3 | 响应式断点缺失 |

---

## 五、执行路线图

```
第 1 周    第 2 周    第 3 周    第 4 周    第 5-8 周
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────┐
│后端 P0/P1│ │前端 P0/P1│ │后端 P2  │ │前端 P2  │ │后端/前端 P3 │
│1.1~1.6  │ │F1.1~F1.5│ │2.1~2.6  │ │F2.1~F2.8│ │3.1~3.4      │
│密钥安全 │ │密码安全 │ │错误格式 │ │交互优化 │ │架构重构     │
│并发修复 │ │内存泄漏 │ │分页优化 │ │表单验证 │ │测试框架     │
│连接泄漏 │ │图表销毁 │ │审计日志 │ │Modal优化│ │响应式完善   │
└─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────────┘
  打 tag:      打 tag:
  v1.1-sec     frontend-fix-1
```

---

## 六、分支策略

| 分支名 | 对应内容 | 合并时机 |
|--------|---------|---------|
| `fix/backend-p0-secrets` | 1.1 密钥移除 | 立即 |
| `fix/backend-p0-thread-safety` | 1.2 线程安全 | 压测通过后 |
| `fix/backend-p0-conn-leak` | 1.3 连接泄漏 | 单元测试通过后 |
| `fix/frontend-p0-password` | F-1.1 密码修改 | 前后端联调后 |
| `fix/frontend-p0-polling` | F-1.3 轮询修复 | 功能验证后 |
| `feat/backend-error-format` | 2.1 统一错误格式 | 前端适配后 |
| `feat/frontend-ux-improve` | F-2.x 批量 UX 改进 | 测试通过后 |
| `refactor/backend-arch` | 3.x 架构优化 | 第三阶段 |

---

## 七、总体质量评分

| 维度 | 当前 | 目标（P1完成）| 目标（全部完成）|
|------|-----|-------------|----------------|
| 安全性 | 5/10 | 8/10 | 9/10 |
| 稳定性 | 6/10 | 8/10 | 9/10 |
| 性能 | 6/10 | 7/10 | 9/10 |
| 可维护性 | 6/10 | 7/10 | 9/10 |
| 用户体验 | 6/10 | 7/10 | 9/10 |
| 可访问性 | 3/10 | 4/10 | 7/10 |
| **综合** | **5.3/10** | **7.5/10** | **8.7/10** |

---

*本文档由 Claude AI 自动生成，基于完整的代码静态分析。所有改动建议均基于 SOLID、DRY、KISS、YAGNI 原则，优先保障医疗系统的稳定性和数据一致性。*
