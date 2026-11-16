import { useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { DryRun, FileInfo, Job, JobSummary, MaskConfig, Meta, SummaryResult } from '../api/types'
import { IconBack } from '../components/icons'
import { Alert, Button, Irreversible, ProgressBar, SectionTitle, Spinner, Tabs, inputCls } from '../components/ui'
import { formatCell } from '../lib/format'
import { useJob } from '../lib/useJob'

export default function Review({
  meta,
  file,
  fileName,
  config,
  projectName,
  onBack,
  onDone,
}: {
  meta: Meta
  file: FileInfo
  fileName: string
  config: MaskConfig
  projectName: string | null
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
  const [jobId, setJobId] = useState<string | null>(null)
  const [maskError, setMaskError] = useState<string | null>(null)
  const { job, error: jobError } = useJob<JobSummary>(jobId)
  const [summaryJobId, setSummaryJobId] = useState<string | null>(null)
  const [summaryStartError, setSummaryStartError] = useState<string | null>(null)
  const { job: summaryJob, error: summaryJobError } = useJob<SummaryResult>(summaryJobId)
  const summary = summaryJob?.status === 'done' ? (summaryJob.summary?.columns ?? []) : null
  const summaryError = summaryStartError ?? summaryJobError
  const selected = Object.values(config.sheets).some((s) => Object.keys(s.columns).length > 0)
  const project = config.project_id !== null

  useEffect(() => {
    api
      .dryRun(file.file_id, config)
      .then((d) => {
        setDry(d)
        setSheet(d.sheets.find((s) => s.columns.some((c) => c.entity))?.sheet ?? d.sheets[0]?.sheet ?? '')
      })
      .catch((e) => setError(errorText(e)))
  }, [file.file_id, config])

  // Итоги считаются фоновой задачей: на больших файлах это полный проход по листам.
  useEffect(() => {
    if (!selected) return
    api.summary(file.file_id, config).then(
      (r) => setSummaryJobId(r.job_id),
      (e) => setSummaryStartError(errorText(e)),
    )
  }, [file.file_id, config, selected])

  useEffect(() => {
    if (job?.status === 'done') onDone(job, outName)
  }, [job, onDone, outName])
  const running = !!jobId && !jobError && job?.status !== 'done'
  const shownError = maskError ?? jobError

  const label = (e: string) => meta.entities.find((x) => x.value === e)?.label ?? e
  const method = (m: string) => meta.methods.find((x) => x.value === m)
  const passwordProblem = project
    ? password
      ? null
      : 'Введите пароль проекта'
    : noMapping
    ? null
    : password.length < meta.min_password
      ? `Не короче ${meta.min_password} символов`
      : password !== repeat
        ? 'Пароли не совпадают'
        : null
  const nameHasData = file.name_findings.length > 0 && outName.includes(stem)

  async function start() {
    setMaskError(null)
    setJobId(null)
    try {
      const { job_id } = await api.mask(file.file_id, {
        config: { ...config, save_mapping: project || !noMapping },
        password: !project && noMapping ? null : password,
        output_name: outName,
      })
      setJobId(job_id)
    } catch (e) {
      setMaskError(errorText(e))
    }
  }

  if (error) {
    return (
      <div className="max-w-2xl space-y-4">
        <Alert tone="error" title="Настройки не подходят">
          {error}
        </Alert>
        <Button onClick={onBack}>
          <IconBack size={16} />
          Вернуться к настройке
        </Button>
      </div>
    )
  }
  if (!dry) return <div className="py-16 text-center"><Spinner label="Готовлю предпросмотр…" /></div>

  const current = dry.sheets.find((s) => s.sheet === sheet)
  const warnings = dry.warnings.filter((w) => w !== meta.free_text_warning)

  return (
    <div className="space-y-10">
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <SectionTitle>До и после</SectionTitle>
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
          <div className="max-h-[28rem] overflow-auto rounded-lg border border-line">
            <table className="w-max border-separate border-spacing-0 text-sm">
              <thead>
                <tr>
                  <th className="sticky top-0 left-0 z-20 border-b border-line bg-panel px-2 py-2 text-xs font-normal text-slate">
                    стр.
                  </th>
                  {current.columns.map((c) => (
                    <th
                      key={c.key}
                      className={`sticky top-0 z-10 max-w-64 min-w-32 border-b border-l border-line px-2 py-2 text-left align-top ${
                        c.entity ? 'bg-band' : 'bg-panel'
                      }`}
                    >
                      <span className="text-xs font-normal text-slate">{c.key} </span>
                      <span className="font-medium">{c.header}</span>
                      {c.entity && c.method && (
                        <span className="block text-xs font-normal text-slate">
                          {label(c.entity)} · {method(c.method)?.label}
                        </span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {current.rows.map((r) => (
                  <tr key={r.row} className={r.row < current.header_row ? 'text-slate' : ''}>
                    <td className="sticky left-0 border-b border-line bg-panel px-2 py-1.5 text-right text-xs text-slate tabular-nums">
                      {r.row}
                    </td>
                    {(view === 'after' ? r.after : r.before).map((v, i) => (
                      <td
                        key={i}
                        className={`max-w-64 truncate border-b border-l border-line px-2 py-1.5 ${
                          r.changed[i] ? 'bg-band' : ''
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
        <p className="text-xs text-slate">
          Первые 50 строк. Изменённые ячейки подсвечены зелёным. Псевдонимы здесь — пример: в
          итоговом файле нумерация считается по всему файлу.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg leading-snug font-semibold">Что будет заменено</h2>
        {!selected ? (
          <Alert tone="warn">
            Ни одна колонка не выбрана. Замаскированы будут только находки в шапке над таблицей и
            слова из своего словаря.
          </Alert>
        ) : summaryError ? (
          <Alert tone="error">{summaryError}</Alert>
        ) : !summary ? (
          <div className="max-w-md">
            <ProgressBar value={summaryJob?.progress ?? 0} label="Считаю значения по всему файлу…" />
            <p className="mt-2 text-xs text-slate">
              Можно не ждать: маскирование запускается и без этой таблицы.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-slate">
                <tr className="border-b border-line">
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
                {summary.map((c) => (
                  <tr key={`${c.sheet}!${c.key}`} className="border-b border-line">
                    <td className="py-2 pr-4">{c.sheet}</td>
                    <td className="py-2 pr-4">
                      <span className="text-slate">{c.key}</span> {c.header}
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

      <section className="grid gap-8 rounded-lg bg-ground p-5 md:grid-cols-2">
        <div className="space-y-3">
          <h2 className="text-lg leading-snug font-semibold">Таблица соответствий</h2>
          {project ? (
            <>
              <p className="text-sm text-slate">
                Новые значения добавятся в проект «{projectName}», уже известные получат прежние
                псевдонимы. В предпросмотре выше нумерация примерная.
              </p>
              <label className="block text-sm">
                Пароль проекта
                <input
                  type="password"
                  autoComplete="current-password"
                  className={`${inputCls} mt-1`}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </label>
            </>
          ) : (
            <>
              <p className="text-sm text-slate">
                Нужна, чтобы потом вернуть настоящие значения. Хранится только в зашифрованном
                виде; пароль нигде не сохраняется — без него восстановить данные нельзя.
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
                <p className="text-sm text-danger">{passwordProblem}</p>
              )}
              <label className="flex gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 size-4"
                  checked={noMapping}
                  onChange={(e) => setNoMapping(e.target.checked)}
                />
                Не сохранять таблицу соответствий (размаскировка будет невозможна)
              </label>
            </>
          )}
        </div>

        <div className="space-y-3">
          <h2 className="text-lg leading-snug font-semibold">Имя результата</h2>
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

      {shownError && <Alert tone="error">{shownError}</Alert>}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
        <Button variant="ghost" onClick={onBack} disabled={!!running}>
          <IconBack size={16} />
          Назад к настройке
        </Button>
        {running ? (
          <div className="w-72">
            <ProgressBar value={job?.progress ?? 0} />
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
