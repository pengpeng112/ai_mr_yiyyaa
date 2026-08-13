import { cpSync, existsSync, mkdirSync, rmSync } from 'node:fs'
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')

/**
 * 仅允许清理 static/ui-next 目录（或其子目录），防止同步参数误指向仓库外部。
 */
export function assertSafeTarget(target, staticRoot) {
  const resolvedTarget = resolve(target)
  const resolvedRoot = resolve(staticRoot)
  const rel = relative(resolvedRoot, resolvedTarget)
  if (rel === '..' || rel.startsWith(`..${sep}`) || isAbsolute(rel)) {
    throw new Error(`sync target must stay within ${resolvedRoot}`)
  }
  return resolvedTarget
}

/**
 * 将 dist 镜像到 static/ui-next。目标先清空，避免旧 hash 分包残留。
 */
export function syncStatic({ dist, target, staticRoot } = {}) {
  const source = resolve(dist || resolve(root, 'dist'))
  const defaultTarget = resolve(root, '../static/ui-next')
  const destination = assertSafeTarget(target || defaultTarget, staticRoot || defaultTarget)
  if (!existsSync(source)) {
    throw new Error(`[sync-static] dist/ missing; run vite build first: ${source}`)
  }

  mkdirSync(dirname(destination), { recursive: true })
  if (process.platform === 'win32') {
    // Windows 在超多旧 hash 文件 + 中文父路径上执行 Node rmSync 可能触发原生崩溃；
    // 目标已经过严格边界校验后，用 robocopy /MIR 获得同样的镜像语义。
    mkdirSync(destination, { recursive: true })
    const copied = spawnSync(
      'robocopy',
      [source, destination, '/MIR', '/NFL', '/NDL', '/NJH', '/NJS', '/NC', '/NS', '/NP', '/R:1', '/W:1'],
      { encoding: 'utf8' },
    )
    const code = copied.status ?? 16
    if (code >= 8) {
      throw new Error(`[sync-static] robocopy failed (${code}): ${copied.stderr || copied.stdout || ''}`)
    }
  } else {
    rmSync(destination, { recursive: true, force: true })
    cpSync(source, destination, { recursive: true, force: true })
  }
  if (!existsSync(resolve(destination, 'index.html'))) {
    throw new Error(`[sync-static] copied target has no index.html: ${destination}`)
  }
  return destination
}

const invokedPath = resolve(process.argv[1] || '')
const modulePath = resolve(fileURLToPath(import.meta.url))
const isDirectInvocation = process.platform === 'win32'
  ? invokedPath.toLowerCase() === modulePath.toLowerCase()
  : invokedPath === modulePath

if (isDirectInvocation) {
  const target = resolve(root, '../static/ui-next')
  const destination = syncStatic({
    dist: resolve(root, 'dist'),
    target,
    staticRoot: target,
  })
  console.log(`[sync-static] mirrored dist -> ${destination}`)
}
