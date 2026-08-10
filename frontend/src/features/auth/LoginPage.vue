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

onMounted(() => {
  try {
    const remembered = localStorage.getItem('remembered_username')
    if (remembered) {
      username.value = remembered
      remember.value = true
    }
  } catch {
    /* ignore */
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
  <div class="login-page">
    <div class="login-card">
      <div class="login-card__brand">
        <div class="login-card__logo">MA</div>
        <div>
          <h1>Med-Audit</h1>
          <p>医疗病历一致性质控系统</p>
        </div>
      </div>
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名">
          <el-input v-model="username" autocomplete="username" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="password"
            type="password"
            show-password
            autocomplete="current-password"
            placeholder="请输入密码"
            @keyup.enter="submit"
          />
        </el-form-item>
        <div class="login-card__row">
          <el-checkbox v-model="remember">记住用户名</el-checkbox>
        </div>
        <el-button
          type="primary"
          class="login-card__btn"
          :loading="auth.loginLoading"
          @click="submit"
        >
          登录
        </el-button>
        <p v-if="auth.loginHint" class="login-card__hint">{{ auth.loginHint }}</p>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(circle at top right, rgba(56, 189, 248, 0.18), transparent 40%),
    radial-gradient(circle at bottom left, rgba(37, 99, 235, 0.16), transparent 45%),
    #0f172a;
}
.login-card {
  width: min(420px, 100%);
  background: #fff;
  border-radius: 16px;
  padding: 28px 24px 24px;
  box-shadow: 0 20px 50px rgba(2, 6, 23, 0.35);
}
.login-card__brand {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 20px;
}
.login-card__logo {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(135deg, #38bdf8, #2563eb);
}
.login-card h1 {
  margin: 0;
  font-size: 20px;
}
.login-card p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 13px;
}
.login-card__row {
  margin-bottom: 12px;
}
.login-card__btn {
  width: 100%;
}
.login-card__hint {
  margin: 12px 0 0;
  color: #64748b;
  font-size: 12px;
}
</style>
