<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import DataTableShell from '@/components/base/DataTableShell.vue'
import { apiGet, apiPost, apiDelete } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { displayText } from '@/utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'

const tab = ref('users')
const loading = ref(false)
const error = ref('')
const users = ref<Array<Record<string, unknown>>>([])
const roles = ref<Array<Record<string, unknown>>>([])
const permissions = ref<Array<Record<string, unknown>>>([])
const departments = ref<Array<Record<string, unknown>>>([])
const menuCatalog = ref<Array<Record<string, unknown>>>([])
const selectedRoleId = ref<number | null>(null)
const roleMenus = ref<Array<Record<string, unknown>>>([])

async function loadUsers() {
  const data = await apiGet<{ items?: Array<Record<string, unknown>> }>('/users', {
    params: { page: 1, limit: 100 },
  })
  users.value = data.items || []
}

async function loadRoles() {
  roles.value = (await apiGet<Array<Record<string, unknown>>>('/roles')) || []
}

async function loadPermissions() {
  permissions.value = (await apiGet<Array<Record<string, unknown>>>('/permissions')) || []
}

async function loadDepartments() {
  departments.value = (await apiGet<Array<Record<string, unknown>>>('/departments')) || []
}

async function loadCatalog() {
  menuCatalog.value =
    (await apiGet<Array<Record<string, unknown>>>('/roles/menus/catalog')) || []
}

async function loadRoleMenus(roleId: number) {
  selectedRoleId.value = roleId
  roleMenus.value = (await apiGet<Array<Record<string, unknown>>>(`/roles/${roleId}/menus`)) || []
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    if (tab.value === 'users') await loadUsers()
    if (tab.value === 'roles') await loadRoles()
    if (tab.value === 'permissions') await loadPermissions()
    if (tab.value === 'departments') await loadDepartments()
    if (tab.value === 'menus') {
      await loadRoles()
      await loadCatalog()
    }
  } catch (e) {
    error.value = toUserMessage(e, '加载权限数据失败')
  } finally {
    loading.value = false
  }
}

async function assignMenu(menuId: string) {
  if (!selectedRoleId.value) return
  try {
    await ElMessageBox.confirm(`确认将菜单 ${menuId} 分配给角色？menu ID 不得改名。`, '请确认')
    await apiPost(`/roles/${selectedRoleId.value}/menus/${menuId}`)
    ElMessage.success('已分配')
    await loadRoleMenus(selectedRoleId.value)
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(toUserMessage(e, '分配失败'))
  }
}

async function revokeMenu(menuId: string) {
  if (!selectedRoleId.value) return
  try {
    await ElMessageBox.confirm(`确认移除菜单 ${menuId}？`, '请确认', { type: 'warning' })
    await apiDelete(`/roles/${selectedRoleId.value}/menus/${menuId}`)
    ElMessage.success('已移除')
    await loadRoleMenus(selectedRoleId.value)
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(toUserMessage(e, '移除失败'))
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page-access">
    <PageHeader title="用户与权限" description="用户、角色、权限、科室与 RoleMenu。菜单 ID 保持兼容。">
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <el-tabs
      v-model="tab"
      @tab-change="() => load()"
    >
      <el-tab-pane label="用户" name="users">
        <DataTableShell :loading="loading" :error="error" :empty="!users.length" :show-pagination="false" @retry="load">
          <el-table :data="users" stripe border size="small">
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="username" label="用户名" min-width="120" />
            <el-table-column label="姓名" min-width="120">
              <template #default="{ row }">{{ displayText(row.full_name) }}</template>
            </el-table-column>
            <el-table-column label="角色" min-width="100">
              <template #default="{ row }">{{ displayText(row.role) }}</template>
            </el-table-column>
          </el-table>
        </DataTableShell>
      </el-tab-pane>
      <el-tab-pane label="角色" name="roles">
        <DataTableShell :loading="loading" :error="error" :empty="!roles.length" :show-pagination="false" @retry="load">
          <el-table :data="roles" stripe border size="small">
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="name" label="名称" min-width="120" />
            <el-table-column label="描述" min-width="180">
              <template #default="{ row }">{{ displayText(row.description) }}</template>
            </el-table-column>
          </el-table>
        </DataTableShell>
      </el-tab-pane>
      <el-tab-pane label="菜单分配" name="menus">
        <el-form inline class="mb">
          <el-form-item label="角色">
            <el-select
              v-model="selectedRoleId"
              placeholder="选择角色"
              style="width: 200px"
              @change="(id: number) => loadRoleMenus(id)"
            >
              <el-option
                v-for="r in roles"
                :key="String(r.id)"
                :label="String(r.name)"
                :value="Number(r.id)"
              />
            </el-select>
          </el-form-item>
        </el-form>
        <el-row :gutter="12">
          <el-col :xs="24" :md="12">
            <el-card shadow="never">
              <template #header>目录（含 hidden 占位，仅管理员）</template>
              <el-table :data="menuCatalog" size="small" max-height="420">
                <el-table-column prop="id" label="ID" min-width="120" />
                <el-table-column prop="label" label="名称" min-width="120" />
                <el-table-column prop="group" label="分组" width="100" />
                <el-table-column label="操作" width="90">
                  <template #default="{ row }">
                    <el-button link type="primary" :disabled="!selectedRoleId" @click="assignMenu(String(row.id))">
                      分配
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-card>
          </el-col>
          <el-col :xs="24" :md="12">
            <el-card shadow="never">
              <template #header>已分配</template>
              <el-table :data="roleMenus" size="small" max-height="420">
                <el-table-column prop="id" label="ID" min-width="120" />
                <el-table-column prop="label" label="名称" min-width="120" />
                <el-table-column label="操作" width="90">
                  <template #default="{ row }">
                    <el-button link type="danger" @click="revokeMenu(String(row.id))">移除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>
      <el-tab-pane label="权限" name="permissions">
        <DataTableShell :loading="loading" :error="error" :empty="!permissions.length" :show-pagination="false" @retry="load">
          <el-table :data="permissions" stripe border size="small">
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="code" label="Code" min-width="160" />
            <el-table-column prop="name" label="名称" min-width="160" />
          </el-table>
        </DataTableShell>
      </el-tab-pane>
      <el-tab-pane label="科室" name="departments">
        <DataTableShell :loading="loading" :error="error" :empty="!departments.length" :show-pagination="false" @retry="load">
          <el-table :data="departments" stripe border size="small">
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="name" label="名称" min-width="160" />
            <el-table-column prop="code" label="编码" min-width="120" />
          </el-table>
        </DataTableShell>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.mb {
  margin-bottom: 12px;
}
</style>
