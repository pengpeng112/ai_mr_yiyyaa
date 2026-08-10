/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  export default component
}

import 'vue-router'

declare module 'vue-router' {
  interface RouteMeta {
    menuId?: string
    title?: string
    group?: string
    requiresAuth?: boolean
    layout?: 'app' | 'standalone'
    risk?: 'readonly' | 'business-write' | 'system-write'
    keepAlive?: boolean
    mutationsEnabled?: boolean
    public?: boolean
    publicMenu?: boolean
  }
}
