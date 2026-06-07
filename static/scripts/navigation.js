export const FALLBACK_GROUPS = [
  { id: 'workbench', label: '工作台', icon: '🏠', order: 10 },
  { id: 'qc', label: '质控业务', icon: '🧑‍⚕️', order: 20 },
  { id: 'push', label: '推送与调度', icon: '🚀', order: 30 },
  { id: 'config', label: '配置中心', icon: '⚙️', order: 40 },
  { id: 'admin', label: '系统管理', icon: '👥', order: 50 },
  { id: 'ops', label: '运维工具', icon: '🛠️', order: 60 },
];

export const SAFE_FALLBACK_MENU = [
  { id: 'dashboard', label: '仪表盘', icon: '🏠', group: 'workbench', order: 10, target: { activeMenu: 'dashboard' } },
  { id: 'patient-qc', label: '患者质控总览', icon: '🧑‍⚕️', group: 'qc', order: 20, target: { activeMenu: 'patient-qc', tab: 'patients' } },
  { id: 'feedback', label: '质控反馈', icon: '💬', group: 'qc', order: 23, target: { activeMenu: 'feedback' } },
];

export const FALLBACK_MENU = [
  { id: 'dashboard', label: '仪表盘', icon: '🏠', group: 'workbench', order: 10, target: { activeMenu: 'dashboard' } },
  { id: 'patient-qc', label: '患者质控总览', icon: '🧑‍⚕️', group: 'qc', order: 20, target: { activeMenu: 'patient-qc', tab: 'patients' } },
  { id: 'relay-alert-logs', label: '前置机告警', icon: '📨', group: 'qc', order: 21, target: { activeMenu: 'patient-qc', tab: 'relay-alerts' } },
  { id: 'relay', label: '前置机接收人配置', icon: '📡', group: 'qc', order: 22, target: { activeMenu: 'relay' } },
  { id: 'audit', label: '审计中心', icon: '📊', group: 'qc', order: 23, target: { activeMenu: 'audit' } },
  { id: 'feedback', label: '质控反馈', icon: '💬', group: 'qc', order: 24, target: { activeMenu: 'feedback' } },
  { id: 'push', label: '手动推送', icon: '🚀', group: 'push', order: 30, target: { activeMenu: 'push' } },
  { id: 'scheduler', label: '定时任务', icon: '⏰', group: 'push', order: 31, target: { activeMenu: 'scheduler' } },
  { id: 'config', label: '系统配置', icon: '⚙️', group: 'config', order: 40, target: { activeMenu: 'config' } },
  { id: 'audit-types', label: '审计类型', icon: '🧩', group: 'config', order: 41, target: { activeMenu: 'audit-types' } },
  { id: 'config-runtime', label: '运行总览', icon: '🧭', group: 'config', order: 42, target: { activeMenu: 'config', tab: 'runtime-summary' } },
  { id: 'access', label: '权限管理', icon: '👥', group: 'admin', order: 50, target: { activeMenu: 'access' } },
  { id: 'health', label: '系统健康', icon: '💚', group: 'ops', order: 60, target: { activeMenu: 'health' } },
  { id: 'debug', label: 'Dify 调试', icon: '🔧', group: 'ops', order: 61, target: { activeMenu: 'debug' } },
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
