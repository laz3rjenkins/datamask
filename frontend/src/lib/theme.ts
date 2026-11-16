/** Тема интерфейса: как в системе, светлая или тёмная. Цвета переключает color-scheme корня
 *  (index.css), здесь — выбор, его хранение и анимация смены. */

export type ThemePref = 'system' | 'light' | 'dark'

export const THEME_LABELS: Record<ThemePref, string> = {
  system: 'как в системе',
  light: 'светлая',
  dark: 'тёмная',
}
const ORDER: ThemePref[] = ['system', 'light', 'dark']

const systemDark = () => window.matchMedia('(prefers-color-scheme: dark)')
let pref: ThemePref = 'system'

/** Выбор из cookie. Cookie, а не localStorage: порт у каждого запуска свой, localStorage
 *  привязан к порту, а cookie — нет. */
export function readTheme(cookie: string): ThemePref {
  const v = /(?:^|;\s*)datamask_theme=(\w+)/.exec(cookie)?.[1]
  return v === 'light' || v === 'dark' ? v : 'system'
}

export const nextTheme = (p: ThemePref): ThemePref => ORDER[(ORDER.indexOf(p) + 1) % ORDER.length]

const resolve = (p: ThemePref) => (p === 'system' ? (systemDark().matches ? 'dark' : 'light') : p)

function apply() {
  document.documentElement.dataset.theme = resolve(pref)
}

/** До первого рендера: тема из cookie и слежение за системной. */
export function initTheme(): ThemePref {
  pref = readTheme(document.cookie)
  apply()
  systemDark().addEventListener('change', () => pref === 'system' && apply())
  return pref
}

/** Сменить тему: новая раскрывается кругом из точки (x, y) — от кнопки переключателя. */
export function setTheme(next: ThemePref, x: number, y: number) {
  const changes = resolve(next) !== resolve(pref)
  pref = next
  document.cookie = `datamask_theme=${next}; path=/; max-age=31536000; samesite=strict`
  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (!changes || still || !document.startViewTransition) {
    apply()
    return
  }
  const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y))
  document.startViewTransition(apply).ready.then(() =>
    document.documentElement.animate(
      { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
      { duration: 500, easing: 'cubic-bezier(0.16, 1, 0.3, 1)', pseudoElement: '::view-transition-new(root)' },
    ),
  )
}
