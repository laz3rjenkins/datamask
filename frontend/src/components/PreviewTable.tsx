import { useVirtualizer } from '@tanstack/react-virtual'
import { useMemo, useRef } from 'react'
import type { CellSpans, ColumnConfig, ColumnSuggestion, Meta, Preview } from '../api/types'
import { formatCell, splitBySpans } from '../lib/format'
import ColumnHeader from './ColumnHeader'

export default function PreviewTable({
  meta,
  preview,
  columns,
  suggestions,
  spans,
  onColumnChange,
}: {
  meta: Meta
  preview: Preview
  columns: Record<string, ColumnConfig>
  suggestions: Record<string, ColumnSuggestion>
  spans: CellSpans[]
  onColumnChange: (key: string, c: ColumnConfig | undefined) => void
}) {
  const scroller = useRef<HTMLDivElement>(null)
  const rows = useMemo(
    () => [
      ...preview.above_header.map((r) => ({ ...r, above: true })),
      ...preview.rows.map((r) => ({ ...r, above: false })),
    ],
    [preview],
  )
  const spanMap = useMemo(() => new Map(spans.map((c) => [`${c.row}:${c.col}`, c.spans])), [spans])
  const labels = useMemo(() => new Map(meta.entities.map((e) => [e.value, e.label])), [meta])

  // Виртуальная прокрутка: в DOM только видимые строки (SPEC §6, экран 2).
  const virtual = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scroller.current,
    estimateSize: () => 33,
    overscan: 12,
  })
  const items = virtual.getVirtualItems()
  const padTop = items[0]?.start ?? 0
  const padBottom = virtual.getTotalSize() - (items.at(-1)?.end ?? 0)
  const width = preview.columns.length + 1

  if (!preview.columns.length) {
    return <p className="py-10 text-center text-neutral-500">Лист пустой</p>
  }

  return (
    <div
      ref={scroller}
      className="max-h-[calc(100vh-17rem)] min-h-80 overflow-auto rounded-lg border border-neutral-200 dark:border-neutral-800"
    >
      <table className="w-max border-separate border-spacing-0 text-sm">
        <thead>
          <tr>
            <th className="sticky top-0 left-0 z-20 border-b border-neutral-200 bg-neutral-50 px-2 py-2 text-xs font-normal text-neutral-400 dark:border-neutral-800 dark:bg-neutral-900">
              стр.
            </th>
            {preview.columns.map((c) => {
              const selected = !!columns[c.key]
              return (
                <th
                  key={c.key}
                  scope="col"
                  className={`sticky top-0 z-10 w-56 max-w-72 min-w-48 border-b border-l border-neutral-200 px-2 py-2 align-top dark:border-neutral-800 ${
                    selected ? 'bg-amber-50 dark:bg-amber-900/30' : 'bg-neutral-50 dark:bg-neutral-900'
                  } ${c.hidden ? 'opacity-60' : ''}`}
                >
                  <ColumnHeader
                    meta={meta}
                    column={c}
                    suggestion={suggestions[c.key]}
                    config={columns[c.key]}
                    kinds={preview.rows.map((r) => r.kinds[c.index - 1])}
                    onChange={(cfg) => onColumnChange(c.key, cfg)}
                  />
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {padTop > 0 && (
            <tr aria-hidden>
              <td colSpan={width} style={{ height: padTop }} />
            </tr>
          )}
          {items.map((it) => {
            const r = rows[it.index]
            return (
              <tr
                key={it.key}
                data-index={it.index}
                ref={virtual.measureElement}
                className={r.above ? 'bg-neutral-50 text-neutral-600 dark:bg-neutral-900/60 dark:text-neutral-400' : ''}
              >
                <td
                  className={`sticky left-0 border-b border-neutral-100 px-2 py-1.5 align-top ${r.above ? "bg-neutral-50 dark:bg-neutral-900" : "bg-white dark:bg-neutral-950"} text-right text-xs text-neutral-400 tabular-nums dark:border-neutral-800/60`}
                  title={r.above ? 'Строка над заголовком: проверяется как свободный текст' : undefined}
                >
                  {r.row}
                </td>
                {preview.columns.map((c) => {
                  const cfg = columns[c.key]
                  const value = r.values[c.index - 1]
                  const text = formatCell(value, r.kinds[c.index - 1])
                  const found = spanMap.get(`${r.row}:${c.index}`)
                  const free = cfg?.entity === 'FREE_TEXT'
                  return (
                    <td
                      key={c.key}
                      className={`max-w-72 border-b border-l border-neutral-100 px-2 py-1.5 align-top dark:border-neutral-800/60 ${
                        cfg && !r.above ? 'bg-amber-50/60 dark:bg-amber-900/15' : ''
                      } ${c.hidden ? 'opacity-50' : ''} ${r.kinds[c.index - 1] === 'number' ? 'text-right tabular-nums' : ''}`}
                    >
                      <div className={free || found ? 'line-clamp-2 whitespace-normal' : 'truncate'} title={text}>
                        {r.kinds[c.index - 1] === 'formula' ? (
                          <span className="font-mono text-xs text-neutral-500">{text}</span>
                        ) : found ? (
                          splitBySpans(text, found).map((p, i) =>
                            p.span ? (
                              <mark
                                key={i}
                                title={labels.get(p.span.entity)}
                                className="rounded-sm bg-amber-200 px-0.5 text-inherit dark:bg-amber-700/60"
                              >
                                {p.text}
                              </mark>
                            ) : (
                              <span key={i}>{p.text}</span>
                            ),
                          )
                        ) : (
                          text
                        )}
                      </div>
                    </td>
                  )
                })}
              </tr>
            )
          })}
          {padBottom > 0 && (
            <tr aria-hidden>
              <td colSpan={width} style={{ height: padBottom }} />
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
