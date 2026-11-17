import type { Router } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useNavigationStore } from '@/stores/navigation'
import { DIRECT_ACCESS_MENU_IDS, getManifestByMenuId } from './route-manifest'

export function installRouterGuards(router: Router) {
  router.beforeEach(async (to, _from, next) => {
    const auth = useAuthStore()
    const nav = useNavigationStore()

    // 公开路由
    if (to.meta.public === true) {
      if (auth.isAuthenticated && to.name === 'login') {
        next({ name: nav.defaultRouteName || 'workbench' })
        return
      }
      next()
      return
    }

    // 恢复会话
    if (!auth.isAuthenticated) {
      await auth.restoreSession()
    }

    if (!auth.isAuthenticated) {
      next({ name: 'login', query: { redirect: to.fullPath } })
      return
    }

    // 加载菜单（失败时 fail-closed，不展示默认管理员菜单）
    if (!nav.loaded && !nav.loading) {
      await nav.loadMenu()
    }

    if (nav.error && !nav.loaded) {
      if (to.name !== 'menu-error') {
        next({ name: 'menu-error' })
        return
      }
      next()
      return
    }

    const menuId = typeof to.meta.menuId === 'string' ? to.meta.menuId : ''
    if (menuId) {
      if (!getManifestByMenuId(menuId)) {
        next({ name: 'forbidden', query: { reason: 'unknown-route' } })
        return
      }
      // 侧栏隐藏的兼容直达路由（任务进度/运行摘要，均只读）：manifest 已知即放行，
      // 保证顶栏「任务」按钮、补推页内按钮与历史书签在后端 hidden 收口后仍可用。
      if (!nav.isMenuAllowed(menuId) && !DIRECT_ACCESS_MENU_IDS.has(menuId)) {
        next({ name: 'forbidden', query: { reason: 'unauthorized-menu', menuId } })
        return
      }
    }

    // 系统写页默认不 keep 脏表单：meta 已配置
    next()
  })

  router.afterEach((to) => {
    const title = typeof to.meta.title === 'string' ? to.meta.title : ''
    document.title = title ? `${title} · Med-Audit` : 'Med-Audit 质控系统'
  })
}
