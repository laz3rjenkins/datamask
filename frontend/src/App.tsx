import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from './api/client'
import type { FileInfo, Job, MaskConfig, Meta } from './api/types'
import { Alert, Spinner, Steps } from './components/ui'
import { initialSettings, type Settings } from './lib/settings'
import Configure from './pages/Configure'
import Result from './pages/Result'
import Review from './pages/Review'
import Upload from './pages/Upload'

type State =
  | { step: 'upload' }
  | { step: 'configure' }
  | { step: 'review'; config: MaskConfig }
  | { step: 'result'; job: Job; outputName: string }

const STEP_INDEX = { upload: 0, configure: 1, review: 2, result: 3 }

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [fatal, setFatal] = useState<string | null>(null)
  const [state, setState] = useState<State>({ step: 'upload' })
  // Имя файла живёт только в памяти вкладки: сервер его не хранит и не пишет в логи.
  const [file, setFile] = useState<{ info: FileInfo; name: string } | null>(null)
  const [settings, setSettings] = useState<Settings>(initialSettings)

  useEffect(() => {
    api.meta().then(setMeta, (e) => setFatal(errorText(e)))
  }, [])
  useEffect(() => {
    window.scrollTo(0, 0) // в новых браузерах возвращает Promise: не отдавать его React как cleanup
  }, [state.step])

  const restart = useCallback(() => {
    setFile(null)
    setSettings(initialSettings())
    setState({ step: 'upload' })
  }, [])
  const onDone = useCallback((job: Job, outputName: string) => setState({ step: 'result', job, outputName }), [])

  return (
    <div className="min-h-screen bg-white text-neutral-900 dark:bg-neutral-950 dark:text-neutral-100">
      <header className="border-b border-neutral-200 dark:border-neutral-800">
        <div className="mx-auto flex max-w-[110rem] items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <span className="font-semibold tracking-tight">datamask</span>
          {meta && <Steps current={STEP_INDEX[state.step]} />}
          <span className="text-xs text-neutral-500 max-md:hidden">работает без интернета</span>
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
        ) : state.step === 'upload' || !file ? (
          <Upload
            meta={meta}
            onUploaded={(info, name) => {
              setFile({ info, name })
              setSettings(initialSettings())
              setState({ step: 'configure' })
            }}
          />
        ) : state.step === 'configure' ? (
          <Configure
            meta={meta}
            file={file.info}
            settings={settings}
            setSettings={setSettings}
            onFile={(info) => setFile({ ...file, info })}
            onBack={restart}
            onNext={(config) => setState({ step: 'review', config })}
          />
        ) : state.step === 'review' ? (
          <Review
            meta={meta}
            file={file.info}
            fileName={file.name}
            config={state.config}
            onBack={() => setState({ step: 'configure' })}
            onDone={onDone}
          />
        ) : (
          <Result meta={meta} job={state.job} outputName={state.outputName} onAnother={restart} onCleared={restart} />
        )}
      </main>
    </div>
  )
}
