import { cpSync, existsSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const dist = resolve(root, 'dist')
const target = resolve(root, '../static/ui-next')

if (!existsSync(dist)) {
  console.error('[sync-static] dist/ missing; run vite build first')
  process.exit(1)
}

mkdirSync(resolve(root, '../static'), { recursive: true })

if (process.platform === 'win32') {
  // robocopy 在含中文路径的 Windows 上比 rmSync/cpSync 更稳
  // 退出码 0–7 视为成功
  const r = spawnSync(
    'robocopy',
    [dist, target, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/nc', '/ns', '/np', '/R:1', '/W:1'],
    { encoding: 'utf8' },
  )
  const code = r.status ?? 1
  if (code >= 8) {
    console.error('[sync-static] robocopy failed', code, r.stderr || r.stdout)
    process.exit(1)
  }
  console.log(`[sync-static] robocopy dist -> ${target} (code ${code})`)
  process.exit(0)
}

mkdirSync(target, { recursive: true })
cpSync(dist, target, { recursive: true, force: true })
console.log(`[sync-static] copied dist -> ${target}`)
