# 内网 10.10.8.84 端口分流与路由映射

> 最后更新：2026-05-29  
> 配置人：med-audit 运维  
> 服务器：10.10.8.84

---

## 端口与容器映射

| 宿主机端口 | 监听进程 | 转发目标 | 说明 |
|---|---|---|---|
| `3000` | **nginx** | 见下方路由表 | 统一入口，按 URL 前缀分流 |
| `3001` | docker-proxy | `ai-hms-frontend:80` | 血透前端（不对外暴露） |
| `8000` | docker-proxy | `med-audit:8000` | 质控系统 |
| `8080` | docker-proxy | `ai-hms-backend:8080` | 血透后端 |

---

## URL 路由规则（nginx 分流）

```
                           ┌──────────────────────────┐
                           │  nginx :3000             │
                           │  /etc/nginx/conf.d/      │
                           │  port-3000-router.conf   │
                           └──────────────────────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              │                        │                        │
    /mobile/qc/*               /api/mobile/*              所有其他路径
              │                        │                        │
              ▼                        ▼                        ▼
    10.10.8.84:8000            10.10.8.84:8000           10.10.8.84:3001
    med-audit 容器              med-audit 容器              ai-hms-frontend 容器
    (质控 H5 页面)              (质控 API)                 (血透前端)
```

| URL 前缀 | 转发地址 | 服务 |
|---|---|---|
| `/mobile/qc/` | `http://127.0.0.1:8000/mobile/qc/` | 质控医生端 H5 页面 |
| `/styles/mobile/` | `http://127.0.0.1:8000/styles/mobile/` | 质控 H5 静态样式 |
| `/scripts/mobile/` | `http://127.0.0.1:8000/scripts/mobile/` | 质控 H5 静态脚本 |
| `/qc-api/` | `http://127.0.0.1:8000/api/mobile/` | 前置机/公网 H5 质控 API 代理 |
| `/api/mobile/` | `http://127.0.0.1:8000/api/mobile/` | 质控移动端 API |
| `/` (默认) | `http://127.0.0.1:3001/` | 血透前端（保持原样） |

---

## 完整请求链路

### 质控告警推送链路

```
RelayAlertService (med-audit 容器)
  → POST http://10.20.1.153:3000/qc-record-alert
  → 前置机 wechat-relay
  → 企业微信推送图文消息（含 detail_url）
```

### 医生点击消息后的链路

```
手机浏览器
  → https://ydbi.sdent.com.cn:29080/qc-detail/{id}?token=xxx（公网）
  → 10.20.1.153:9080（APISIX 网关）
  → 10.20.1.153:3000/qc-detail/{id}?token=xxx（wechat-relay 前置机）
  → 10.10.8.84:3000/mobile/qc/{id}?token=xxx（nginx 分流）
  → 127.0.0.1:8000/mobile/qc/{id}?token=xxx（med-audit 容器）
```

### 医生提交反馈链路

```
手机浏览器
  → POST 10.20.1.153:3000/qc-api/qc-feedback
  → 10.10.8.84:3000/api/mobile/qc-feedback（nginx 分流）
  → 127.0.0.1:8000/api/mobile/qc-feedback（med-audit 容器）
```

---

## nginx 配置文件

**路径**：`/etc/nginx/conf.d/port-3000-router.conf`

```nginx
# QC + Blood Dialysis router on port 3000
server {
    listen 3000;
    listen [::]:3000;
    server_name _;

    access_log /var/log/nginx/port3000.access.log main;
    error_log  /var/log/nginx/port3000.error.log;

    # ---- QC H5 pages ----
    location /mobile/qc/ {
        proxy_pass http://127.0.0.1:8000/mobile/qc/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout 10s;
    }

    # ---- QC Mobile API ----
    location /api/mobile/ {
        proxy_pass http://127.0.0.1:8000/api/mobile/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout 10s;
    }

    # ---- Blood Dialysis frontend (default) ----
    location / {
        proxy_pass http://127.0.0.1:3001/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## docker-compose 端口修改

**文件**：`/opt/ai-hms-docker/docker-compose.yml`（已备份 `.bak`）

```yaml
# 修改前
frontend:
  ports:
    - "${FRONTEND_PORT:-3000}:80"

# 修改后（3000 交给 nginx 接管）
frontend:
  ports:
    - "${FRONTEND_PORT:-3001}:80"
```

---

## 服务管理命令

```bash
# nginx 管理
systemctl status nginx
systemctl restart nginx
nginx -t                           # 测试配置
nginx -s reload                    # 热重载

# 查看端口
ss -tlnp | grep -E "3000|3001|8000"

# 验证路由
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/                    # 血透
curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:3000/mobile/qc/1?token=test"  # 质控H5
curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:3000/api/mobile/qc-detail/1?token=test"  # 质控API

# 日志
tail -f /var/log/nginx/port3000.access.log
tail -f /var/log/nginx/port3000.error.log
```

---

## 验证结果（2026-05-29 16:43）

| 测试 | 结果 |
|---|---|
| `GET /` (血透) | **HTTP 200** |
| `GET /mobile/qc/1?token=test` (质控H5) | **HTTP 200** |
| `GET /api/mobile/qc-detail/1?token=test` (质控API) | **HTTP 401** (正确——token 无效被拒绝) |
| nginx 开机自启 | **enabled** |
