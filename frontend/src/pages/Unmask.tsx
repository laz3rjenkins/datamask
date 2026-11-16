import { useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { Project, UnmaskReport } from '../api/types'
import { IconDownload } from '../components/icons'
import { Alert, Button, ButtonLink, PageHeader, ProgressBar, fileCls, inputCls, selectCls } from '../components/ui'
import { useJob } from '../lib/useJob'

const ACCEPT = '.xlsx,.csv,.txt,.md,.html,.htm,.json'

export default function Unmask() {
  const [file, setFile] = useState<File | null>(null)
  const [source, setSource] = useState<'mapping' | 'project'>('mapping')
  const [mapping, setMapping] = useState<File | null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState('')
  const [password, setPassword] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const [startError, setStartError] = useState<string | null>(null)
  const { job, error: jobError } = useJob<UnmaskReport>(jobId)

  useEffect(() => {
    api.projects().then((ps) => {
      setProjects(ps)
      setProjectId(ps[0]?.id ?? '')
    }, () => setProjects([]))
  }, [])

  const running = !!jobId && !jobError && job?.status !== 'done'
  const ready = file && password && (source === 'mapping' ? mapping : projectId)
  const report = job?.status === 'done' ? job.summary : null
  const outName = file ? file.name.replace(/(\.[^.]+)$/, '_unmasked$1') : ''

  async function start() {
    if (!ready || !file) return
    setStartError(null)
    setJobId(null)
    try {
      const src = source === 'mapping' && mapping ? { mapping } : { projectId }
      setJobId((await api.unmask(file, src, password)).job_id)
    } catch (e) {
      setStartError(errorText(e))
    }
  }

  const error = startError ?? jobError

  return (
    <div className="max-w-2xl space-y-8">
      <div>
        <PageHeader title="Размаскировка" />
        <p className="mt-3 text-base text-slate">
          Верните настоящие значения в файл, сделанный по замаскированным данным: например, в
          дашборд от облачной модели. Всё происходит на этом компьютере.
        </p>
      </div>

      <section className="space-y-2">
        <label htmlFor="unmask-file" className="block font-medium">
          1. Файл с псевдонимами
        </label>
        <input
          id="unmask-file"
          type="file"
          accept={ACCEPT}
          className={fileCls}
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null)
            setJobId(null)
          }}
        />
        <p className="text-xs text-slate">XLSX, CSV, TXT, MD, HTML или JSON</p>
      </section>

      <section className="space-y-3">
        <p className="font-medium">2. Откуда взять соответствия</p>
        <div className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-2">
            <input type="radio" name="source" checked={source === 'mapping'} onChange={() => setSource('mapping')} />
            Файл таблицы соответствий (.dmmap)
          </label>
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="source"
              checked={source === 'project'}
              disabled={!projects.length}
              onChange={() => setSource('project')}
            />
            Проект{!projects.length && ' (проектов пока нет)'}
          </label>
        </div>
        {source === 'mapping' ? (
          <input
            type="file"
            accept=".dmmap"
            aria-label="Таблица соответствий"
            className={fileCls}
            onChange={(e) => setMapping(e.target.files?.[0] ?? null)}
          />
        ) : (
          <select
            aria-label="Проект"
            className={`${selectCls} h-10 min-w-72`}
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} · записей: {p.entries}
              </option>
            ))}
          </select>
        )}
        <label className="block max-w-sm text-sm">
          {source === 'project' ? 'Пароль проекта' : 'Пароль таблицы соответствий'}
          <input
            type="password"
            autoComplete="current-password"
            className={`${inputCls} mt-1`}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && start()}
          />
        </label>
      </section>

      {error && <Alert tone="error">{error}</Alert>}

      <div className="flex items-center gap-4">
        <Button variant="primary" disabled={!ready || running} onClick={start}>
          Восстановить
        </Button>
        {running && (
          <div className="w-72">
            <ProgressBar value={job?.progress ?? 0} label="Восстанавливаю…" />
          </div>
        )}
      </div>

      {report && job && (
        <section className="space-y-4 border-t border-line pt-6">
          <h2 className="text-lg leading-snug font-semibold">Готово</h2>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
            <Stat label="Псевдонимов и хешей заменено" value={report.tokens_replaced} />
            <Stat label="Фейков заменено" value={report.fakes_replaced} />
            <Stat label="Не найдено в таблице" value={report.unknown_tokens} warn={report.unknown_tokens > 0} />
            {report.dates_restored > 0 && <Stat label="Дат восстановлено" value={report.dates_restored} />}
            {report.numbers_restored > 0 && <Stat label="Чисел восстановлено" value={report.numbers_restored} />}
          </dl>
          {report.unknown_sample.length > 0 && (
            <Alert tone="warn" title="Остались без замены">
              <p className="font-mono text-xs break-words">{report.unknown_sample.join(', ')}</p>
            </Alert>
          )}
          {report.missing_columns.length > 0 && (
            <Alert tone="warn" title="Не найдены колонки для восстановления дат и чисел">
              {report.missing_columns.join('; ')}
            </Alert>
          )}
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate">
            {report.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
          <ButtonLink variant="primary" href={api.downloadUrl(job.job_id, 'restored')} download>
            <IconDownload size={16} />
            Скачать {outName}
          </ButtonLink>
          <p className="text-xs text-slate">
            Восстановленный файл содержит настоящие данные — не отправляйте его в облако.
          </p>
        </section>
      )}
    </div>
  )
}

function Stat({ label, value, warn }: { label: string; value: number; warn?: boolean }) {
  return (
    <div>
      <dt className="text-slate">{label}</dt>
      <dd className={`text-xl font-semibold tabular-nums ${warn ? 'text-warn' : ''}`}>{value}</dd>
    </div>
  )
}
