import { apiGet, apiPost } from '../utils/api.js?v=20260524-download-blob';

export const authMethods = {
  setupAxiosAuth() {
    axios.interceptors.request.use((config) => {
      const token = this.authToken || localStorage.getItem('auth_token');
      if (token) {
        config.headers = config.headers || {};
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
      localStorage.setItem('auth_token', this.authToken);
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
    if (!this.authToken || !this.isValidJwtToken(this.authToken)) {
      this.clearAuthState();
      return;
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
