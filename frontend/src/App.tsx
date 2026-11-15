import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from './api/client'
import type { FileInfo, Job, MaskConfig, Meta, Project } from './api/types'
import { Alert, Spinner, Steps } from './components/ui'
import { initialSettings, type Settings } from './lib/settings'
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
const SECTIONS: { value: Section; label: string }[] = [
  { value: 'mask', label: 'Маскирование' },
  { value: 'unmask', label: 'Размаскировка' },
  { value: 'projects', label: 'Проекты' },
]

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [fatal, setFatal] = useState<string | null>(null)
  const [section, setSection] = useState<Section>('mask')
  const [state, setState] = useState<State>({ step: 'upload' })
  // Имя файла живёт только в памяти вкладки: сервер его не хранит и не пишет в логи.
  const [file, setFile] = useState<{ info: FileInfo; name: string; project: Project | null } | null>(null)
  const [settings, setSettings] = useState<Settings>(initialSettings)

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

  return (
    <div className="min-h-screen bg-white text-neutral-900 dark:bg-neutral-950 dark:text-neutral-100">
      <header className="border-b border-neutral-200 dark:border-neutral-800">
        <div className="mx-auto flex max-w-[110rem] flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3 sm:px-6">
          <span className="font-semibold tracking-tight">datamask</span>
          <nav aria-label="Разделы" className="flex gap-1">
            {SECTIONS.map((s) => (
              <button
                key={s.value}
                type="button"
                aria-current={section === s.value ? 'page' : undefined}
                onClick={() => setSection(s.value)}
                className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
                  section === s.value
                    ? 'bg-neutral-100 font-medium dark:bg-neutral-800'
                    : 'text-neutral-600 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:bg-neutral-800'
                }`}
              >
                {s.label}
              </button>
            ))}
          </nav>
          <span className="ml-auto text-xs text-neutral-500 max-md:hidden">работает без интернета</span>
        </div>
      </header>

      <main className="mx-auto max-w-[110rem] px-4 py-6 sm:px-6">
        {fatal ? (
          <div className="mx-auto max-w-xl py-16">
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
          <>
            <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
              <Steps current={STEP_INDEX[state.step]} />
              {file?.project && (
                <span className="text-sm text-neutral-500">Проект: {file.project.name}</span>
              )}
            </div>
            {maskFlow(meta)}
          </>
        )}
      </main>
    </div>
  )
}
