// Зеркало ответов бэкенда (backend/datamask/api, core/models.py, core/pipeline.py).

export type Category = 'personal' | 'financial' | 'commercial'
export type CellValue = string | number | boolean | null
export type CellKind = 'empty' | 'string' | 'number' | 'bool' | 'date' | 'formula' | 'error'

export interface EntityMeta {
  value: string
  label: string
  category: Category | null
  methods: string[]
  default_method: string
}

export interface MethodMeta {
  value: string
  label: string
  reversible: boolean
}

export interface Meta {
  entities: EntityMeta[]
  methods: MethodMeta[]
  min_password: number
  max_upload_mb: number
  free_text_warning: string
}

export interface SheetInfo {
  name: string
  hidden: boolean
  rows: number | null
  cols: number | null
  hidden_columns: [number, number][]
}

export interface Risk {
  code: string
  message: string
  sheet: string | null
  count: number
}

export interface CsvParams {
  encoding: string
  delimiter: string
}

export interface FileInfo {
  file_id: string
  format: 'xlsx' | 'csv'
  sheets: SheetInfo[]
  csv: CsvParams | null
  risks: Risk[]
  name_findings: string[]
}

export interface Column {
  index: number
  key: string
  header: string
  hidden: boolean
}

export interface PreviewRow {
  row: number
  values: CellValue[]
  kinds: CellKind[]
}

export interface Preview {
  sheet: string
  header_row: number
  detected_header_row: number
  columns: Column[]
  above_header: PreviewRow[]
  rows: PreviewRow[]
}

export interface Suggestion {
  entity: string
  confidence: number
  method: string
  reasons: string[]
}

export interface ColumnSuggestion {
  key: string
  header: string
  suggestion: Suggestion | null
  non_empty: number
  formulas: number
}

export interface SheetSuggestions {
  sheet: string
  header_row: number
  columns: ColumnSuggestion[]
  above_header: { entity: string; count: number }[]
}

export interface TextFinding {
  kind: 'sheet_name' | 'defined_name' | 'comment' | 'comment_author'
  sheet: string | null
  ref: string | null
  entities: string[]
}

export interface SuggestResult {
  sheets: SheetSuggestions[]
  text_findings: TextFinding[]
}

export interface Span {
  start: number
  end: number
  entity: string
}

export interface CellSpans {
  row: number
  col: number
  spans: Span[]
}

export type Params = Record<string, string | number>

export interface ColumnConfig {
  entity: string
  method: string
  params?: Params
}

export interface Categories {
  personal: boolean
  financial: boolean
  commercial: boolean
}

export interface Sanitize {
  comments: 'remove' | 'keep'
  hidden_sheets: 'keep' | 'remove'
  images: 'keep' | 'remove'
}

export interface SheetConfig {
  header_row: number
  columns: Record<string, ColumnConfig>
  scan_above_header: boolean
}

export interface MaskConfig {
  categories: Categories
  sheets: Record<string, SheetConfig>
  custom_terms: string[]
  sanitize: Sanitize
  save_mapping: boolean
}

export interface DryRunColumn {
  key: string
  header: string
  entity: string | null
  method: string | null
  reversible: boolean
}

export interface DryRunRow {
  row: number
  before: CellValue[]
  after: CellValue[]
  changed: boolean[]
}

export interface DryRunSheet {
  sheet: string
  header_row: number
  columns: DryRunColumn[]
  rows: DryRunRow[]
}

export interface ColumnSummary {
  sheet: string
  key: string
  header: string
  entity: string
  method: string
  values: number
  unique: number
  skipped_formulas: number
}

export interface DryRun {
  sheets: DryRunSheet[]
  summary: ColumnSummary[]
  warnings: string[]
}

export interface JobSummary {
  by_entity: Record<string, { replaced: number; unique: number }>
  outside_selected: number
  warnings: string[]
}

export interface Job {
  job_id: string
  status: 'queued' | 'running' | 'done' | 'error'
  progress: number
  artifacts: string[]
  error: string | null
  summary: JobSummary | null
}
