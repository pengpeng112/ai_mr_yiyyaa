
# AI质控平台左侧菜单分类与显示样式改造方案

> 目标：只改前端菜单结构和样式，不修改后端接口，不影响现有页面功能。  
> 适用页面：AI质控平台左侧导航菜单。  
> 适用项目：`pengpeng112/ai_mr_yiyyaa`。  
> 推荐方向：将菜单从“硬编码/重复分组”调整为“配置化分组菜单 + 紧凑清晰样式”。

---

## 1. 代码现状判断

当前 GitHub 中 `backend/static/index.html` 的菜单仍是硬编码结构：

```html
<el-menu :default-active="activeMenu" @select="handleMenuSelect" style="border-right: none;">
  <el-menu-item index="dashboard"><span>🏠 仪表盘</span></el-menu-item>
  <el-menu-item index="push"><span>🚀 数据推送</span></el-menu-item>
  <el-menu-item index="logs"><span>📋 推送日志</span></el-menu-item>
  <el-menu-item index="config"><span>⚙️ 配置管理</span></el-menu-item>
  <el-menu-item index="health"><span>💚 系统监控</span></el-menu-item>
</el-menu>
```

现有菜单的主要问题：

1. 菜单项硬编码在模板中，后续扩展容易重复。
2. 一级分组、二级菜单、权限、图标、排序没有统一配置。
3. 当前截图中已经出现较多分组，但视觉上仍偏密、重复入口风险较高。
4. 左侧宽度和菜单项高度需要在“紧凑”和“可读”之间平衡。
5. 菜单点击逻辑 `handleMenuSelect(index)` 已可复用，不需要改后端。

---

## 2. 菜单分类建议

建议保留 6 个一级分组，避免过多分散：

```text
工作台
├─ 首页总览

质控闭环
├─ 患者质控
├─ 前置机告警
├─ 质控反馈
├─ 推送日志

推送调度
├─ 手动推送
├─ 定时任务
├─ 推送进度

配置中心
├─ 系统配置
├─ 审计类型
├─ 企业微信推送配置
├─ 运行总览

运维管理
├─ 系统健康
├─ Dify 调试
├─ 权限管理
├─ Oracle 连接
├─ 运行日志

开发辅助（可选，仅开发环境显示）
├─ 接口文档
├─ 页面预览
```

> **已确认（2026-06-14）**：前置机告警从患者质控 Tab 拆分为质控业务组独立菜单项；推送进度新增到推送管理组；权限管理保留在运维管理组。

### 分类原则

1. **工作台**：只放首页、今日总览类入口。
2. **质控闭环**：放患者质控、前置机告警、反馈、日志。
3. **推送调度**：放主动推送和任务调度。
4. **配置中心**：放业务参数配置。
5. **运维管理**：放系统健康、连接状态、日志。
6. **开发辅助**：只在开发环境显示，避免干扰业务用户。

---

## 3. 推荐菜单配置结构

新增前端菜单配置，避免在 HTML 里重复写分组：

```javascript
const menuGroups = [
  {
    key: 'workbench',
    title: '工作台',
    icon: '▦',
    children: [
      { key: 'dashboard', title: '首页总览', icon: '⌂' }
    ]
  },
  {
    key: 'quality',
    title: '质控闭环',
    icon: '⟳',
    children: [
      { key: 'patient_qc', title: '患者质控', icon: '👤' },
      { key: 'premachine_alert', title: '前置机告警', icon: '⚠' },
      { key: 'feedback', title: '质控反馈', icon: '💬' },
      { key: 'logs', title: '推送日志', icon: '📋' }
    ]
  },
  {
    key: 'push',
    title: '推送调度',
    icon: '▶',
    children: [
      { key: 'push_manual', title: '手动推送', icon: '▶' },
      { key: 'push_task', title: '定时任务', icon: '⏱' },
      { key: 'push_progress', title: '推送进度', icon: '📈' }
    ]
  },
  {
    key: 'config',
    title: '配置中心',
    icon: '⚙',
    children: [
      { key: 'config', title: '系统配置', icon: '⚙' },
      { key: 'audit_type', title: '审计类型', icon: '🏷' },
      { key: 'wechat_config', title: '企业微信推送配置', icon: '🔔' },
      { key: 'run_overview', title: '运行总览', icon: '📊' }
    ]
  },
  {
    key: 'ops',
    title: '运维管理',
    icon: '♥',
    children: [
      { key: 'health', title: '系统健康', icon: '♥' },
      { key: 'dify_debug', title: 'Dify 调试', icon: '🧪' },
      { key: 'access', title: '权限管理', icon: '🔒' },
      { key: 'oracle_status', title: 'Oracle 连接', icon: '🗄' },
      { key: 'system_logs', title: '运行日志', icon: '📄' }
    ]
  }
];
```

---

## 4. 模板改造建议

将原来的硬编码 `el-menu-item` 替换为配置渲染：

```html
<div class="aside">
  <div class="logo-container">
    <div class="logo-title">山东省第二人民医院</div>
    <div class="logo-subtitle">AI病历质控平台</div>
  </div>

  <div class="menu-scroll">
    <div
      v-for="group in menuGroups"
      :key="group.key"
      class="menu-group"
    >
      <div class="menu-group-title" @click="toggleMenuGroup(group.key)">
        <span class="group-left">
          <span class="group-icon">{{ group.icon }}</span>
          <span>{{ group.title }}</span>
        </span>
        <span class="group-arrow">{{ collapsedGroups[group.key] ? '⌄' : '⌃' }}</span>
      </div>

      <transition name="menu-collapse">
        <div v-show="!collapsedGroups[group.key]" class="menu-children">
          <div
            v-for="item in group.children"
            :key="item.key"
            class="menu-item"
            :class="{ active: activeMenu === item.key }"
            @click="handleMenuSelect(item.key)"
          >
            <span class="menu-icon">{{ item.icon }}</span>
            <span class="menu-text">{{ item.title }}</span>
            <span
              v-if="item.badge && item.badge > 0"
              class="menu-badge"
            >{{ item.badge }}</span>
          </div>
        </div>
      </transition>
    </div>
  </div>
</div>
```

---

## 5. CSS 样式建议

### 5.1 侧边栏整体

```css
.aside {
  width: 224px;
  background: #0f172a;
  border-right: none;
  display: flex;
  flex-direction: column;
  color: #cbd5e1;
}

.logo-container {
  height: 58px;
  padding: 10px 14px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.logo-title {
  color: #ffffff;
  font-size: 14px;
  font-weight: 700;
  line-height: 20px;
}

.logo-subtitle {
  color: #94a3b8;
  font-size: 12px;
  margin-top: 2px;
}
```

### 5.2 菜单滚动区

```css
.menu-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 8px 8px 12px;
}

.menu-scroll::-webkit-scrollbar {
  width: 4px;
}

.menu-scroll::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.35);
  border-radius: 6px;
}
```

### 5.3 分组标题

```css
.menu-group {
  margin-bottom: 6px;
}

.menu-group-title {
  height: 34px;
  padding: 0 10px;
  border-radius: 8px;
  color: #e2e8f0;
  font-size: 13px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
}

.menu-group-title:hover {
  background: rgba(255, 255, 255, 0.05);
}

.group-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.group-icon {
  width: 16px;
  text-align: center;
  color: #93c5fd;
}

.group-arrow {
  color: #64748b;
  font-size: 12px;
}
```

### 5.4 二级菜单

```css
.menu-children {
  margin: 2px 0 6px;
}

.menu-item {
  height: 34px;
  margin: 2px 0;
  padding: 0 10px 0 26px;
  border-radius: 8px;
  color: #cbd5e1;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  position: relative;
}

.menu-item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #ffffff;
}

.menu-item.active {
  background: linear-gradient(90deg, #2563eb 0%, #1d4ed8 100%);
  color: #ffffff;
  box-shadow: 0 6px 14px rgba(37, 99, 235, 0.25);
}

.menu-item.active::before {
  content: "";
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 3px;
  background: #93c5fd;
}

.menu-icon {
  width: 16px;
  text-align: center;
  font-size: 13px;
}

.menu-text {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.menu-badge {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: #ef4444;
  color: #fff;
  font-size: 11px;
  line-height: 18px;
  text-align: center;
}
```

---

## 6. JS 状态补充

在 `setup()` 中增加：

```javascript
const collapsedGroups = reactive({
  workbench: false,
  quality: false,
  push: false,
  config: false,
  ops: false
});

const toggleMenuGroup = (key) => {
  collapsedGroups[key] = !collapsedGroups[key];
};
```

并在 `return` 中暴露：

```javascript
menuGroups,
collapsedGroups,
toggleMenuGroup
```

---

## 7. 页面兼容关系

当前代码中 `handleMenuSelect(index)` 根据 `activeMenu` 加载不同页面：

```javascript
if (index === 'dashboard') loadDashboard();
if (index === 'logs') loadLogs(1);
if (index === 'health') checkHealth();
if (index === 'config') loadAllConfigs();
```

改造后要注意：

1. 如果新菜单 key 与旧 activeMenu 一致，例如 `dashboard/logs/health/config`，不需要改加载逻辑。
2. 如果新增 key，例如 `patient_qc/premachine_alert/feedback`，需要在内容区增加对应 `v-show`，或者先映射到已有页面。
3. 对于暂未开发页面，点击后不要报错，可以显示“功能建设中”。

建议增加映射：

```javascript
const handleMenuSelect = (index) => {
  activeMenu.value = index;

  if (index === 'dashboard') loadDashboard();
  if (index === 'logs') loadLogs(1);
  if (index === 'health') checkHealth();
  if (index === 'config') loadAllConfigs();

  if (index === 'patient_qc') {
    // 后续加载患者质控列表
  }
  if (index === 'premachine_alert') {
    // 后续加载前置机告警
  }
};
```

---

## 8. 菜单标题映射

原来 `menuTitles` 也要同步改为：

```javascript
const menuTitles = {
  dashboard: '首页总览',
  patient_qc: '患者质控',
  premachine_alert: '前置机告警',
  feedback: '质控反馈',
  logs: '推送日志',
  push_manual: '手动推送',
  push_task: '定时任务',
  push_progress: '推送进度',
  config: '系统配置',
  audit_type: '审计类型',
  wechat_config: '企业微信推送配置',
  run_overview: '运行总览',
  health: '系统健康',
  dify_debug: 'Dify 调试',
  access: '权限管理',
  oracle_status: 'Oracle 连接',
  system_logs: '运行日志'
};
```

---

## 9. 推荐实施步骤

### 第一阶段：只改样式和结构

1. 替换 `.aside`、`.logo-container`、菜单相关 CSS。
2. 将硬编码菜单改为 `menuGroups` 渲染。
3. 保持 `handleMenuSelect` 不变。
4. 只使用原有 `dashboard/push/logs/config/health` 入口验证。

### 第二阶段：补齐新菜单入口

1. 增加 `patient_qc` 患者质控页面容器。
2. 增加 `premachine_alert` 前置机告警页面容器。
3. 增加 `feedback` 质控反馈页面容器。
4. 暂未开发的页面显示空状态，不要跳转失败。

### 第三阶段：权限和环境控制

1. 开发辅助菜单仅开发环境显示。
2. 系统配置类菜单仅管理员显示。
3. 运维类菜单仅管理员/运维角色显示。

---

## 10. 本地 AI 执行提示词

```text
请基于 backend/static/index.html 对左侧菜单进行前端重构，不修改后端接口，不影响原有功能。

当前代码中菜单是硬编码的 el-menu-item：
dashboard、push、logs、config、health。
请改为 menuGroups 配置化渲染。

要求：
1. 侧边栏保持深色风格，宽度 224px。
2. 菜单分组为：
   - 工作台：首页总览
   - 质控闭环：患者质控、前置机告警、质控反馈、推送日志
   - 推送调度：手动推送、定时任务、推送进度
   - 配置中心：系统配置、审计类型、企业微信推送配置、运行总览
   - 运维管理：系统健康、Dify 调试、权限管理、Oracle 连接、运行日志
3. 使用 menuGroups 数组渲染菜单，不要再在模板里重复写 el-menu-item。
4. 每个分组支持展开/收起。
5. 选中菜单使用蓝色背景、白字、左侧高亮条。
6. 菜单项高度 34px，字体 13px，整体紧凑但可读。
7. 保留原有 handleMenuSelect 逻辑，dashboard/logs/health/config 必须正常加载。
8. 新增 patient_qc、premachine_alert、feedback 等菜单时，如果页面暂未完成，显示“功能建设中”，不要报错。
9. 同步更新 menuTitles。
10. 完成后回归测试：首页总览、推送日志、系统配置、系统健康均能正常打开。
```

---

## 11. 回归测试清单

1. 首页总览是否正常加载。
2. 推送日志是否正常加载。
3. 系统配置是否正常加载。
4. 系统健康是否正常加载。
5. 菜单选中态是否正确。
6. 分组展开/收起是否正常。
7. 滚动条是否不影响菜单点击。
8. 新增菜单如果未实现，是否显示“功能建设中”。
9. 刷新页面后默认菜单是否仍为首页总览。
10. 小屏幕下菜单是否仍可滚动。

---

## 当前实现状态（对照检查）

- **符合度**：75%
- **已落地**：左侧菜单已改为 5 个一级分组、配置化渲染、分组折叠、选中蓝色背景+左侧高亮条、侧边栏宽度 240px、菜单项高度 38px、原 `dashboard/push/logs/config/health` 入口正常。
- **已确认调整（2026-06-14）**：
  1. 前置机告警从患者质控 Tab 拆分为质控业务组独立菜单项。
  2. 推送进度新增到推送管理组作为独立页面。
  3. 权限管理保留在运维管理组。
- **未落地/差异**：
  1. 本文档写“运维管理”，但 `ai_mr_dashboard_ui_redesign_plan.md` 写“系统运维”，建议统一为“运维管理”。
  2. 本文档已纳入“权限管理”，与当前代码一致；但“Oracle 连接”“运行日志”尚未实现。
  3. 本文档配置中心包含“运行总览”，与当前代码一致；dashboard 计划中“运行参数”应统一为“运行总览”。
- **建议**：代码实现时直接按本文档 `menuGroups` 配置更新 `navigation.js`。
