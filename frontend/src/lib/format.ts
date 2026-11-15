import type { CellKind, CellValue, Span } from '../api/types'

const ISO = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?)?$/
const number = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 10 })

/** Значение ячейки для показа. Даты приходят строкой ISO, в CSV всё — строки как есть. */
export function formatCell(value: CellValue, kind?: CellKind): string {
  if (value === null) return ''
  if (typeof value === 'number') return number.format(value)
  if (typeof value === 'boolean') return value ? 'ИСТИНА' : 'ЛОЖЬ'
  // Без kind (экран «до/после») дату узнаём по «T» из datetime.isoformat(): в CSV так не пишут.
  const m = (kind === 'date' || (kind === undefined && value.includes('T'))) && ISO.exec(value)
  if (m) {
    const [, y, mo, d, h, mi] = m
    const time = h && (h !== '00' || mi !== '00') ? ` ${h}:${mi}` : ''
    return `${d}.${mo}.${y}${time}`
  }
  return value
}

export interface Piece {
  text: string
  span?: Span
}

/** Текст, разрезанный по найденным фрагментам (они не пересекаются и отсортированы). */
export function splitBySpans(text: string, spans: Span[]): Piece[] {
  const out: Piece[] = []
  let pos = 0
  for (const s of spans) {
    if (s.start > pos) out.push({ text: text.slice(pos, s.start) })
    out.push({ text: text.slice(s.start, s.end), span: s })
    pos = s.end
  }
  if (pos < text.length) out.push({ text: text.slice(pos) })
  return out
}
