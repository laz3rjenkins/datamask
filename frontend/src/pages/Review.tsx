import { useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { DryRun, FileInfo, Job, MaskConfig, Meta } from '../api/types'
import { Alert, Button, Irreversible, Spinner, Tabs, inputCls } from '../components/ui'
import { formatCell } from '../lib/format'

export default function Review({
  meta,
  file,
  fileName,
  config,
  onBack,
  onDone,
}: {
  meta: Meta
  file: FileInfo
  fileName: string
  config: MaskConfig
  onBack: () => void
  onDone: (job: Job, outputName: string) => void
}) {
  const [dry, setDry] = useState<DryRun | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sheet, setSheet] = useState('')
  const [view, setView] = useState<'after' | 'before'>('after')
  const ext = fileName.slice(fileName.lastIndexOf('.'))
  const stem = fileName.slice(0, -ext.length)
  const [outName, setOutName] = useState(`${stem}_masked${ext}`)
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [noMapping, setNoMapping] = useState(false)
  const [job, setJob] = useState<Job | null>(null)
  const [maskError, setMaskError] = useState<string | null>(null)

  useEffect(() => {
    api
      .dryRun(file.file_id, config)
      .then((d) => {
        setDry(d)
        setSheet(d.sheets.find((s) => d.summary.some((c) => c.sheet === s.sheet))?.sheet ?? d.sheets[0]?.sheet ?? '')
      })
      .catch((e) => setError(errorText(e)))
  }, [file.file_id, config])

  // Опрос фоновой задачи до завершения.
  const jobId = job?.job_id
  const running = job && (job.status === 'queued' || job.status === 'running')
  useEffect(() => {
    if (!jobId || !running) return
    const t = setInterval(async () => {
      try {
        const j = await api.job(jobId)
        setJob(j)
        if (j.status === 'done') onDone(j, outName)
        if (j.status === 'error') setMaskError(j.error)
      } catch (e) {
        setMaskError(errorText(e))
        setJob(null)
      }
    }, 400)
    return () => clearInterval(t)
  }, [jobId, running, onDone, outName])

  const label = (e: string) => meta.entities.find((x) => x.value === e)?.label ?? e
  const method = (m: string) => meta.methods.find((x) => x.value === m)
  const passwordProblem = noMapping
    ? null
    : password.length < meta.min_password
      ? `Не короче ${meta.min_password} символов`
      : password !== repeat
        ? 'Пароли не совпадают'
        : null
  const nameHasData = file.name_findings.length > 0 && outName.includes(stem)

  async function start() {
    setMaskError(null)
    try {
      const { job_id } = await api.mask(file.file_id, {
        config: { ...config, save_mapping: !noMapping },
        password: noMapping ? null : password,
        output_name: outName,
      })
      setJob({ job_id, status: 'queued', progress: 0, artifacts: [], error: null, summary: null })
    } catch (e) {
      setMaskError(errorText(e))
    }
  }

  if (error) {
    return (
      <div className="mx-auto max-w-2xl space-y-4 py-10">
        <Alert tone="error" title="Настройки не подходят">
          {error}
        </Alert>
        <Button onClick={onBack}>← Вернуться к настройке</Button>
      </div>
    )
  }
  if (!dry) return <div className="py-16 text-center"><Spinner label="Готовлю предпросмотр…" /></div>

  const current = dry.sheets.find((s) => s.sheet === sheet)
  const warnings = dry.warnings.filter((w) => w !== meta.free_text_warning)

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-xl font-semibold">Проверьте результат</h1>
          <Tabs
            label="Вид"
            value={view}
            onChange={setView}
            items={[
              { value: 'before', label: 'До' },
              { value: 'after', label: 'После' },
            ]}
          />
        </div>
        <Alert tone="warn">{meta.free_text_warning}</Alert>
        {dry.sheets.length > 1 && (
          <Tabs label="Листы" value={sheet} onChange={setSheet} items={dry.sheets.map((s) => ({ value: s.sheet, label: s.sheet }))} />
        )}
        {current && (
          <div className="max-h-[28rem] overflow-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
            <table className="w-max border-separate border-spacing-0 text-sm">
              <thead>
                <tr>
                  <th className="sticky top-0 left-0 z-20 border-b border-neutral-200 bg-neutral-50 px-2 py-2 text-xs font-normal text-neutral-400 dark:border-neutral-800 dark:bg-neutral-900">
                    стр.
                  </th>
                  {current.columns.map((c) => (
                    <th
                      key={c.key}
                      className={`sticky top-0 z-10 max-w-64 min-w-32 border-b border-l border-neutral-200 px-2 py-2 text-left align-top dark:border-neutral-800 ${
                        c.entity ? 'bg-amber-50 dark:bg-amber-900/30' : 'bg-neutral-50 dark:bg-neutral-900'
                      }`}
                    >
                      <span className="text-xs font-normal text-neutral-400">{c.key} </span>
                      <span className="font-medium">{c.header}</span>
                      {c.entity && c.method && (
                        <span className="block text-xs font-normal text-neutral-500">
                          {label(c.entity)} · {method(c.method)?.label}
                        </span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {current.rows.map((r) => (
                  <tr key={r.row} className={r.row < current.header_row ? 'text-neutral-500' : ''}>
                    <td className="sticky left-0 border-b border-neutral-100 bg-white px-2 py-1.5 text-right text-xs text-neutral-400 tabular-nums dark:border-neutral-800/60 dark:bg-neutral-950">
                      {r.row}
                    </td>
                    {(view === 'after' ? r.after : r.before).map((v, i) => (
                      <td
                        key={i}
                        className={`max-w-64 truncate border-b border-l border-neutral-100 px-2 py-1.5 dark:border-neutral-800/60 ${
                          r.changed[i] ? 'bg-emerald-50 dark:bg-emerald-950/50' : ''
                        }`}
                        title={formatCell(v)}
                      >
                        {formatCell(v)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-xs text-neutral-500">
          Первые 50 строк. Изменённые ячейки подсвечены зелёным. Псевдонимы здесь — пример: в
          итоговом файле нумерация считается по всему файлу.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Что будет заменено</h2>
        {dry.summary.length === 0 ? (
          <Alert tone="warn">
            Ни одна колонка не выбрана. Замаскированы будут только находки в шапке над таблицей и
            слова из своего словаря.
          </Alert>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-neutral-500">
                <tr className="border-b border-neutral-200 dark:border-neutral-800">
                  <th className="py-2 pr-4 font-normal">Лист</th>
                  <th className="py-2 pr-4 font-normal">Колонка</th>
                  <th className="py-2 pr-4 font-normal">Тип</th>
                  <th className="py-2 pr-4 font-normal">Способ</th>
                  <th className="py-2 pr-4 text-right font-normal">Значений</th>
                  <th className="py-2 pr-4 text-right font-normal">Уникальных</th>
                  <th className="py-2 text-right font-normal">Пропущено формул</th>
                </tr>
              </thead>
              <tbody>
                {dry.summary.map((c) => (
                  <tr key={`${c.sheet}!${c.key}`} className="border-b border-neutral-100 dark:border-neutral-800/60">
                    <td className="py-2 pr-4">{c.sheet}</td>
                    <td className="py-2 pr-4">
                      <span className="text-neutral-400">{c.key}</span> {c.header}
                    </td>
                    <td className="py-2 pr-4">{label(c.entity)}</td>
                    <td className="py-2 pr-4">
                      <span className="flex flex-wrap items-center gap-2">
                        {method(c.method)?.label}
                        {!method(c.method)?.reversible && <Irreversible />}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums">{c.values}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">{c.unique}</td>
                    <td className="py-2 text-right tabular-nums">{c.skipped_formulas || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {warnings.length > 0 && (
          <Alert tone="warn" title="Предупреждения">
            <ul className="list-disc space-y-0.5 pl-5">
              {warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </Alert>
        )}
      </section>

      <section className="grid gap-6 md:grid-cols-2">
        <div className="space-y-3">
          <h2 className="text-lg font-semibold">Таблица соответствий</h2>
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            Нужна, чтобы потом вернуть настоящие значения. Хранится только в зашифрованном виде;
            пароль нигде не сохраняется — без него восстановить данные нельзя.
          </p>
          <label className="block text-sm">
            Пароль
            <input
              type="password"
              autoComplete="new-password"
              className={`${inputCls} mt-1`}
              disabled={noMapping}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <label className="block text-sm">
            Повтор пароля
            <input
              type="password"
              autoComplete="new-password"
              className={`${inputCls} mt-1`}
              disabled={noMapping}
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
            />
          </label>
          {passwordProblem && (password || repeat) && (
            <p className="text-sm text-red-700 dark:text-red-300">{passwordProblem}</p>
          )}
          <label className="flex gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 size-4 accent-neutral-900 dark:accent-neutral-100"
              checked={noMapping}
              onChange={(e) => setNoMapping(e.target.checked)}
            />
            Не сохранять таблицу соответствий (размаскировка будет невозможна)
          </label>
        </div>

        <div className="space-y-3">
          <h2 className="text-lg font-semibold">Имя результата</h2>
          <label className="block text-sm">
            <span className="sr-only">Имя замаскированного файла</span>
            <input className={inputCls} value={outName} onChange={(e) => setOutName(e.target.value)} />
          </label>
          {nameHasData && (
            <Alert tone="warn">
              В имени файла найдено: {file.name_findings.map(label).join(', ')}. Переименуйте
              результат, чтобы имя не выдало данные.
            </Alert>
          )}
        </div>
      </section>

      {maskError && <Alert tone="error">{maskError}</Alert>}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-neutral-200 pt-4 dark:border-neutral-800">
        <Button variant="ghost" onClick={onBack} disabled={!!running}>
          ← Назад к настройке
        </Button>
        {running ? (
          <div className="flex w-72 items-center gap-3" role="status">
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800">
              <div className="h-full bg-neutral-900 transition-all dark:bg-neutral-100" style={{ width: `${job.progress}%` }} />
            </div>
            <span className="text-sm tabular-nums">{job.progress}%</span>
          </div>
        ) : (
          <Button variant="primary" disabled={!!passwordProblem || !outName.trim()} onClick={start}>
            Замаскировать
          </Button>
        )}
      </div>
    </div>
  )
}
