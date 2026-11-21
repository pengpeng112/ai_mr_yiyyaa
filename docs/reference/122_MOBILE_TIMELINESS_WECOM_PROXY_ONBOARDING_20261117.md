# 病历时效手机端 H5 外部前置机代理对接规范（2026-11-17）

> 目标读者：负责**另一个前置机（公网/外网段反代）**对接映射的运维或 AI 助手。
> 本文档自包含：无需读取本仓库其他文件即可完成对接、验收与排障。
> 源站（内网已就绪，无需改动）：`10.10.8.84`，宿主机 Nginx `:3000`。
> 业务系统：AI 病历质控系统 · 企微手机端「病历超时解锁查询与时效统计」H5。

---

## 〇、红线（对接方必须遵守）

1. **只做转发，不改写内容**：禁止修改响应体、禁止剥离/改写 `Authorization`、`X-Requested-With`、`Content-Type` 请求头（免登与 CSRF 校验依赖它们）。
2. **HTML 严禁缓存**：`/mobile/qc/timeliness` 页面由源站下发 `Cache-Control: no-store`，代理必须原样透传（企业微信内置浏览器对旧页面缓存极顽固）。
3. **`/api/` 路径禁止加缓存**；静态 JS/CSS 可按需加浏览器缓存。
4. **不建议对响应再叠加一层 CSP/X-Frame-Options**：源站已带精确 CSP（允许同源脚本）；叠加 `X-Frame-Options: DENY` 会破坏客户侧 iframe 嵌入场景。
5. 生产业务库与质控应用库对本对接**完全只读透明**——代理侧不得引入任何改写业务数据的功能（如统一改写返回 JSON）。

---

## 一、业务背景与嵌入 URL 形态

手机端 H5 支持「工号免登」：URL 带 `?empno=工号` 打开即免密登录（前提：系统内已按 `用户名=工号` 建立账号；无绑定则页面回退手动登录，不会白屏）。

对外分发 URL 模板（把 `外部域名` 换成前置机映射后的地址）：

```
https://外部域名/mobile/qc/timeliness?empno=0517001
```

- 工号 = 医院系统账号的用户名（数字工号形态）。
- 免登签发 8 小时短时 JWT；过期自动回登录页。
- 页面纯中文，三 Tab：超时解锁（查询/同步/豁免/解锁）/ 在院预警（倒计时/时间线）/ 统计通报（按时率/科室排行/医师扣罚）。

---

## 二、必须转发的路径清单（缺一即白屏/功能残缺）

| # | 路径前缀（精确） | 内容 | 透传要求 |
| --- | --- | --- | --- |
| 1 | `/mobile/qc/timeliness` | H5 入口 HTML（另有别名 `/mobile/timeliness`） | `no-store` 原样透传，**禁缓存** |
| 2 | `/mobile/qc/` 其余子路径 | 原有「医生端告警详情」H5（`/mobile/qc/{id}?token=...`） | 与手机端同前缀，整段转发即可；**请一并转发以保原有企微告警消息不失效** |
| 3 | `/styles/mobile/` | H5 样式表 | 可缓存（建议 expires 1d） |
| 4 | `/scripts/mobile/` | H5 脚本 `timeliness_h5.js` + **Vue 运行时 `vue.global.prod.js`（约 1MB，源站桥接路由提供）** | 可缓存（建议 expires 1d）；**必须整前缀转发** |
| 5 | `/api/mobile/` | 全部手机端 API（免登/ping/me/dicts/overview/approvals/events/stats + 原有 qc-feedback） | 禁缓存；`POST` 原样转发（含 JSON body） |

> 源站 `:3000` Nginx 的既有转发清单即：`/mobile/qc/`、`/styles/mobile/`、`/scripts/mobile/`、`/api/mobile/`、`/qc-api/`。外部前置机照抄这 5 个前缀即可完全等价。

---

## 三、源站与上游参数

| 项 | 值 |
| --- | --- |
| 源站地址 | `10.10.8.84:3000`（宿主机 Nginx；内网可达性需先打通） |
| 备选直连 | `10.10.8.84:8000`（质控 FastAPI 容器；与 :3000 等价，路径一致） |
| 建议代理超时 | connect 5s / read 60s / send 60s |
| 请求体 | 均为小 JSON（≤4KB），无需放大 client_max_body_size |
| 大文件 | `/scripts/mobile/vue.global.prod.js` 约 1MB，一次性下载后浏览器缓存 |
| WebSocket | 不涉及 |

---

## 四、两种映射形态（二选一，均无需改源站）

### 形态 A（推荐）：同路径透传

外部前置机把上述 5 个前缀**原样**转发到 `http://10.10.8.84:3000`。对外 URL 与源站完全同构：

```
https://外部域名/mobile/qc/timeliness?empno=0517001
```

Nginx 示例（外部前置机）：

```nginx
# ---- 病历时效手机端 H5（→ 84 源站 :3000）----
location /mobile/ {
    proxy_pass http://10.10.8.84:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 5s;
    proxy_read_timeout 60s;
    proxy_send_timeout 60s;
    # HTML no-store 由源站下发，Nginx 默认透传；不要在此 add_header Cache-Control
}
location /styles/mobile/ {
    proxy_pass http://10.10.8.84:3000;
    proxy_set_header Host $host;
    expires 1d;
}
location /scripts/mobile/ {
    proxy_pass http://10.10.8.84:3000;
    proxy_set_header Host $host;
    expires 1d;
}
location /api/mobile/ {
    proxy_pass http://10.10.8.84:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 60s;
}
# 若希望兼容「医生端告警」等既有 /qc-api/ 习惯，可同构转发：
location /qc-api/ {
    proxy_pass http://10.10.8.84:3000/api/;
    proxy_set_header Host $host;
    proxy_read_timeout 60s;
}
```

### 形态 B：换路径挂载（H5 自适应兜底）

若外部前置机只能挂在别的路径下（如 `https://外部域名/medaudit/...`），**页面与静态资源同前缀改写即可**；但手机端 API 有一个内置自适应兜底可利用：

- H5 启动时先探测 `外部前缀/api/mobile/timeliness/ping`；若 404/不可达，**自动回退尝试 `/qc-api/timeliness/ping`**。
- 因此外部前置机可以把 API 映射为 `/qc-api/` → `10.10.8.84:3000/api/`（源站既有形态），页面与静态资源按新路径转发，H5 会自动切到 `/qc-api/` 通道工作。

> 形态 B 的页面/静态 location 需按实际挂载路径书写，并保证 `/mobile/qc/timeliness` 页面本身可达（页面是免登入口，路径最简原则推荐形态 A）。

---

## 五、验收清单（对接完成后逐条 curl，全部满足为对接成功）

把 `外部域名` 替换为前置机实际地址：

| # | 命令 | 期望 |
| --- | --- | --- |
| 1 | `curl -s -o /dev/null -w '%{http_code}' https://外部域名/mobile/qc/timeliness` | `200` |
| 2 | `curl -s https://外部域名/mobile/qc/timeliness \| grep -c 'timeliness_h5.js'` | `1`（HTML 含脚本引用） |
| 3 | `curl -s -D - -o /dev/null https://外部域名/mobile/qc/timeliness \| grep -i 'no-store'` | 命中（HTML 禁缓存透传） |
| 4 | `curl -s -o /dev/null -w '%{http_code}' https://外部域名/styles/mobile/timeliness_h5.css` | `200` |
| 5 | `curl -s -o /dev/null -w '%{http_code}' https://外部域名/scripts/mobile/timeliness_h5.js` | `200` |
| 6 | `curl -s -o /dev/null -w '%{http_code}' -X POST https://外部域名/api/mobile/timeliness/login/empno -H 'Content-Type: application/json' -d '{"empno":"__probe__"}'` | `401`（工号不存在=接口与校验连通；**不是 404/502**） |
| 7 | `curl -s -o /dev/null -w '%{http_code}' https://外部域名/api/mobile/timeliness/overview` | `403`（未带 Token=鉴权守卫生效；不是 404） |
| 8 | `curl -s -o /dev/null -w '%{http_code}' https://外部域名/mobile/qc/1?token=invalid` | `401`（原有医生端告警页零受影响） |

补充真实验证（有测试账号时）：浏览器/企微打开 `…/mobile/qc/timeliness?empno=真实工号` 应免密进入三 Tab 主界面；工号未绑定时应看到「工号免登失败」红字提示与手动登录表单（同样证明链路通）。

---

## 五A、外网最小暴露面安全基线（2026-11-17 直签发增强，强烈推荐）

外网前置机**只透传 OAuth 通道，不透传工号免登接口**——外网用户只能经企微 OAuth（code 换 userid、企微背书身份）进入；工号直登仅保留在内网通道。前置机路径白名单示例：

```nginx
# ---- 外网前置机：最小暴露面（无 /api/mobile/timeliness/login/empno）----
location = /mobile/qc/timeliness               { proxy_pass http://10.10.8.84:3000; proxy_set_header Host $host; }
location = /mobile/qc/timeliness/oauth/wecom/callback { proxy_pass http://10.10.8.84:3000; proxy_set_header Host $host; proxy_read_timeout 30s; }
location = /api/mobile/timeliness/logout { proxy_pass http://10.10.8.84:3000; proxy_set_header Host $host; }
location /styles/mobile/                        { proxy_pass http://10.10.8.84:3000; expires 1d; }
location /scripts/mobile/                       { proxy_pass http://10.10.8.84:3000; expires 1d; }
location /mobile/qc/                            { proxy_pass http://10.10.8.84:3000; }  # 原医生端告警
# 只读业务 API（免登接口 login/empno 与 login **不在外网暴露**）
location ~ ^/api/mobile/timeliness/(ping|me|dicts|overview|approvals|events|stats|approvals/sync) {
    proxy_pass http://10.10.8.84:3000;
    proxy_set_header Host $host;
    proxy_read_timeout 60s;
}
# 其余 /api/mobile/... 一律 403（在外网侧直接拦截，不到源站）
location /api/mobile/ { return 403; }
```

要点：
- 外网打开链接统一为企微 OAuth 授权链（见 §五B），免登凭证只经 HttpOnly Cookie 下发（2026-11-17 直签发：回调 302 的 Location 不再携带 `?empno=`，凭证不留 URL）。
- 当前版本的工号直登默认关闭。内网显式开启 `MOBILE_TIMELINESS_EMPNO_LOGIN=true` 时，已配置病历时效查看范围的账号、时效查看员、医疗部和系统管理员仍需通过企微 OAuth 或密码登录。外网仅透传 OAuth 登录入口。
- 内网启用工号直登时，按工号限流为 5 次/5 分钟，全局限流为 60 次/分钟。

### 病历时效查看范围（2026-11-18 本地实现）

- PC 和企微 OAuth 使用同一系统账号。管理员在「用户与权限 → 用户」建立或编辑账号，企微 `userid` 要与系统用户名完全一致。科室填写人员实际所属科室。
- 目录同步的员工在用户列表显示「待分配」，可按工号或姓名查询。待分配员工在企微验证身份、且 HIS 人员有效时，保留原有本科室只读访问。管理员分配角色并启用后，企微使用正式账号权限。正式禁用会停止该账号的企微访问。
- 旧线上版本的同步账号在管理页面暂显示为禁用。升级时会将本批仍未修改的账号标记为「待分配」，保留企微本科室只读登录。上线前需逐个核对同步后已被编辑过、仍需保留原有企微权限的账号，避免自动重开人工停用账号。
- 个人跨科人员可选「时效查看员」，并在用户编辑页配置「全院」和「优先显示本科室」。医疗部可在「角色授权」选择「医疗部」，设置「全院」和「显示全部授权科室」，再给人员分配该角色。全院查看范围由管理员保存后生效。
- 个人配置优先于角色配置。所选科室与批准范围取交集。查看权限、导出、审批与豁免分别校验。新角色初始只获病历时效查看权限。
- 升级后，旧会话中的管理员与受控账号需通过 PC 密码或企微工作台重新登录。外网代理应透传 `POST /api/mobile/timeliness/logout` 供 H5 清除会话 Cookie。

### 已启用员工的电脑端首次登录

- 当前已给有效且科室已匹配的员工开通「时效查看员」，默认本科室只读。未匹配科室的人员继续待分配。
- 员工从企微工作台重新进入，点击「设置个人密码」，输入初始密码，再设置至少 12 个字符的个人密码。以后在电脑端用工号和个人密码登录。
- `POST /api/mobile/timeliness/me` 走现有 `/me` 代理路径。请求使用经企业微信验证的本人会话，保留 Cookie 和 `X-Requested-With` 请求头。初始密码只用于这次设置。

## 五B、企微 OAuth 配置（用户侧参数，2026-11-17）

用户侧授权链（企业微信工作台/菜单挂此链接，`snsapi_base` 静默授权无需用户点击确认）：

```
https://open.weixin.qq.com/connect/oauth2/authorize?appid=ww9021c8e20f77fb24&redirect_uri=https%3A%2F%2Fydbi.sdent.com.cn%2Fmobile%2Fqc%2Ftimeliness%2Foauth%2Fwecom%2Fcallback&response_type=code&scope=snsapi_base&state=empno&agentid=1000033#wechat_redirect
```

- 回调路径 `/mobile/qc/timeliness/oauth/wecom/callback` 源站已实现：code→userid（relay 代换或直连 qyapi）→ **直签发 HttpOnly 会话 Cookie** → 302 干净 H5（应用库账号保留角色权限；无应用库账号回退 HIS 有效员工只读虚拟身份）。
- 需要运维在源站 `config/config.json` 增加（或容器 env）**企微凭据**（secret 由管理员填写，勿经聊天传递）：
  ```json
  "wecom": {
    "corpid": "ww9021c8e20f77fb24",
    "agentid": "1000033",
    "secret": "<在企微管理后台-自建应用-查看Secret>",
    "relay_url": "<前置机代换地址（84 无公网出口时必需）>",
    "relay_hmac_key": "<与前置机约定的 HMAC 密钥>"
  }
  ```
- 企业微信管理后台需把 `ydbi.sdent.com.cn` 配置为该自建应用的**可信域名**。
- 未配置凭据时回调自动回退 H5 登录表单（不裸报错），可先行映射后补配。

## 六、安全要求与边界

1. **鉴权边界**：页面外壳与免登接口无需登录即可触达（免登接口仅接受「已按工号建账」的在用账号，且限流 5 次/5 分钟、签发 8h 短时 JWT）；其余 `/api/mobile/*` 全部要求 JWT（未带 Token 一律 403）。代理侧无需再做一层认证，但**强烈建议**：
   - 来源 IP 白名单（仅医院内网/企微回调网段）；
   - 前置 HTTPS（企业微信「工作台自建应用主页」与可信域名要求 HTTPS）；
   - 不要把 `?empno=` 链接公开扩散（知道工号即可查看其权限范围内的质控数据）。
2. **写路径说明**：本 H5 当前运行在**安全只读模式**（源站写闸 `jhemr_write.enabled=False`）——「同意解锁」操作会引导用户去嘉和客户端完成，代理侧无真实写库风险暴露。
3. **故障回滚**：删掉前置机映射即完全回滚，源站零改动、零依赖。

---

## 七、排障速查

| 现象 | 定位点 |
| --- | --- |
| 页面 200 但白屏 | 检查 `/scripts/mobile/vue.global.prod.js` 是否 200（Vue 桥接约 1MB）；检查代理是否改写了响应体 |
| 免登后一直转圈/回登录 | 抓包看 `POST …/login/empno` 返回码：401=工号未建账/停用；429=触发限流（5 次/5 分钟）；502/504=代理到源站不通 |
| 页面提示「工号免登失败」 | 属预期兜底：工号未绑定系统账号 → 改手动登录，或按工号建账后重试 |
| 样式错乱 | `/styles/mobile/` 未转发或被缓存改写 |
| 企微内打开提示域名不可信 | 工作台自建应用需配置可信域名并使用 HTTPS（收藏夹方式可直接打开） |
| 医生端告警消息打不开 | `/mobile/qc/` 前缀未整段转发（漏了原有告警详情页） |

---

## 八、版本与变更记录

| 日期 | 变更 |
| --- | --- |
| 2026-11-16 | 手机端 H5 门户上线（:3000 五前缀转发打通，双端口冒烟 14/14） |
| 2026-11-17 | 工号免登 `?empno=` 上线（`/login/empno`；8h JWT；限流；env 可关）；HTML 资源版本参数升至 `v=20261117` |
| 2026-11-17（晚） | OAuth 回调直签发增强（Cookie 下发、Location 去凭证）+ 免登全局限流 60 次/分钟 + §五A 外网最小暴露面基线 + §五B OAuth 配置说明 |
| 待对接 | 外部前置机映射（本文档） |
