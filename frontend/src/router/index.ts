import { createRouter, createWebHashHistory } from 'vue-router'
import { buildAppRoutes } from './route-manifest'
import { installRouterGuards } from './guards'

const router = createRouter({
  history: createWebHashHistory('/ui-next/'),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/features/auth/LoginPage.vue'),
      meta: { public: true, layout: 'standalone', title: '登录' },
    },
    {
      path: '/',
      component: () => import('@/layouts/AppShell.vue'),
      meta: { requiresAuth: true, layout: 'app' },
      children: [
        {
          path: '',
          name: 'home',
          redirect: () => {
            // 由守卫后的导航 store 决定；此处先到工作台
            return { name: 'workbench' }
          },
        },
        ...buildAppRoutes(),
        {
          path: 'forbidden',
          name: 'forbidden',
          component: () => import('@/features/system/ForbiddenPage.vue'),
          meta: {
            title: '无权限',
            requiresAuth: true,
            layout: 'app',
            publicMenu: true,
          },
        },
        {
          path: 'menu-error',
          name: 'menu-error',
          component: () => import('@/features/system/MenuErrorPage.vue'),
          meta: {
            title: '菜单加载失败',
            requiresAuth: true,
            layout: 'app',
            publicMenu: true,
          },
        },
        {
          path: 'server-error',
          name: 'server-error',
          component: () => import('@/features/system/ServerErrorPage.vue'),
          meta: {
            title: '服务异常',
            requiresAuth: true,
            layout: 'app',
            publicMenu: true,
          },
        },
        {
          path: ':pathMatch(.*)*',
          name: 'not-found',
          component: () => import('@/features/system/NotFoundPage.vue'),
          meta: {
            title: '页面不存在',
            requiresAuth: true,
            layout: 'app',
            publicMenu: true,
          },
        },
      ],
    },
  ],
  scrollBehavior(to, _from, saved) {
    if (saved) return saved
    if (to.hash) return { el: to.hash, behavior: 'smooth' }
    return { top: 0 }
  },
})

installRouterGuards(router)

export default router
