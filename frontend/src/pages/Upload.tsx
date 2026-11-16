import { useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api/client'
import type { FileInfo, Meta, Project } from '../api/types'
import { IconUpload } from '../components/icons'
import { Alert, Button, Spinner, linkCls, selectCls } from '../components/ui'

const REJECT: Record<string, string> = {
  xls: 'Старый формат .xls не поддерживается. Пересохраните файл в Excel как .xlsx',
  xlsm: 'Файлы с макросами (.xlsm) не поддерживаются. Сохраните книгу как .xlsx',
}

export default function Upload({
  meta,
  onUploaded,
  onOpenProjects,
}: {
  meta: Meta
  onUploaded: (info: FileInfo, name: string, project: Project | null) => void
  onOpenProjects?: () => void // нет, пока раздел «Проекты» в разработке
}) {
  const input = useRef<HTMLInputElement>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState('')

  useEffect(() => {
    api.projects().then(setProjects, () => setProjects([]))
  }, [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [over, setOver] = useState(false)

  async function take(file: File | undefined) {
    if (!file || busy) return
    const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
    if (ext !== 'xlsx' && ext !== 'csv') {
      setError(REJECT[ext] ?? 'Поддерживаются только файлы .xlsx и .csv')
      return
    }
    if (file.size > meta.max_upload_mb * 2 ** 20) {
      setError(`Файл больше ${meta.max_upload_mb} МБ`)
      return
    }
    setBusy(true)
    setError(null)
    try {
      onUploaded(await api.upload(file), file.name, projects.find((p) => p.id === projectId) ?? null)
    } catch (e) {
      setError(errorText(e))
      setBusy(false)
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <p className="text-base text-slate">
          Загрузите выгрузку — datamask найдёт колонки с персональными данными и заменит их
          псевдонимами. Файл не покидает этот компьютер.
        </p>
      </div>

      {/* создать проект негде, пока раздел «Проекты» в разработке: блок — только для уже созданных */}
      {projects.length > 0 && (
        <div className="space-y-2">
          <label htmlFor="project" className="block text-sm font-semibold">
            Проект
          </label>
          <div className="flex flex-wrap items-center gap-3">
            <select
              id="project"
              className={`${selectCls} h-10 min-w-72`}
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
            >
              <option value="">Без проекта (только этот файл)</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            {onOpenProjects && (
              <button type="button" className={`text-sm ${linkCls}`} onClick={onOpenProjects}>
                {projects.length ? 'Управление проектами' : 'Создать проект'}
              </button>
            )}
          </div>
          <p className="text-xs text-slate">
            Проект нужен, чтобы псевдонимы совпадали в разных файлах одного клиента.
          </p>
        </div>
      )}

      <div
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setOver(false)
          take(e.dataTransfer.files[0])
        }}
        className={`flex flex-col items-center gap-4 rounded-lg border-2 border-dashed px-6 py-14 text-center transition-colors duration-150 ${
          over ? 'border-accent bg-band' : 'border-chip bg-ground'
        }`}
      >
        {busy ? (
          <Spinner label="Загружаю и читаю файл…" />
        ) : (
          <>
            <span className="text-slate">
              <IconUpload size={32} />
            </span>
            <p className="text-base font-medium">Перетащите файл сюда</p>
            <p className="text-sm text-slate">
              .xlsx или .csv, до {meta.max_upload_mb} МБ
            </p>
            <Button variant="primary" onClick={() => input.current?.click()}>
              Выбрать файл
            </Button>
          </>
        )}
        <input
          ref={input}
          type="file"
          accept=".xlsx,.csv"
          className="hidden"
          onChange={(e) => {
            take(e.target.files?.[0])
            e.target.value = ''
          }}
        />
      </div>

      {error && <Alert tone="error">{error}</Alert>}

      <Alert tone="info">
        Исходный файл не изменяется: результат сохраняется отдельной копией. Временные файлы
        удаляются при выходе из программы или по кнопке «Очистить сессию».
      </Alert>
    </div>
  )
}
