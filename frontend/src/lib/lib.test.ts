import { describe, expect, it } from 'vitest'
import type { Meta, SuggestResult, Template } from '../api/types'
import { formatCell, splitBySpans } from './format'
import { nextTheme, readTheme } from './theme'
import {
  applySuggestions,
  applyTemplate,
  templateRules,
  buildConfig,
  changeEntity,
  changesType,
  initialSettings,
  parseTerms,
} from './settings'

const meta = {
  entities: [
    { value: 'PHONE', label: 'Телефон', category: 'personal', methods: ['pseudonym', 'partial'], default_method: 'pseudonym' },
    { value: 'BIRTH_DATE', label: 'Дата рождения', category: 'personal', methods: ['label', 'date_shift'], default_method: 'date_shift' },
  ],
} as Meta

const suggestions: SuggestResult = {
  sheets: [
    {
      sheet: 'Клиенты',
      header_row: 3,
      above_header: [],
      columns: [
        { key: 'B', header: 'Тел.', non_empty: 10, formulas: 0, suggestion: { entity: 'PHONE', confidence: 0.9, method: 'pseudonym', reasons: [] } },
        { key: 'C', header: 'Город', non_empty: 10, formulas: 0, suggestion: null },
      ],
    },
  ],
  text_findings: [],
}

describe('settings', () => {
  it('принимает подсказки, не трогая ручной выбор', () => {
    const manual = { Клиенты: { C: { entity: 'PHONE', method: 'partial' } } }
    expect(applySuggestions(manual, suggestions)).toEqual({
      Клиенты: { B: { entity: 'PHONE', method: 'pseudonym' }, C: { entity: 'PHONE', method: 'partial' } },
    })
  })

  it('при смене типа сохраняет подходящий способ, иначе берёт способ по умолчанию', () => {
    expect(changeEntity(meta, { entity: 'PHONE', method: 'partial' }, 'BIRTH_DATE')).toEqual({
      entity: 'BIRTH_DATE',
      method: 'date_shift',
    })
    expect(changeEntity(meta, { entity: 'BIRTH_DATE', method: 'label' }, 'PHONE')?.method).toBe('pseudonym')
    expect(changeEntity(meta, { entity: 'PHONE', method: 'partial' }, null)).toBeUndefined()
  })

  it('собирает конфигурацию: ручная строка заголовка важнее автоопределённой', () => {
    const s = { ...initialSettings(), customTerms: ' Ромашка \n\n Проект Альфа', headerRows: {} }
    const cfg = buildConfig(s, suggestions)
    expect(cfg.sheets['Клиенты']).toEqual({ header_row: 3, columns: {}, scan_above_header: true })
    expect(cfg.custom_terms).toEqual(['Ромашка', 'Проект Альфа'])
    expect(buildConfig({ ...s, headerRows: { Клиенты: 1 } }, suggestions).sheets['Клиенты'].header_row).toBe(1)
    expect(parseTerms('')).toEqual([])
  })

  it('проект включает согласованность по проекту', () => {
    const cfg = buildConfig({ ...initialSettings(), projectId: 'abc' }, suggestions)
    expect([cfg.consistency_scope, cfg.project_id]).toEqual(['project', 'abc'])
    expect(buildConfig(initialSettings(), suggestions).consistency_scope).toBe('file')
  })

  it('сохраняет и применяет шаблон по заголовкам', () => {
    const cols = { Клиенты: { B: { entity: 'PHONE', method: 'partial', params: { keep_last: 2 } } } }
    const rules = templateRules(cols, suggestions)
    expect(rules).toEqual([{ header: 'Тел.', entity: 'PHONE', method: 'partial', params: { keep_last: 2 } }])

    // другой файл: колонку переставили, заголовок записан иначе
    const other: SuggestResult = {
      text_findings: [],
      sheets: [{ ...suggestions.sheets[0], columns: [{ ...suggestions.sheets[0].columns[0], key: 'F', header: ' тел. ' }] }],
    }
    const t: Template = { id: '1', name: 'CRM', created_at: '', rules }
    expect(applyTemplate({}, t, other)).toEqual({
      columns: { Клиенты: { F: { entity: 'PHONE', method: 'partial', params: { keep_last: 2 } } } },
      matched: 1,
    })
  })

  it('предупреждает о смене типа только для числовых и датовых колонок', () => {
    expect(changesType(['number', 'number', 'empty'], 'pseudonym')).toBe(true)
    expect(changesType(['number', 'number'], 'scale')).toBe(false)
    expect(changesType(['date'], 'date_shift')).toBe(false)
    expect(changesType(['string', 'string', 'number'], 'pseudonym')).toBe(false)
  })
})

describe('format', () => {
  it('показывает даты по-русски, а строки CSV — как есть', () => {
    expect(formatCell('1991-03-14T00:00:00', 'date')).toBe('14.03.1991')
    expect(formatCell('1991-03-14T09:30:00')).toBe('14.03.1991 09:30')
    expect(formatCell('1991-03-14', 'string')).toBe('1991-03-14')
    expect(formatCell('007', 'string')).toBe('007')
    expect(formatCell(null)).toBe('')
  })

  it('режет текст по найденным фрагментам', () => {
    const pieces = splitBySpans('тел +79121234567 звонить', [{ start: 4, end: 16, entity: 'PHONE' }])
    expect(pieces.map((p) => p.text)).toEqual(['тел ', '+79121234567', ' звонить'])
    expect(pieces[1].span?.entity).toBe('PHONE')
  })
})

describe('тема', () => {
  it('читает выбор из cookie, неизвестное — как в системе', () => {
    expect(readTheme('')).toBe('system')
    expect(readTheme('datamask_8765=x; datamask_theme=dark')).toBe('dark')
    expect(readTheme('datamask_theme=light')).toBe('light')
    expect(readTheme('datamask_theme=purple')).toBe('system')
    expect(readTheme('xdatamask_theme=dark')).toBe('system')
  })

  it('переключает по кругу', () => {
    expect([nextTheme('system'), nextTheme('light'), nextTheme('dark')]).toEqual(['light', 'dark', 'system'])
  })
})
