/**
 * 看板 i18n 统一入口：语言清单 / 默认语言 / 字典注册 / 插值。
 *
 * 语言开关有两层，二者都以本文件为唯一落点：
 * 1. 构建期配置：环境变量 VITE_DASHBOARD_LOCALE（缺省或非法值 → zh）。
 * 2. 运行时状态：I18nProvider 持有的 locale，可调用 setLocale() 切换；
 *    当前无切换 UI（本阶段只留结构，不做交互）。
 *
 * 新增语言：复制 messages.zh.ts 为 messages.en.ts（默认导出保持），
 * 本文件按文件名自动登记，组件零改动。字典缺失的语言自动回落默认语言。
 */

import { zhMessages, type MessageKey } from './messages.zh'

export type { MessageKey } from './messages.zh'

export const SUPPORTED_LOCALES = ['zh', 'en'] as const
export type Locale = (typeof SUPPORTED_LOCALES)[number]
export const DEFAULT_LOCALE: Locale = 'zh'

export type MessageCatalog = Record<MessageKey, string>

/**
 * 字典自动登记：src/i18n/messages.<locale>.ts 的默认导出即为该语言字典。
 * `en` 尚未翻译：即使把开关切到 en，也会回落 zh，不会出现空白界面；
 * 补齐 messages.en.ts 后无需改本文件或任何组件。
 */
const catalogModules = import.meta.glob<{ default: MessageCatalog }>('./messages.*.ts', {
  eager: true,
})
const catalogs: Partial<Record<Locale, MessageCatalog>> = {}
for (const [path, module] of Object.entries(catalogModules)) {
  const name = path.match(/^\.\/messages\.(\w+)\.ts$/)?.[1]
  if (name && resolveLocale(name) === name) catalogs[resolveLocale(name)] = module.default
}

export type MessageParams = Record<string, string | number>

/** 把 {name} 占位符替换为参数值；缺参时保留原占位符，便于发现漏传。 */
function interpolate(template: string, params?: MessageParams): string {
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (match, name) => {
    const value = params[name]
    return value === undefined ? match : String(value)
  })
}

/** 解析语言标识：仅接受受支持的语言，其余一律回落默认语言。 */
export function resolveLocale(raw: string | null | undefined): Locale {
  return SUPPORTED_LOCALES.find((locale) => locale === raw) ?? DEFAULT_LOCALE
}

/** 构建期语言开关：VITE_DASHBOARD_LOCALE=zh|en（未设置时默认 zh）。 */
export const initialLocale: Locale = resolveLocale(
  import.meta.env.VITE_DASHBOARD_LOCALE as string | undefined,
)

/**
 * 取文案：指定语言缺字典或缺该键时回落默认语言，仍缺则返回键名本身。
 * 组件不直接调用本函数，统一经 I18nProvider 的 t()。
 */
export function translate(locale: Locale, key: MessageKey, params?: MessageParams): string {
  const base = catalogs[DEFAULT_LOCALE] ?? zhMessages
  return interpolate((catalogs[locale] ?? base)[key] ?? base[key] ?? key, params)
}
