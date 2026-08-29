# 归档前病历预检服务（prearchive_service）

> 028 一期原型（`docs/ACTIVE/028_PREARCHIVE_CHECK_AND_JHEMR_REMINDER_EXECUTION_PLAN_20260827.md` P1 全量 + P2 外挂助手骨架）。
> **本地原型，零生产依赖**：全部测试用 fixture 假源驱动，不连接任何真实库/IP，不执行 DDL，不发真实推送。

## 1. 隔离边界（028 §2，违反即返工）

- 全部代码在本目录；**禁止 `import app.*`**（自动检查：`python check_isolation.py`，CI 依赖其退出码）；
- 独立 `requirements.txt`（**pyodbc 只出现在这里**）；不修改主服务任何文件；
- 凭据 Fernet 加密独立实现，**不共享主服务 SECRET_KEY**（密钥经环境变量 `PREARCHIVE_SECRET_KEY` 注入）；
- 结果表 `MED_PREARCHIVE_RESULT` 独立；Oracle DDL 在 `sql/` 随码交付、**手工执行**（服务启动零 DDL）；
- HMAC 推送协议与 relay 一致（独立实现 + `tests/contract_vectors.json` 契约向量；协议变更必须双改）。

## 2. 目录结构

```text
prearchive_service/
├─ prearchive/                 # Python 包
│  ├─ config.py                # JSON 配置 + Fernet 加解密（genkey/encrypt CLI）
│  ├─ context.py               # 归一化数据结构（PatientContext/DocumentEntry/…）
│  ├─ collectors.py            # 四源网关抽象 + 真实 SQL 网关（惰性建连）+ 适配器
│  ├─ fixture_sources.py       # fixture 假源（字段名与真实一致，虚构 TEST 患者）
│  ├─ rules.py                 # 规则 DSL 加载/校验（028 §3.2 v2 完整字段）
│  ├─ engine.py                # 四类判定器 + 治理门（科室/豁免/时间窗/源水位）
│  ├─ models.py / store.py     # PrearchiveResult（检查键三列联合/current 标记/双通道状态）
│  ├─ trigger.py               # 轮询（水位持久化/防重入锁/检查键去重/复检发现）
│  ├─ signing.py               # HMAC-SHA256（relay 协议独立实现）
│  ├─ receivers.py             # 接收人解析：完成医生优先/管床兜底（映射可注入）
│  ├─ pusher.py                # 企微推送：单患者合并一条/严重度阈值/通道去重
│  ├─ heartbeat.py             # 自监控心跳文件（R13）
│  └─ api.py                   # GET /healthz + GET /api/precheck/{pid}/{vid}（A19 鉴权）
├─ rules/example_rules.json    # 示例规则 7 条（mark_item_fid 全部待质控科签字版回填）
├─ sql/create_prearchive_result_oracle.sql   # Oracle DDL（手工执行，不自动跑）
├─ reminder_agent/             # C# 外挂托盘助手骨架（4.1 首选方案，fail-open）
├─ tests/                      # 105 项单测 + 契约向量 + e2e
├─ check_isolation.py          # 隔离红线检查（import app.* 零命中 + 助手禁词）
├─ run_service.py              # 入口（--fixtures 演示 / --once 冒烟 / 常驻 API）
├─ config.example.json         # 配置模板（全部占位符，无任何真实凭据）
└─ requirements.txt
```

## 3. 快速开始（fixture 演示，零依赖真实库）

```bash
cd prearchive_service
python -m pytest tests -q              # 全部测试（fixture 驱动）
python check_isolation.py              # 隔离检查
python run_service.py --fixtures --once   # 冒烟一轮：3 个虚构患者 → 判定 → 存储 → 推送(mock)
python run_service.py --fixtures          # 常驻：轮询线程 + API(http://127.0.0.1:8600/docs)
```

演示数据（`fixture_sources.build_demo_fixtures`，全部虚构 TEST 患者）：

| 患者 | 场景 |
|---|---|
| TEST0001 张某 | 手术缺核查表/护理单 + 缺术前小结/术前讨论/术后首次病程；首页源不可用 → 首页族整族跳过 |
| TEST0002 李某 | 入院记录超 24h + 首页过敏空 + 诊断重复（全角序号）+ 检验报告缺血常规/生化 |
| TEST0003 王某 | 全负例（文书齐全，过敏=「无」合法） |

## 4. 真实部署（P0 完成后）

1. `pip install -r requirements.txt`（目标机 Python 3.11+；Linux 容器装 LIS 驱动注意 unixODBC + MS ODBC Driver，028 R11）；
2. 生成密钥与加密凭据：
   ```bash
   python -m prearchive.config genkey                        # → PREARCHIVE_SECRET_KEY 环境变量
   python -m prearchive.config encrypt <key> '<明文口令>'     # → enc:v1:... 填入 config.json
   ```
3. `cp config.example.json config.json`，回填四源连接（占位符替换）、push、api.shared_token；
4. Oracle 应用库**手工**执行 `sql/create_prearchive_result_oracle.sql`（023 §9.1 批准单流程）；
5. `python run_service.py --config config.json`；
6. 接入方（relay）验签协议见 `tests/contract_vectors.json`。

## 5. API（只读两个）

- `GET /healthz` —— 心跳/水位/锁状态（心跳超时=degraded，外部可探测停跳，R13）；
- `GET /api/precheck/{patient_id}/{visit_id}?doctor_id=&dept_code=` —— 最新（current）问题清单；
  鉴权：header `X-Precheck-Token`（=配置 `api.shared_token`）+ 工号/科室必填 + 患者归属科室校验
  （`require_dept_binding`，A19 最小实现：401/400/403/404 语义见 `tests/test_pa_api.py`）。

## 6. 外挂提醒助手（C# 骨架）

```bat
cd reminder_agent
build.bat                 :: csc.exe 编译 → ReminderAgent.exe
copy agent_config.example.json agent_config.json   :: 回填服务地址/token/工号/科室
ReminderAgent.exe
```

- 行为：托盘常驻 → 定时轮询（EMR 窗口标题解析当前患者，正则可配；联调可用 `watchlist` 兜底）
  → 检出问题弹**非模态置顶窗**（owner=EMR 主窗口句柄，找不到则退化普通置顶窗）→ 已知晓/去整改；
- fail-open 铁律：全域 try-catch，服务不可达/超时/异常数据一律降级为托盘图标状态；
  夜间静默时段（`quiet_hours`）不弹窗（R16）；同一 result_id 处理后不再打扰；
- 骨架不含 AppDomainManager/IL 注入（4.2/4.3 不在一期范围，`check_isolation.py` 含禁词检查）。

## 7. 与 P0/P2 的衔接点（待回填清单）

| 项 | 位置 | 等什么 |
|---|---|---|
| `mark_item_fid`（92 条评分项映射） | `rules/example_rules.json` | **质控科签字版**（P0-4 关键闸门，签字前不得编写正式规则） |
| HIS REPORTNAME 数字编码字典 | 规则 `trigger.evidence.report_codes`（现占位 `["1"]`） | P0-3① 实测 |
| v_blws 时间列/progress_status 值域 | `collectors.py` `SqlJhemrGateway.BLWS_SQL`（列名集中一处） | P0-3③ |
| HIS 首页结构化表位置 | `collectors.py` `SqlHisGateway.FIRSTPAGE_SQL`（空=整族跳过） | P0-3④ 硬闸门 |
| 四源连接占位符 | `config.json`（本仓库只交模板） | P0-2 网络开通 + §1.4 凭据受控配置 |
| 工号→企微 userid 映射 | `receivers.py`（现为透传沙箱实现） | P0-6 基线命中率 |
| EMR 窗口标题/患者号正则 | `reminder_agent/agent_config.json` | P2-1 实测（嘉和客户端 Config.xml/标题） |

## 8. 已知限制（原型口径）

- 真实 SQL 网关已写但未对生产验证（P1-2 影子运行验证）；
- Oracle 结果库接线（result_store.type=oracle）未启用——先手工建表再补 engine 构造（run_service 内有留痕报错）；
- 检查键去重表存 JSON state 文件（`data/state.json`），单机规模够用；多实例部署应迁入 MED_PREARCHIVE_* 表；
- 分页翻页游标按秒粒度回退 1s + examined 去重，同秒大量完成记录（>batch_limit×50）极端场景需换键集分页；
- 弹窗助手为骨架，窗口句柄 owner/360 白名单/升级容忍（P2-2/2-4）待试点验证。

### 8.1 触发锚点模式 anchor_mode（031 T2-1，默认 finished 行为不变）

| 模式 | 锚点 | 生产可用性 |
|---|---|---|
| `finished`（默认） | pat_visit.finished_date_time | **不可用**——029 K1 实测 177 副本完成字段族 100% NULL（完成事件不落库，应用层直推） |
| `discharge` | pat_visit.discharge_date_time | 兜底可用（177 实测 99% 有值）；语义退化：出院时点≠书写完成时点，检查键第三列=出院时间 |
| `blws_status` | v_blws.modify_date 患者聚合 | **生产不可用（029 K5：视图全表聚合 120s 超时），仅联调** |

新模式必须显式配置 `service.anchor_mode` 才生效；默认保持 finished 现状。过渡期正式锚点=无纸化 RPA 采集完成表（031 §11 方案④，T8-1 实现 `paperless_rpa` 模式）。
