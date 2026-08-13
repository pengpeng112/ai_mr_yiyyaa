/**
 * 复制文本到剪贴板：优先 Clipboard API，失败降级 textarea + execCommand。
 *
 * navigator.clipboard 仅在 secure context（HTTPS / localhost）可用；
 * 生产若以 HTTP 暴露，必须保留 execCommand 兜底，否则复制会静默失败。
 *
 * 本函数只负责复制并返回是否成功，不弹任何 UI 提示——
 * 由调用方根据返回值自行决定 ElMessage，避免 utils 层耦合 element-plus。
 *
 * @returns 是否复制成功（内容为空返回 false）
 */
export async function copyTextToClipboard(text: string): Promise<boolean> {
  const content = String(text ?? '').trim()
  if (!content) return false
  try {
    await navigator.clipboard.writeText(content)
    return true
  } catch {
    // 降级：无 clipboard 权限 / 非 secure context
    try {
      const ta = document.createElement('textarea')
      ta.value = content
      ta.style.position = 'fixed'
      ta.style.left = '-9999px'
      ta.setAttribute('aria-hidden', 'true')
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      return ok
    } catch {
      return false
    }
  }
}
