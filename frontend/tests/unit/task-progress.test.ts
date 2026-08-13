import { describe, expect, it } from 'vitest'
import { historyProcessed, mergeCurrentTask, normalizeCurrentTask, summarizeTaskRows } from '@/utils/task-progress'
describe('task progress contracts', () => {
  it('uses processed for percent and ignores missing task', () => { expect(normalizeCurrentTask({ status: 'not_found', task_id: '' })).toBeNull(); expect(normalizeCurrentTask({ status: 'running', task_id: 't1', total: 8, processed: 2 })?.percent).toBe(25) })
  it('merges current only for manual no-date matching filters on page one', () => { const current = normalizeCurrentTask({ status: 'running', task_id: 't1', total: 1, processed: 0 }); expect(mergeCurrentTask(current, [], { trigger_type: 'manual' })).toHaveLength(1); expect(mergeCurrentTask(current, [], { trigger_type: 'manual' }, 2)).toHaveLength(0); expect(mergeCurrentTask(current, [], { date_from: '2026-08-01' })).toHaveLength(0); expect(mergeCurrentTask(current, [], { status: 'failed' })).toHaveLength(0); expect(mergeCurrentTask(current, [], { audit_run_mode: 'daily_increment' })).toHaveLength(0) })
  it('summarizes page rows', () => { expect(summarizeTaskRows([{ id: 1, status: 'completed', trigger_type: 'auto', run_time: '', query_date: '', audit_type_code: '', audit_run_mode: '', total_records: 1, success_count: 1, failed_count: 0, duration_seconds: 4, error_msg: '' }])).toEqual({ running: 0, completed: 1, failed: 0, averageDuration: 4 }) })
  it('uses success plus failed as history processed count', () => { expect(historyProcessed({ success_count: 3, failed_count: 2 })).toBe(5) })
})
