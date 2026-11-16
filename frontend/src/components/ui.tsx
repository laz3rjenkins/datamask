import type { AnchorHTMLAttributes, ButtonHTMLAttributes, KeyboardEvent, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

// Одна форма на все кнопки (6px, высота 36px); различаются заливкой, как на портале.
const buttonBase =
  'inline-flex h-9 items-center justify-center gap-2 rounded-md px-4 text-sm font-medium whitespace-nowrap transition-colors duration-150'
const DISABLED = 'disabled:cursor-not-allowed disabled:bg-pill disabled:text-disabled'

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-primary text-on-primary hover:bg-primary-hover',
  secondary: 'bg-pill text-ink hover:bg-pill-hover',
  ghost: 'text-link hover:bg-pill',
  danger: 'bg-danger-bg text-danger hover:bg-pill-hover',
}

export function Button({
  variant = 'secondary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return <button type="button" className={`${buttonBase} ${DISABLED} ${VARIANTS[variant]} ${className}`} {...props} />
}

/** Ссылка, оформленная как кнопка: скачивание файлов. */
export function ButtonLink({
  variant = 'secondary',
  className = '',
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: Variant }) {
  return <a className={`${buttonBase} ${VARIANTS[variant]} ${className}`} {...props} />
}

/** Строка заголовка страницы: крупный светлый заголовок и действия рядом, как на портале. */
export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
      <h1 className="text-[1.625rem] leading-tight font-light">{title}</h1>
      {children}
    </div>
  )
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <h2 className="text-lg leading-snug font-semibold">{children}</h2>
}

type Tone = 'warn' | 'error' | 'info'

const TONES: Record<Tone, { box: string; title: string }> = {
  warn: { box: 'bg-warn-bg', title: 'text-warn' },
  error: { box: 'bg-danger-bg', title: 'text-danger' },
  info: { box: 'bg-ground', title: '' },
}

export function Alert({
  tone = 'info',
  title,
  children,
}: {
  tone?: Tone
  title?: string
  children?: ReactNode
}) {
  const t = TONES[tone]
  return (
    <div role={tone === 'error' ? 'alert' : undefined} className={`rounded-lg px-4 py-3 text-sm ${t.box}`}>
      {title && <p className={`font-semibold ${t.title}`}>{title}</p>}
      {children && <div className={title ? 'mt-1' : tone === 'error' ? 'text-danger' : ''}>{children}</div>}
    </div>
  )
}

export function Spinner({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-slate" role="status">
      <span className="size-4 animate-spin rounded-full border-2 border-accent border-t-transparent" aria-hidden />
      {label}
    </span>
  )
}

/** Ход фоновой задачи: полоса и проценты. */
export function ProgressBar({ value, label }: { value: number; label?: string }) {
  return (
    <div className="flex items-center gap-3" role="status">
      {label && <span className="text-sm text-slate">{label}</span>}
      <div className="h-1.5 min-w-24 flex-1 overflow-hidden rounded-full bg-pill">
        <div className="h-full rounded-full bg-primary transition-[width] duration-200" style={{ width: `${value}%` }} />
      </div>
      <span className="text-sm tabular-nums">{value}%</span>
    </div>
  )
}

/** Значок необратимого способа (SPEC §4 «Честность перед пользователем»). */
export function Irreversible() {
  return (
    <span
      className="inline-flex items-center rounded-full bg-danger-bg px-2.5 py-0.5 text-xs font-medium text-danger"
      title="Исходное значение нельзя будет вернуть даже с таблицей соответствий"
    >
      не восстанавливается
    </span>
  )
}

/** Вкладки в серой капсуле, выбранная подчёркнута. Стрелки влево/вправо переключают. */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
  label,
}: {
  items: { value: T; label: ReactNode }[]
  value: T
  onChange: (v: T) => void
  label: string
}) {
  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    const i = items.findIndex((it) => it.value === value)
    const next = items[(i + (e.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length]
    onChange(next.value)
    const list = e.currentTarget
    // фокус следует за выбором: кнопки перерисуются с новым tabIndex
    requestAnimationFrame(() => list.querySelector<HTMLButtonElement>('[aria-selected="true"]')?.focus())
  }
  return (
    <div
      role="tablist"
      aria-label={label}
      onKeyDown={onKey}
      className="inline-flex max-w-full gap-x-5 overflow-x-auto rounded-3xl bg-pill px-4 [scrollbar-width:none]"
    >
      {items.map((it) => {
        const selected = it.value === value
        return (
          <button
            key={it.value}
            type="button"
            role="tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(it.value)}
            className={`shrink-0 border-b-2 py-2 text-sm whitespace-nowrap transition-colors duration-150 ${
              selected ? 'border-accent text-ink' : 'border-transparent text-slate hover:text-ink'
            }`}
          >
            {it.label}
          </button>
        )
      })}
    </div>
  )
}

const STEPS = ['Загрузка', 'Настройка', 'Проверка', 'Результат']

export function Steps({ current }: { current: number }) {
  return (
    <ol className="inline-flex max-w-full gap-x-5 overflow-x-auto rounded-3xl bg-pill px-4 text-sm [scrollbar-width:none]" aria-label="Шаги">
      {STEPS.map((s, i) => (
        <li
          key={s}
          aria-current={i === current ? 'step' : undefined}
          className={`shrink-0 border-b-2 py-2 whitespace-nowrap ${
            i === current ? 'border-accent text-ink' : `border-transparent ${i < current ? 'text-ink' : 'text-slate'}`
          }`}
        >
          <span className="tabular-nums">{i + 1}.</span>{' '}
          <span className={i === current ? '' : 'max-sm:sr-only'}>{s}</span>
        </li>
      ))}
    </ol>
  )
}

const field = 'rounded-md border border-field bg-panel text-ink placeholder:text-placeholder disabled:text-disabled'
export const selectCls = `${field} px-2 py-1.5 text-sm`
export const inputCls = `${field} h-10 w-full px-3 text-sm`
export const fileCls =
  'block text-sm text-slate file:mr-3 file:h-9 file:cursor-pointer file:rounded-md file:border-0 file:bg-pill file:px-4 file:text-sm file:font-medium file:text-ink hover:file:bg-pill-hover'
export const linkCls = 'text-link hover:underline underline-offset-2'
