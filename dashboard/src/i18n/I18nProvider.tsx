/**
 * 语言状态容器（运行时开关的唯一入口）。
 *
 * 组件通过 useI18n() 拿 { locale, setLocale, t }，不直接读字典、不写文案。
 * 未来接切换 UI 时，只需在某处调用 setLocale('en')，组件零改动。
 * 当前阶段不提供切换控件（只留结构，不做交互）。
 */

import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import { initialLocale, translate, type Locale, type MessageKey, type MessageParams } from './index'

interface I18nValue {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: MessageKey, params?: MessageParams) => string
}

const I18nContext = createContext<I18nValue | null>(null)

export function I18nProvider({
  children,
  initial = initialLocale,
}: {
  children: ReactNode
  initial?: Locale
}) {
  const [locale, setLocale] = useState<Locale>(initial)
  const value = useMemo<I18nValue>(
    () => ({
      locale,
      setLocale,
      t: (key, params) => translate(locale, key, params),
    }),
    [locale],
  )
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext)
  if (value === null) throw new Error('useI18n 必须在 I18nProvider 内使用')
  return value
}
