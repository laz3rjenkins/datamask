import { type FormEvent, useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { Meta, Project, Template } from '../api/types'
import { Alert, Button, PageHeader, inputCls } from '../components/ui'

const date = (iso: string) =>
  new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })

export default function Projects({ meta }: { meta: Meta }) {
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [templates, setTemplates] = useState<Template[]>([])
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState<string | null>(null) // id удаляемого

  useEffect(() => {
    api.projects().then(setProjects, (e) => setError(errorText(e)))
    api.templates().then(setTemplates, () => setTemplates([]))
  }, [])

  const problem = !name.trim()
    ? 'Введите название'
    : password.length < meta.min_password
      ? `Пароль — не короче ${meta.min_password} символов`
      : password !== repeat
        ? 'Пароли не совпадают'
        : null

  async function create(e: FormEvent) {
    e.preventDefault()
    if (problem) return
    setBusy(true)
    setError(null)
    try {
      const p = await api.createProject(name, password)
      setProjects((ps) => [p, ...(ps ?? [])])
      setName('')
      setPassword('')
      setRepeat('')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove(kind: 'project' | 'template', id: string) {
    setError(null)
    try {
      if (kind === 'project') {
        await api.deleteProject(id)
        setProjects((ps) => (ps ?? []).filter((p) => p.id !== id))
      } else {
        await api.deleteTemplate(id)
        setTemplates((ts) => ts.filter((t) => t.id !== id))
      }
    } catch (err) {
      setError(errorText(err))
    } finally {
      setConfirm(null)
    }
  }

  const confirmRow = (kind: 'project' | 'template', id: string, what: string) =>
    confirm === id ? (
      <span className="flex flex-wrap items-center justify-end gap-2 text-sm">
        {what}
        <Button variant="danger" onClick={() => remove(kind, id)}>
          Удалить
        </Button>
        <Button variant="ghost" onClick={() => setConfirm(null)}>
          Отмена
        </Button>
      </span>
    ) : (
      <Button variant="ghost" onClick={() => setConfirm(id)}>
        Удалить
      </Button>
    )

  return (
    <div className="max-w-3xl space-y-10">
      <section className="space-y-4">
        <div>
          <PageHeader title="Проекты" />
          <p className="mt-3 text-base text-slate">
            Проект — общая таблица соответствий для нескольких файлов одного клиента: один и тот же
            человек получает один псевдоним во всех выгрузках. Хранится на этом компьютере в
            зашифрованном виде.
          </p>
        </div>

        {error && <Alert tone="error">{error}</Alert>}

        {projects === null ? null : projects.length === 0 ? (
          <p className="text-sm text-slate">Проектов пока нет.</p>
        ) : (
          <ul className="divide-y divide-line rounded-lg border border-line">
            {projects.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div>
                  <p className="font-medium">{p.name}</p>
                  <p className="text-sm text-slate">
                    создан {date(p.created_at)} · изменён {date(p.updated_at)} · записей: {p.entries}
                  </p>
                </div>
                {confirmRow('project', p.id, 'Все соответствия проекта будут потеряны. Удалить?')}
              </li>
            ))}
          </ul>
        )}
      </section>

      <form onSubmit={create} className="space-y-3 rounded-lg bg-ground p-5">
        <h2 className="font-semibold">Новый проект</h2>
        <label className="block text-sm">
          Название
          <input className={`${inputCls} mt-1`} maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
          <span className="mt-1 block text-xs text-slate">
            Название хранится открыто, чтобы показать список без пароля. Не пишите в нём персональные данные.
          </span>
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            Пароль проекта
            <input
              type="password"
              autoComplete="new-password"
              className={`${inputCls} mt-1`}
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
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
            />
          </label>
        </div>
        <p className="text-xs text-slate">
          Пароль нигде не сохраняется. Без него нельзя ни дополнить проект, ни восстановить данные.
        </p>
        {problem && (name || password || repeat) && <p className="text-sm text-danger">{problem}</p>}
        <Button type="submit" variant="primary" disabled={!!problem || busy}>
          Создать проект
        </Button>
      </form>

      <section className="space-y-3">
        <h2 className="text-lg leading-snug font-semibold">Шаблоны настроек</h2>
        <p className="text-sm text-slate">
          Правила «заголовок колонки → тип и способ». Сохраняются на экране настройки и
          применяются к файлам той же структуры.
        </p>
        {templates.length === 0 ? (
          <p className="text-sm text-slate">Шаблонов пока нет.</p>
        ) : (
          <ul className="divide-y divide-line rounded-lg border border-line">
            {templates.map((t) => (
              <li key={t.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div>
                  <p className="font-medium">{t.name}</p>
                  <p className="text-sm text-slate">
                    {t.rules.map((r) => r.header).join(', ')}
                  </p>
                </div>
                {confirmRow('template', t.id, 'Удалить шаблон?')}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
