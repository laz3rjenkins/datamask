import type { CellKind, Column, ColumnConfig, ColumnSuggestion, Meta, Params } from '../api/types'
import { changeEntity, changesType } from '../lib/settings'
import { Irreversible, selectCls } from './ui'

const CATEGORY_LABELS = { personal: 'Персональные', financial: 'Финансовые', commercial: 'Коммерческие' }
const HIDDEN_ENTITIES = new Set(['CUSTOM']) // свой словарь задаётся списком слов, а не колонкой

function suggestionText(meta: Meta, s: NonNullable<ColumnSuggestion['suggestion']>): string {
  const label = meta.entities.find((e) => e.value === s.entity)?.label ?? s.entity
  return `${label}, ${Math.round(s.confidence * 100)}%: ${s.reasons.join(', ')}`
}

export default function ColumnHeader({
  meta,
  column,
  suggestion,
  config,
  kinds,
  onChange,
}: {
  meta: Meta
  column: Column
  suggestion?: ColumnSuggestion
  config?: ColumnConfig
  kinds: CellKind[]
  onChange: (c: ColumnConfig | undefined) => void
}) {
  const s = suggestion?.suggestion
  const entityMeta = config && meta.entities.find((e) => e.value === config.entity)
  const method = config && meta.methods.find((m) => m.value === config.method)
  const groups = (['personal', 'financial', 'commercial'] as const).map((c) => ({
    label: CATEGORY_LABELS[c],
    items: meta.entities.filter((e) => e.category === c && !HIDDEN_ENTITIES.has(e.value)),
  }))
  const applied = s && config?.entity === s.entity
  const id = `col-${column.key}`

  return (
    <div className="flex flex-col gap-1.5 text-left font-normal">
      <div className="flex items-baseline gap-1.5">
        <span className="text-xs text-neutral-400">{column.key}</span>
        <span className="truncate font-medium" title={column.header}>
          {column.header || <span className="text-neutral-400 italic">без заголовка</span>}
        </span>
        {column.hidden && <span className="text-xs text-neutral-500">(скрытая)</span>}
      </div>

      {s && (
        <button
          type="button"
          onClick={() => onChange({ entity: s.entity, method: s.method })}
          title={suggestionText(meta, s)}
          aria-label={`Подсказка: ${suggestionText(meta, s)}${applied ? '' : '. Нажмите, чтобы применить'}`}
          className={`self-start rounded-full px-2 py-0.5 text-xs ${
            applied
              ? 'bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300'
              : 'bg-sky-100 text-sky-900 hover:bg-sky-200 dark:bg-sky-950 dark:text-sky-100'
          }`}
        >
          {applied ? '✓ ' : 'Похоже: '}
          {meta.entities.find((e) => e.value === s.entity)?.label} · {Math.round(s.confidence * 100)}%
        </button>
      )}

      <label className="sr-only" htmlFor={`${id}-type`}>
        Тип данных колонки {column.key}
      </label>
      <select
        id={`${id}-type`}
        className={`${selectCls} w-full`}
        value={config?.entity ?? ''}
        onChange={(e) => onChange(changeEntity(meta, config, e.target.value || null))}
      >
        <option value="">Не маскировать</option>
        {groups.map((g) => (
          <optgroup key={g.label} label={g.label}>
            {g.items.map((e) => (
              <option key={e.value} value={e.value}>
                {e.label}
              </option>
            ))}
          </optgroup>
        ))}
        <option value="FREE_TEXT">Свободный текст</option>
      </select>

      {config && entityMeta && (
        <>
          <label className="sr-only" htmlFor={`${id}-method`}>
            Способ маскирования колонки {column.key}
          </label>
          <select
            id={`${id}-method`}
            className={`${selectCls} w-full`}
            value={config.method}
            onChange={(e) => onChange({ entity: config.entity, method: e.target.value })}
          >
            {entityMeta.methods.map((m) => {
              const mm = meta.methods.find((x) => x.value === m)
              return (
                <option key={m} value={m}>
                  {mm?.label}
                  {mm && !mm.reversible ? ' ⚠' : ''}
                </option>
              )
            })}
          </select>
          <ParamControl config={config} id={id} onChange={(params) => onChange({ ...config, params })} />
          {method && !method.reversible && <Irreversible />}
          {config.entity !== 'FREE_TEXT' && changesType(kinds, config.method) && (
            <span className="text-xs text-amber-700 dark:text-amber-300">Тип колонки изменится на текст</span>
          )}
          {!!suggestion?.formulas && (
            <span className="text-xs text-amber-700 dark:text-amber-300">
              Формул: {suggestion.formulas} — будут пропущены
            </span>
          )}
        </>
      )}
    </div>
  )
}

function ParamControl({
  config,
  id,
  onChange,
}: {
  config: ColumnConfig
  id: string
  onChange: (p: Params) => void
}) {
  const p = config.params ?? {}
  const small = 'flex items-center gap-1.5 text-xs text-neutral-600 dark:text-neutral-400'
  switch (config.method) {
    case 'pseudonym':
      if (config.entity === 'FREE_TEXT') return null
      return (
        <label className={small} htmlFor={`${id}-prefix`}>
          Префикс
          <input
            id={`${id}-prefix`}
            className={`${selectCls} w-full`}
            placeholder="по умолчанию"
            maxLength={30}
            value={String(p.prefix ?? '')}
            // только буквы: префикс должен однозначно ловиться при размаскировке
            onChange={(e) => {
              const prefix = e.target.value.replace(/[^A-Za-zА-Яа-яЁё]/g, '')
              onChange(prefix ? { prefix } : {})
            }}
          />
        </label>
      )
    case 'partial':
      if (config.entity === 'EMAIL') return null
      return (
        <label className={small}>
          Оставить последних цифр
          <select
            className={`${selectCls} w-16`}
            value={Number(p.keep_last ?? 4)}
            onChange={(e) => onChange({ keep_last: Number(e.target.value) })}
          >
            {[0, 2, 3, 4, 5, 6].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
      )
    case 'noise':
      return (
        <label className={small}>
          Шум ±
          <select
            className={`${selectCls} w-20`}
            value={Number(p.percent ?? 10)}
            onChange={(e) => onChange({ percent: Number(e.target.value) })}
          >
            {[5, 10, 20, 30, 50].map((n) => (
              <option key={n} value={n}>
                {n}%
              </option>
            ))}
          </select>
        </label>
      )
    case 'date_generalize':
      return (
        <select
          aria-label="Точность"
          className={`${selectCls} w-full`}
          value={String(p.level ?? 'month')}
          onChange={(e) => onChange({ level: e.target.value })}
        >
          <option value="month">До месяца (01.03.1991)</option>
          <option value="year">До года (1991)</option>
        </select>
      )
    case 'date_shift':
    case 'scale':
      return (
        <select
          aria-label={config.method === 'scale' ? 'Коэффициент' : 'Сдвиг'}
          className={`${selectCls} w-full`}
          value={String(p.scope ?? 'column')}
          onChange={(e) => onChange({ scope: e.target.value })}
        >
          <option value="column">Своё значение для колонки</option>
          <option value="file">Одно на весь файл</option>
        </select>
      )
    default:
      return null
  }
}
