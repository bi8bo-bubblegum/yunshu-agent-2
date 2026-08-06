// 时间展示工具：服务端/数据库以 UTC 存储（timestamptz），
// 前端统一按本地时区格式化，避免直接 slice 展示 UTC 造成时间差。

const pad = (n: number) => String(n).padStart(2, '0')

function parse(iso?: string | null): Date | null {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

/** 本地时间：YYYY-MM-DD HH:mm */
export function fmtDateTime(iso?: string | null): string {
  const d = parse(iso)
  if (!d) return iso ?? ''
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 本地时间：HH:mm:ss */
export function fmtTime(iso?: string | null): string {
  const d = parse(iso)
  if (!d) return ''
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
