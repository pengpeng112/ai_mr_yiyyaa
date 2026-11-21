# 自动调度 Dify 多节点配置与可靠性加固开发计划

> 状态：本地开发已完成（A–G），待测试回归确认与生产部署书面批准  
> 日期：2026-07-16  
> 目标：让日常增量和出院终末自动任务使用与手动推送一致的 Dify 多节点负载分配，并在“系统配置 → Dify 配置”中完成统一维护。  
> 语义冻结：多节点是“每个患者选择一个节点”的负载均衡，不是将同一患者 fan-out 到全部节点。  
> 实施说明：核心 Bulk 能力沿用既有 `BulkPushExecutor`；本轮补齐策略/熔断持久化、统一 `resolve_dify_target_pool`、系统配置 UI、同源手动页与调度接线。

## 1. 用户目标

1. 在系统配置的 Dify 页面维护一个或多个 Dify 节点。
2. 手动推送、日常自动推送、出院终末自动推送读取同一套持久化节点。
3. 支持节点启停、名称、Base URL、API Key、超时和权重。
4. 支持 `round_robin` 与 `weighted_random` 两种策略。
5. 单节点或没有 targets 时保持原有行为，不影响现有任务。
6. 节点故障时有限熔断并选择其他节点，不因一个节点故障导致整类漏跑。
7. 不改变六类 audit type code、Dify 输入输出契约、高危临床门槛和告警规则。

## 2. 当前代码事实

### 2.1 已经存在的能力

当前不是“自动任务完全不支持多节点”。以下能力已经存在：

- `app/routers/config.py`
  - `GET /api/config/dify/targets`：读取持久化目标并脱敏密钥。
  - `POST /api/config/dify/targets`：保存最多 10 个目标，密钥加密存储。
- `app/services/config_parser.py::parse_persisted_dify_targets()`
  - 从全局 `config.dify.targets` 读取启用节点。
  - 解密 `api_key_enc`，过滤无地址、无有效 Key 和已停用节点。
- `app/services/scheduler_audit_runner.py::run_daily_push_for_audit_type()`
  - daily_increment 和 discharge_final 都会读取持久化 targets。
  - targets 非空时已经使用 `BulkPushExecutor`。
- `app/scheduler.py` 旧兼容调度路径也存在同类判断。
- `app/services/bulk_push_executor.py`
  - 支持多个目标、权重、轮询/加权随机、节点指标和进程内熔断。
  - 每名患者只选择一个节点，不 fan-out。
- `static/templates/pages/push.html`
  - “手动推送 → Dify 节点配置”已经提供新增、复制、删除、启停、权重、地址、Key、超时和保存。

### 2.2 当前缺口

1. “系统配置 → Dify 配置”只显示单一 Base URL/Key，没有多节点可视化编辑器。
2. 自动任务虽读取 targets，但策略没有从持久化配置显式解析，通常落到 `BulkPushExecutor` 默认 `round_robin`。
3. 手动页面与系统配置页面可能形成两个维护入口，缺少明确的同源提示和刷新规则。
4. 自动任务没有在 SchedulerHistory/UI 中展示目标选择、成功、失败、空输出和熔断统计。
5. 全局 targets 会覆盖 Dify 端点和密钥，但输入变量、输出变量、`mr_type` 仍来自审计类型配置；该合并规则缺少页面说明和契约测试。
6. 未证明 daily/discharge、legacy/multi-source 四条自动路径都使用同一策略配置。
7. 多节点全部失效时的回退语义尚未明确展示：应整类失败，还是回退单节点。
8. 当前 ACTIVE/002 幂等 execution/attempt 尚未完成，多节点网络重试与业务幂等仍需保持边界。

## 3. 本计划冻结的行为语义

### 3.1 节点选择

- `round_robin`：按权重构造轮询环。
- `weighted_random`：按权重随机选择。
- 每个患者每次业务 attempt 只调用一个节点。
- 禁止把同一患者并行发送给所有节点后择优，避免重复费用、重复落库和临床结果竞争。

### 3.2 配置优先级

对某个 audit type：

```text
审计类型 Dify 配置
  提供 workflow_input_variable、workflow_output_key、extra_inputs/mr_type、response_paths 基础
      +
全局启用 target
  只覆盖 name、base_url、api_key、timeout_seconds、weight
      =
本次实际 Dify 调用配置
```

不得让 target 覆盖：

- `workflow_input_variable`
- `workflow_output_key`
- `extra_inputs.mr_type`
- audit type code
- response paths
- 高危规则

### 3.3 空配置与故障

| 场景 | 行为 |
| --- | --- |
| `targets=[]` | 使用当前审计类型专属 Dify；不存在时回退全局单节点 |
| 仅一个 enabled target | 使用该 target；行为等价单节点 |
| 多个 enabled target | 按持久化策略分配 |
| 某节点达到熔断阈值 | 冷却期内选择其他可用节点 |
| 所有节点均冷却 | v1 保持现有逻辑，从节点池继续选择并记录 degraded；不得静默回退另一套未声明 Key |
| target 空输出 | 按现有有限 empty retry；不得形成 high |
| parse failed/fallback | 不落维度、不 supersede、不 relay enqueue、不通知 |

### 3.4 业务重试与节点切换

- 同一次业务调用内部的网络重试可以切换到其他节点，但不得创建第二份业务结果。
- ACTIVE/002 完成前，不新增 execution/attempt ORM，也不宣称跨进程 exactly-once。
- 已成功、未复核或同版本已复核的跳过规则保持不变。
- daily 和 discharge 是两个合法运行模式；discharge 可用终末结果才 supersede daily。

## 4. 配置结构设计

不新增数据库表，不修改 ORM。继续使用 `config/config.json`：

```json
{
  "dify": {
    "base_url": "http://default-dify/v1",
    "api_key_enc": "...",
    "workflow_input_variable": "mr_txt",
    "workflow_output_key": "aa",
    "target_strategy": "round_robin",
    "circuit_breaker_failures": 3,
    "circuit_breaker_seconds": 60,
    "targets": [
      {
        "name": "dify-a",
        "base_url": "http://dify-a/v1",
        "api_key_enc": "...",
        "timeout_seconds": 90,
        "weight": 1,
        "enabled": true
      }
    ]
  }
}
```

规则：

- `target_strategy`：`round_robin | weighted_random`，默认 `round_robin`。
- `circuit_breaker_failures`：1–20，默认沿用执行器当前值。
- `circuit_breaker_seconds`：1–3600。
- targets 最多 10 个。
- target name 非空且唯一。
- Base URL 规范化为 API base，禁止用户存完整 `/workflows/run`。
- 新 Key 非空才覆盖原 `api_key_enc`；留空保留旧 Key。
- API 响应只返回 `api_key_masked/has_api_key`，不得返回明文或 `api_key_enc`。
- 多个节点允许同主机但不同 Workflow Key；重复 `(base_url, key identity)` 应拒绝或明确警告。不得通过返回密钥进行前端去重。

## 5. 页面设计

### 5.1 主入口

入口固定为：

```text
系统配置 → Dify 配置
```

在现有单节点表单下新增“Dify 多节点池”区域：

- 启用多节点开关：可不新增独立布尔值，以 enabled targets 数量作为是否启用的事实源。
- 分配策略：轮询 / 加权随机。
- 熔断失败阈值。
- 熔断冷却秒数。
- 节点卡片：名称、启用、权重、Base URL、新 API Key、当前 Key 状态、超时。
- 新增、复制、删除、保存节点。
- “从默认节点创建”按钮。
- “重新载入”按钮。
- 只读提示：自动日常、自动出院和手动批量共同使用本节点池。

### 5.2 手动推送页面

保留 `手动推送 → Dify 节点配置`，但调整为：

- 默认展示系统持久化节点的只读摘要或编辑同一数据源。
- 明确“保存配置”写入的是系统全局 `dify.targets`。
- 临时任务自定义 targets 仍可保留，但必须明确“仅本次任务”与“保存为系统节点池”的差异。
- 两个页面保存后应刷新同一个 `/api/config/dify/targets` 结果，不能形成两份配置。

### 5.3 自动任务页面

调度页面增加只读信息：

- 当前 enabled target 数。
- 当前策略。
- 是否使用单节点回退。
- 最近一次每个节点 selected/success/failed/empty。
- 若统计仅存在内存/日志，页面必须标记“本进程最近运行”，不得伪装成持久历史。

## 6. 后端开发工作包

### 工作包 A：现状锁定与失败测试

修改前先补测试，禁止直接改执行器：

1. `scheduler_audit_runner` 在 targets 非空时构造 `BulkPushExecutor`。
2. daily_increment legacy 路径覆盖。
3. daily_increment multi-source 路径覆盖。
4. discharge_final multi-source 路径覆盖。
5. targets 为空时仍使用 `PushExecutor`。
6. target 只覆盖端点字段，不覆盖 `mr_type/input/output`。
7. 同一患者只调用一个 target。

交付后停止复核，证明现有能力和真实缺口。

### 工作包 B：配置 schema 与 API

涉及：

- `app/schemas.py`
- `app/routers/config.py`
- `app/services/config_parser.py`
- `app/config.py`
- `config/config.json.template`

步骤：

1. 新增多节点池运行参数 schema，或扩展现有 Dify response/save schema。
2. `GET /api/config/dify` 返回脱敏的策略摘要和 targets 摘要，或继续由 `/dify/targets` 独立返回；必须选定唯一写入口。
3. 扩展 `/api/config/dify/targets` 保存策略、熔断参数和节点列表。
4. 保持现有单节点 `POST /api/config/dify` 保存时不覆盖 `targets` 和多节点策略。
5. 验证 name 唯一、数值范围、URL、最多 10 个、密钥留空保留。
6. 保存前创建配置备份；失败不得留下半套配置。
7. 审计日志只记用户名、节点数、节点名、脱敏 host、策略，不记录 Key。

停止点：API 测试全部通过后再进入页面开发。

### 工作包 C：统一运行配置解析

新增或扩展共享解析函数，建议集中在 `ConfigParser`：

```python
resolve_dify_target_pool(config, audit_type) -> {
    "base_config": {...},
    "targets": [...],
    "strategy": "round_robin",
    "circuit_breaker_failures": 3,
    "circuit_breaker_seconds": 60
}
```

要求：

- serial、bulk、scheduler、manual 使用同一字段合并函数。
- 不在 `scheduler.py`、router 和 executor 各复制一套解密/覆盖逻辑。
- 输入输出变量和 `mr_type` 来自 audit type/base config。
- target 只覆盖允许字段。
- 返回对象不得写回原 config，避免不同审计类型互相污染。

### 工作包 D：自动调度接线加固

涉及：

- `app/services/scheduler_audit_runner.py`
- `app/scheduler.py` 中仍活跃的兼容路径
- `app/services/bulk_push_executor.py`

步骤：

1. 使用统一 resolver 代替两处手写 `parse_persisted_dify_targets()` 分支。
2. 向 `BulkPushExecutor` 传入持久化 `target_strategy`。
3. 传入熔断阈值和冷却时间。
4. daily/discharge、legacy/multi-source 四条路径行为一致。
5. 保持 app DB 并发限制：SQLite 自动降并发，Oracle 按现有 `effective_parallel_workers()`。
6. 不改变调度锁名称；daily_push 与 discharge_push 继续使用不同锁。
7. 不改变任务候选、跳过、落库、告警和 supersede 语义。
8. 所有节点无效时在 SchedulerHistory 写类型级失败，错误码建议 `dify_target_pool_unavailable`，不得显示 completed/0。

### 工作包 E：系统配置页面

涉及：

- `static/templates/pages/config.html`
- `static/scripts/modules/config.js`
- 必要的现有样式文件

步骤：

1. 在 Dify 配置页加入节点池编辑器。
2. 页面初始化同时加载单节点与 targets。
3. Key 输入留空保留；显示“已配置/未配置”，不回显密文。
4. 实时校验节点名、URL、权重、超时和重复节点。
5. 单节点保存与 targets 保存分开按钮，避免修改 Base URL 时意外覆盖节点池。
6. 保存成功后重新 GET，确保页面显示服务端真实状态。
7. 增加醒目说明：节点池同时影响自动和手动推送。

### 工作包 F：手动推送页面同源化

涉及：

- `static/templates/pages/push.html`
- `static/scripts/modules/push.js`

步骤：

1. 明确系统持久节点与本次临时节点的状态。
2. “载入已保存”始终读取 `/api/config/dify/targets`。
3. “保存配置”与系统配置页面使用同一 API 和校验。
4. 临时 targets 不自动写回系统配置。
5. 手动任务继续允许请求体传临时 targets，但不得把明文 Key写入日志或 PushLog。

### 工作包 G：可观测性

最小方案不做 ORM 迁移：

- SchedulerHistory 保持现有总数。
- target metrics 写结构化脱敏日志。
- 调度运行汇总 API 可从当次执行结果返回 target_metrics。
- 页面展示仅标记为“最近一次/当前进程”。

如需持久化每次 target attempt，必须依赖 ACTIVE/002 的 attempt 表设计，另行书面批准；本计划不得私自新增表或字段。

## 7. 测试要求

### 7.1 配置与安全

- 保存 0、1、2、10 个节点成功。
- 11 个节点、重复名称、空地址、非法 URL、权重越界、超时越界拒绝。
- API Key 留空保留旧密钥。
- 删除节点不影响全局默认 Dify。
- GET 不返回明文 Key 或 `api_key_enc`。
- 日志、异常和审计记录不包含 Key。
- 普通用户不能读写配置，管理员可以。

### 7.2 节点分配

- 两个权重相同节点 round-robin 分配稳定。
- 权重 2:1 的轮询环符合预期。
- weighted_random 使用固定随机种子验证分布边界，不断言精确序列。
- 单患者只调用一个节点。
- 不同患者可以分配到不同节点。
- 节点达到失败阈值后冷却，其他节点接管。
- 成功后失败计数清零。
- 空输出不记为临床成功，不产生 high。

### 7.3 自动任务矩阵

| 模式 | 数据路径 | targets | 预期 |
| --- | --- | --- | --- |
| daily | legacy | 0 | PushExecutor 单节点 |
| daily | legacy | 2 | BulkPushExecutor 多节点 |
| daily | multi-source | 0 | PushExecutor 单节点 |
| daily | multi-source | 2 | BulkPushExecutor 多节点 |
| discharge | multi-source | 0 | PushExecutor 单节点 |
| discharge | multi-source | 2 | BulkPushExecutor 多节点 |

六类均验证：

- `mr_txt` 为字符串。
- `mr_type` 正确。
- output key 为配置的 `aa/hcjg`。
- audit_type_code 正确传入 parser。
- parse failed 不落维度、不告警、不 supersede。

### 7.4 回归

至少运行：

```bash
python -m compileall -q app tests scripts
python -m pytest tests/test_bulk_push_executor.py -q
python -m pytest tests/test_push_executor.py -q
python -m pytest tests/test_scheduler.py -q
python -m pytest tests/test_scheduler_safety.py -q
python -m pytest tests/test_runtime_config_resolver.py -q
python -m pytest tests/test_config_frontend_static.py -q
python -m pytest tests/test_push_router_bulk_options.py -q
python scripts/check_naming_convention.py
```

随后运行全量 `python -m pytest`。测试失败不得删测试、放宽断言、添加无条件 skip 或吞异常。

## 8. 发布步骤

1. 备份服务器 `config/config.json`、`.env` 和当前镜像 ID。
2. 本地完成 A–G 自动化测试和页面静态检查。
3. 新镜像部署后保持 scheduler disabled，验证配置读取、保存、脱敏和单节点测试。
4. 使用两个 mock Dify 服务验证轮询、权重、故障和熔断；不得使用真实患者或企业微信。
5. 启用 scheduler 前确认 daily/discharge 单 worker、锁和 002 当前状态。
6. 第一阶段只启用一个 target，观察一个自动周期。
7. 第二阶段启用第二 target，先 daily_increment，再 discharge_final。
8. 每阶段对账候选、transport、parse、qc_usable、high、alert 状态。
9. 真实 high 告警仍受现有科室白名单和临床门槛控制，不因多节点发布扩大科室。

## 9. 回滚

配置级快速回滚：

1. 停用或清空 `dify.targets`。
2. 自动和手动路径立即回到审计类型/全局单节点。
3. 保留历史 PushLog 和目标指标，不删除业务记录。

代码级回滚：

- 恢复上一镜像和备份配置。
- 禁止更换 `SECRET_KEY`，否则现有加密 Key 无法解密。
- 不回滚或删除已产生的成功质控结果。

## 10. 停止点

每个工作包完成后提交：

- 修改文件清单。
- 行为契约前后对比。
- 完整测试命令和结果。
- 未完成事项和风险。
- 未改六类 code、Dify JSON、高危门槛、告警规则的证明。

以下操作必须另行书面批准：

- 生产部署和启用第二节点。
- 真实自动任务或补跑。
- 真实 Dify 患者数据、企业微信或 H5 测试。
- 新增 ORM/迁移/attempt 表。
- fan-out 同一患者到多个模型并自动择优。

## 11. 验收标准

1. 系统配置 Dify 页面能完整维护节点池，Key 不回显。
2. 手动和自动读取同一持久化节点池。
3. daily/discharge 的 legacy/multi-source 路径均按配置策略分配。
4. 0/1 节点时原有功能不回退。
5. 单节点故障不会导致其他健康节点停止工作。
6. 全节点失效形成明确类型级 failed，不出现 completed/0 假成功。
7. 不重复调用同一患者、不重复落库、不扩大告警。
8. 六类输入、输出、parser 和高危门槛全部保持兼容。
9. 全量测试通过，并完成 mock 双节点自动周期演练。
10. 生产启用须完成一个 daily 和一个 discharge 完整周期的只读对账。

## 12. 当前裁定

自动调度多节点的核心执行能力已经存在，本次开发应以“系统配置可视化、策略持久化、统一 resolver、失败状态和测试闭环”为主，不应重写 BulkPushExecutor 或建立第二套节点配置。计划复核通过前不得直接实施；尤其不得把多节点误实现为同一患者 fan-out。
