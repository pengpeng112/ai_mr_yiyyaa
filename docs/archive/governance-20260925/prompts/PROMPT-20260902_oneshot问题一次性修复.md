# PROMPT — 037 oneshot 测试问题一次性修复

交接日期：2026-09-02 ｜ 委托：用户 ｜ 起草：Grok 4.6
你的身份：一次性修复执行 AI。按本提示词 + **`docs/ACTIVE/037`（唯一作业书）** 一口气修完。

## 0. 必读顺序

`AGENTS.md` → `开发起步包/README.md` → `00_AI协作规则.md` → `01_统一修改记录.md` 末 10 行 → `docs/INDEX.md` → **`docs/ACTIVE/037` 全文** → 本提示词其余部分。

## 1. 基线（2026-09-02 定格）

- 分支 `fix/ora-12609-p4-error-code`，HEAD 参考 `52998cc`（oneshot 测试锚）。
- oneshot 已跑完：主服务 1211 passed；prearchive 211+1 skipped；ui-next 既有 52 passed。
- 工作区可能已有：`01_统一修改记录.md` 脏、`frontend/tests/e2e-legacy/oneshot-sweep.spec.ts` 与 `frontend/tests/e2e/oneshot-uinext-sweep.spec.ts` 未跟踪。后两者按 037 RP-I 收口，不要删。
- **零生产**。不 SSH、不改容器、不改 `config/config.json` 业务值。

## 2. 已裁定事实（禁止再争论）

1. P-001～P-007、K-1、O-5 **全部属实**，对照代码已核。P-002 从 C **升级为 B**（空 body 能把生产 Oracle/Dify 主机写成 schema 占位地址）。
2. P-008、U-3、O-1/O-2/O-3/O-4 **不修**。
3. K-1 必须修：H5 反馈是 token 认证，不能被管理端残留 Cookie 打成 CSRF 403。
4. relay-alert 部分保存红线继续有效；本轮只是把其它 config POST 对齐成 unset-merge，**不要**把 relay 改回整段覆盖。

## 3. 执行顺序（037 §2）

RP-C IsolatedModeError→400 → RP-B 配置 merge/空 body 422 → RP-D/E/F 数据源能力分支 → RP-A SQLite busy_timeout → RP-H 移动端 CSRF → RP-G 删除 404 → RP-I oneshot skip 守卫 → §15 门禁 → 写 `docs/ACTIVE/038` + INDEX + 01。

每包测该包新测试，红则停，不带病前进。详细改法、函数名、用例表以 **037 正文为准**，本提示词不重复贴代码。

## 4. 门禁（仓库根）

```
python -m compileall app tests scripts
python -m pytest
python scripts/check_naming_convention.py
python -m pytest prearchive_service/tests -q
python prearchive_service/check_isolation.py
npm --prefix frontend run typecheck
npm --prefix frontend run test:unit
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

0 failed；prearchive 不要被你改坏；ui-next e2e 里 `oneshot-uinext-sweep` 必须 skip；不要为凑旧计数 1211 删测试。

## 5. 升级出口（停下问用户）

- 必须改 AGENTS 红线行为才能过测试。
- 门禁连续两轮红且根因不在 037 范围内。
- 需要生产写入或部署。

## 6. 完成定义

037 §19 勾选全过 + 038 交付报告 + INDEX/01 登记。用户未批准不 commit、不 push。
