import { useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { Job } from '../api/types'

interface Polled<S> {
  id: string
  job: Job<S> | null
  error: string | null
}

/** Опрос фоновой задачи до завершения. jobId = null — задачи нет. */
export function useJob<S>(jobId: string | null): { job: Job<S> | null; error: string | null } {
  const [polled, setPolled] = useState<Polled<S> | null>(null)

  useEffect(() => {
    if (!jobId) return
    let live = true
    let timer: ReturnType<typeof setTimeout>
    const tick = async () => {
      try {
        const j = await api.job<S>(jobId)
        if (!live) return
        setPolled({ id: jobId, job: j, error: j.status === 'error' ? j.error : null })
        if (j.status === 'queued' || j.status === 'running') timer = setTimeout(tick, 400)
      } catch (e) {
        if (live) setPolled({ id: jobId, job: null, error: errorText(e) })
      }
    }
    tick()
    return () => {
      live = false
      clearTimeout(timer)
    }
  }, [jobId])

  // Ответ по прошлой задаче не показываем: он относится к другому запуску.
  const current = polled?.id === jobId ? polled : null
  return { job: current?.job ?? null, error: current?.error ?? null }
}
