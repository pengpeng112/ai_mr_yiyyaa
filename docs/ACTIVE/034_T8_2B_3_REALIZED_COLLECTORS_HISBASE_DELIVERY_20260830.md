# 034 — T8 全源采集器真实化 + HIS 基本信息工号映射接线 交付报告

> 文档编号：034
> 编制日期：2026-08-30
> 编制者：ZCode/GLM-5.3
> 任务来源：`开发起步包/PROMPT-20260830_全源采集器真实化与工号映射接线.md`（自包含实测数据交接，为 031 T8-2/T8-3 的"实测数据解堵版"；与 031 冲突处以 031 为准）
> 性质：本地执行交付报告（零生产写入）。从属 023/031 体系，不构成新执行入口。

---

## 1. 执行基线与结论

- 基线：分支 `fix/ora-12609-p4-error-code`，起点 HEAD `2407bc0`（031 已执行完毕、生产已热更部署）；
- 起点测试基线：主服务 1176 passed / 0 failed；prearchive 196 passed / 1 skipped；check_isolation 通过（46 py）；
- **结论：P-A/P-B/P-C/P-D 四包全部完成**，终态见 §3-§5；心电（xd）= 唯一未接源（骨架保留 BLOCKED+TODO，对接信息待用户提供）。

## 2. 完成清单（逐包）

### P-A 四源采集器真实化（T8-2 收尾）— ✅ 完成（commit `c3678ca`）

1. `collectors.py` 四个 Sql*Gateway ITF_SQL 按 2026-08-29 平台实测列结构回填：
   - 病理 `SqlBlGateway`：`dbo.T_ITF_BL` 13 列（DSN 库=pitaya 由连接配置负责；代码注记**该源需 TDS 7.0**，连接器已内置回退）；
   - 血透 `SqlXtGateway`：`"T_ITF_XT"`（表名大小写敏感带双引号）14 列=标准 13+IDNo；
   - 电测听 `SqlDcnGateway`：`t_itf_report` 16 列小写命名（visit_index 疑似住院次映射注记待 W9 核对，本期不取）；
   - 气管镜 `SqlQgjGateway`：`"T_ITF_HisQuery"` 13 列（REPORTNAME 实测恒=呼吸内镜检查报告）；
   - 心电 `SqlXdGateway` 不动（唯一未接源，BLOCKED+TODO 保留）。
2. 类型差异适配：数值型身份列（血透 FID/PATIENTID=bigint、气管镜 FBINCU/PAGECOUNT=int）由 fixture 网关 `str()` 过滤+适配层小写归一覆盖（单测断言）；timestamp/timestamptz 直返 datetime——`parse_datetime` 新增 aware→naive 墙钟归一（防 aware/naive 比较 TypeError，附单测）。
3. **血透 IDNo PHI 双保险**：SQL 不查该列 + `adapt_itf_rows` 对 xt_itf 行整列丢弃（`row.pop("idno")`，连 `DocumentEntry.raw` 也不含）；fixture 用明显假号 `FAKE-IDNO-XT-DO-NOT-USE` 并以"断言假号不出现在任何输出"证明丢弃生效。
4. `fixture_sources.py` 四源 demo 行改为实测列结构（虚构 TEST 值）；四个 Fixture 网关 docstring 去 BLOCKED/未登记平台字样。
5. 测试：删除旧"BLOCKED 骨架"测试，新增 6 项（四源实测列适配/数值身份 str()/表名断言/占位字样断言/心电保留断言/tz 归一）。

### P-B HIS 基本信息接入（T8-3）— ✅ 完成（commit `1a4efa8`）

1. `his_base.py` 按实测三视图转正：
   - VW_user_info（4,278 行）：FID=工号/FNAME=姓名/FDEPT=科室代码/**FDOCT=科室名称（实测语义，非医生标志位）**/FPOSITION/FUSERTYPE；视图无 active/企微列→active 缺省有效（fail-open）、wecom_userid 恒回落工号；
   - VW_dept_dict（816 行）：FID/FNAME/FQUN/FBETO/FTYPE/FBQNT；
   - VW_pats_out_hospital（62,885 行 53 列）：仅限量采样接口 `fetch_out_hospital_sample(limit)`（FGUIDANGDATE=归档日期/FLEVWAY=离院方式在位），**零触发实现**，留作未来出院交叉校验/手术证据候选源（README §8.3 记录）；
   - 新增 `fetch_user_info()` 全量通道；fixture 行改为 VW_* 实测列名结构。
2. `receivers.py` 新增 `HisBaseUserIdMapper`：命中回落工号、查无/停用/异常返回 None → `DefaultReceiverResolver` 下探兜底链（不透传未知工号）。
3. `HisBaseDeptNormalizer`（VW_dept_dict 代码→标准名）：`name_for_code`/`normalize_name`（全角半角空白归一）；`build_push_payload` 可选接线（科室名按字典标准名进推送文案，异常 fail-open）。
4. **配置开关**：`receiver.userid_mapper_source: passthrough(默认)|hisbase`、`receiver.dept_normalizer_source: off(默认)|hisbase`，`validate_config` 白名单校验；`run_service.build_stack` 双模式接线（fixtures/真实），默认完全不变现状。
5. **join 命中率采样（sjzc 只读聚合，平台受控连接器）**：
   `SELECT COUNT(*) TOTAL, COUNT(d.FID) HIT FROM hisuser.VW_user_info u LEFT JOIN hisuser.VW_dept_dict d ON u.FDEPT=d.FID`
   → **TOTAL=4,278 / HIT=4,268 = 命中率 99.77%**（仅 10 行未命中）。结论：FDEPT↔VW_dept_dict.FID 关联高度可靠，科室规范化通道可放心启用。零人员明细落盘。
6. 测试：test_pa_his_base.py 重写为 11 项（实测列/三态映射+企微优先路径/兜底链/开关校验/build_stack 级接线双态断言/normalizer）。

### P-C 配置模板与文档同步 — ✅ 完成（commit `819baf6`）

1. `config.example.json`：五源节点齐备（bl/xt/dcn/qgj/his_base，enabled=false、host/凭据占位、库名=实测值 pitaya/dialysis/report/clouddb）；`service._comment_anchor_mode` 注记"生产过渡建议=paperless_rpa（用户已拍板，时效≈出院后5天；179 作废注记）"；receiver 开关入模板。
2. `prearchive_service/README.md`：§7 衔接表更新（签字轨已授权/hisbase 通道就绪/心电唯一未接）；§8.3 新增"五源采集器现状"（含 join 命中率、IDNo 红线、五源表）；§8 已知限制与规则行同步（14 条 v2026.08.29-qc-authorized-v1）。
3. `.gitignore` 追加 `docs/docs/`（用户截图目录，已核实生效）；顺手修复 `prearchive_service/.gitignore` 行尾注释破坏模式匹配的隐患（gitignore 注释必须行首，data/ 现已正确忽略）。
4. 031 §8 修订记录追加"补记 2026-08-30"（不改已执行正文）；033 修订记录 v2 + 速查表第 2 行标记采集器侧收口。

### P-D 门禁、登记与提交 — ✅ 完成（commit 见 §6）

## 3. 验收断言勾选

**P-A**
- [x] 四源 Gateway 无 TODO/无占位字样（`test_four_gateways_no_placeholder_markers` 文本断言四类源码）
- [x] 四源 fixture 适配单测 + builder e2e 绿（`test_four_realized_sources_adapt_measured_columns` 等 + 既有 e2e）
- [x] 血透 IDNo 不进入任何输出：SQL 不查列 + 适配层 pop + 假号哨兵断言（真 PHI 零落仓库；fixture/assert 仅含明显假号，符合"血透 IDNo 用假号"红线口径）
- [x] 原 196+新增全绿（终态 209 项：208 passed + 1 skipped，exit 0）
- [x] check_isolation 过（46 py，零 `import app.*`）

**P-B**
- [x] 默认配置行为与现状完全一致（全量现状测试绿 + `test_build_stack_hisbase_switch_fixture_chain` 默认态断言 passthrough/off）
- [x] hisbase 开启时 fixture 链路映射正确（build_stack 级：resolver 用 HisBaseUserIdMapper、pusher 带 Normalizer、命中/查无行为断言）
- [x] join 命中率数字进交付报告（§2 P-B 第 5 点：4,268/4,278=99.77%）
- [x] check_isolation 过

**P-C**
- [x] config 校验测试过（example 加载/合并/占位断言 9 项绿）
- [x] README 无过时描述（衔接表/已知限制/规则数/五源现状全部同步）
- [x] .gitignore 含 docs/docs/（`git check-ignore` 验证生效）

**P-D（全绿门禁实测）**

| 门禁 | 结果 |
|---|---|
| 主服务全量 pytest | **1176 passed / 0 failed**（与基线一致，零回归；37 warnings 为既有 SQLAlchemy 弃用告警） |
| prearchive pytest | 209 项收集：208 passed + 1 skipped，exit 0 |
| check_isolation | PASSED（46 py，零 `import app.*`） |
| compileall（app tests scripts） | exit 0 |
| 命名检查（mr_txt 误用） | PASS |
| fixture 冒烟（run_service --fixtures --once） | fetched/processed/errors=[] 正常（复跑走检查键去重） |

## 4. 红线遵守声明

- **零生产接触**：开发/测试全部 fixture 驱动；唯一真实库访问=§2 P-B 第 5 点 sjzc 只读聚合（平台受控连接器、授权范围内、单条 SELECT COUNT、零明细落盘）；未 SSH 生产、未部署、未动容器。
- **隔离**：prearchive_service 零 `import app.*`（check_isolation 保持通过）；主服务仅文档面无代码改动。
- **PHI**：血透 IDNo 双保险丢弃（SQL+适配层）；fixture/测试仅明显假号；患者数据全部 TEST 前缀虚构。
- **未动正式规则**：`rules/example_rules.json` 14 条 v2026.08.29-qc-authorized-v1 与 `system_push_rules.json`（零规则等 W10）零改动。
- **每包独立提交、未 push**；真实 DSN/口令零入仓（五源模板全部占位符）。

## 5. 遗留事项（不阻塞本交付）

1. **心电（xd）**：唯一未接源——实测实例两库均无 ITF 对象、库型与登记不符；等用户提供库型/实例/表名后回填 `SqlXdGateway`（骨架+TODO 已留）。
2. **W10 系统推送类规则清单**：等用户提供（病理+PACS 两条起步，5 字段模板见 033 请求三）；`system_push_rules.json` 保持零真实规则。
3. **现场项**（继承 032）：W8 实验机 C# 助手 exe 运行冒烟（本机安全策略阻断已留证据）、五源生产受控配置回填+真实影子运行（W9 开闸后）。
4. 电测听 `visit_index` 与 FBINCU 映射、VW_pats_out_hospital 完整 53 列语义——待 W9 核对（注释已标注）。

## 6. 提交清单（4 笔，未 push）

| # | hash | 提交信息 |
|---|---|---|
| 1 | `c3678ca` | feat(prearchive): 四源真实采集器(病理/气管镜/血透/电测听,实测列回填) |
| 2 | `1a4efa8` | feat(prearchive): HIS基本信息工号映射与科室规范化(hisbase,T8-3) |
| 3 | `819baf6` | chore(prearchive): 配置模板与README同步五源现状 |
| 4 | 本笔（docs 收口，即含本报告之提交；hash 见 `git log` 该笔） | docs: 033办结注记与INDEX登记(2026-08-29会话遗留收口)（含 034 本报告、031 补记、033 v2、01 记录、PROMPT-20260830、T0 三脏文件） |

## 7. 给用户的提醒（交付后外部依赖仅两项）

1. **W10 推送类规则清单**（病理+PACS 两条起步，5 字段模板见 033 请求三）；
2. **心电对接信息**（库型/实例/表名）。
