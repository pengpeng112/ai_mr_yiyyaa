import { apiGet, apiPost } from '../utils/api.js?v=20260524-download-blob';

export const authMethods = {
  setupAxiosAuth() {
    axios.interceptors.request.use((config) => {
      // CSRF：Cookie 会话下的写操作必须携带自定义头（服务端 P1-03 中间件校验）
      config.headers = config.headers || {};
      config.headers['X-Requested-With'] = 'XMLHttpRequest';
      // 双轨：内存/旧 localStorage token 存在时继续携带 Bearer（兼容期），否则依赖 HttpOnly Cookie
      const token = this.authToken || localStorage.getItem('auth_token');
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
      return config;
    });

    axios.interceptors.response.use(
      (response) => response,
      (error) => {
        if (!error?.response) {
          ElementPlus.ElMessage.error('网络连接失败，请检查服务是否可达');
        } else if (error.response.status === 401) {
          this.clearAuthState();
          this.loginHint = '登录已失效，请重新登录。';
        } else if (error.response.status >= 500) {
          ElementPlus.ElMessage.error('服务器内部错误，请稍后重试');
        }
        return Promise.reject(error);
      },
    );
  },

  isValidJwtToken(token) {
    if (!token || typeof token !== 'string') return false;
    return /^[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+$/.test(token);
  },

  clearAuthState() {
    this.stopTaskPolling();
    this.isAuthenticated = false;
    this.authToken = '';
    this.currentUser = {};
    localStorage.removeItem('auth_token');
    this.clearPushIndicator();
  },

  async login() {
    if (!this.loginForm.username || !this.loginForm.password) {
      ElementPlus.ElMessage.warning('请输入用户名和密码');
      return;
    }
    this.loginLoading = true;
    try {
      const res = await apiPost('/api/users/login', this.loginForm);
      this.authToken = res.data.access_token || '';
      if (!this.isValidJwtToken(this.authToken)) {
        throw new Error('登录返回的 Token 格式无效');
      }
      // P1-03：会话凭据改由 HttpOnly Cookie 承载，不再写入 localStorage；
      // 旧 localStorage token（遗留会话）由 restoreSession 兜底读取，登出时清除。
      this.currentUser = res.data.user || {};
      this.isAuthenticated = true;
      this.loginForm.password = '';
      this.loginHint = '登录成功';
      if (this.rememberUsername) {
        localStorage.setItem('remembered_username', this.loginForm.username);
      } else {
        localStorage.removeItem('remembered_username');
      }
      ElementPlus.ElMessage.success('登录成功');
      await this.bootstrapApp();
    } catch (e) {
      this.clearAuthState();
      this.loginHint = this.getErrorMessage(e, '登录失败');
      ElementPlus.ElMessage.error(this.loginHint);
    } finally {
      this.loginLoading = false;
    }
  },

  async restoreSession() {
    // 双轨会话恢复：内存 token → 旧 localStorage token（Bearer）→ HttpOnly Cookie（同源自动携带）
    if (!this.authToken) {
      this.authToken = localStorage.getItem('auth_token') || '';
    }
    try {
      const res = await apiGet('/api/users/me');
      this.currentUser = res.data || {};
      this.isAuthenticated = true;
      await this.bootstrapApp();
    } catch (e) {
      this.clearAuthState();
    }
  },

  async logout() {
    try {
      if (this.authToken) await apiPost('/api/users/logout');
    } catch (e) {
      this.showApiError(e, '退出登录时发生异常');
    }
    this.clearAuthState();
    this.loginHint = '已退出，请重新登录。';
    this.activeMenu = 'dashboard';
    this.currentLogicalMenu = 'dashboard';
  },

  async bootstrapApp() {
    await this.loadCurrentMenu();
    await this.loadDataSource();
    await this.loadDashboard();
    await this.loadLatestPushTask({ silent: true });
  },
};
