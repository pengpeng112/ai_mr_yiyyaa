import { createApp } from 'vue'
import { createPinia } from 'pinia'
// 按需组件样式由 unplugin-vue-components 注入；命令式 API 需显式样式
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import 'element-plus/es/components/notification/style/css'
import App from './App.vue'
import router from './router'
import './styles/global.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
