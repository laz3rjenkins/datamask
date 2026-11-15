import { useEffect, useMemo, useState } from 'react'
import { api, errorText } from '../api/client'
import type { CellSpans, FileInfo, MaskConfig, Meta, Preview, SuggestResult, Template } from '../api/types'
import PreviewTable from '../components/PreviewTable'
import Sidebar from '../components/Sidebar'
import { Alert, Button, Spinner, Tabs, selectCls } from '../components/ui'
import {
  applySuggestions,
  applyTemplate,
  buildConfig,
  parseTerms,
  selectedCount,
  templateRules,
  type Settings,
} from '../lib/settings'

const ENCODINGS: [string, string][] = [
  ['utf-8', 'UTF-8'],
  ['utf-8-sig', 'UTF-8 с BOM'],
  ['cp1251', 'Windows-1251'],
  ['koi8_r', 'KOI8-R'],
  ['cp866', 'DOS (866)'],
  ['utf-16', 'UTF-16'],
]
const DELIMITERS: [string, string][] = [
  [',', 'запятая ,'],
  [';', 'точка с запятой ;'],
  ['\t', 'табуляция'],
  ['|', 'черта |'],
]

export default function Configure({
  meta,
  file,
  settings,
  setSettings,
  onFile,
  onBack,
  onNext,
}: {
  meta: Meta
  file: FileInfo
  settings: Settings
  setSettings: (f: (s: Settings) => Settings) => void
  onFile: (f: FileInfo) => void
  onBack: () => void
  onNext: (config: MaskConfig) => void
}) {
  const [sheet, setSheet] = useState(file.sheets[0].name)
  const [suggestions, setSuggestions] = useState<SuggestResult | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [spans, setSpans] = useState<CellSpans[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState({ suggest: false, preview: false, csv: false })
  const [templates, setTemplates] = useState<Template[]>([])
  const [templateName, setTemplateName] = useState<string | null>(null) // null — форма закрыта
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    api.templates().then(setTemplates, () => setTemplates([]))
  }, [])
  const patch = (p: Partial<Settings>) => setSettings((s) => ({ ...s, ...p }))
  const csvKey = file.csv ? `${file.csv.encoding}|${file.csv.delimiter}` : ''
  const terms = useMemo(() => parseTerms(settings.customTerms), [settings.customTerms])
  const sheetCols = settings.columns[sheet] ?? {}
  const userHeader = settings.headerRows[sheet]

  // Подсказки по всем листам: при смене категорий, словаря, строк заголовка, параметров CSV.
  const suggestKey = JSON.stringify([settings.categories, terms, settings.headerRows, csvKey])
  useEffect(() => {
    let live = true
    setBusy((b) => ({ ...b, suggest: true }))
    api
      .suggest(file.file_id, {
        categories: settings.categories,
        header_rows: settings.headerRows,
        custom_terms: terms,
      })
      .then((res) => {
        if (!live) return
        setSuggestions(res)
        // Первый раз подсказки применяются сами: так ничего не забудется, если сразу нажать «Далее».
        setSettings((s) =>
          s.initialized ? s : { ...s, columns: applySuggestions(s.columns, res), initialized: true },
        )
      })
      .catch((e) => live && setError(errorText(e)))
      .finally(() => live && setBusy((b) => ({ ...b, suggest: false })))
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- всё нужное в suggestKey
  }, [file.file_id, suggestKey])

  useEffect(() => {
    let live = true
    setBusy((b) => ({ ...b, preview: true }))
    api
      .preview(file.file_id, sheet, userHeader)
      .then((p) => live && setPreview(p))
      .catch((e) => live && setError(errorText(e)))
      .finally(() => live && setBusy((b) => ({ ...b, preview: false })))
    return () => {
      live = false
    }
  }, [file.file_id, sheet, userHeader, csvKey])

  // Подсветка находок: шапка над заголовком и колонки «Свободный текст».
  const freeCols = Object.keys(sheetCols).filter((k) => sheetCols[k].entity === 'FREE_TEXT')
  const spansKey = JSON.stringify([freeCols, settings.categories, terms])
  useEffect(() => {
    if (!preview || preview.sheet !== sheet) return
    let live = true
    api
      .spans(file.file_id, sheet, {
        header_row: preview.header_row,
        columns: freeCols,
        categories: settings.categories,
        custom_terms: terms,
      })
      .then((s) => live && setSpans(s))
      .catch(() => live && setSpans([]))
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- всё нужное в spansKey
  }, [preview, spansKey])

  async function changeCsv(p: { encoding?: string; delimiter?: string }) {
    setBusy((b) => ({ ...b, csv: true }))
    setError(null)
    try {
      onFile(await api.csvOptions(file.file_id, p))
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy((b) => ({ ...b, csv: false }))
    }
  }

  const sheetSugg = suggestions?.sheets.find((s) => s.sheet === sheet)
  const suggByKey = Object.fromEntries((sheetSugg?.columns ?? []).map((c) => [c.key, c]))
  const label = (e: string) => meta.entities.find((x) => x.value === e)?.label ?? e
  const suggested = suggestions?.sheets.reduce((n, s) => n + s.columns.filter((c) => c.suggestion).length, 0) ?? 0
  const findings = suggestions?.text_findings ?? []
  const count = selectedCount(settings.columns)

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_17rem]">
      <div className="min-w-0 space-y-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          {file.sheets.length > 1 && (
            <Tabs
              label="Листы"
              value={sheet}
              onChange={setSheet}
              items={file.sheets.map((s) => ({
                value: s.name,
                label: (
                  <>
                    {s.name}
                    {s.hidden && <span className="ml-1.5 text-xs opacity-70">скрытый</span>}
                  </>
                ),
              }))}
            />
          )}
          {preview && (
            <HeaderRowControl
              key={`${sheet}-${preview.header_row}`}
              value={preview.header_row}
              detected={preview.detected_header_row}
              manual={userHeader !== undefined}
              onChange={(n) => {
                const rows = { ...settings.headerRows }
                if (n === undefined) delete rows[sheet]
                else rows[sheet] = n
                patch({ headerRows: rows })
              }}
            />
          )}
          <div className="ml-auto flex flex-wrap gap-2">
            {templates.length > 0 && (
              <select
                aria-label="Применить шаблон"
                className={`${selectCls} py-2`}
                value=""
                disabled={!suggestions}
                onChange={(e) => {
                  const t = templates.find((x) => x.id === e.target.value)
                  if (!t || !suggestions) return
                  const res = applyTemplate(settings.columns, t, suggestions)
                  patch({ columns: res.columns })
                  setNotice(
                    res.matched
                      ? `Шаблон «${t.name}» применён: колонок — ${res.matched}`
                      : `В шаблоне «${t.name}» нет подходящих заголовков`,
                  )
                }}
              >
                <option value="">Применить шаблон…</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            )}
            <Button disabled={!count || !suggestions} onClick={() => setTemplateName('')}>
              Сохранить как шаблон
            </Button>
            <Button
              disabled={!suggestions || !suggested}
              onClick={() => suggestions && patch({ columns: applySuggestions(settings.columns, suggestions) })}
            >
              Принять все подсказки
            </Button>
            <Button disabled={!count} onClick={() => patch({ columns: {} })}>
              Сбросить
            </Button>
          </div>
        </div>

        {file.csv && (
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <label className="flex items-center gap-2">
              Кодировка
              <select
                className={selectCls}
                value={file.csv.encoding}
                disabled={busy.csv}
                onChange={(e) => changeCsv({ encoding: e.target.value })}
              >
                {ENCODINGS.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2">
              Разделитель
              <select
                className={selectCls}
                value={file.csv.delimiter}
                disabled={busy.csv}
                onChange={(e) => changeCsv({ delimiter: e.target.value })}
              >
                {DELIMITERS.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <span className="text-xs text-neutral-500">
              Определены автоматически. Если текст в таблице нечитаемый, поменяйте кодировку.
            </span>
          </div>
        )}

        {templateName !== null && suggestions && (
          <form
            className="flex flex-wrap items-center gap-2 text-sm"
            onSubmit={async (e) => {
              e.preventDefault()
              const rules = templateRules(settings.columns, suggestions)
              if (!rules.length) {
                setNotice('У выбранных колонок нет заголовков: шаблон сохранить нельзя')
                return
              }
              try {
                const t = await api.createTemplate(templateName.trim(), rules)
                setTemplates((ts) => [...ts, t])
                setTemplateName(null)
                setNotice(`Шаблон «${t.name}» сохранён: правил — ${rules.length}`)
              } catch (err) {
                setError(errorText(err))
              }
            }}
          >
            <label htmlFor="template-name">Название шаблона</label>
            <input
              id="template-name"
              autoFocus
              maxLength={100}
              className={`${selectCls} w-64 py-1.5`}
              placeholder="Например, «Выгрузка CRM»"
              value={templateName}
              onChange={(e) => setTemplateName(e.target.value)}
            />
            <Button type="submit" variant="primary" disabled={!templateName.trim()}>
              Сохранить
            </Button>
            <Button variant="ghost" onClick={() => setTemplateName(null)}>
              Отмена
            </Button>
            <span className="text-xs text-neutral-500">
              В шаблон попадут только заголовки колонок и выбранные способы, без данных.
            </span>
          </form>
        )}
        {notice && (
          <p className="text-sm text-neutral-600 dark:text-neutral-400" role="status">
            {notice}
          </p>
        )}

        {error && <Alert tone="error">{error}</Alert>}

        {(file.risks.length > 0 || findings.length > 0 || !!sheetSugg?.above_header.length) && (
          <Alert tone="warn" title="Обратите внимание">
            <ul className="list-disc space-y-0.5 pl-5">
              {file.risks.map((r, i) => (
                <li key={i}>{r.message}</li>
              ))}
              {findings.map((f, i) => (
                <li key={`f${i}`}>{findingText(f, label)}</li>
              ))}
              {!!sheetSugg?.above_header.length && (
                <li>
                  В шапке над таблицей найдено:{' '}
                  {sheetSugg.above_header.map((f) => `${label(f.entity)} (${f.count})`).join(', ')}. Будет
                  замаскировано
                </li>
              )}
            </ul>
          </Alert>
        )}

        <div className="flex h-5 items-center gap-4">
          {busy.suggest && <Spinner label="Ищу персональные данные в колонках…" />}
          {busy.preview && <Spinner label="Читаю лист…" />}
        </div>

        {preview && preview.sheet === sheet && (
          <PreviewTable
            meta={meta}
            preview={preview}
            columns={sheetCols}
            suggestions={suggByKey}
            spans={spans}
            onColumnChange={(key, cfg) => {
              const cols = { ...sheetCols }
              if (cfg) cols[key] = cfg
              else delete cols[key]
              patch({ columns: { ...settings.columns, [sheet]: cols } })
            }}
          />
        )}
        {preview && preview.rows.length >= 200 && (
          <p className="text-xs text-neutral-500">
            Показаны первые 200 строк. Маскируется весь файл.
          </p>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-neutral-200 pt-4 dark:border-neutral-800">
          <Button variant="ghost" onClick={onBack}>
            ← Другой файл
          </Button>
          <div className="flex items-center gap-4">
            <span className="text-sm text-neutral-500">
              {count ? `Выбрано колонок: ${count}` : 'Колонки не выбраны'}
            </span>
            <Button
              variant="primary"
              disabled={!suggestions || busy.suggest}
              onClick={() => suggestions && onNext(buildConfig(settings, suggestions))}
            >
              Далее: проверка →
            </Button>
          </div>
        </div>
      </div>

      <Sidebar meta={meta} settings={settings} risks={file.risks} onChange={patch} />
    </div>
  )
}

function findingText(
  f: SuggestResult['text_findings'][number],
  label: (e: string) => string,
): string {
  const types = f.entities.map(label).join(', ')
  switch (f.kind) {
    case 'sheet_name':
      return `Имя листа «${f.sheet}» содержит данные (${types}): переименуйте его в Excel`
    case 'defined_name':
      return `Имя именованного диапазона содержит данные (${types}): переименуйте его в Excel`
    case 'comment':
      return `Примечание ${f.ref} на листе «${f.sheet}» содержит данные (${types})`
    default:
      return `Автор примечания на листе «${f.sheet}» указан с данными (${types})`
  }
}

function HeaderRowControl({
  value,
  detected,
  manual,
  onChange,
}: {
  value: number
  detected: number
  manual: boolean
  onChange: (n: number | undefined) => void
}) {
  const [draft, setDraft] = useState(String(value))
  const commit = () => {
    const n = Number(draft)
    if (Number.isInteger(n) && n >= 1 && n !== value) onChange(n)
    else setDraft(String(value))
  }
  return (
    <div className="flex items-center gap-2 text-sm">
      <label htmlFor="header-row" className="whitespace-nowrap">Строка заголовка:</label>
      <input
        id="header-row"
        type="number"
        min={1}
        className={`${selectCls} w-16`}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === 'Enter' && commit()}
      />
      {manual ? (
        <button type="button" className="text-xs underline" onClick={() => onChange(undefined)}>
          авто ({detected})
        </button>
      ) : (
        <span className="text-xs text-neutral-500">определена автоматически</span>
      )}
    </div>
  )
}
