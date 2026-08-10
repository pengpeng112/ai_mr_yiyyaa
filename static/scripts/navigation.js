// 过渡期 legacy fallback：分组/文案/顺序与 app/routers/menu.py 保持一致。
// 新前端不得复制整份授权目录；仅旧 static/ 入口在菜单 API 失败时使用安全兜底。

export const FALLBACK_GROUPS = [
  { id: 'workbench', label: '工作台', icon: '', order: 10 },
  { id: 'quality', label: '质控中心', icon: '', order: 20 },
  { id: 'closure', label: '闭环管理', icon: '', order: 30 },
  { id: 'tasks', label: '任务中心', icon: '', order: 40 },
  { id: 'governance', label: '规则与配置', icon: '', order: 50 },
  { id: 'system', label: '系统管理', icon: '', order: 60 },
];

/** 菜单 API 失败时的安全兜底：仅核心只读业务，不含配置/运维/占位 */
export const SAFE_FALLBACK_MENU = [
  { id: 'dashboard', label: '工作台', icon: '', group: 'workbench', order: 10, target: { activeMenu: 'dashboard' } },
  { id: 'patient-qc', label: '患者质控', icon: '', group: 'quality', order: 10, target: { activeMenu: 'patient-qc' } },
  { id: 'audit', label: '质控记录', icon: '', group: 'quality', order: 20, target: { activeMenu: 'audit' } },
  { id: 'relay-alert-logs', label: '告警记录', icon: '', group: 'closure', order: 10, target: { activeMenu: 'relay-alert-logs' } },
  { id: 'feedback', label: '整改反馈', icon: '', group: 'closure', order: 20, target: { activeMenu: 'feedback' } },
];

/** 完整目录镜像（过渡期与后端 MENU_CATALOG 对齐；不含 hidden 占位） */
export const FALLBACK_MENU = [
  { id: 'dashboard', label: '工作台', icon: '', group: 'workbench', order: 10, route_name: 'workbench', target: { activeMenu: 'dashboard' } },
  { id: 'patient-qc', label: '患者质控', icon: '', group: 'quality', order: 10, route_name: 'quality-patients', target: { activeMenu: 'patient-qc' } },
  { id: 'audit', label: '质控记录', icon: '', group: 'quality', order: 20, route_name: 'quality-records', target: { activeMenu: 'audit' } },
  { id: 'relay-alert-logs', label: '告警记录', icon: '', group: 'closure', order: 10, route_name: 'closure-alerts', target: { activeMenu: 'relay-alert-logs' } },
  { id: 'feedback', label: '整改反馈', icon: '', group: 'closure', order: 20, route_name: 'closure-feedback', target: { activeMenu: 'feedback' } },
  { id: 'push', label: '手动推送', icon: '', group: 'tasks', order: 10, route_name: 'tasks-push', target: { activeMenu: 'push' } },
  { id: 'push-progress', label: '任务进度', icon: '', group: 'tasks', order: 20, route_name: 'tasks-progress', target: { activeMenu: 'push-progress' } },
  { id: 'scheduler', label: '定时任务', icon: '', group: 'tasks', order: 30, route_name: 'tasks-scheduler', target: { activeMenu: 'scheduler' } },
  { id: 'audit-types', label: '质控类型', icon: '', group: 'governance', order: 10, route_name: 'governance-audit-types', target: { activeMenu: 'audit-types' } },
  { id: 'config', label: '系统配置', icon: '', group: 'governance', order: 20, route_name: 'governance-config', target: { activeMenu: 'config' } },
  { id: 'relay', label: '告警推送配置', icon: '', group: 'governance', order: 30, route_name: 'governance-relay', target: { activeMenu: 'relay' } },
  { id: 'config-runtime', label: '运行总览', icon: '', group: 'system', order: 10, route_name: 'system-runtime', target: { activeMenu: 'config', tab: 'runtime-summary' } },
  { id: 'health', label: '系统健康', icon: '', group: 'system', order: 20, route_name: 'system-health', target: { activeMenu: 'health' } },
  { id: 'access', label: '用户与权限', icon: '', group: 'system', order: 30, route_name: 'system-access', target: { activeMenu: 'access' } },
  { id: 'debug', label: 'Dify 调试', icon: '', group: 'system', order: 40, route_name: 'system-debug', target: { activeMenu: 'debug' }, dev_only: true },
];

const MENU_ICON_KEYS = {
  dashboard: 'dashboard',
  'patient-qc': 'patient',
  'relay-alert-logs': 'alert',
  feedback: 'feedback',
  audit: 'audit',
  push: 'push',
  scheduler: 'scheduler',
  'push-progress': 'progress',
  config: 'config',
  'audit-types': 'audit-types',
  relay: 'relay',
  'config-runtime': 'runtime',
  health: 'health',
  debug: 'debug',
  access: 'access',
  'oracle-status': 'database',
  'system-logs': 'logs',
};

const GROUP_ICON_KEYS = {
  workbench: 'workbench',
  quality: 'qc',
  closure: 'qc',
  tasks: 'push-group',
  governance: 'config-group',
  system: 'ops',
  // 兼容旧 group id（历史缓存/混用）
  qc: 'qc',
  push: 'push-group',
  config: 'config-group',
  ops: 'ops',
};

export function buildMenuTree(menuItems = [], groups = FALLBACK_GROUPS) {
  const visibleItems = (menuItems || [])
    .filter((item) => item && !item.hidden)
    .slice()
    .sort((a, b) => Number(a.order || 999) - Number(b.order || 999));

  const groupMap = new Map(
    (groups || FALLBACK_GROUPS)
      .slice()
      .sort((a, b) => Number(a.order || 999) - Number(b.order || 999))
      .map((group) => [
        group.id,
        {
          ...group,
          iconKey: GROUP_ICON_KEYS[group.id] || group.id || 'default',
          children: [],
        },
      ]),
  );

  visibleItems.forEach((item) => {
    const groupId = item.group || 'workbench';
    if (!groupMap.has(groupId)) {
      groupMap.set(groupId, {
        id: groupId,
        label: groupId,
        iconKey: GROUP_ICON_KEYS[groupId] || groupId || 'default',
        order: 999,
        children: [],
      });
    }
    const enriched = { ...item, iconKey: MENU_ICON_KEYS[item.id] || item.id || 'default' };
    groupMap.get(groupId).children.push(enriched);
  });

  return Array.from(groupMap.values()).filter((group) => group.children.length > 0);
}

export function flattenMenuTree(menuTree = []) {
  return menuTree.flatMap((group) => group.children || []);
}
