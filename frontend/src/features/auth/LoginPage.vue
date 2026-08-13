<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useNavigationStore } from '@/stores/navigation'
import { ElMessage } from 'element-plus'

const auth = useAuthStore()
const nav = useNavigationStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const remember = ref(false)
const syntheticEnvironment = ref(false)
const syntheticRunId = ref('')

onMounted(async () => {
  try {
    const remembered = localStorage.getItem('remembered_username')
    if (remembered) {
      username.value = remembered
      remember.value = true
    }
  } catch {
    /* ignore */
  }
  try {
    const infoResponse = await fetch('/api/demo/info')
    if (infoResponse.ok) {
      const info = await infoResponse.json()
      syntheticEnvironment.value = info?.synthetic === true
      syntheticRunId.value = String(info?.run_id || '')
    }
    if (syntheticEnvironment.value) {
      const credentialResponse = await fetch('/api/demo/credentials')
      if (credentialResponse.ok) {
        const credential = await credentialResponse.json()
        username.value = String(credential?.username || '')
        password.value = String(credential?.password || '')
      }
    }
  } catch {
    /* production or legacy mode: no demo endpoints */
  }
})

async function submit() {
  try {
    await auth.login(username.value.trim(), password.value)
    if (remember.value) {
      localStorage.setItem('remembered_username', username.value.trim())
    } else {
      localStorage.removeItem('remembered_username')
    }
    password.value = ''
    await nav.loadMenu()
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
    if (redirect && !redirect.includes('login')) {
      await router.replace(redirect)
    } else {
      await router.replace({ name: nav.defaultRouteName })
    }
    ElMessage.success('登录成功')
  } catch {
    ElMessage.error(auth.loginHint || '登录失败')
  }
}
</script>

<template>
  <div class="login">
    <div v-if="syntheticEnvironment" class="login__synthetic">
      SYNTHETIC TEST DATA / 脱敏合成测试数据 · 12科室隔离测试
      <span v-if="syntheticRunId"> · {{ syntheticRunId }}</span>
    </div>
    <div class="login__bg" aria-hidden="true" />
    <div class="login__shell">
      <aside class="login__hero">
        <div class="login__hero-badge">山东省第二人民医院</div>
        <h1 class="login__hero-title">AI病历质控系统</h1>
        <p class="login__hero-desc">
          住院病历一致性智能核查 · 风险预警 · 闭环跟踪
        </p>
        <ul class="login__points">
          <li>多类型 AI 质控一站管理</li>
          <li>高危结果实时可追踪</li>
          <li>院内安全登录，权限分控</li>
        </ul>
      </aside>

      <section class="login__panel">
        <header class="login__panel-head">
          <div class="login__logo" aria-hidden="true">AI</div>
          <div>
            <h2>欢迎登录</h2>
            <p>请使用院内分配账号进入工作台</p>
          </div>
        </header>

        <el-form class="login__form" label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名">
            <el-input
              v-model="username"
              size="large"
              clearable
              autocomplete="username"
              placeholder="请输入用户名"
            />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="password"
              size="large"
              type="password"
              show-password
              autocomplete="current-password"
              placeholder="请输入密码"
              @keyup.enter="submit"
            />
          </el-form-item>
          <div class="login__row">
            <el-checkbox v-model="remember">记住用户名</el-checkbox>
          </div>
          <el-button
            type="primary"
            size="large"
            class="login__btn"
            :loading="auth.loginLoading"
            @click="submit"
          >
            登录系统
          </el-button>
          <p v-if="auth.loginHint" class="login__hint">{{ auth.loginHint }}</p>
        </el-form>

        <footer class="login__foot">仅供院内授权人员使用 · 请勿泄露账号密码</footer>
      </section>
    </div>
  </div>
</template>

<style scoped>
.login {
  position: relative;
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 24px;
  overflow: hidden;
  background: #0b1f3a;
}
.login__synthetic {
  position: fixed;
  z-index: 10;
  top: 0;
  left: 0;
  right: 0;
  padding: 8px 14px;
  text-align: center;
  color: #451a03;
  background: #fbbf24;
  border-bottom: 1px solid #d97706;
  font-size: 12px;
  font-weight: 750;
}
.login__bg {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse 80% 60% at 10% 20%, rgba(56, 189, 248, 0.28), transparent 55%),
    radial-gradient(ellipse 70% 50% at 90% 80%, rgba(37, 99, 235, 0.35), transparent 50%),
    linear-gradient(145deg, #07162b 0%, #0f2a4d 48%, #123a5f 100%);
}
.login__bg::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.03) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: radial-gradient(circle at center, black 20%, transparent 75%);
  opacity: 0.5;
}
.login__shell {
  position: relative;
  z-index: 1;
  width: min(920px, 100%);
  display: grid;
  grid-template-columns: 1.05fr 0.95fr;
  border-radius: 22px;
  overflow: hidden;
  box-shadow:
    0 24px 60px rgba(2, 8, 23, 0.45),
    0 0 0 1px rgba(148, 163, 184, 0.18);
  background: rgba(255, 255, 255, 0.04);
  backdrop-filter: blur(10px);
}
.login__hero {
  padding: 40px 36px;
  color: #e2e8f0;
  background:
    linear-gradient(160deg, rgba(14, 116, 144, 0.35), transparent 55%),
    linear-gradient(200deg, rgba(37, 99, 235, 0.4), transparent 60%),
    rgba(15, 23, 42, 0.55);
}
.login__hero-badge {
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12px;
  letter-spacing: 0.04em;
  color: #e0f2fe;
  background: rgba(14, 165, 233, 0.18);
  border: 1px solid rgba(125, 211, 252, 0.35);
  margin-bottom: 18px;
}
.login__hero-title {
  margin: 0 0 12px;
  font-size: clamp(26px, 3.2vw, 34px);
  line-height: 1.25;
  font-weight: 800;
  color: #f8fafc;
}
.login__hero-desc {
  margin: 0 0 28px;
  color: #94a3b8;
  font-size: 14px;
  line-height: 1.7;
  max-width: 34ch;
}
.login__points {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 12px;
}
.login__points li {
  position: relative;
  padding-left: 22px;
  font-size: 13px;
  color: #cbd5e1;
}
.login__points li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.45em;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: linear-gradient(135deg, #38bdf8, #2563eb);
  box-shadow: 0 0 0 4px rgba(56, 189, 248, 0.15);
}
.login__panel {
  background: #ffffff;
  padding: 36px 32px 28px;
  display: flex;
  flex-direction: column;
}
.login__panel-head {
  display: flex;
  gap: 14px;
  align-items: center;
  margin-bottom: 22px;
}
.login__logo {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  font-weight: 800;
  font-size: 15px;
  color: #fff;
  background: linear-gradient(135deg, #0ea5e9, #2563eb 55%, #1d4ed8);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.28);
}
.login__panel-head h2 {
  margin: 0;
  font-size: 22px;
  color: #0f172a;
}
.login__panel-head p {
  margin: 4px 0 0;
  font-size: 13px;
  color: #64748b;
}
.login__form :deep(.el-form-item__label) {
  font-weight: 600;
  color: #334155;
}
.login__form :deep(.el-input__wrapper) {
  border-radius: 10px;
  min-height: 44px;
}
.login__row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 0 0 16px;
}
.login__btn {
  width: 100%;
  height: 44px;
  font-weight: 700;
  border-radius: 10px;
  letter-spacing: 0.02em;
}
.login__hint {
  margin: 14px 0 0;
  color: #dc2626;
  font-size: 12px;
  line-height: 1.5;
}
.login__foot {
  margin-top: auto;
  padding-top: 22px;
  text-align: center;
  font-size: 12px;
  color: #94a3b8;
}

@media (max-width: 800px) {
  .login__shell {
    grid-template-columns: 1fr;
  }
  .login__hero {
    padding: 28px 24px 20px;
  }
  .login__hero-desc {
    margin-bottom: 16px;
  }
  .login__points {
    display: none;
  }
  .login__panel {
    padding: 28px 22px 22px;
  }
}
</style>
