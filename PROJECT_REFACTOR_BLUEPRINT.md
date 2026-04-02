# 医疗记录一致性审计系统 - 项目重构蓝图

> **目标**：优化架构、提升可维护性、支持长期演进  
> **重点**：前端从单文件拆分为模块化结构、后端分层规范化

---

## 一、现状分析

### 当前架构问题

| 问题 | 影响 | 优先级 |
|------|------|--------|
| 前端 `index.html` 1700+ 行单文件 | 难以维护、难以复用、难以权限控制 | **P0** |
| 后端 `main.py` 承载过多职责 | 路由注册、日志、CORS、lifespan 混在一起 | **P1** |
| 内部库用 SQLite，无迁移工具 | 后期扩展困难、备份恢复不标准 | **P1** |
| 路由层逻辑过重 | 业务逻辑分散、难以测试、难以复用 | **P1** |

---

## 二、前端重构方案（重点）

### 现状
- 单文件 Vue 2 应用，1700+ 行代码
- 所有页面、逻辑、API 调用混在一起
- 难以拆分权限、难以复用组件

### 目标架构

```
frontend/
├── public/
│   └── index.html                    # 简化的入口 HTML
├── src/
│   ├── main.js                       # Vue 应用入口
│   ├── App.vue                       # 根组件
│   ├── router/
│   │   └── index.js                  # 路由配置
│   ├── api/
│   │   ├── config.js                 # 配置管理 API
│   │   ├── push.js                   # 数据推送 API
│   │   ├── logs.js                   # 日志查询 API
│   │   ├── stats.js                  # 统计 API
│   │   ├── health.js                 # 健康检查 API
│   │   ├── notify.js                 # 通知 API
│   │   └── scheduler.js              # 定时任务 API
│   ├── stores/                       # Pinia 状态管理
│   │   ├── index.js
│   │   ├── config.js                 # 配置状态
│   │   ├── push.js                   # 推送状态
│   │   ├── user.js                   # 用户状态
│   │   └── ui.js                     # UI 状态
│   ├── components/
│   │   ├── common/
│   │   │   ├── Header.vue
│   │   │   ├── Sidebar.vue
│   │   │   ├── StatusTag.vue
│   │   │   └── LoadingSpinner.vue
│   │   ├── config/
│   │   │   ├── OracleConfig.vue
│   │   │   ├── PostgreSQLConfig.vue
│   │   │   ├── DifyConfig.vue
│   │   │   ├── DeptConfig.vue
│   │   │   ├── PushConfig.vue
│   │   │   └── NotifyConfig.vue
│   │   ├── push/
│   │   │   ├── ManualPush.vue
│   │   │   ├── PushProgress.vue
│   │   │   └── PushResult.vue
│   │   ├── logs/
│   │   │   ├── LogList.vue
│   │   │   ├── LogDetail.vue
│   │   │   └── LogExport.vue
│   │   ├── stats/
│   │   │   ├── Dashboard.vue
│   │   │   ├── TrendChart.vue
│   │   │   ├── DeptChart.vue
│   │   │   └── DimensionChart.vue
│   │   ├── health/
│   │   │   ├── HealthStatus.vue
│   │   │   └── ComponentStatus.vue
│   │   └── scheduler/
│   │       ├── SchedulerStatus.vue
│   │       └── SchedulerHistory.vue
│   ├── views/
│   │   ├── Dashboard.vue
│   │   ├── Config.vue
│   │   ├── Push.vue
│   │   ├── Logs.vue
│   │   ├── Stats.vue
│   │   ├── Health.vue
│   │   ├── Scheduler.vue
│   │   └── Debug.vue
│   ├── utils/
│   │   ├── http.js                   # HTTP 客户端
│   │   ├── format.js                 # 格式化工具
│   │   ├── storage.js                # 本地存储
│   │   └── permission.js             # 权限检查
│   ├── styles/
│   │   ├── index.css
│   │   ├── variables.css
│   │   └── theme.css
│   └── App.vue
├── package.json
├── vite.config.js
└── .env.example
```

### 前端技术栈

```json
{
  "dependencies": {
    "vue": "^3.3.0",
    "vue-router": "^4.2.0",
    "pinia": "^2.1.0",
    "axios": "^1.6.0",
    "element-plus": "^2.4.0",
    "echarts": "^5.4.0"
  },
  "devDependencies": {
    "vite": "^5.0.0",
    "@vitejs/plugin-vue": "^5.0.0",
    "sass": "^1.69.0"
  }
}
```

### 前端分层说明

#### 1. API 层 (`src/api/config.js`)

```javascript
import http from '@/utils/http'

export const configAPI = {
  // Oracle 配置
  getOracleConfig: () => http.get('/api/config/oracle'),
  saveOracleConfig: (data) => http.post('/api/config/oracle', data),
  testOracleConnection: () => http.post('/api/config/oracle/test'),
  
  // PostgreSQL 配置
  getPostgreSQLConfig: () => http.get('/api/config/postgresql'),
  savePostgreSQLConfig: (data) => http.post('/api/config/postgresql', data),
  testPostgreSQLConnection: () => http.post('/api/config/postgresql/test'),
  
  // 数据源切换
  getDataSource: () => http.get('/api/config/data-source'),
  setDataSource: (type) => http.post('/api/config/data-source', { type }),
}
```

#### 2. 状态管理 (`src/stores/config.js`)

```javascript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { configAPI } from '@/api/config'

export const useConfigStore = defineStore('config', () => {
  const dataSourceType = ref('oracle')
  const oracleConfig = ref({})
  const postgresqlConfig = ref({})
  
  const loadDataSource = async () => {
    const res = await configAPI.getDataSource()
    dataSourceType.value = res.data.type
  }
  
  const switchDataSource = async (type) => {
    await configAPI.setDataSource(type)
    dataSourceType.value = type
  }
  
  return {
    dataSourceType,
    oracleConfig,
    postgresqlConfig,
    loadDataSource,
    switchDataSource,
  }
})
```

#### 3. 组件层 (`src/components/config/OracleConfig.vue`)

```vue
<template>
  <div class="oracle-config">
    <el-form :model="form" label-width="150px">
      <el-form-item label="主机地址">
        <el-input v-model="form.host" />
      </el-form-item>
      <el-form-item label="端口">
        <el-input-number v-model="form.port" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="save">保存</el-button>
        <el-button @click="test">测试连接</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { configAPI } from '@/api/config'
import { ElMessage } from 'element-plus'

const form = ref({})

onMounted(async () => {
  const res = await configAPI.getOracleConfig()
  form.value = res.data
})

const save = async () => {
  await configAPI.saveOracleConfig(form.value)
  ElMessage.success('保存成功')
}

const test = async () => {
  const res = await configAPI.testOracleConnection()
  if (res.data.status === 'up') {
    ElMessage.success(`连接成功，延迟 ${res.data.latency_ms}ms`)
  } else {
    ElMessage.error(`连接失败: ${res.data.message}`)
  }
}
</script>
```

#### 4. 页面层 (`src/views/Config.vue`)

```vue
<template>
  <div class="config-page">
    <el-tabs v-model="activeTab">
      <el-tab-pane label="Oracle 连接" name="oracle">
        <OracleConfig />
      </el-tab-pane>
      <el-tab-pane label="PostgreSQL 连接" name="postgresql">
        <PostgreSQLConfig />
      </el-tab-pane>
      <el-tab-pane label="Dify 配置" name="dify">
        <DifyConfig />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import OracleConfig from '@/components/config/OracleConfig.vue'
import PostgreSQLConfig from '@/components/config/PostgreSQLConfig.vue'
import DifyConfig from '@/components/config/DifyConfig.vue'

const activeTab = ref('oracle')
</script>
```

#### 5. 路由配置 (`src/router/index.js`)

```javascript
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    component: () => import('@/views/Dashboard.vue'),
    meta: { title: '仪表盘' }
  },
  {
    path: '/config',
    component: () => import('@/views/Config.vue'),
    meta: { title: '配置管理', requiresAuth: true }
  },
  {
    path: '/push',
    component: () => import('@/views/Push.vue'),
    meta: { title: '数据推送' }
  },
  {
    path: '/logs',
    component: () => import('@/views/Logs.vue'),
    meta: { title: '推送日志' }
  },
  {
    path: '/stats',
    component: () => import('@/views/Stats.vue'),
    meta: { title: '数据统计' }
  },
  {
    path: '/health',
    component: () => import('@/views/Health.vue'),
    meta: { title: '系统健康' }
  },
  {
    path: '/scheduler',
    component: () => import('@/views/Scheduler.vue'),
    meta: { title: '定时任务' }
  },
  {
    path: '/debug',
    component: () => import('@/views/Debug.vue'),
    meta: { title: 'Dify 调试' }
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
```

---

## 三、后端重构方案

### 目标结构

```
app/
├── core/                             # 核心配置
│   ├── config.py                     # Pydantic Settings
│   ├── logging.py                    # 日志配置
│   ├── security.py                   # 安全相关
│   ├── lifespan.py                   # 生命周期
│   └── exceptions.py                 # 自定义异常
├── api/                              # API 层
│   ├── router.py                     # 总路由
│   └── endpoints/
│       ├── config.py
│       ├── push.py
│       ├── logs.py
│       ├── stats.py
│       └── ...
├── db/                               # 数据库层
│   ├── base.py                       # SQLAlchemy 基础
│   ├── session.py                    # 会话管理
│   ├── models/                       # ORM 模型
│   └── repositories/                 # 数据访问层
├── services/                         # 业务逻辑层
│   ├── config_service.py
│   ├── push_service.py
│   ├── data_source_service.py
│   └── ...
├── integrations/                     # 外部集成
│   ├── oracle/
│   ├── postgresql/
│   ├── dify/
│   └── notify/
├── schemas/                          # Pydantic 模型
├── utils/                            # 工具函数
├── migrations/                       # Alembic 迁移
├── static/                           # 前端构建输出
└── main.py                           # 简化入口
```

### 简化的主入口 (`app/main.py`)

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.lifespan import lifespan
from app.api.router import create_api_router

setup_logging()

app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(create_api_router())
app.mount("/", StaticFiles(directory="static/dist", html=True), name="static")
```

---

## 四、实施路线图

### Phase 1：基础重构（第 1-2 周）
- [ ] 前端从单文件拆分为 Vue 3 + Vite 工程
- [ ] 后端 `main.py` 拆分为 `core/` + `api/` + `router.py`
- [ ] 引入 Alembic 管理数据库迁移
- [ ] 配置统一用 Pydantic Settings

### Phase 2：分层完善（第 3-4 周）
- [ ] 完成 Repository 层实现
- [ ] 完成 Service 层重构
- [ ] 前端 API 层、Store 层、组件层完整拆分
- [ ] 前端路由配置

### Phase 3：功能增强（第 5-6 周）
- [ ] 多工作流策略支持
- [ ] SQL 模板中心
- [ ] 配置版本管理

### Phase 4：生产就绪（第 7-8 周）
- [ ] 完整的权限控制
- [ ] 审计日志完善
- [ ] 性能优化

---

## 五、快速开始

### 前端初始化

```bash
npm create vite@latest frontend -- --template vue
cd frontend
npm install
npm install element-plus axios pinia vue-router
npm run dev
```

### 后端初始化

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install alembic
alembic init migrations
alembic upgrade head
python -m uvicorn app.main:app --reload
```

---

**下一步**：建议优先级：**前端拆分 > 后端分层 > 数据库升级**
