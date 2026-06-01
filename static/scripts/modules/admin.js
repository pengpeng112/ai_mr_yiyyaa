import { apiDelete, apiGet, apiPost, apiPut } from '../utils/api.js?v=20260524-download-blob';

export const adminMethods = {
  switchAccessTab(tab) {
    this.accessTab = tab;
    const loaders = {
      users: () => this.loadUsersPage(),
      roles: () => this.loadRolesPage(),
      permissions: () => this.loadPermissionsPage(),
      departments: () => this.loadDepartmentsPage(),
    };
    if (loaders[tab]) loaders[tab]();
  },

  async loadUsersPage() {
    await this.runConfigAction(async () => {
      await Promise.all([this.loadUsersList(), this.loadRolesList(), this.loadDepartmentsList()]);
    });
  },

  async loadUsersList(page) {
    if (page) this.usersPage = page;
    try {
      const r = await apiGet('/api/users', { params: { page: this.usersPage, limit: this.usersLimit } });
      this.usersList = r.data.items || [];
      this.usersTotal = r.data.total || 0;
    } catch (e) {
      this.showApiError(e, '加载用户列表失败');
    }
  },

  async handleUsersPageChange(page) {
    this.usersPage = page;
    await this.loadUsersList();
  },

  openUserCreate() {
    this.userDialogMode = 'create';
    this.userForm = { id: null, username: '', password: '', full_name: '', email: '', dept_id: null, role_id: null };
    this.userDialogVisible = true;
  },

  openUserEdit(row) {
    this.userDialogMode = 'edit';
    const role = this.rolesList.find((item) => item.name === row.role);
    this.userForm = {
      id: row.id,
      username: row.username,
      password: '',
      full_name: row.full_name,
      email: row.email,
      dept_id: row.dept_id,
      role_id: role ? role.id : null,
    };
    this.userDialogVisible = true;
  },

  async submitUserForm() {
    if (!this.userForm.full_name || !this.userForm.username) {
      ElementPlus.ElMessage.warning('请填写用户名和姓名');
      return;
    }
    if (this.userForm.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.userForm.email)) {
      ElementPlus.ElMessage.warning('请输入有效邮箱地址');
      return;
    }
    if (this.userDialogMode === 'create' && (!this.userForm.password || this.userForm.password.length < 6)) {
      ElementPlus.ElMessage.warning('初始密码至少 6 位');
      return;
    }
    await this.runConfigAction(async () => {
      if (this.userDialogMode === 'create') {
        await apiPost('/api/users', {
          username: this.userForm.username,
          password: this.userForm.password,
          full_name: this.userForm.full_name,
          email: this.userForm.email,
          dept_id: this.userForm.dept_id,
          role_id: this.userForm.role_id,
        });
      } else {
        await apiPut(`/api/users/${this.userForm.id}`, {
          full_name: this.userForm.full_name,
          email: this.userForm.email,
          dept_id: this.userForm.dept_id,
          role_id: this.userForm.role_id,
        });
      }
      this.userDialogVisible = false;
      await this.loadUsersList();
    }, this.userDialogMode === 'create' ? '用户已创建' : '用户已更新');
  },

  openUserPassword(row) {
    this.userPasswordForm = { id: row.id, old_password: '', new_password: '' };
    this.userPasswordDialogVisible = true;
  },

  async changeUserPassword() {
    if (!this.userPasswordForm.new_password || this.userPasswordForm.new_password.length < 6) {
      ElementPlus.ElMessage.warning('新密码至少 6 位');
      return;
    }
    await this.runConfigAction(async () => {
      await apiPost(`/api/users/${this.userPasswordForm.id}/change-password`, {
        old_password: this.userPasswordForm.old_password || '',
        new_password: this.userPasswordForm.new_password,
      });
      this.userPasswordDialogVisible = false;
      this.userPasswordForm = { id: null, old_password: '', new_password: '' };
    }, '密码已更新');
  },

  // DEF-03 修复：禁用用户前二次确认，防止误操作
  async disableUser(row) {
    try {
      await ElementPlus.ElMessageBox.confirm(
        `确定要禁用用户「${row.full_name || row.username}」吗？禁用后该用户将无法登录。`,
        '禁用用户',
        { confirmButtonText: '确定禁用', cancelButtonText: '取消', type: 'warning' },
      );
    } catch {
      return; // 用户点取消
    }
    await this.runConfigAction(async () => {
      await apiDelete(`/api/users/${row.id}`);
      await this.loadUsersList();
    }, '用户已禁用');
  },

  async loadRolesPage() {
    await this.runConfigAction(async () => {
      await Promise.all([this.loadRolesList(), this.loadPermissionsList(), this.loadDepartmentsList(), this.loadMenuCatalog()]);
    });
  },

  async loadRolesList() {
    try {
      const r = await apiGet('/api/roles');
      this.rolesList = r.data || [];
    } catch (e) {
      this.showApiError(e, '加载角色列表失败');
    }
  },

  async openRolePermissions(row) {
    await this.runConfigAction(async () => {
      const [roleResp, permissionsResp] = await Promise.all([
        apiGet(`/api/roles/${row.id}`),
        apiGet('/api/permissions'),
      ]);
      this.roleDetail = roleResp.data;
      this.permissionsList = permissionsResp.data || [];
      await Promise.all([this.loadDepartmentsList(), this.loadMenuCatalog()]);
      this.roleDialogVisible = true;
    });
  },

  async loadMenuCatalog() {
    try {
      const r = await apiGet('/api/roles/menus/catalog');
      this.menuCatalog = r.data || [];
    } catch (e) {
      this.showApiError(e, '加载菜单目录失败');
    }
  },

  async assignRolePermission(permissionId) {
    await this.runConfigAction(async () => {
      await apiPost(`/api/roles/${this.roleDetail.id}/permissions/${permissionId}`);
      await this.openRolePermissions(this.roleDetail);
      await this.loadRolesList();
    }, '权限已分配');
  },

  async revokeRolePermission(permissionId) {
    await this.runConfigAction(async () => {
      await apiDelete(`/api/roles/${this.roleDetail.id}/permissions/${permissionId}`);
      await this.openRolePermissions(this.roleDetail);
      await this.loadRolesList();
    }, '权限已移除');
  },

  async assignRoleMenu(menuId) {
    await this.runConfigAction(async () => {
      await apiPost(`/api/roles/${this.roleDetail.id}/menus/${menuId}`);
      await this.openRolePermissions(this.roleDetail);
      await this.loadRolesList();
    }, '菜单已分配');
  },

  async revokeRoleMenu(menuId) {
    await this.runConfigAction(async () => {
      await apiDelete(`/api/roles/${this.roleDetail.id}/menus/${menuId}`);
      await this.openRolePermissions(this.roleDetail);
      await this.loadRolesList();
    }, '菜单已移除');
  },

  async assignRoleDepartment(deptId) {
    await this.runConfigAction(async () => {
      await apiPost(`/api/roles/${this.roleDetail.id}/departments/${deptId}`);
      await this.openRolePermissions(this.roleDetail);
      await this.loadRolesList();
    }, '科室已分配');
  },

  async revokeRoleDepartment(deptId) {
    await this.runConfigAction(async () => {
      await apiDelete(`/api/roles/${this.roleDetail.id}/departments/${deptId}`);
      await this.openRolePermissions(this.roleDetail);
      await this.loadRolesList();
    }, '科室已移除');
  },

  async loadPermissionsPage() {
    await this.runConfigAction(async () => {
      await this.loadPermissionsList();
    });
  },

  async loadPermissionsList() {
    try {
      const params = {};
      if (this.permissionFilter.module) params.module = this.permissionFilter.module;
      const r = await apiGet('/api/permissions', { params });
      this.permissionsList = r.data || [];
    } catch (e) {
      this.showApiError(e, '加载权限列表失败');
    }
  },

  resetPermissionFilter() {
    this.permissionFilter = { module: '' };
    this.loadPermissionsList();
  },

  openPermissionCreate() {
    this.permissionDialogMode = 'create';
    this.permissionForm = { id: null, name: '', description: '', module: '' };
    this.permissionDialogVisible = true;
  },

  openPermissionEdit(row) {
    this.permissionDialogMode = 'edit';
    this.permissionForm = { id: row.id, name: row.name, description: row.description, module: row.module };
    this.permissionDialogVisible = true;
  },

  async submitPermissionForm() {
    if (!this.permissionForm.name) {
      ElementPlus.ElMessage.warning('请填写权限名');
      return;
    }
    await this.runConfigAction(async () => {
      if (this.permissionDialogMode === 'create') {
        await apiPost('/api/permissions', this.permissionForm);
      } else {
        await apiPut(`/api/permissions/${this.permissionForm.id}`, {
          description: this.permissionForm.description,
          module: this.permissionForm.module,
        });
      }
      this.permissionDialogVisible = false;
      await this.loadPermissionsList();
      if (this.rolesList.length) await this.loadRolesList();
    }, this.permissionDialogMode === 'create' ? '权限已创建' : '权限已更新');
  },

  // DEF-04 修复：删除权限前二次确认
  async deletePermission(row) {
    try {
      await ElementPlus.ElMessageBox.confirm(
        `确定要删除权限「${row.name}」吗？删除后已分配该权限的角色将失去此权限。`,
        '删除权限',
        { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning' },
      );
    } catch {
      return;
    }
    await this.runConfigAction(async () => {
      await apiDelete(`/api/permissions/${row.id}`);
      await this.loadPermissionsList();
      if (this.rolesList.length) await this.loadRolesList();
    }, '权限已删除');
  },

  async loadDepartmentsPage() {
    await this.runConfigAction(async () => {
      await Promise.all([this.loadDepartmentsList(), this.loadUsersList(1)]);
    });
  },

  async loadDepartmentsList() {
    try {
      const r = await apiGet('/api/departments');
      this.departmentsList = r.data || [];
    } catch (e) {
      this.showApiError(e, '加载科室列表失败');
    }
  },

  openDepartmentCreate() {
    this.departmentDialogMode = 'create';
    this.departmentForm = { id: null, name: '', code: '', manager_id: null };
    this.departmentDialogVisible = true;
  },

  openDepartmentEdit(row) {
    this.departmentDialogMode = 'edit';
    this.departmentForm = { id: row.id, name: row.name, code: row.code, manager_id: row.manager_id };
    this.departmentDialogVisible = true;
  },

  async submitDepartmentForm() {
    if (!this.departmentForm.name) {
      ElementPlus.ElMessage.warning('请填写科室名称');
      return;
    }
    await this.runConfigAction(async () => {
      if (this.departmentDialogMode === 'create') {
        await apiPost('/api/departments', {
          name: this.departmentForm.name,
          code: this.departmentForm.code,
          manager_id: this.departmentForm.manager_id,
        });
      } else {
        await apiPut(`/api/departments/${this.departmentForm.id}`, {
          name: this.departmentForm.name,
          code: this.departmentForm.code,
          manager_id: this.departmentForm.manager_id,
        });
      }
      this.departmentDialogVisible = false;
      await this.loadDepartmentsList();
    }, this.departmentDialogMode === 'create' ? '科室已创建' : '科室已更新');
  },

  // DEF-04 修复：删除科室前二次确认
  async deleteDepartment(row) {
    try {
      await ElementPlus.ElMessageBox.confirm(
        `确定要删除科室「${row.name}」吗？删除后关联该科室的用户将失去科室归属。`,
        '删除科室',
        { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning' },
      );
    } catch {
      return;
    }
    await this.runConfigAction(async () => {
      await apiDelete(`/api/departments/${row.id}`);
      await this.loadDepartmentsList();
    }, '科室已删除');
  },
};
