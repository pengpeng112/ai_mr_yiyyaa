/**
 * WP08：用户批量操作分批工具（纯函数，供 AccessPage 与单测直测）。
 * 后端 POST /users/batch-update 单批上限 200（超限 400），前端按 200 切片
 * 顺序提交；分批不可整除时尾批 < 200。
 */

/** 把用户 ID 列表按每批 ≤200 切片（去重保序）。 */
export function splitBatches(userIds: Array<number | string>, batchSize = 200): number[][] {
  const unique: number[] = []
  const seen = new Set<string>()
  for (const raw of userIds || []) {
    const id = Number(raw)
    const key = String(id)
    if (!Number.isSafeInteger(id) || id <= 0 || seen.has(key)) continue
    seen.add(key)
    unique.push(id)
  }
  const batches: number[][] = []
  for (let index = 0; index < unique.length; index += batchSize) {
    batches.push(unique.slice(index, index + batchSize))
  }
  return batches
}

/** 期望的调用次数（=splitBatches 长度；空选集为 0）。 */
export function expectedBatchCount(userIds: Array<number | string>, batchSize = 200): number {
  return splitBatches(userIds, batchSize).length
}
