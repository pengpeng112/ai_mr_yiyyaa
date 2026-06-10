export const FALLBACK_GROUPS = [
  { id: 'workbench', label: '工作台', icon: '', order: 10 },
  { id: 'qc', label: '质控闭环', icon: '', order: 20 },
  { id: 'push', label: '推送调度', icon: '', order: 30 },
  { id: 'config', label: '配置中心', icon: '', order: 40 },
  { id: 'ops', label: '运维管理', icon: '', order: 50 },
];

export const SAFE_FALLBACK_MENU = [
  { id: 'dashboard', label: '首页总览', icon: '', group: 'workbench', order: 10, target: { activeMenu: 'dashboard' } },
  { id: 'patient-qc', label: '患者质控', icon: '', group: 'qc', order: 20, target: { activeMenu: 'patient-qc', tab: 'patients' } },
  { id: 'feedback', label: '质控反馈', icon: '', group: 'qc', order: 30, target: { activeMenu: 'feedback' } },
];

export const FALLBACK_MENU = [
  { id: 'dashboard', label: '首页总览', icon: '', group: 'workbench', order: 10, target: { activeMenu: 'dashboard' } },
  { id: 'patient-qc', label: '患者质控', icon: '', group: 'qc', order: 20, target: { activeMenu: 'patient-qc', tab: 'patients' } },
  { id: 'relay-alert-logs', label: '前置机告警', icon: '', group: 'qc', order: 25, target: { activeMenu: 'patient-qc', tab: 'relay-alerts' } },
  { id: 'feedback', label: '质控反馈', icon: '', group: 'qc', order: 30, target: { activeMenu: 'feedback' } },
  { id: 'audit', label: '推送日志', icon: '', group: 'qc', order: 35, target: { activeMenu: 'audit' } },
  { id: 'push', label: '手动推送', icon: '', group: 'push', order: 10, target: { activeMenu: 'push' } },
  { id: 'scheduler', label: '定时任务', icon: '', group: 'push', order: 20, target: { activeMenu: 'scheduler' } },
  { id: 'config', label: '系统配置', icon: '', group: 'config', order: 10, target: { activeMenu: 'config' } },
  { id: 'audit-types', label: '审计类型', icon: '', group: 'config', order: 20, target: { activeMenu: 'audit-types' } },
  { id: 'relay', label: '企业微信推送配置', icon: '', group: 'config', order: 30, target: { activeMenu: 'relay' } },
  { id: 'config-runtime', label: '运行总览', icon: '', group: 'config', order: 40, target: { activeMenu: 'config', tab: 'runtime-summary' } },
  { id: 'health', label: '系统健康', icon: '', group: 'ops', order: 10, target: { activeMenu: 'health' } },
  { id: 'debug', label: 'Dify 调试', icon: '', group: 'ops', order: 20, target: { activeMenu: 'debug' } },
  { id: 'access', label: '权限管理', icon: '', group: 'ops', order: 30, target: { activeMenu: 'access' } },
];

export function buildMenuTree(menuItems = [], groups = FALLBACK_GROUPS) {
  const visibleItems = (menuItems || [])
    .filter((item) => item && !item.hidden)
    .slice()
    .sort((a, b) => Number(a.order || 999) - Number(b.order || 999));

  const groupMap = new Map(
    (groups || FALLBACK_GROUPS)
      .slice()
      .sort((a, b) => Number(a.order || 999) - Number(b.order || 999))
      .map((group) => [group.id, { ...group, children: [] }]),
  );

  visibleItems.forEach((item) => {
    const groupId = item.group || 'workbench';
    if (!groupMap.has(groupId)) {
      groupMap.set(groupId, { id: groupId, label: groupId, icon: '', order: 999, children: [] });
    }
    groupMap.get(groupId).children.push(item);
  });

  return Array.from(groupMap.values()).filter((group) => group.children.length > 0);
}

export function flattenMenuTree(menuTree = []) {
  return menuTree.flatMap((group) => group.children || []);
}
