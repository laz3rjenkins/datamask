import { useState } from 'react'
import type { Category, Meta, Risk, Sanitize } from '../api/types'
import type { Settings } from '../lib/settings'
import { selectCls } from './ui'

const GROUPS: { value: Category; label: string }[] = [
  { value: 'personal', label: 'Персональные данные' },
  { value: 'financial', label: 'Финансовые' },
  { value: 'commercial', label: 'Коммерческие' },
]

export default function Sidebar({
  meta,
  settings,
  risks,
  onChange,
}: {
  meta: Meta
  settings: Settings
  risks: Risk[]
  onChange: (patch: Partial<Settings>) => void
}) {
  const [terms, setTerms] = useState(settings.customTerms)
  const has = (code: string) => risks.some((r) => r.code === code)
  const sanitize = (patch: Partial<Sanitize>) => onChange({ sanitize: { ...settings.sanitize, ...patch } })

  return (
    <aside className="space-y-6 text-sm">
      <section>
        <h2 className="font-semibold">Что маскировать</h2>
        <p className="mt-1 text-xs text-neutral-500">
          Влияет на подсказки и поиск в тексте. Выбор в колонке важнее.
        </p>
        <div className="mt-3 space-y-3">
          {GROUPS.map((g) => (
            <label key={g.value} className="flex gap-2">
              <input
                type="checkbox"
                className="mt-0.5 size-4 accent-neutral-900 dark:accent-neutral-100"
                checked={settings.categories[g.value]}
                onChange={(e) =>
                  onChange({ categories: { ...settings.categories, [g.value]: e.target.checked } })
                }
              />
              <span>
                <span className="font-medium">{g.label}</span>
                <span className="block text-xs text-neutral-500">
                  {meta.entities
                    .filter((e) => e.category === g.value && e.value !== 'CUSTOM')
                    .map((e) => e.label)
                    .join(', ')}
                </span>
              </span>
            </label>
          ))}
        </div>
      </section>

      <section>
        <label htmlFor="terms" className="font-semibold">
          Свой словарь
        </label>
        <p className="mt-1 text-xs text-neutral-500">
          Слова, которые скрываются везде: название клиента, продукта. По одному на строку.
          Регистр и ё/е не важны.
        </p>
        <textarea
          id="terms"
          rows={4}
          className={`${selectCls} mt-2 w-full`}
          placeholder={'Ромашка\nПроект Альфа'}
          value={terms}
          onChange={(e) => setTerms(e.target.value)}
          onBlur={() => terms !== settings.customTerms && onChange({ customTerms: terms })}
        />
        {settings.projectId && (
          <p className="mt-1 text-xs text-neutral-500">
            Словарь проекта применяется автоматически, новые слова добавятся в проект.
          </p>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="font-semibold">Очистка файла</h2>
        <p className="text-xs text-neutral-500">
          Автор, компания и другие свойства файла удаляются всегда.
          {has('pivot_cache') && ' Кэш сводных таблиц удаляется: обновите сводные в Excel.'}
        </p>
        {has('comments') && (
          <label className="block">
            Примечания к ячейкам
            <select
              className={`${selectCls} mt-1 w-full`}
              value={settings.sanitize.comments}
              onChange={(e) => sanitize({ comments: e.target.value as Sanitize['comments'] })}
            >
              <option value="remove">Удалить</option>
              <option value="keep">Оставить и проверить как текст</option>
            </select>
          </label>
        )}
        {has('hidden_sheet') && (
          <label className="block">
            Скрытые листы
            <select
              className={`${selectCls} mt-1 w-full`}
              value={settings.sanitize.hidden_sheets}
              onChange={(e) => sanitize({ hidden_sheets: e.target.value as Sanitize['hidden_sheets'] })}
            >
              <option value="keep">Оставить и обработать</option>
              <option value="remove">Удалить</option>
            </select>
          </label>
        )}
        {has('images') && (
          <label className="block">
            Изображения
            <select
              className={`${selectCls} mt-1 w-full`}
              value={settings.sanitize.images}
              onChange={(e) => sanitize({ images: e.target.value as Sanitize['images'] })}
            >
              <option value="keep">Оставить</option>
              <option value="remove">Удалить</option>
            </select>
          </label>
        )}
      </section>

      <p className="rounded-md bg-neutral-100 px-3 py-2 text-xs text-neutral-600 dark:bg-neutral-900 dark:text-neutral-400">
        Имена и адреса внутри свободного текста в этой версии не ищутся — только телефоны, email,
        документы и слова из своего словаря.
      </p>
    </aside>
  )
}
