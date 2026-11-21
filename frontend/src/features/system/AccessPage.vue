<template>
  <div class="page-access">
    <PageHeader
      title="用户与权限管理"
      description="全院账号、菜单可见权限与科室数据查询范围（双层授权中心）。"
    >
      <template #actions>
        <el-button :loading="loading" @click="loadAll">刷新</el-button>
      </template>
    </PageHeader>

    <el-tabs v-model="activeTab" class="access-tabs">
      <!-- ─────────── Tab 1 用户管理 ─────────── -->
      <el-tab-pane label="用户管理" name="users">
        <FilterPanel title="用户筛选" :collapsible="false" @search="resetAndLoad" @reset="resetFilters">
          <div class="acc-filter-row">
            <label class="acc-filter-item">
              <span class="ma-field__label">工号或姓名</span>
              <el-input
                v-model="filters.q"
                clearable
                :maxlength="100"
                placeholder="姓名 / 账号 / 工号，回车查询"
                style="width: 200px"
                @keyup.enter="resetAndLoad"
                @clear="resetAndLoad"
              />
            </label>
            <label class="acc-filter-item">
              <span class="ma-field__label">角色</span>
              <el-select v-model="filters.role_id" clearable filterable placeholder="全部" style="width: 150px" @change="resetAndLoad">
                <el-option label="未分配角色" value="unassigned" />
                <el-option v-for="role in roles" :key="role.id" :label="roleLabel(role.name)" :value="role.id" />
              </el-select>
            </label>
            <label class="acc-filter-item">
              <span class="ma-field__label">所属科室</span>
              <el-select
                v-model="filters.dept_id"
                clearable
                filterable
                remote
                :remote-method="searchDeptOptions"
                :loading="deptSearching"
                reserve-keyword
                placeholder="输入科室名称/编码搜索"
                style="width: 200px"
                @change="resetAndLoad"
                @focus="searchDeptOptions('')"
              >
                <el-option v-for="dept in deptOptions" :key="dept.id" :label="`${dept.name}（${dept.code || '无编码'}）`" :value="dept.id" />
              </el-select>
            </label>
            <label class="acc-filter-item">
              <span class="ma-field__label">账号状态</span>
              <el-select v-model="filters.status" clearable placeholder="全部" style="width: 130px" @change="resetAndLoad">
                <el-option label="已启用" value="active" />
                <el-option label="已停用" value="disabled" />
                <el-option label="待分配" value="pending" />
              </el-select>
            </label>
            <label class="acc-filter-item">
              <span class="ma-field__label">数据范围</span>
              <el-select v-model="filters.scope" clearable placeholder="全部" style="width: 150px" @change="resetAndLoad">
                <el-option label="全院" value="all" />
                <el-option label="仅本科室" value="home" />
                <el-option label="指定多科室" value="selected" />
              </el-select>
            </label>
          </div>
        </FilterPanel>

        <!-- 批量工具条 -->
        <div class="batch-bar">
          <div class="batch-left">
            <span class="batch-count">已选 <b>{{ selectedIds.length }}</b> 人</span>
            <el-button size="small" :disabled="!selectedIds.length" @click="openBatch('role')">批量分配角色</el-button>
            <el-button size="small" :disabled="!selectedIds.length" @click="openBatch('scope')">批量设置数据范围</el-button>
            <el-button size="small" :disabled="!selectedIds.length" @click="openBatch('status')">批量启用/停用</el-button>
          </div>
          <el-button type="primary" data-testid="create-user" @click="openUser()">新建用户</el-button>
        </div>

        <DataTableShell :loading="loading" :error="error" :empty="!loading && !users.length" :total="total" :page="page" :page-size="pageSize" @update:page="onPageChange" @update:pageSize="onPageSizeChange" @retry="loadAll">
          <el-table
            ref="userTableRef"
            :data="users"
            stripe
            border
            size="small"
            :max-height="tableMaxHeight"
            @selection-change="onSelectionChange"
          >
            <el-table-column type="selection" width="40" fixed="left" />
            <el-table-column label="姓名与工号" width="160" fixed="left">
              <template #default="{ row }">
                <div class="acc-cell-main"><b>{{ row.full_name || '—' }}</b></div>
                <div class="cell-sub">{{ row.username }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="dept_name" label="所属科室" min-width="130" show-overflow-tooltip>
              <template #default="{ row }">{{ row.dept_name || '—' }}</template>
            </el-table-column>
            <el-table-column label="角色" width="130">
              <template #default="{ row }">
                <el-tag v-if="row.role" size="small" type="info">{{ roleLabel(row.role) }}</el-tag>
                <el-tag v-else size="small" type="warning">待分配</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="生效数据范围" min-width="180">
              <template #default="{ row }">
                <el-tag size="small" :type="scopeTagType(row)" effect="plain">{{ scopeText(row) }}</el-tag>
                <span v-if="row.effective_scope?.source === 'user'" class="cell-sub">（个人设置）</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90" align="center">
              <template #default="{ row }">
                <el-switch
                  :model-value="row.is_active !== false"
                  :disabled="!canDisable(row)"
                  @change="toggleUser(row as UserRow, ($event as unknown as boolean) === true)"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="160" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click.stop="openUser(row as UserRow)">编辑</el-button>
                <el-button link size="small" @click.stop="openPassword(row as UserRow)">重置密码</el-button>
              </template>
            </el-table-column>
          </el-table>
        </DataTableShell>

        <!-- 新建/编辑用户弹窗（600px，label-position top 两列） -->
        <el-dialog v-model="userDialogVisible" :title="editing ? '编辑用户' : '新建用户'" width="600px">
          <el-form label-position="top">
            <div class="acc-dialog-section-title">基础信息</div>
            <div class="acc-form-grid">
              <label class="acc-field"><span class="ma-field__label">账号</span>
                <el-input v-model="userForm.username" :disabled="!!editing" placeholder="登录账号（HIS 工号）" />
              </label>
              <label class="acc-field"><span class="ma-field__label">姓名</span>
                <el-input v-model="userForm.full_name" placeholder="真实姓名" />
              </label>
              <template v-if="!editing">
                <label class="acc-field"><span class="ma-field__label">初始密码</span>
                  <el-input v-model="userForm.password" type="password" show-password placeholder="至少 6 位" />
                </label>
                <label class="acc-field"><span class="ma-field__label">确认密码</span>
                  <el-input v-model="userForm.confirm" type="password" show-password placeholder="再次输入" />
                </label>
              </template>
              <label class="acc-field"><span class="ma-field__label">所属科室</span>
                <el-select v-model="userForm.dept_id" clearable filterable remote :remote-method="searchDeptOptions" :loading="deptSearching" reserve-keyword placeholder="搜索科室" style="width: 100%">
                  <el-option v-for="dept in deptOptions" :key="dept.id" :label="`${dept.name}（${dept.code || '无编码'}）`" :value="dept.id" />
                </el-select>
              </label>
              <label class="acc-field"><span class="ma-field__label">角色</span>
                <el-select v-model="userForm.role_id" clearable filterable placeholder="未分配" style="width: 100%">
                  <el-option v-for="role in roles" :key="role.id" :label="roleLabel(role.name)" :value="role.id" />
                </el-select>
              </label>
              <label class="acc-field"><span class="ma-field__label">邮箱</span>
                <el-input v-model="userForm.email" placeholder="选填" />
              </label>
              <div class="acc-field"><span class="ma-field__label">启用状态</span>
                <el-checkbox v-model="userForm.is_active">启用该账号</el-checkbox>
              </div>
            </div>
            <div class="acc-dialog-section-title">数据查询范围</div>
            <el-radio-group v-model="userScopeMode" class="acc-scope-radios">
              <el-radio value="inherit_role">跟随角色</el-radio>
              <el-radio value="all">个人设置：全院</el-radio>
              <el-radio value="home">个人设置：仅本科室</el-radio>
              <el-radio value="selected">个人设置：指定科室</el-radio>
            </el-radio-group>
            <el-select
              v-if="userScopeMode === 'selected'"
              v-model="userScopeDeptIds"
              multiple
              filterable
              remote
              collapse-tags
              collapse-tags-tooltip
              :remote-method="searchDeptOptions"
              :loading="deptSearching"
              reserve-keyword
              placeholder="搜索并选择科室"
              style="width: 100%; margin-top: 8px"
            >
              <el-option v-for="dept in deptOptions" :key="dept.id" :label="`${dept.name}（${dept.code || '无编码'}）`" :value="dept.id" />
            </el-select>
            <p class="acc-hint">「跟随角色」表示以角色默认数据范围为准；个人设置优先生效。</p>
          </el-form>
          <template #footer>
            <el-button @click="userDialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="busy('user-save')" @click="saveUser">保存</el-button>
          </template>
        </el-dialog>

        <!-- 重置密码弹窗 -->
        <el-dialog v-model="passwordDialogVisible" :title="`重置密码：${editing?.username || ''}`" width="440px">
          <el-form label-position="top">
            <label v-if="editing && requiresOldPassword(editing.id, auth.user?.id)" class="acc-field"><span class="ma-field__label">旧密码</span>
              <el-input v-model="userForm.old_password" type="password" show-password />
            </label>
            <label class="acc-field"><span class="ma-field__label">新密码</span>
              <el-input v-model="userForm.new_password" type="password" show-password placeholder="至少 6 位" />
            </label>
            <label class="acc-field"><span class="ma-field__label">确认密码</span>
              <el-input v-model="userForm.confirm" type="password" show-password placeholder="再次输入" />
            </label>
          </el-form>
          <template #footer>
            <el-button @click="passwordDialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="busy('password-save')" @click="changePassword">确认修改</el-button>
          </template>
        </el-dialog>

        <!-- 批量操作弹窗 -->
        <el-dialog v-model="batchVisible" :title="batchTitle" width="560px">
          <el-alert
            type="warning"
            :closable="false"
            class="batch-alert"
            :title="`本操作将影响 ${selectedIds.length} 名用户；超过 200 人时将自动分批提交。`"
          />
          <el-form label-position="top">
            <template v-if="batchKind === 'role'">
              <label class="acc-field"><span class="ma-field__label">批量分配角色</span>
                <el-select v-model="batchRoleId" clearable filterable placeholder="选择角色（清空=移除角色）" style="width: 100%">
                  <el-option v-for="role in roles" :key="role.id" :label="roleLabel(role.name)" :value="role.id" />
                </el-select>
              </label>
            </template>
            <template v-else-if="batchKind === 'status'">
              <label class="acc-field"><span class="ma-field__label">批量启停</span>
                <el-radio-group v-model="batchActive">
                  <el-radio :value="true">启用</el-radio>
                  <el-radio :value="false">停用</el-radio>
                </el-radio-group>
              </label>
            </template>
            <template v-else>
              <label class="acc-field"><span class="ma-field__label">数据范围</span>
                <el-radio-group v-model="batchScopeMode" class="acc-scope-radios">
                  <el-radio value="inherit_role">跟随角色</el-radio>
                  <el-radio value="all">个人设置：全院</el-radio>
                  <el-radio value="home">个人设置：仅本科室</el-radio>
                  <el-radio value="selected">个人设置：指定科室</el-radio>
                </el-radio-group>
              </label>
              <el-select
                v-if="batchScopeMode === 'selected'"
                v-model="batchScopeDeptIds"
                multiple
                filterable
                remote
                collapse-tags
                collapse-tags-tooltip
                :remote-method="searchDeptOptions"
                :loading="deptSearching"
                reserve-keyword
                placeholder="搜索并选择科室"
                style="width: 100%; margin-top: 8px"
              >
                <el-option v-for="dept in deptOptions" :key="dept.id" :label="`${dept.name}（${dept.code || '无编码'}）`" :value="dept.id" />
              </el-select>
            </template>
            <el-progress v-if="batchRunning" :percentage="batchPercent" :format="batchProgressText" style="margin-top: 10px" />
            <el-alert v-if="batchFailures.length" type="error" :closable="false" class="batch-alert"
              :title="`失败批次：${batchFailures.length} 个`" :description="batchFailures.join('；')" />
          </el-form>
          <template #footer>
            <el-button :disabled="batchRunning" @click="batchVisible = false">取消</el-button>
            <el-button type="primary" :loading="batchRunning" @click="submitBatch">开始执行</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>

      <!-- ─────────── Tab 2 角色与权限 ─────────── -->
      <el-tab-pane label="角色与权限" name="roles">
        <div class="role-layout">
          <aside class="role-rail">
            <button
              v-for="role in roles"
              :key="role.id"
              class="role-card"
              :class="{ active: selectedRole?.id === role.id }"
              @click="selectRole(role)"
            >
              <span class="role-card-name">{{ roleLabel(role.name) }}</span>
              <span class="role-card-en">{{ role.name }}</span>
              <span class="role-card-badge">{{ roleMemberCount(role.id) }} 人</span>
            </button>
            <el-tooltip content="系统预置角色由后端 RBAC 权威维护，新建角色接口暂未开放" placement="top">
              <el-button class="role-new-btn" disabled>新建角色</el-button>
            </el-tooltip>
          </aside>
          <div class="role-editor">
            <el-empty v-if="!selectedRole" description="请先选择左侧角色" />
            <template v-else>
              <!-- 粘性保存条 -->
              <div class="role-sticky-bar">
                <span class="role-sticky-label">正在配置：<b>{{ roleLabel(selectedRole.name) }}</b></span>
                <el-tag v-if="roleDirty" type="warning" size="small">有未保存修改</el-tag>
                <span class="role-sticky-spacer" />
                <el-button type="primary" :loading="busy('access-bundle')" data-testid="save-role-bundle" @click="saveRoleBundle">保存本角色权限</el-button>
              </div>

              <!-- 区块① 菜单可见权限（5 组卡） -->
              <div class="role-section">
                <h3 class="role-section-title">菜单可见权限</h3>
                <div class="menu-group-grid">
                  <el-card v-for="group in menuGroups" :key="group.key" shadow="never" class="menu-group-card">
                    <template #header>
                      <div class="menu-group-head">
                        <span>{{ group.label }}</span>
                        <el-checkbox
                          :model-value="groupAllChecked(group)"
                          @change="(value: unknown) => toggleGroup(group, value === true)"
                        >本组全选</el-checkbox>
                      </div>
                    </template>
                    <div class="menu-check-grid">
                      <el-checkbox
                        v-for="menu in group.items"
                        :key="menu.id"
                        :model-value="draftMenuIds.has(menu.id)"
                        @change="(value: unknown) => toggleMenu(menu.id, value === true)"
                      >{{ menu.label || menu.id }}</el-checkbox>
                    </div>
                  </el-card>
                </div>
              </div>

              <!-- 区块② 科室数据查询范围（三卡单选） -->
              <div class="role-section">
                <h3 class="role-section-title">科室数据查询范围</h3>
                <div class="scope-card-grid">
                  <button class="scope-card" :class="{ active: roleScopeMode === 'all' }" type="button" @click="setRoleScope('all')">
                    <b>全院数据</b>
                    <span>可查看全院所有科室的病历与时效数据</span>
                  </button>
                  <button class="scope-card" :class="{ active: roleScopeMode === 'home' }" type="button" @click="setRoleScope('home')">
                    <b>仅本人所属科室</b>
                    <span>只查看角色所属科室范围内的数据</span>
                  </button>
                  <button class="scope-card" :class="{ active: roleScopeMode === 'selected' }" type="button" @click="setRoleScope('selected')">
                    <b>指定多个科室</b>
                    <span>按下方选择的科室清单授权</span>
                  </button>
                </div>
                <template v-if="roleScopeMode === 'selected'">
                  <el-select
                    v-model="roleScopeDeptIds"
                    multiple
                    filterable
                    remote
                    collapse-tags
                    collapse-tags-tooltip
                    :remote-method="searchDeptOptions"
                    :loading="deptSearching"
                    reserve-keyword
                    placeholder="搜索并选择科室"
                    style="width: 100%; margin-top: 10px"
                  >
                    <el-option v-for="dept in deptOptions" :key="dept.id" :label="`${dept.name}（${dept.code || '无编码'}）`" :value="dept.id" />
                  </el-select>
                  <div class="scope-tags">
                    <el-tag
                      v-for="code in roleScopeDeptIds"
                      :key="code"
                      closable
                      @close="removeRoleScopeDept(code)"
                    >{{ deptLabelById(code) }}</el-tag>
                    <el-button v-if="roleScopeDeptIds.length" link size="small" @click="roleScopeDeptIds = []">清空</el-button>
                  </div>
                </template>
              </div>

              <!-- 区块③ 功能操作权限（默认折叠）+ 权限目录维护 -->
              <el-collapse v-model="permOpen" class="perm-collapse">
                <el-collapse-item name="perms">
                  <template #title><span class="perm-collapse-title">功能操作权限（按模块分组，共 {{ permissions.length }} 项）</span></template>
                  <div class="perm-module-grid">
                    <el-card v-for="mod in permissionModules" :key="mod.key" shadow="never" class="perm-module-card">
                      <template #header>{{ mod.label }}（{{ mod.items.length }}）</template>
                      <el-checkbox
                        v-for="perm in mod.items"
                        :key="perm.id"
                        :model-value="draftPermissionIds.has(perm.id)"
                        @change="(value: unknown) => togglePermission(perm.id, value === true)"
                      >{{ perm.description || perm.name }}</el-checkbox>
                    </el-card>
                  </div>
                  <el-divider content-position="left">权限目录维护</el-divider>
                  <el-table :data="permissions" size="small" border max-height="260">
                    <el-table-column prop="name" label="名称" min-width="150" />
                    <el-table-column prop="description" label="说明" min-width="180" show-overflow-tooltip />
                    <el-table-column prop="module" label="模块" width="120" />
                    <el-table-column label="操作" width="140" fixed="right">
                      <template #default="{ row }">
                        <el-button link size="small" @click="openPermission(row as Record<string, any>)">编辑</el-button>
                        <el-button link type="danger" size="small" :loading="busy(`permission-delete-${row.id}`)" @click="deletePermission(row as Record<string, any>)">删除</el-button>
                      </template>
                    </el-table-column>
                  </el-table>
                  <el-button size="small" style="margin-top: 8px" @click="openPermission()">新增权限</el-button>
                </el-collapse-item>
              </el-collapse>
            </template>
          </div>
        </div>

        <!-- 权限新增/编辑弹窗 -->
        <el-dialog v-model="permissionDialogVisible" :title="permissionEditing ? '编辑权限' : '新增权限'" width="480px">
          <el-form label-position="top">
            <label class="acc-field"><span class="ma-field__label">权限名称</span>
              <el-input v-model="permissionForm.name" :disabled="!!permissionEditing" />
            </label>
            <label class="acc-field"><span class="ma-field__label">说明</span>
              <el-input v-model="permissionForm.description" />
            </label>
            <label class="acc-field"><span class="ma-field__label">所属模块</span>
              <el-input v-model="permissionForm.module" />
            </label>
          </el-form>
          <template #footer>
            <el-button @click="permissionDialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="busy('permission-save')" @click="savePermission">保存</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>

      <!-- ─────────── Tab 3 科室目录 ─────────── -->
      <el-tab-pane label="科室目录" name="departments">
        <div class="dept-toolbar">
          <label class="acc-filter-item">
            <span class="ma-field__label">搜索科室（编码/名称）</span>
            <el-input v-model="deptKeyword" clearable placeholder="编码或名称，回车搜索" style="width: 220px" @keyup.enter="loadDeptPage" @clear="loadDeptPage" />
          </label>
          <el-button size="small" :loading="deptPageLoading" @click="loadDeptPage">查询</el-button>
          <el-button size="small" type="primary" @click="openDepartment()">新增科室</el-button>
        </div>
        <el-table v-loading="deptPageLoading" :data="deptPage.items" stripe border size="small" :max-height="tableMaxHeight">
          <el-table-column prop="code" label="编码" width="130" />
          <el-table-column prop="name" label="名称" min-width="200" show-overflow-tooltip />
          <el-table-column prop="user_count" label="用户数" width="100" align="center" />
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openDepartment(row as Record<string, any>)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="dept-pager">
          <el-pagination
            v-model:current-page="deptPage.page"
            v-model:page-size="deptPage.limit"
            :page-sizes="[20, 50, 100]"
            :total="deptPage.total"
            layout="total, sizes, prev, pager, next"
            @current-change="loadDeptPage"
            @size-change="() => { deptPage.page = 1; loadDeptPage() }"
          />
        </div>

        <el-dialog v-model="departmentDialogVisible" :title="departmentEditing ? '编辑科室' : '新增科室'" width="440px">
          <el-form label-position="top">
            <label class="acc-field"><span class="ma-field__label">科室名称</span>
              <el-input v-model="deptForm.name" placeholder="科室全称" />
            </label>
            <label class="acc-field"><span class="ma-field__label">科室编码</span>
              <el-input v-model="deptForm.code" placeholder="HIS 科室编码（选填）" />
            </label>
          </el-form>
          <template #footer>
            <el-button @click="departmentDialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="busy('department-save')" @click="saveDepartment">保存</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
// WP08（064 总计划）：全院级「用户与权限」双层授权中心（原单科试点页面重构）。
// - Tab1 用户管理：多维筛选（含 departments/paged 远程科室）+ 批量操作（batch-update
//   每批 ≤200 自动分批顺序提交+进度/失败汇总）+ 8 列表格（生效数据范围 label）+
//   新建/编辑（基础信息 + 数据范围单选，个人设置走 batch-update 单人）；
// - Tab2 角色与权限：左侧角色卡 + 右侧粘性保存条，**一次 PUT access-bundle** 保存
//   菜单/权限/数据范围（删除旧「每勾一个弹一次确认」逐项交互）；hidden 菜单不显示；
// - Tab3 科室目录：departments/paged 分页搜索 + 新增/编辑；
// - contracts 纯函数（access-contracts.ts）继续复用；X-Requested-With 由 api client 保持。
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageHeader from '@/components/base/PageHeader.vue'
import FilterPanel from '@/components/base/FilterPanel.vue'
import DataTableShell from '@/components/base/DataTableShell.vue'
import { apiDelete, apiGet, apiPost, apiPut } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { useAuthStore } from '@/stores/auth'
import {
  buildUserPayload,
  requiresOldPassword,
  roleLabel,
} from '@/utils/access-contracts'
import { splitBatches } from '@/utils/access-batch'

interface UserRow {
  id: number
  username: string
  full_name?: string
  dept_name?: string
  role?: string
  role_id?: number | null
  is_active?: boolean
  directory_pending?: boolean
  email?: string | null
  dept_id?: number | null
  timeliness_access?: { scope?: string; department_codes?: string[] } | null
  effective_scope?: { scope?: string; source?: string; label?: string } | null
}

type R = Record<string, any>

const auth = useAuthStore()
const activeTab = ref('users')
const loading = ref(false)
const error = ref('')
const users = ref<R[]>([])
const roles = ref<R[]>([])
const permissions = ref<R[]>([])
const menus = ref<R[]>([])
const selectedRole = ref<R | null>(null)
const selectedRoleDetail = ref<R | null>(null)
const tableMaxHeight = 'calc(100vh - 400px)'

const saving = ref<Record<string, boolean>>({})
function busy(key: string): boolean { return !!saving.value[key] }
function setBusy(key: string, value: boolean): void { saving.value[key] = value }
function isCancel(e: unknown): boolean { return e === 'cancel' || e === 'close' }

// ── 筛选（后端 GET /users 真实参数映射） ──
const filters = reactive({
  q: '',
  role_id: '' as string | number,
  dept_id: null as number | null,
  status: '',
  scope: '',
})
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const deptOptions = ref<Array<{ id: number; code: string; name: string }>>([])
const deptSearching = ref(false)
let deptSearchSeq = 0

/** 远程科室搜索（GET /departments/paged?keyword=&limit=20；禁平铺 640 科）。 */
async function searchDeptOptions(keyword: string): Promise<void> {
  const seq = ++deptSearchSeq
  deptSearching.value = true
  try {
    const data = await apiGet<{ items?: Array<{ id: number; code: string; name: string }> }>(
      '/departments/paged',
      { params: { keyword: (keyword || '').trim() || undefined, page: 1, limit: 20 } },
    )
    if (seq !== deptSearchSeq) return
    deptOptions.value = data.items || []
  } catch {
    if (seq === deptSearchSeq) deptOptions.value = []
  } finally {
    if (seq === deptSearchSeq) deptSearching.value = false
  }
}

function resetAndLoad(): void {
  page.value = 1
  void loadUsers()
}

function resetFilters(): void {
  filters.q = ''
  filters.role_id = ''
  filters.dept_id = null
  filters.status = ''
  filters.scope = ''
  resetAndLoad()
}

function onPageChange(next: number): void {
  page.value = next
  void loadUsers()
}

function onPageSizeChange(next: number): void {
  pageSize.value = next
  page.value = 1
  void loadUsers()
}

async function loadUsers(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, unknown> = { page: page.value, limit: pageSize.value }
    if (String(filters.q).trim()) params.q = String(filters.q).trim()
    if (filters.role_id === 'unassigned') params.unassigned_role = true
    else if (filters.role_id !== '') params.role_id = Number(filters.role_id)
    if (filters.dept_id != null) params.dept_id = filters.dept_id
    if (filters.status === 'active') params.is_active = true
    else if (filters.status === 'disabled') params.is_active = false
    else if (filters.status === 'pending') params.directory_pending = true
    if (filters.scope) params.scope = filters.scope
    const data = await apiGet<{ items: R[]; total: number }>('/users', { params })
    users.value = data.items || []
    total.value = data.total || 0
  } catch (e) {
    error.value = toUserMessage(e, '加载用户失败')
  } finally {
    loading.value = false
  }
}

/** 生效数据范围展示（effective_scope.label + source 标注）。 */
function scopeText(row: R): string {
  const scope = row.effective_scope as { label?: string; scope?: string } | null | undefined
  if (scope?.label) return scope.label
  if (row.directory_pending) return '待分配（目录账号）'
  return '未配置'
}
function scopeTagType(row: R): 'success' | 'primary' | 'warning' | 'info' {
  const scope = String(row.effective_scope?.scope || '')
  if (scope === 'all') return 'warning'      // 紫 → Element 无紫，用 warning 近似高亮
  if (scope === 'home') return 'primary'     // 蓝
  if (scope === 'selected') return 'success' // 青
  return 'info'
}

function canDisable(row: R): boolean {
  return Number(row.id) !== Number(auth.user?.id)
}

// ── 批量操作 ──
const selectedRows = ref<R[]>([])
const selectedIds = computed(() => selectedRows.value.map((row) => Number(row.id)))
function onSelectionChange(rows: R[]): void {
  selectedRows.value = rows
}

const batchVisible = ref(false)
const batchKind = ref<'role' | 'scope' | 'status'>('role')
const batchTitle = computed(() => ({
  role: '批量分配角色',
  scope: '批量设置数据范围',
  status: '批量启用/停用',
}[batchKind.value]))
const batchRoleId = ref<number | null>(null)
const batchActive = ref(true)
const batchScopeMode = ref<'inherit_role' | 'all' | 'home' | 'selected'>('inherit_role')
const batchScopeDeptIds = ref<number[]>([])
const batchRunning = ref(false)
const batchDone = ref(0)
const batchTotal = ref(0)
const batchFailures = ref<string[]>([])

const batchPercent = computed(() =>
  batchTotal.value ? Math.round((batchDone.value / batchTotal.value) * 100) : 0)
function batchProgressText(): string {
  return `已完成 ${batchDone.value} / ${batchTotal.value}`
}

function openBatch(kind: 'role' | 'scope' | 'status'): void {
  if (!selectedIds.value.length) return
  batchKind.value = kind
  batchRoleId.value = null
  batchActive.value = true
  batchScopeMode.value = 'inherit_role'
  batchScopeDeptIds.value = []
  batchDone.value = 0
  batchTotal.value = 0
  batchFailures.value = []
  batchVisible.value = true
}

/** 组装单批 batch-update 请求体（每批 ≤200，后端 400 护栏对应）。 */
function buildBatchBody(ids: number[]): Record<string, unknown> {
  const body: Record<string, unknown> = { user_ids: ids }
  if (batchKind.value === 'role') body.role_id = batchRoleId.value
  if (batchKind.value === 'status') body.is_active = batchActive.value
  if (batchKind.value === 'scope') {
    body.data_scope = {
      mode: batchScopeMode.value,
      department_codes: batchScopeMode.value === 'selected'
        ? batchScopeDeptIds.value.map(String)
        : [],
    }
  }
  return body
}

async function submitBatch(): Promise<void> {
  if (batchKind.value === 'scope' && batchScopeMode.value === 'selected'
    && !batchScopeDeptIds.value.length) {
    ElMessage.warning('指定科室模式请至少选择一个科室')
    return
  }
  const ids = [...selectedIds.value]
  const batches = splitBatches(ids)
  try {
    await ElMessageBox.confirm(
      `确认为 ${ids.length} 名用户执行「${batchTitle.value}」？将分 ${batches.length} 批提交。`,
      '批量操作确认', { type: 'warning' },
    )
  } catch {
    return
  }
  batchRunning.value = true
  batchTotal.value = ids.length
  batchDone.value = 0
  batchFailures.value = []
  for (let index = 0; index < batches.length; index++) {
    try {
      await apiPost('/users/batch-update', buildBatchBody(batches[index]))
      batchDone.value += batches[index].length
    } catch (e) {
      batchFailures.value.push(
        `第 ${index + 1} 批（${batches[index].length} 人）：${toUserMessage(e, '提交失败')}`)
    }
  }
  batchRunning.value = false
  if (batchFailures.value.length) {
    ElMessage.error(`批量操作完成，但 ${batchFailures.value.length} 个批次失败（详见弹窗汇总）`)
    return
  }
  ElMessage.success(`批量操作完成：已更新 ${batchDone.value} 名用户`)
  batchVisible.value = false
  await loadUsers()
}

// ── 用户新建/编辑 ──
const userDialogVisible = ref(false)
const passwordDialogVisible = ref(false)
const editing = ref<R | null>(null)
const userForm = reactive({
  username: '', password: '', confirm: '', full_name: '', email: '',
  dept_id: null as number | null, role_id: null as number | null, is_active: true,
  old_password: '', new_password: '',
})
const userScopeMode = ref<'inherit_role' | 'all' | 'home' | 'selected'>('inherit_role')
const userScopeDeptIds = ref<number[]>([])
/** 编辑打开时的原始范围（判断是否需要追加 data_scope 保存）。 */
let originalScopeMode = 'inherit_role'
let originalScopeDeptIds: number[] = []

function openUser(row?: R): void {
  editing.value = row || null
  Object.assign(userForm, {
    username: row?.username || '', password: '', confirm: '',
    full_name: row?.full_name || '', email: row?.email || '',
    dept_id: row?.dept_id ?? null,
    role_id: row?.role_id ?? null,
    is_active: row?.is_active !== false,
    old_password: '', new_password: '',
  })
  // 现有数据范围反推：timeliness_access（个人设置）或跟随角色
  const access = row?.timeliness_access as { scope?: string; department_codes?: string[] } | null | undefined
  if (access?.scope) {
    userScopeMode.value = access.scope as 'all' | 'home' | 'selected'
    userScopeDeptIds.value = (access.department_codes || []).map((code) => Number(code) || 0)
      .filter((id) => id > 0)
  } else {
    userScopeMode.value = 'inherit_role'
    userScopeDeptIds.value = []
  }
  originalScopeMode = userScopeMode.value
  originalScopeDeptIds = [...userScopeDeptIds.value]
  userDialogVisible.value = true
}

async function saveUser(): Promise<void> {
  if (!userForm.full_name.trim() || (!editing.value
    && (!userForm.username.trim() || userForm.password.length < 6))) {
    ElMessage.warning('请填写必填项，密码至少 6 位')
    return
  }
  if (!editing.value && userForm.password !== userForm.confirm) {
    ElMessage.warning('两次密码不一致')
    return
  }
  setBusy('user-save', true)
  try {
    const payload = buildUserPayload(userForm, !editing.value)
    if (editing.value) await apiPut(`/users/${editing.value.id}`, payload)
    else await apiPost('/users', payload)
    // 数据范围变化 → batch-update 单人（WP02 等价接口；inherit_role 也可下发）
    const scopeChanged = editing.value
      && (userScopeMode.value !== originalScopeMode
        || JSON.stringify(userScopeDeptIds.value) !== JSON.stringify(originalScopeDeptIds))
    if (editing.value && scopeChanged) {
      await apiPost('/users/batch-update', {
        user_ids: [Number(editing.value.id)],
        data_scope: {
          mode: userScopeMode.value,
          department_codes: userScopeMode.value === 'selected'
            ? userScopeDeptIds.value.map(String)
            : [],
        },
      })
    }
    userDialogVisible.value = false
    ElMessage.success('用户已保存')
    await loadUsers()
  } catch (e) {
    ElMessage.error(toUserMessage(e, '用户保存失败'))
  } finally {
    setBusy('user-save', false)
  }
}

function openPassword(row: R): void {
  editing.value = row
  userForm.old_password = ''
  userForm.new_password = ''
  userForm.confirm = ''
  passwordDialogVisible.value = true
}

async function changePassword(): Promise<void> {
  if (!editing.value || userForm.new_password.length < 6
    || userForm.new_password !== userForm.confirm
    || (requiresOldPassword(editing.value.id, auth.user?.id) && !userForm.old_password)) {
    ElMessage.warning('请正确填写密码；修改自己的密码必须填写旧密码')
    return
  }
  setBusy('password-save', true)
  try {
    await apiPost(`/users/${editing.value.id}/change-password`, {
      old_password: userForm.old_password,
      new_password: userForm.new_password,
    })
    passwordDialogVisible.value = false
    ElMessage.success('密码已修改')
  } catch (e) {
    ElMessage.error(toUserMessage(e, '密码修改失败'))
  } finally {
    setBusy('password-save', false)
  }
}

async function toggleUser(row: R, active: boolean): Promise<void> {
  if (!canDisable(row) || busy(`toggle-${row.id}`)) return
  setBusy(`toggle-${row.id}`, true)
  try {
    await ElMessageBox.confirm(
      active ? `确认启用用户 ${row.username}？` : `确认停用用户 ${row.username}？这是停用，不会物理删除。`,
      '请确认', { type: 'warning' },
    )
    if (active) await apiPut(`/users/${row.id}`, { is_active: true })
    else await apiDelete(`/users/${row.id}`)
    ElMessage.success(active ? '用户已启用' : '用户已停用')
    await loadUsers()
  } catch (e) {
    if (!isCancel(e)) ElMessage.error(toUserMessage(e, '状态更新失败'))
  } finally {
    setBusy(`toggle-${row.id}`, false)
  }
}

// ── Tab2 角色与权限 ──
const roleMemberCounts = ref<Record<number, number>>({})
const permOpen = ref<string[]>(['perms'])  // WP08：功能操作权限默认展开（e2e 直点复选框）
const roleMenuIds = ref<string[]>([])
const rolePermissionIds = ref<number[]>([])
const roleScopeMode = ref<'all' | 'home' | 'selected'>('home')
const roleScopeDeptIds = ref<string[]>([])
let originalBundle = { menuIds: [] as string[], permissionIds: [] as number[], scopeMode: 'home', scopeDeptIds: [] as string[] }

const draftMenuIds = computed(() => new Set(roleMenuIds.value))
const draftPermissionIds = computed(() => new Set(rolePermissionIds.value))

const roleDirty = computed(() => {
  if (!selectedRole.value) return false
  const scopeChanged = roleScopeMode.value !== originalBundle.scopeMode
    || JSON.stringify(roleScopeDeptIds.value) !== JSON.stringify(originalBundle.scopeDeptIds)
  const menusChanged = JSON.stringify([...roleMenuIds.value].sort())
    !== JSON.stringify([...originalBundle.menuIds].sort())
  const permsChanged = JSON.stringify([...rolePermissionIds.value].sort())
    !== JSON.stringify([...originalBundle.permissionIds].sort())
  return scopeChanged || menusChanged || permsChanged
})

function roleMemberCount(roleId: number): number {
  return roleMemberCounts.value[roleId] ?? 0
}

const MENU_GROUP_LABELS: Record<string, string> = {
  workbench: '质控总览',
  timeliness: '病历时效管理',
  quality: '内涵与终末质控',
  governance: '质控规则中心',
  system: '系统与运维',
}

const menuGroups = computed(() => {
  const groups: Record<string, Array<{ id: string; label: string }>> = {}
  for (const menu of menus.value) {
    if (menu.hidden) continue    // hidden 菜单不显示
    const key = String(menu.group || 'system')
    ;(groups[key] = groups[key] || []).push({ id: String(menu.id), label: String(menu.label || menu.id) })
  }
  return Object.entries(groups)
    .map(([key, items]) => ({ key, label: MENU_GROUP_LABELS[key] || key, items }))
    .sort((a, b) => (a.key === 'workbench' ? -1 : b.key === 'workbench' ? 1 : a.key.localeCompare(b.key)))
})

const permissionModules = computed(() => {
  const groups: Record<string, Array<R>> = {}
  for (const perm of permissions.value) {
    const key = String(perm.module || '其他')
    ;(groups[key] = groups[key] || []).push(perm)
  }
  return Object.entries(groups)
    .map(([key, items]) => ({ key, label: key, items }))
    .sort((a, b) => a.key.localeCompare(b.key))
})

function toggleMenu(menuId: string, checked: boolean): void {
  const set = new Set(roleMenuIds.value)
  if (checked) set.add(menuId)
  else set.delete(menuId)
  roleMenuIds.value = Array.from(set)
}

function groupAllChecked(group: { items: Array<{ id: string }> }): boolean {
  return group.items.every((item) => draftMenuIds.value.has(item.id))
}

function toggleGroup(group: { items: Array<{ id: string }> }, checked: boolean): void {
  const set = new Set(roleMenuIds.value)
  for (const item of group.items) {
    if (checked) set.add(item.id)
    else set.delete(item.id)
  }
  roleMenuIds.value = Array.from(set)
}

function togglePermission(permissionId: number, checked: boolean): void {
  const set = new Set(rolePermissionIds.value)
  if (checked) set.add(permissionId)
  else set.delete(permissionId)
  rolePermissionIds.value = Array.from(set)
}

function setRoleScope(mode: 'all' | 'home' | 'selected'): void {
  roleScopeMode.value = mode
  if (mode !== 'selected') roleScopeDeptIds.value = []
}

function removeRoleScopeDept(code: string): void {
  roleScopeDeptIds.value = roleScopeDeptIds.value.filter((item) => item !== code)
}

function deptLabelById(code: string): string {
  const id = Number(code)
  const dept = deptOptions.value.find((item) => item.id === id)
  return dept ? `${dept.name}（${dept.code || '无编码'}）` : `科室 ${code}`
}

function selectRole(role: R): void {
  if (selectedRole.value && roleDirty.value) {
    ElMessageBox.confirm(
      `角色「${roleLabel(selectedRole.value.name)}」有未保存修改，切换将丢弃，是否继续？`,
      '未保存修改', { type: 'warning' },
    ).then(() => {
      void applySelectedRole(role)
    }).catch(() => undefined)
    return
  }
  void applySelectedRole(role)
}

async function applySelectedRole(role: R): Promise<void> {
  selectedRole.value = role
  selectedRoleDetail.value = null
  try {
    const detail = await apiGet<R>(`/roles/${role.id}`)
    selectedRoleDetail.value = detail
    roleMenuIds.value = (detail.menus || []).map((m: R) => String(m.id))
    rolePermissionIds.value = (detail.permissions || []).map((p: R) => Number(p.id))
    const access = detail.timeliness_access as { scope?: string; department_codes?: string[] } | null | undefined
    if (access?.scope) {
      roleScopeMode.value = access.scope as 'all' | 'home' | 'selected'
      roleScopeDeptIds.value = [...(access.department_codes || [])]
    } else {
      roleScopeMode.value = 'home'
      roleScopeDeptIds.value = (detail.departments || []).map((d: R) => String(d.code || d.name || d.id))
    }
    originalBundle = {
      menuIds: [...roleMenuIds.value],
      permissionIds: [...rolePermissionIds.value],
      scopeMode: roleScopeMode.value,
      scopeDeptIds: [...roleScopeDeptIds.value],
    }
  } catch (e) {
    ElMessage.error(toUserMessage(e, '角色详情加载失败'))
  }
}

/** 保存本角色权限：一次 PUT access-bundle（menu_ids/permission_ids/data_scope）。 */
async function saveRoleBundle(): Promise<void> {
  const role = selectedRole.value
  if (!role || busy('access-bundle')) return
  if (roleScopeMode.value === 'selected' && !roleScopeDeptIds.value.length) {
    ElMessage.warning('指定科室模式请至少选择一个科室')
    return
  }
  setBusy('access-bundle', true)
  try {
    const body: Record<string, unknown> = {
      menu_ids: roleMenuIds.value,
      permission_ids: rolePermissionIds.value,
    }
    if (role.name !== 'admin') {
      // data_scope：TimelinessAccessSettings（all/home/selected）；admin 保持现状不动
      body.data_scope = {
        scope: roleScopeMode.value,
        department_codes: roleScopeMode.value === 'selected' ? roleScopeDeptIds.value : [],
        default_view: roleScopeMode.value === 'all' ? 'all' : 'home',
      }
    }
    const updated = await apiPut<R>(`/roles/${role.id}/access-bundle`, body)
    const index = roles.value.findIndex((item) => item.id === role.id)
    if (index >= 0) roles.value.splice(index, 1, updated)
    ElMessage.success(`角色「${roleLabel(role.name)}」权限已保存（菜单/权限/数据范围一次提交）`)
    await applySelectedRole(updated)
  } catch (e) {
    ElMessage.error(toUserMessage(e, '角色权限保存失败'))
  } finally {
    setBusy('access-bundle', false)
  }
}

// ── 权限目录维护（保留原 CRUD 能力） ──
const permissionDialogVisible = ref(false)
const permissionEditing = ref<R | null>(null)
const permissionForm = reactive({ name: '', description: '', module: '' })

function openPermission(row?: R): void {
  permissionEditing.value = row || null
  Object.assign(permissionForm, {
    name: row?.name || '', description: row?.description || '', module: row?.module || '',
  })
  permissionDialogVisible.value = true
}

async function savePermission(): Promise<void> {
  if (!permissionForm.name.trim()) return
  setBusy('permission-save', true)
  try {
    if (permissionEditing.value) {
      await apiPut(`/permissions/${permissionEditing.value.id}`, {
        description: permissionForm.description, module: permissionForm.module,
      })
    } else {
      await apiPost('/permissions', { ...permissionForm })
    }
    permissionDialogVisible.value = false
    ElMessage.success('权限已保存')
    await loadRoles()
  } catch (e) {
    ElMessage.error(toUserMessage(e, '权限保存失败'))
  } finally {
    setBusy('permission-save', false)
  }
}

async function deletePermission(row: R): Promise<void> {
  if (busy(`permission-delete-${row.id}`)) return
  try {
    await ElMessageBox.confirm(`确认删除权限 ${row.name}？不可恢复，且会移除角色关联。`, '删除确认', { type: 'error' })
  } catch {
    return
  }
  setBusy(`permission-delete-${row.id}`, true)
  try {
    await apiDelete(`/permissions/${row.id}`)
    await loadRoles()
  } catch (e) {
    ElMessage.error(toUserMessage(e, '权限删除失败'))
  } finally {
    setBusy(`permission-delete-${row.id}`, false)
  }
}

// ── Tab3 科室目录 ──
const deptKeyword = ref('')
const deptPage = reactive({ page: 1, limit: 20, total: 0, items: [] as Array<{ id: number; code: string; name: string; user_count: number }> })
const deptPageLoading = ref(false)
const departmentDialogVisible = ref(false)
const departmentEditing = ref<R | null>(null)
const deptForm = reactive({ name: '', code: '' })

async function loadDeptPage(): Promise<void> {
  deptPageLoading.value = true
  try {
    const data = await apiGet<{ total: number; items: typeof deptPage.items }>('/departments/paged', {
      params: {
        keyword: deptKeyword.value.trim() || undefined,
        page: deptPage.page,
        limit: deptPage.limit,
      },
    })
    deptPage.items = data.items || []
    deptPage.total = data.total || 0
  } catch (e) {
    ElMessage.error(toUserMessage(e, '科室目录加载失败'))
  } finally {
    deptPageLoading.value = false
  }
}

function openDepartment(row?: R): void {
  departmentEditing.value = row || null
  Object.assign(deptForm, { name: row?.name || '', code: row?.code || '' })
  departmentDialogVisible.value = true
}

async function saveDepartment(): Promise<void> {
  if (!deptForm.name.trim() || busy('department-save')) return
  setBusy('department-save', true)
  try {
    if (departmentEditing.value) {
      await apiPut(`/departments/${departmentEditing.value.id}`, { ...deptForm })
    } else {
      await apiPost('/departments', { ...deptForm })
    }
    departmentDialogVisible.value = false
    ElMessage.success('科室已保存')
    await loadDeptPage()
  } catch (e) {
    ElMessage.error(toUserMessage(e, '科室保存失败'))
  } finally {
    setBusy('department-save', false)
  }
}

// ── 全量加载 ──
async function loadRoles(): Promise<void> {
  const [r, p, m] = await Promise.all([
    apiGet<R[]>('/roles'),
    apiGet<R[]>('/permissions'),
    apiGet<R[]>('/roles/menus/catalog'),
  ])
  roles.value = r || []
  permissions.value = p || []
  menus.value = m || []
  if (!selectedRole.value && roles.value.length) await applySelectedRole(roles.value[0])
  // 角色人数徽章：并发 6 个 limit=1 total 查询（轻量；RoleInfo 无 user_count）
  const counts: Record<number, number> = {}
  await Promise.all(roles.value.map(async (role) => {
    try {
      const data = await apiGet<{ total: number }>('/users', {
        params: { role_id: role.id, page: 1, limit: 1 },
      })
      counts[role.id] = data.total || 0
    } catch {
      counts[role.id] = 0
    }
  }))
  roleMemberCounts.value = counts
}

async function loadAll(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    await Promise.all([loadUsers(), loadRoles(), loadDeptPage(), searchDeptOptions('')])
  } catch (e) {
    error.value = toUserMessage(e, '加载权限数据失败')
  } finally {
    loading.value = false
  }
}

watch(activeTab, (tab) => {
  if (tab === 'departments' && !deptPage.items.length) void loadDeptPage()
})

onMounted(() => {
  void loadAll()
})
</script>

<style scoped>
.page-access { padding: 4px; }
.access-tabs { margin-top: 4px; }
.acc-filter-row { display: flex; gap: 14px; flex-wrap: wrap; align-items: flex-end; }
.acc-filter-item { display: grid; gap: 4px; }
.ma-field__label { font-size: 12px; color: var(--el-text-color-secondary); }
.batch-bar { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.batch-left { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.batch-count { font-size: 13px; color: var(--el-text-color-regular); }
.batch-count b { color: var(--el-color-primary); }
.acc-cell-main { font-weight: 600; }
.cell-sub { font-size: 11px; color: var(--el-text-color-secondary); }
.batch-alert { margin-top: 10px; }
.acc-dialog-section-title { font-size: 13px; font-weight: 700; margin: 4px 0 10px; }
.acc-form-grid { display: grid; grid-template-columns: repeat(2, minmax(220px, 1fr)); gap: 12px 20px; }
.acc-field { display: grid; gap: 4px; min-width: 0; }
.acc-scope-radios { display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
.acc-hint { font-size: 12px; color: var(--el-text-color-secondary); margin: 8px 0 0; line-height: 1.6; }

.role-layout {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.role-rail { display: grid; gap: 8px; align-content: start; }
.role-card {
  display: grid; gap: 2px; text-align: left; cursor: pointer;
  border: 1px solid var(--el-border-color-lighter); border-left: 3px solid transparent;
  border-radius: 10px; padding: 10px 12px; background: var(--el-bg-color);
}
.role-card.active {
  background: var(--el-color-primary-light-9);
  border-left: 3px solid var(--el-color-primary);
}
.role-card-name { font-weight: 700; font-size: 13px; }
.role-card-en { font-size: 11px; color: var(--el-text-color-secondary); }
.role-card-badge {
  margin-top: 4px; justify-self: start; padding: 0 8px; border-radius: 999px;
  background: var(--el-fill-color); font-size: 11px; color: var(--el-text-color-secondary);
}
.role-new-btn { width: 100%; }
.role-editor { min-width: 0; }
.role-sticky-bar {
  position: sticky; top: 0; z-index: 5; background: #fff;
  border-bottom: 1px solid var(--ma-border, var(--el-border-color-lighter));
  padding: 12px 16px;
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  margin-bottom: 12px;
}
.role-sticky-label { font-size: 13px; }
.role-sticky-spacer { flex: 1; }
.role-section { margin-bottom: 16px; }
.role-section-title { font-size: 14px; font-weight: 700; margin: 0 0 10px; }
.menu-group-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
.menu-group-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.menu-check-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 6px 10px;
}
.scope-card-grid { display: grid; grid-template-columns: repeat(3, minmax(160px, 1fr)); gap: 12px; }
.scope-card {
  display: grid; gap: 4px; text-align: left; cursor: pointer;
  border: 1px solid var(--el-border-color-lighter); border-radius: 10px;
  padding: 12px 14px; background: var(--el-bg-color);
}
.scope-card.active { border-color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.scope-card b { font-size: 13px; }
.scope-card span { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.5; }
.scope-tags { margin-top: 10px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.perm-collapse { margin-top: 4px; }
.perm-collapse-title { font-size: 13px; font-weight: 600; }
.perm-module-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.dept-toolbar { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; margin-bottom: 12px; }
.dept-pager { margin-top: 10px; display: flex; justify-content: flex-end; }
@media (max-width: 960px) {
  .role-layout { grid-template-columns: 1fr; }
  .scope-card-grid { grid-template-columns: 1fr; }
  .acc-form-grid { grid-template-columns: 1fr; }
}
</style>
