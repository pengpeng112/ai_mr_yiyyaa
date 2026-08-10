import dayjs from 'dayjs'

export function formatDateTime(value?: string | number | null, fallback = '--'): string {
  if (value === null || value === undefined || value === '') return fallback
  const d = dayjs(value)
  if (!d.isValid()) return fallback
  return d.format('YYYY-MM-DD HH:mm:ss')
}

export function formatDate(value?: string | number | null, fallback = '--'): string {
  if (value === null || value === undefined || value === '') return fallback
  const d = dayjs(value)
  if (!d.isValid()) return fallback
  return d.format('YYYY-MM-DD')
}

export function displayText(value: unknown, fallback = '--'): string {
  if (value === null || value === undefined || value === '') return fallback
  return String(value)
}

export function truthyFlag(value: unknown): boolean {
  return value === true || value === 1 || value === '1' || value === 'true'
}
