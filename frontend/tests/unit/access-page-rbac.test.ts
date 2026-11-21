/**
 * WP08：全院「用户与权限」重构测试（任务书 §七）。
 * 筛选参数映射、未选禁用、>200 自动分批、access-bundle 单次保存、
 * 指定科室不平铺复选框。源码契约断言 + 分批纯函数直测。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import pageSource from '@/features/system/AccessPage.vue?raw'
import { expectedBatchCount, splitBatches } from '@/utils/access-batch'

const pagePath = resolve(process.cwd(), 'src/features/system/AccessPage.vue')
const page = readFileSync(pagePath, 'utf-8')

describe('WP08：用户筛选参数映射（GET /users 真实参数）', () => {
  it('分页参数名 page/limit + 分页 size [20, 50, 100]', () => {
    expect(page).toContain('page: page.value, limit: pageSize.value')
    expect(page).toContain(':page-sizes="[20, 50, 100]"')
    expect(page).toContain("layout=\"total, sizes, prev, pager, next\"")
  })

  it('筛选映射：q/role_id/unassigned_role/dept_id/is_active/directory_pending/scope', () => {
    for (const key of ['params.q', 'params.unassigned_role = true', 'params.role_id = Number(filters.role_id)',
      'params.dept_id = filters.dept_id', 'params.is_active = true', 'params.is_active = false',
      'params.directory_pending = true', 'params.scope = filters.scope']) {
      expect(page).toContain(key)
    }
  })

  it('科室筛选走 departments/paged 远程搜索（不一次性渲染 640 选项）', () => {
    expect(page).toContain("'/departments/paged'")
    expect(page).toContain('remote')
    expect(page).toContain('limit: 20')
    // 科室下拉不在数据范围区块平铺复选框
    expect(page).not.toContain('v-for="dept in departments"')
  })

  it('批量工具条：未选用户时三个批量按钮禁用 + 新建用户主按钮', () => {
    for (const label of ['批量分配角色', '批量设置数据范围', '批量启用/停用']) {
      expect(page).toContain(label)
    }
    expect(page).toMatch(/:disabled="!selectedIds\.length"[^>]*>批量分配角色/)
    expect(pageSourceContains(page, ':disabled="!selectedIds.length"') >= 3).toBe(true)
    expect(page).toContain('新建用户')
  })

  it('超过 200 人自动分批：splitBatches 261→[200,61]、400→[200,200]、199→[199]', () => {
    expect(splitBatches(Array.from({ length: 261 }, (_, i) => i + 1))).toEqual([
      Array.from({ length: 200 }, (_, i) => i + 1),
      Array.from({ length: 61 }, (_, i) => i + 201),
    ])
    expect(expectedBatchCount(Array.from({ length: 400 }, (_, i) => i + 1))).toBe(2)
    expect(expectedBatchCount(Array.from({ length: 199 }, (_, i) => i + 1))).toBe(1)
    expect(expectedBatchCount([])).toBe(0)
    // 去重与非法 ID 剔除（[1,2] → 1 批）
    expect(expectedBatchCount([1, 1, 2, 'x' as unknown as number, 0, -3])).toBe(1)
  })

  it('提交走 POST /users/batch-update 且进度文案「已完成 x / y」+失败批次汇总', () => {
    expect(page).toContain("'/users/batch-update'")
    expect(page).toContain('已完成 ${batchDone.value} / ${batchTotal.value}')
    expect(page).toContain('batchFailures')
    expect(page).toContain('batchPercent')
  })

  it('生效数据范围列：effective_scope.label + source=user 后缀（个人设置）+ 范围配色', () => {
    expect(page).toContain('row.effective_scope')
    expect(page).toContain('scope?.label')
    expect(page).toContain("effective_scope?.source === 'user'")
    expect(page).toContain('（个人设置）')
    for (const text of ['全院', '仅本科室', '指定多科室']) {
      expect(page).toContain(text)
    }
  })
})

describe('WP08：角色与权限 Tab（access-bundle 单次保存）', () => {
  it('保存只调用一次 PUT access-bundle（无逐项 assignment 端点残留）', () => {
    expect(page).toContain("apiPut<R>(`/roles/${role.id}/access-bundle`")
    // 旧逐项交互已删除（每勾一个弹一次确认）
    expect(page).not.toContain("'/roles/${roleId}/permissions/")
    expect(page).not.toContain("'/roles/${roleId}/menus/")
    expect(page).not.toContain("'/roles/${roleId}/departments/")
    // data_scope 仅非 admin 下发（admin 保持现状）
    expect(page).toContain("body.data_scope = {")
    expect(page).toContain("if (role.name !== 'admin')")
  })

  it('粘性保存条 + 未保存修改 tag + 切换角色确认', () => {
    expect(page).toContain('role-sticky-bar')
    expect(page).toContain('position: sticky')
    expect(page).toContain('有未保存修改')
    expect(page).toContain('保存本角色权限')
    expect(page).toContain('有未保存修改，切换将丢弃')
    expect(page).toContain('roleDirty')
  })

  it('菜单可见权限按 5 分组渲染（hidden 不显示）+ 本组全选 + auto-fill 180px', () => {
    expect(page).toContain('menu.hidden')       // hidden 菜单不显示
    for (const label of ['质控总览', '病历时效管理', '内涵与终末质控', '质控规则中心', '系统与运维']) {
      expect(page).toContain(label)
    }
    expect(page).toContain('本组全选')
    expect(page).toContain('minmax(180px, 1fr)')
    expect(page).toContain('groupAllChecked')
  })

  it('数据范围三卡单选（全院/仅本科室/指定多科室）+ selected 用 remote 多选与 closable tag（DOM 复选框 < 50）', () => {
    expect(page).toContain('全院数据')
    expect(page).toContain('仅本人所属科室')
    expect(page).toContain('指定多个科室')
    // 指定科室选择是 el-select multiple（非复选框平铺）→ DOM 复选框恒 < 50
    // 只截数据范围区块（至下一区块「功能操作权限」前，避免把权限复选框计入）
    const scopeSection = page.slice(
      page.indexOf('role-section-title">科室数据查询范围'),
      page.indexOf('功能操作权限（按模块分组'),
    )
    expect(scopeSection).toContain('multiple')
    expect(scopeSection).toContain('collapse-tags')
    expect(scopeSection).not.toContain('el-checkbox')  // 三卡为 button 单选，无复选框
    expect(page).toContain('removeRoleScopeDept')
    expect(page).toContain('>清空</el-button>')
  })

  it('角色卡列表：中文名+英文名小字+人数徽章+浅蓝选中态；新建角色禁用（后端无接口）', () => {
    expect(page).toContain('role-card-name')
    expect(page).toContain('role-card-en')
    expect(page).toContain('role-card-badge')
    expect(page).toContain('roleMemberCount')
    expect(page).toContain('role-card.active')
    expect(page).toContain('新建角色')
    expect(page).toContain('disabled')
  })
})

describe('WP08：科室目录 Tab', () => {
  it('paged 分页搜索 + 编码/名称/用户数列 + 新增/编辑', () => {
    expect(page).toContain("'/departments/paged'")
    expect(page).toContain('deptKeyword')
    expect(page).toContain('user_count')
    expect(page).toContain(':page-sizes="[20, 50, 100]"')
    expect(page).toContain('新增科室')
    expect(page).toContain("apiPut(`/departments/${departmentEditing.value.id}`")
  })
})

/** 小工具：统计子串出现次数（供禁用按钮数量断言）。 */
function pageSourceContains(source: string, needle: string): number {
  return source.split(needle).length - 1
}
