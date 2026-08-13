import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { assertSafeTarget, syncStatic } from './sync-static.mjs'

const fixture = mkdtempSync(join(tmpdir(), 'med-audit-sync-static-'))
try {
  const dist = join(fixture, 'dist')
  const staticRoot = join(fixture, 'static', 'ui-next')
  mkdirSync(dist, { recursive: true })
  mkdirSync(staticRoot, { recursive: true })
  writeFileSync(join(dist, 'index.html'), '<html>new</html>')
  writeFileSync(join(dist, 'new-hash.js'), 'new')
  writeFileSync(join(staticRoot, 'old-hash.js'), 'old')

  syncStatic({ dist, target: staticRoot, staticRoot })
  assert.equal(readFileSync(join(staticRoot, 'index.html'), 'utf8'), '<html>new</html>')
  assert.equal(readFileSync(join(staticRoot, 'new-hash.js'), 'utf8'), 'new')
  assert.throws(() => readFileSync(join(staticRoot, 'old-hash.js')), /ENOENT/)
  assert.throws(
    () => assertSafeTarget(join(fixture, 'static', 'other'), staticRoot),
    /must stay within/,
  )
  assert.throws(
    () => syncStatic({ dist, target: join(fixture, 'outside') }),
    /must stay within/,
  )
  console.log('sync-static mirror and target safety checks passed')
} finally {
  rmSync(fixture, { recursive: true, force: true })
}
