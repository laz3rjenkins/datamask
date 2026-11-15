import type {
  CellKind,
  Categories,
  ColumnConfig,
  MaskConfig,
  Meta,
  Sanitize,
  SuggestResult,
} from '../api/types'

/** Настройки экрана 2. Живут в App, чтобы пережить переход «Назад» с экрана проверки. */
export interface Settings {
  categories: Categories
  customTerms: string // по слову или фразе на строку
  sanitize: Sanitize
  headerRows: Record<string, number> // только выбранные вручную; остальные — автоопределение
  columns: Record<string, Record<string, ColumnConfig>> // лист → колонка → настройка
  initialized: boolean // подсказки уже применялись автоматически
}

export const initialSettings = (): Settings => ({
  categories: { personal: true, financial: true, commercial: false },
  customTerms: '',
  sanitize: { comments: 'remove', hidden_sheets: 'keep', images: 'keep' },
  headerRows: {},
  columns: {},
  initialized: false,
})

export const parseTerms = (text: string): string[] =>
  text
    .split('\n')
    .map((t) => t.trim())
    .filter(Boolean)

/** «Принять все подсказки»: колонки с подсказкой получают её тип и способ, остальные не трогаем. */
export function applySuggestions(
  columns: Settings['columns'],
  suggestions: SuggestResult,
): Settings['columns'] {
  const out = { ...columns }
  for (const sheet of suggestions.sheets) {
    const cols = { ...out[sheet.sheet] }
    for (const c of sheet.columns) {
      if (c.suggestion) cols[c.key] = { entity: c.suggestion.entity, method: c.suggestion.method }
    }
    out[sheet.sheet] = cols
  }
  return out
}

/** Смена типа: способ сохраняется, если подходит новому типу, иначе — способ по умолчанию. */
export function changeEntity(
  meta: Meta,
  current: ColumnConfig | undefined,
  entity: string | null,
): ColumnConfig | undefined {
  if (!entity) return undefined
  const em = meta.entities.find((e) => e.value === entity)
  if (!em) return undefined
  const keep = current && em.methods.includes(current.method)
  return { entity, method: keep ? current.method : em.default_method }
}

export function buildConfig(settings: Settings, suggestions: SuggestResult): MaskConfig {
  const sheets: MaskConfig['sheets'] = {}
  for (const s of suggestions.sheets) {
    sheets[s.sheet] = {
      header_row: settings.headerRows[s.sheet] ?? s.header_row,
      columns: settings.columns[s.sheet] ?? {},
      scan_above_header: true,
    }
  }
  return {
    categories: settings.categories,
    sheets,
    custom_terms: parseTerms(settings.customTerms),
    sanitize: settings.sanitize,
    save_mapping: true,
  }
}

export const selectedCount = (columns: Settings['columns']): number =>
  Object.values(columns).reduce((n, cols) => n + Object.keys(cols).length, 0)

// Способы, после которых число остаётся числом, а дата датой.
const KEEPS_TYPE = new Set(['date_shift', 'date_generalize', 'scale', 'noise', 'delete'])

/** Числовая или датовая колонка станет текстовой («тип колонки изменится», SPEC §7). */
export function changesType(kinds: CellKind[], method: string): boolean {
  if (KEEPS_TYPE.has(method)) return false
  const filled = kinds.filter((k) => k !== 'empty' && k !== 'formula' && k !== 'error')
  const typed = filled.filter((k) => k === 'number' || k === 'date').length
  return typed > 0 && typed * 2 >= filled.length
}
