import type {
  Categories,
  CellSpans,
  CsvParams,
  DryRun,
  FileInfo,
  Job,
  MaskConfig,
  Meta,
  Preview,
  SuggestResult,
} from './types'

export class ApiError extends Error {
  status: number
  code: string
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const json = typeof init.body === 'string'
  let r: Response
  try {
    r = await fetch(path, {
      ...init,
      credentials: 'same-origin',
      headers: json ? { 'Content-Type': 'application/json' } : undefined,
    })
  } catch {
    throw new ApiError(0, 'offline', 'Сервер datamask не отвечает. Проверьте, что он запущен')
  }
  if (!r.ok) {
    let code = 'http_error'
    let message = 'Ошибка запроса'
    try {
      ;({ code, message } = (await r.json()).error)
    } catch {
      // не JSON — оставляем общее сообщение
    }
    throw new ApiError(r.status, code, message)
  }
  return r.json() as Promise<T>
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) })
const sheetPath = (fileId: string, sheet: string) =>
  `/api/files/${fileId}/sheets/${encodeURIComponent(sheet)}`

export const api = {
  meta: () => request<Meta>('/api/meta'),

  upload(file: File) {
    const body = new FormData()
    body.append('file', file)
    return request<FileInfo>('/api/files', { method: 'POST', body })
  },

  csvOptions: (fileId: string, params: Partial<CsvParams>) =>
    request<FileInfo>(`/api/files/${fileId}`, { method: 'PATCH', body: JSON.stringify(params) }),

  preview(fileId: string, sheet: string, headerRow?: number) {
    const q = new URLSearchParams({ limit: '200' })
    if (headerRow) q.set('header_row', String(headerRow))
    return request<Preview>(`${sheetPath(fileId, sheet)}/preview?${q}`)
  },

  suggest: (
    fileId: string,
    body: { categories: Categories; header_rows: Record<string, number>; custom_terms: string[] },
  ) => post<SuggestResult>(`/api/files/${fileId}/suggest`, body),

  spans: (
    fileId: string,
    sheet: string,
    body: {
      header_row: number
      columns: string[]
      categories: Categories
      custom_terms: string[]
    },
  ) => post<CellSpans[]>(`${sheetPath(fileId, sheet)}/spans`, body),

  dryRun: (fileId: string, config: MaskConfig) =>
    post<DryRun>(`/api/files/${fileId}/dry-run`, config),

  mask: (
    fileId: string,
    body: { config: MaskConfig; password: string | null; output_name: string },
  ) => post<{ job_id: string }>(`/api/files/${fileId}/mask`, body),

  job: (jobId: string) => request<Job>(`/api/jobs/${jobId}`),

  downloadUrl: (jobId: string, kind: string) => `/api/jobs/${jobId}/download/${kind}`,

  clearSession: () => request<{ status: string }>('/api/session', { method: 'DELETE' }),
}

export function errorText(e: unknown): string {
  return e instanceof ApiError ? e.message : 'Что-то пошло не так. Попробуйте ещё раз'
}
