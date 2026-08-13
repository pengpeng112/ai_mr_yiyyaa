import { describe, expect, it } from 'vitest'
import { buildHistoricalCreatePayload, buildHistoricalPreviewPayload } from '@/utils/historical-rerun'

describe('historical rerun request contracts', () => {
  const scope = { query_date: '2026-08-11', date_from: null, date_to: null, date_dimension: 'query_date', audit_type_codes: ['progress_vs_nursing'], dept_filter: ['一科'] }

  it('uses schema field names for create and excludes legacy fields', () => {
    const body = buildHistoricalCreatePayload(scope, { audit_run_mode: 'daily_increment', candidate_hash: '1234567890123456', reaudit_reason: 'review', alert_policy: 'suppress', include_rectified: false })
    expect(body.confirm_candidate_hash).toBe('1234567890123456')
    expect(body).not.toHaveProperty('candidate_hash')
    expect(body).not.toHaveProperty('confirm')
    expect(body).not.toHaveProperty('allow_rectified')
  })

  it('keeps explicit run mode and shard limit for preview', () => {
    expect(buildHistoricalPreviewPayload(scope, 'discharge_final', 200)).toMatchObject({ audit_run_mode: 'discharge_final', shard_limit: 200 })
  })
})
