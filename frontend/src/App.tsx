import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from './api/client'
import type { FileInfo, Job, MaskConfig, Meta, Project } from './api/types'
import { IconLock, IconMask, IconMenu, IconMoon, IconProjects, IconSun, IconSystem, IconUnmask } from './components/icons'
import { Alert, PageHeader, Spinner, Steps } from './components/ui'
import { initialSettings, type Settings } from './lib/settings'
import { THEME_LABELS, nextTheme, readTheme, setTheme, type ThemePref } from './lib/theme'
import Configure from './pages/Configure'
import Projects from './pages/Projects'
import Result from './pages/Result'
import Review from './pages/Review'
import Unmask from './pages/Unmask'
import Upload from './pages/Upload'

type Section = 'mask' | 'unmask' | 'projects'
type State =
  | { step: 'upload' }
  | { step: 'configure' }
  | { step: 'review'; config: MaskConfig }
  | { step: 'result'; job: Job; outputName: string }

const STEP_INDEX = { upload: 0, configure: 1, review: 2, result: 3 }
const STEP_TITLE = {
  upload: 'Маскирование таблицы',
  configure: 'Настройка колонок',
  review: 'Проверка',
  result: 'Готово',
}
const THEME_ICONS = { system: IconSystem, light: IconSun, dark: IconMoon }
const SECTIONS = [
  { value: 'mask', label: 'Маскирование', icon: IconMask },
  { value: 'unmask', label: 'Размаскировка', icon: IconUnmask },
  { value: 'projects', label: 'Проекты', icon: IconProjects },
] as const

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [fatal, setFatal] = useState<string | null>(null)
  const [section, setSection] = useState<Section>('mask')
  const [state, setState] = useState<State>({ step: 'upload' })
  // Имя файла живёт только в памяти вкладки: сервер его не хранит и не пишет в логи.
  const [file, setFile] = useState<{ info: FileInfo; name: string; project: Project | null } | null>(null)
  const [settings, setSettings] = useState<Settings>(initialSettings)
  // Панель сама сворачивается на «Настройке»: таблице нужна ширина. Кнопка меню — выбор вручную.
  const [manualCollapse, setManualCollapse] = useState<boolean | null>(null)
  const collapsed = manualCollapse ?? (section === 'mask' && state.step === 'configure')
  const [actions, setActions] = useState<HTMLDivElement | null>(null)
  const [theme, setThemePref] = useState<ThemePref>(() => readTheme(document.cookie))
  const ThemeIcon = THEME_ICONS[theme]

  useEffect(() => {
    api.meta().then(setMeta, (e) => setFatal(errorText(e)))
  }, [])
  useEffect(() => {
    window.scrollTo(0, 0) // в новых браузерах возвращает Promise: не отдавать его React как cleanup
  }, [state.step, section])

  const restart = useCallback(() => {
    setFile(null)
    setSettings(initialSettings())
    setState({ step: 'upload' })
  }, [])
  const onDone = useCallback((job: Job, outputName: string) => setState({ step: 'result', job, outputName }), [])

  function maskFlow(meta: Meta) {
    if (state.step === 'upload' || !file) {
      return (
        <Upload
          meta={meta}
          onOpenProjects={() => setSection('projects')}
          onUploaded={(info, name, project) => {
            setFile({ info, name, project })
            setSettings({ ...initialSettings(), projectId: project?.id ?? null })
            setState({ step: 'configure' })
          }}
        />
      )
    }
    if (state.step === 'configure') {
      return (
        <Configure
          meta={meta}
          file={file.info}
          settings={settings}
          setSettings={setSettings}
          actions={actions}
          onFile={(info) => setFile({ ...file, info })}
          onBack={restart}
          onNext={(config) => setState({ step: 'review', config })}
        />
      )
    }
    if (state.step === 'review') {
      return (
        <Review
          meta={meta}
          file={file.info}
          fileName={file.name}
          config={state.config}
          projectName={file.project?.name ?? null}
          onBack={() => setState({ step: 'configure' })}
          onDone={onDone}
        />
      )
    }
    return <Result meta={meta} job={state.job} outputName={state.outputName} onAnother={restart} onCleared={restart} />
  }

  const step = file ? state.step : 'upload'
  // Узкий экран: панель всегда свёрнута до иконок.
  const label = collapsed ? 'sr-only' : 'whitespace-nowrap max-md:sr-only'
  const iconOnly = collapsed ? 'justify-center px-0' : 'max-md:justify-center max-md:px-0'

  return (
    <div className="flex min-h-screen">
      {/* ширина плавно меняется при сворачивании; без движения при prefers-reduced-motion (index.css) */}
      <aside
        className={`sticky top-0 flex h-screen w-16 shrink-0 flex-col overflow-hidden transition-[width] duration-200 ease-out ${collapsed ? '' : 'md:w-60'}`}
      >
        <div className="flex h-16 items-center gap-2 px-3">
          <button
            type="button"
            onClick={() => setManualCollapse(!collapsed)}
            aria-label={collapsed ? 'Развернуть меню' : 'Свернуть меню'}
            aria-expanded={!collapsed}
            className="grid size-10 place-items-center rounded-md text-slate transition-colors duration-150 hover:bg-pill-hover hover:text-ink max-md:hidden"
          >
            <IconMenu />
          </button>
          <span className={`text-xl font-bold text-navy ${label}`}>datamask</span>
          <span className="mx-auto text-base font-bold text-navy md:hidden" aria-hidden>
            dm
          </span>
        </div>

        <nav aria-label="Разделы" className="mt-6 flex flex-col">
          {SECTIONS.map(({ value, label: text, icon: Icon }) => {
            const active = section === value
            return (
              <button
                key={value}
                type="button"
                aria-current={active ? 'page' : undefined}
                title={collapsed ? text : undefined}
                onClick={() => setSection(value)}
                className={`relative flex h-12 items-center gap-3 px-5 text-[0.9375rem] transition-colors duration-150 ${iconOnly} ${
                  active ? 'bg-row-active font-semibold' : 'hover:bg-pill-hover'
                }`}
              >
                {/* черта выбранного раздела у края панели, как на портале */}
                {active && <span className="absolute inset-y-0 left-0 w-1 bg-accent" aria-hidden />}
                <Icon />
                <span className={label}>{text}</span>
              </button>
            )
          })}
        </nav>

        <button
          type="button"
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect()
            const next = nextTheme(theme)
            setTheme(next, r.x + r.width / 2, r.y + r.height / 2)
            setThemePref(next)
          }}
          aria-label={`Тема: ${THEME_LABELS[theme]}. Переключить`}
          title={collapsed ? `Тема: ${THEME_LABELS[theme]}` : undefined}
          className={`mt-auto mb-3 flex h-10 items-center gap-3 px-5 text-sm text-slate transition-colors duration-150 hover:bg-pill-hover hover:text-ink ${iconOnly}`}
        >
          <ThemeIcon />
          <span className={label}>Тема: {THEME_LABELS[theme]}</span>
        </button>

        <p
          className={`flex items-start gap-2 px-5 pb-5 text-xs text-slate ${iconOnly}`}
          title={collapsed ? 'Работает без интернета. Файлы не покидают компьютер' : undefined}
        >
          <IconLock size={16} />
          {/* фиксированная ширина: текст переносится, но не перестраивается во время анимации панели */}
          <span className={collapsed ? 'sr-only' : 'w-44 shrink-0 max-md:sr-only'}>
            Работает без интернета. Файлы не покидают компьютер
          </span>
        </p>
      </aside>

      <main className="min-w-0 flex-1 bg-panel px-4 pt-6 pb-12 sm:px-8 md:mt-3 md:rounded-tl-2xl">
        {fatal ? (
          <div className="max-w-xl py-10">
            <Alert tone="error" title="Нет связи с datamask">
              {fatal}
            </Alert>
          </div>
        ) : !meta ? (
          <div className="py-16 text-center">
            <Spinner label="Загрузка…" />
          </div>
        ) : section === 'unmask' ? (
          <Unmask />
        ) : section === 'projects' ? (
          <Projects meta={meta} />
        ) : (
          <div className="space-y-6">
            <div className="space-y-4">
              <PageHeader title={STEP_TITLE[step]}>
                {file?.project && <span className="text-sm text-slate">Проект: {file.project.name}</span>}
                {/* сюда шаг рисует свои действия через портал: строка заголовка, как на портале */}
                <div ref={setActions} className="ml-auto flex flex-wrap gap-2 empty:hidden" />
              </PageHeader>
              <Steps current={STEP_INDEX[step]} />
            </div>
            {maskFlow(meta)}
          </div>
        )}
      </main>
    </div>
  )
}
