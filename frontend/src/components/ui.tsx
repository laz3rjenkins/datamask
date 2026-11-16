import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

const VARIANTS: Record<Variant, string> = {
  primary:
    'bg-neutral-900 text-white hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300',
  secondary:
    'border border-neutral-300 bg-white hover:bg-neutral-100 dark:border-neutral-700 dark:bg-neutral-900 dark:hover:bg-neutral-800',
  ghost: 'hover:bg-neutral-100 dark:hover:bg-neutral-800',
  danger: 'bg-red-600 text-white hover:bg-red-500',
}

export function Button({
  variant = 'secondary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-neutral-500 disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
      {...props}
    />
  )
}

type Tone = 'warn' | 'error' | 'info'

const TONES: Record<Tone, string> = {
  warn: 'border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-700/60 dark:bg-amber-950/40 dark:text-amber-100',
  error: 'border-red-300 bg-red-50 text-red-950 dark:border-red-800 dark:bg-red-950/40 dark:text-red-100',
  info: 'border-neutral-200 bg-neutral-50 text-neutral-800 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-200',
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
  return (
    <div role={tone === 'error' ? 'alert' : undefined} className={`rounded-md border px-4 py-3 text-sm ${TONES[tone]}`}>
      {title && <p className="font-medium">{title}</p>}
      {children && <div className={title ? 'mt-1' : ''}>{children}</div>}
    </div>
  )
}

export function Spinner({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-neutral-500 dark:text-neutral-400" role="status">
      <span className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden />
      {label}
    </span>
  )
}

/** Ход фоновой задачи: полоса и проценты. */
export function ProgressBar({ value, label }: { value: number; label?: string }) {
  return (
    <div className="flex items-center gap-3" role="status">
      {label && <span className="text-sm text-neutral-500 dark:text-neutral-400">{label}</span>}
      <div className="h-2 min-w-24 flex-1 overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800">
        <div className="h-full bg-neutral-900 transition-all dark:bg-neutral-100" style={{ width: `${value}%` }} />
      </div>
      <span className="text-sm tabular-nums">{value}%</span>
    </div>
  )
}

/** Значок необратимого способа (SPEC §4 «Честность перед пользователем»). */
export function Irreversible() {
  return (
    <span
      className="inline-flex items-center gap-1 rounded bg-red-100 px-1.5 py-0.5 text-xs font-medium text-red-800 dark:bg-red-950 dark:text-red-200"
      title="Исходное значение нельзя будет вернуть даже с таблицей соответствий"
    >
      ⚠ не восстанавливается
    </span>
  )
}

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
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-1">
      {items.map((it) => (
        <button
          key={it.value}
          type="button"
          role="tab"
          aria-selected={it.value === value}
          onClick={() => onChange(it.value)}
          className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
            it.value === value
              ? 'bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900'
              : 'text-neutral-600 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:bg-neutral-800'
          }`}
        >
          {it.label}
        </button>
      ))}
    </div>
  )
}

const STEPS = ['Загрузка', 'Настройка', 'Проверка', 'Результат']

export function Steps({ current }: { current: number }) {
  return (
    <ol className="flex items-center gap-2 text-sm" aria-label="Шаги">
      {STEPS.map((s, i) => (
        <li key={s} className="flex items-center gap-2" aria-current={i === current ? 'step' : undefined}>
          {i > 0 && <span className="h-px w-5 bg-neutral-300 dark:bg-neutral-700" aria-hidden />}
          <span
            className={`flex size-6 items-center justify-center rounded-full text-xs font-medium ${
              i < current
                ? 'bg-neutral-300 text-neutral-800 dark:bg-neutral-700 dark:text-neutral-100'
                : i === current
                  ? 'bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900'
                  : 'border border-neutral-300 text-neutral-500 dark:border-neutral-700'
            }`}
          >
            {i + 1}
          </span>
          <span className={i === current ? 'font-medium' : 'text-neutral-500 max-sm:hidden'}>{s}</span>
        </li>
      ))}
    </ol>
  )
}

export const selectCls =
  'rounded-md border border-neutral-300 bg-white px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-900'
export const inputCls =
  'w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900'
