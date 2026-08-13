/** 仅管理员可编辑推送 marker；后端仍是最终权限裁决。 */
export function canEditPushMarker(role: unknown): boolean {
  return String(role || '').trim().toLowerCase() === 'admin'
}
