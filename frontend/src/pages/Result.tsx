import { useState } from 'react'
import { api, errorText } from '../api/client'
import type { Job, Meta } from '../api/types'
import { Alert, Button } from '../components/ui'

const DOWNLOADS: { kind: string; title: string; note: string }[] = [
  { kind: 'masked', title: 'Замаскированный файл', note: 'Его можно отдавать дальше' },
  { kind: 'mapping', title: 'Таблица соответствий (.dmmap)', note: 'Зашифрована. Храните у себя, никому не отправляйте' },
  { kind: 'report_html', title: 'Отчёт (HTML)', note: 'Что и сколько заменено, без самих данных' },
  { kind: 'report_json', title: 'Отчёт (JSON)', note: 'То же для автоматической обработки' },
]

export default function Result({
  meta,
  job,
  outputName,
  onAnother,
  onCleared,
}: {
  meta: Meta
  job: Job
  outputName: string
  onAnother: () => void
  onCleared: () => void
}) {
  const [confirm, setConfirm] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const label = (e: string) => meta.entities.find((x) => x.value === e)?.label ?? e
  const s = job.summary
  const warnings = (s?.warnings ?? []).filter((w) => w !== meta.free_text_warning)

  async function clear() {
    try {
      await api.clearSession()
      onCleared()
    } catch (e) {
      setError(errorText(e))
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8 py-6">
      <div>
        <h1 className="text-2xl font-semibold">Готово</h1>
        <p className="mt-1 text-neutral-600 dark:text-neutral-400">{outputName}</p>
      </div>

      <Alert tone="warn">{meta.free_text_warning}</Alert>

      <ul className="divide-y divide-neutral-200 rounded-lg border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
        {DOWNLOADS.filter((d) => job.artifacts.includes(d.kind)).map((d) => (
          <li key={d.kind} className="flex items-center justify-between gap-4 px-4 py-3">
            <div>
              <p className="font-medium">{d.title}</p>
              <p className="text-sm text-neutral-500">{d.note}</p>
            </div>
            <a
              href={api.downloadUrl(job.job_id, d.kind)}
              download
              className="rounded-md border border-neutral-300 px-3.5 py-2 text-sm font-medium hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
            >
              Скачать
            </a>
          </li>
        ))}
      </ul>
      {!job.artifacts.includes('mapping') && (
        <p className="text-sm text-neutral-500">Таблица соответствий не сохранялась: размаскировка невозможна.</p>
      )}

      {s && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">Сводка</h2>
          <table className="w-full text-sm">
            <thead className="text-left text-neutral-500">
              <tr className="border-b border-neutral-200 dark:border-neutral-800">
                <th className="py-2 pr-4 font-normal">Тип</th>
                <th className="py-2 pr-4 text-right font-normal">Заменено</th>
                <th className="py-2 text-right font-normal">Уникальных</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(s.by_entity).map(([e, n]) => (
                <tr key={e} className="border-b border-neutral-100 dark:border-neutral-800/60">
                  <td className="py-2 pr-4">{label(e)}</td>
                  <td className="py-2 pr-4 text-right tabular-nums">{n.replaced}</td>
                  <td className="py-2 text-right tabular-nums">{e === 'FREE_TEXT' ? '—' : n.unique}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {s.outside_selected > 0 && (
            <p className="text-sm">
              Ещё заменено вне выбранных колонок (те же значения на других листах, свой словарь):{' '}
              {s.outside_selected}
            </p>
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
      )}

      {error && <Alert tone="error">{error}</Alert>}

      <div className="flex flex-wrap items-center gap-3 border-t border-neutral-200 pt-4 dark:border-neutral-800">
        <Button variant="primary" onClick={onAnother}>
          Маскировать ещё файл
        </Button>
        {confirm ? (
          <span className="flex flex-wrap items-center gap-2 text-sm">
            Удалить все файлы сессии, включая результаты?
            <Button variant="danger" onClick={clear}>
              Да, удалить
            </Button>
            <Button variant="ghost" onClick={() => setConfirm(false)}>
              Отмена
            </Button>
          </span>
        ) : (
          <Button onClick={() => setConfirm(true)}>Очистить сессию</Button>
        )}
      </div>
    </div>
  )
}
