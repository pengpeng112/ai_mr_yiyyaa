# PROMPT 交接：企微 OAuth 真实联调 + 外网前置机对接（病历时效手机端 H5，2026-11-17）

> 交接对象：下一个接手的 AI（任何工具/模型）。本文档自包含——按顺序执行即可，不需要追问上下文。
> 上一任：ZCode / GLM-5.3-Flash（2026-11-16/17 多轮，登记见 `开发起步包/01_统一修改记录.md` 当日各行、任务板 `20261116-mobile-wecom-h5-01`、`20261117-*` 各行）。
> 现状一句话：**手机端 H5 门户与工号免登、HIS 直登、OAuth 回调直签发代码已全部上线生产（med-audit:latest），仅剩「企微凭据配置 + 真实 OAuth 全链联调 + 外网前置机映射」三项由本文档交接执行。**

---

## 〇、红线（违反任一条立即停工）

1. `10.10.8.177`（Vastbase JHEMR）/`10.10.8.216`（Oracle HIS）**100% 只读**；严禁任何写/DDL/DCL；严禁触碰 `jhemr.goal_setting_table`。
2. 84 容器四项安全闸**必须保持原值**：`timeliness.jhemr_write.enabled=False`、`insert_monitor_enabled=False`、`notify_mode=LOG_ONLY`、`oracle_lock_enabled=None`（每次变更后复核）。
3. **严禁 `git reset/checkout --/clean/commit/push`**；工作区多轮未提交改动共存，只做增量修改，改前先 `git status --short` 核对。
4. **企微 Secret 严禁出现**在聊天、文档、代码、日志、git 中。配置只能由**用户本人**在 84 宿主机直接编辑（见 §二.1 的占位符方式），或用户自己注入容器 env；AI 只提供命令模板与验证方法。
5. 菜单契约不动：`MENU_CATALOG` 保持 22 项/5 组；`route-manifest.ts` 不改。
6. 部署 84 前先打回滚镜像 tag + 备份被覆盖文件；部署后 verify + `docker commit` 固化（脚本模板见 §五）。

---

## 一、现状与已完成（不要重做）

| 能力 | 状态 | 位置 |
| --- | --- | --- |
| 手机端 H5 门户（三 Tab：超时解锁/在院预警/统计通报，纯中文） | ✅ 已上线 | `static/templates/mobile/timeliness_h5.html` + `styles` + `scripts` |
| 工号免登 `?empno=`（应用库账号 → 常规身份） | ✅ 已上线 | `POST /api/mobile/timeliness/login/empno`（限流：按工号 5 次/5 分钟 + 全局 60 次/分钟） |
| HIS 工号直登（应用库未命中 → `HIS.SYS_EMPLOYEE` 只读虚拟身份，2382 有效员工，科室硬隔离） | ✅ 已上线 | 同端点回退分支；虚拟身份写操作天然 403 |
| **企微 OAuth 回调直签发**（code→userid→**直签 HttpOnly Cookie**→302 干净 H5，URL 无凭证） | ✅ 代码已上线，**待凭据配置后联调** | `GET /mobile/qc/timeliness/oauth/wecom/callback` |
| OAuth 双通道换 userid | ✅ 已实现 | relay 代换（84 无公网出口时用，HMAC 保护）优先；直连 qyapi 次之 |
| 转圈/白屏根修（`Vue.reactive(state)` + `APP.mount` + loadMe 非 2xx reject + ping 3s 超时 + 启动 8s 兜底） | ✅ 已上线并有 jsdom 真实渲染测试守护 | `frontend/tests/unit/mobile-h5-render.test.ts` |
| 外网前置机映射规范（含最小暴露面基线） | ✅ 文档已就绪 | `docs/reference/122_MOBILE_TIMELINESS_WECOM_PROXY_ONBOARDING_20261117.md`（§五A 最小暴露面 Nginx 白名单、§五B OAuth 配置说明、8 条验收 curl） |

测试基线：pytest 全量 **2143/0**；vitest **23 文件 151 用例**；quick 门禁 4/4。当前镜像链：latest ← `backup-pre-oauth-direct-20261117`（=7d46521762b3）← 更早回滚链见 `docker images med-audit`。

---

## 二、待执行任务（按序）

### T1 企微凭据配置（需要用户参与的一步）

凭据 = `corpid=ww9021c8e20f77fb24`、`agentid=1000033`、`secret`（用户从企微管理后台-自建应用查看）。

**安全操作方式（AI 执行时严禁索要/转发明文 secret）**——引导用户在 84 宿主机自己执行：

```bash
# 宿主机 10.10.8.84 上（用户手工操作；<SECRET> 由用户键入后命令历史可清）
python3 - <<'PYEOF'
import json, pathlib
p = pathlib.Path('/opt/med-audit-docker/config/config.json')  # 注意：实际挂载路径以宿主机 compose 为准（./config:/app/config）
cfg = json.loads(p.read_text(encoding='utf-8'))
cfg.setdefault('wecom', {})
cfg['wecom'].update({
    'corpid': 'ww9021c8e20f77fb24',
    'agentid': '1000033',
    'secret': input('wecom secret: ').strip(),
})
p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
print('wecom section written, secret not echoed')
PYEOF
docker restart med-audit
```

或容器 env 方式：`WECOM_CORPID / WECOM_SECRET / WECOM_AGENTID`（env 优先于 config.json）。**改配置前后各打印一次写闸四值确认未变**（命令见 §四验收）。代码读取逻辑见 `app/routers/mobile_timeliness.py` 的 `_wecom_oauth_config()`。

### T2 relay 代换通道（84 无公网出口时的必需件）

84 容器大概率无公网出口（qyapi.weixin.qq.com 不可达）。此时需要前置机提供代换端点：

- 源站回调会 `POST {relay_url}/wecom-oauth/exchange`，body=`{"code","corpid","secret","agentid"}`（JSON），头 `X-Relay-Timestamp`（unix 秒）+ `X-Relay-Signature` = `HMAC-SHA256(relay_key, ts + "." + body)`。
- 前置机职责：校验 HMAC（±300s）→ 自己调企微 `gettoken` + `auth/getuserinfo?code=` → 返回 JSON `{"userid": "..."}`。
- 配置：`config.json` wecom 节或 env `WECOM_RELAY_URL` / `WECOM_RELAY_HMAC_KEY`。
- **如果外网前置机映射是同路径透传（形态 A）且 84 出口已打通**，可跳过 relay 走直连 qyapi 分支（代码自动判断：有 relay 配置用 relay，否则直连）。

前置机 AI 需要：①实现上述 exchange 端点；②按 `docs/reference/122` §五A 最小暴露面做映射；③把 exchange 的可达地址与 HMAC key 与用户约定后配入源站。

### T3 真实 OAuth 全链联调（凭据配好后）

1. 用户在企微内打开（手机企微 = 真实 snsapi_base 静默授权）：
   `https://open.weixin.qq.com/connect/oauth2/authorize?appid=ww9021c8e20f77fb24&redirect_uri=https%3A%2F%2Fydbi.sdent.com.cn%2Fmobile%2Fqc%2Ftimeliness%2Foauth%2Fwecom%2Fcallback&response_type=code&scope=snsapi_base&state=empno&agentid=1000033#wechat_redirect`
2. 预期：静默 302 → 回调 → 302 干净 H5 → **免密进入本人科室**的三 Tab 界面。
3. AI 侧服务级验证（84 容器内，脱敏）：
   - 容器日志出现 `mobile wecom oauth ok: username=<工号> scope=...`；
   - 手工 curl 模拟：`/oauth/wecom/callback?code=<一次性真实code>` 302 且 `Set-Cookie: med_audit_token=...`；用该 Cookie 调 `/api/mobile/timeliness/me` 返回本人身份。
4. 失败排查：`docker logs med-audit | grep wecom`；`mobile wecom oauth exchange failed`=出口/凭据问题；`userid not bound`=企微 userid 与系统用户名/HIS EMPLCODE 不一致（需映射，回退手动登录，不猜映射）。

### T4 外网前置机映射（按 122 文档执行）

严格按 `docs/reference/122_MOBILE_TIMELINESS_WECOM_PROXY_ONBOARDING_20261117.md`：
- §五A **最小暴露面**（外网只透传 OAuth 回调/页面/静态/只读 API；**`login/empno` 不出外网**）；
- 8 条验收 curl 全过；
- T2 的 exchange 端点若由前置机实现，需另加来源校验（仅允许 84 出口 IP 调用）。

### T5 企微工作台配置（用户侧）

管理后台 → 自建应用（agentid=1000033）→ 主页/工作台链接 = T3 的授权链；可信域名加 `ydbi.sdent.com.cn`（需域名归属校验文件）。

---

## 三、技术契约速查（改代码前必读）

- **路由注册顺序**：`mobile_timeliness.router` 必须在 `mobile_qc.router` 之前（`/mobile/qc/{alert_id:int}` 会捕获 "timeliness" → 422）。
- **CSP**：H5 严禁内联 `<script>` 与 `on*=` 属性（`security_middleware` script-src 无 unsafe-inline）；有源码断言测试。
- **H5 JS 响应式铁律**：外部闭包操作 `state` 生效的前提是 `state = Vue.reactive(state)`（已修，勿回退）；`APP.mount('#app')` 必须存在（白屏根因）。
- **虚拟 HIS 身份**：JWT `sub=his_empno:<工号>`；`role_id=None` → 写操作天然 403；可见性按 `his_dept_code` 硬隔离（`require_mobile_view` / `_apply_mobile_*_visibility`）。
- **`/api/mobile/timeliness/login/empno` 双层限流**：按工号 5 次/5 分钟 + 全局 60 次/分钟；开关 `MOBILE_TIMELINESS_EMPNO_LOGIN`；HIS 直登开关 `MOBILE_TIMELINESS_HIS_EMPNO_LOGIN`。
- 相关测试（改行为必须同步）：`tests/timeliness/test_mobile_timeliness_20261116.py`、`test_mobile_empno_login_20261117.py`、`test_mobile_his_empno_20261117.py`、`test_mobile_oauth_direct_issue_20261117.py`、`test_mobile_wecom_oauth_20261117.py`；渲染冒烟 `frontend/tests/unit/mobile-h5-render.test.ts`。

---

## 四、验收清单（全部满足才算完成）

1. 企微手机内点开工作台链接 → 免密进入本人科室三 Tab（人工确认）；
2. `/api/mobile/timeliness/me` 返回本人 `username/full_name/dept_name`；
3. 长按转发该页面 URL 给他人 → 他人打开**不会**变成转发者身份（Cookie 不随 URL）；
4. 写闸四值复核 `False/False/LOG_ONLY/None`；`docker logs med-audit` 无异常栈；
5. 外网通道（ydbi 域名）复跑 122 §五的 8 条验收 curl 全过；
6. 全量门禁：`python -m pytest -q` 0 failed、`frontend: typecheck+vitest+build`、`run_gates --quick` 4/4。

## 五、部署与回滚模板

- 部署脚本模板：`scripts/deploy_mobile_timeliness_20261116.py` / `deploy_oauth_direct_20261117.py`（backup/deploy/verify/persist 四阶段，改 BUNDLE_FILES 即复用）；
- 打包走 ASCII 临时目录 `C:\Users\ADMINI~1\AppData\Local\Temp\opencode\`；
- 当前回滚链（最新在前）：`backup-pre-oauth-direct-20261117`(7d46521762b3) → `backup-pre-reactive-20261117`(8a687e246962) → `backup-pre-spinfix-20261117b`(d1794a15b166) → `backup-pre-his-empno-20261117`(91faa521eed5) → `backup-pre-mobile-timeliness-20261116`(41ed612523f1)；
- 一键回滚：`docker tag med-audit:backup-pre-oauth-direct-20261117 med-audit:latest && cd /opt/med-audit-docker && docker compose up -d med-audit`。

## 六、遗留与建议（交接说明）

- `?empno=` 内网便利通道：外网已建议不透传；若内网也要关，容器 env `MOBILE_TIMELINESS_EMPNO_LOGIN=false`（代码与测试均已支持）。
- `verify_frontend_20261012.py` 历史任务书引用的脚本不存在，等效门禁=`run_gates --quick`。
- 若企微 userid 与 HIS EMPLCODE 出现系统性不一致（如前缀差异），需要业务方给映射表后再立项，勿在免登链路做模糊匹配。

---

## 七、2026-11-17 晚间执行补充（relay 侧 ZCode / GLM-5.3 实测后回填；本节取代上文与现状冲突处）

### 已完成（T1/T2/T3 服务端部分全部收口，无需再执行）

| 项 | 状态 | 事实 |
| --- | --- | --- |
| T1 企微凭据 | ✅ 已配置 | corpid/agentid/secret 已注入容器 `/app/config/config.json` 的 `wecom` 节（config 为宿主机 `/opt/med-audit-docker/config` 挂载，持久）。注意：secret 经用户在会话中提供（与本文件 §〇.4 预期方式不同，已完成注入）；**建议联调通过后重置一次 Secret**，重置后仅需更新 config.json 该值 |
| T2 relay 代换 | ✅ 已上线并实证 | relay（10.20.1.153）热补丁新增 `POST /wecom-oauth/exchange`（HMAC 口径与本文件 §T2 完全一致；R9 清单见 qywx 仓 `review/wecom-oauth-relay-20261117/EXECUTION.md`）。84→relay HMAC 调用已端到端实证：假 code → relay 调企微真实 API → `errcode=40029` → 302 回退 |
| 公网入口 | ⚠️ 重大变更 | **DNS 已切 `ydbi.sdent.com.cn → 123.233.249.133`，公网入口为标准 `443`（153:443 TLS 中转）**；`:29080` 全端口失效（含 122 号文档所有 `:29080` 示例 URL，对接时一律去掉端口）。血透 /p/、PC、患者链路经 443 实测零影响 |
| 外网验收 | ✅ 122 §五 8 条 curl 已全过（经 443） | 另：`/mobile-bi.html` 已改为 302 跳时效 H5（APISIX P1000 路由变更，原 DataEase OAuth 落地页废弃） |
| WW_verify 域名校验 | ⚠️ 部分 | `https://ydbi.sdent.com.cn/WW_verify_kLcTpDgslBQof2VG.txt` 已通（精确内容）；`http://` 形态待出口 80 转发生效（网络组称已加，实测仍设备 404——需其复核目标是否 `10.20.1.153:80`） |
| T3 真机联调 | ⏳ 待用户 | 服务端链路已全通（relay 日志 `errcode=40029 agent=1000033` = 真实 API 应答）；用户在企微后台保存可信域名+配置主页链接后真机点击即验 |
| 直签发回调 | ✅ 已上线 | 直签 Cookie 版（URL 无凭证）已部署生产并 `docker commit` 固化（latest=e99f2fdcdfb1）；本地测试 231/231 全绿（含 test_mobile_oauth_direct_issue 全契约） |

### 回滚链更新（最新在前）

```
latest(e99f2fdcdfb1, 含 wecom-oauth 直签+relay 配置) ← backup-pre-wecom-oauth-20261117(b291e8f03fc6, 本日晨状态) ← backup-pre-oauth-direct-20261117(7d46521762b3) → …原链不变
```

relay 侧回滚（独立）：容器内 `/app/app/main.py.bak-20261117-wecom-oauth` 恢复 + 删 `/app/app/routers/wecom_oauth_exchange.py` + restart。

### 遗留提醒（不变项复核均通过）

- 写闸四值 `False/False/LOG_ONLY/None` 每次部署后复核 ✅（本日 3 次部署均 PASS）；
- 84 出口仍不通 qyapi（relay 代换为常态通道，直连分支保留作出口打通后的自动切换）；
- `userid==工号` 假设待真机首验；系统性不一致再立项映射表（§六 口径不变）。
### §七.1 追加（2026-11-17 22:5x）：真机首验两连障修复记录

1. **relay 配置被覆盖**：`deploy_wecom_oauth_20261117.py` 原 inject 合并逻辑为整段替换，v3 部署时把 v2 注入的 `relay_url/relay_hmac_key` 冲掉 → 回调退回直连 qyapi → 84 无出口 → 登录表单。已改为**增量 update**（保留既有键）并重新注入（5 键齐全 + 容器内 `_wecom_relay_config()` 自检 OK）。
2. **SameSite=Strict 拒发 Cookie**：修复 1 后日志实证 OAuth 链全通（`oauth ok: empno=003966 scope=his_virtual`），但 Cookie `SameSite=Strict` 在 open.weixin.qq.com 跨站跳转落地时不随请求发送 → H5 `/me` 401 → 登录表单。OAuth 回调两处签发（应用库/HIS 虚拟）已改 `SameSite=Lax`（empno XHR 场景保持 strict 不动），部署 v4 + commit 固化（latest=bfcef5b82c6d）。
3. **身份解析已实证**：22:39/22:40 两次真机点击日志 `empno=003966 → HIS 命中 彭赫/PCCM[Ⅶ-Ⅷ部]` → 生成 8h 只读虚拟身份 Cookie。修复 2 后真机点击应直接进入。
4. 回滚链注意：`backup-pre-wecom-oauth-20261117` tag 已被 v4 轮 phase_backup 重打（现指向 v3 commit e99f2fdcdfb1；原始晨前镜像转为无 tag 悬空层）。现行回滚：`latest(bfcef5b82c6d)` ← `backup-pre-wecom-oauth(e99f2fdcdfb1)` ← `backup-pre-oauth-direct(7d46521762b3)`。
### §七.2 追加（2026-11-17 23:0x）：直签 Cookie 被 JS 门控忽略的最后一环修复

**现象**：OAuth 后端链路全通（日志 `oauth ok: empno=003966 scope=his_virtual`，Cookie 签发+302 干净 H5），但真机仍落登录页；日志中**始终无 `/me` 请求**。

**根因**：`timeliness_h5.js` 启动门控只看 localStorage token——`getToken()` 为空且 URL 无 `?empno=` 时直接渲染登录表单，从不探测服务端 Cookie 会话。直签方案（Cookie 落地、URL 干净）恰好落进这个盲区。另：JS 带 `?v=20261117d` 且企微 WebView 304 缓存顽固，改 JS 必须同步升版本参数。

**修复（v5，已部署+commit 固化 latest=4347c227a80e）**：
1. `timeliness_h5.js` 启动链 else 分支改为先探 `/me`（同源 fetch 自动携带 HttpOnly Cookie），命中 `bootMainData` 免登进主界面，401 才落登录页；
2. HTML/测试的 JS 版本参数同步升 `v=20261117e`（防 WebView 旧缓存）；
3. 部署验证全 PASS（写闸 False/False/LOG_ONLY/None）；公网 443 已确认下发新版 HTML+JS。

**回滚链**：latest(4347c227a80e) ← backup-pre-wecom-oauth(bfcef5b82c6d) ← backup-pre-oauth-direct(7d46521762b3) → 原链。
**真机预期**：仅从工作台 OAuth 链（或 open.weixin.qq.com 长链）进入免登；直接打开收藏的干净 H5 URL 仍显示登录（无 Cookie，属预期）。
