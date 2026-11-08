/*
 * 「看什么」的模式判定
 *
 * 原则：能确定就自动定，定不了就用人话问一句，不把「主题 / 实体」这个
 * 内部枚举摆到界面上让用户先学一遍。
 */

import { strings } from '../i18n'

export type QueryMode = 'topic' | 'entity'

const ENTITY_SUFFIX =
  /(公司|集团|股份|控股|银行|证券|基金|保险|药业|制药|生物|科技|电子|能源|汽车|传媒|网络|软件|半导体|时代|国际|控股有限公司)$/

const TOPIC_WORD =
  /(电池|药物|疗法|技术|市场|行业|政策|趋势|融资|价格|供应链|需求|产能|监管|临床|疫苗|并购|裁员|出口|关税|芯片|模型|算力)/

const TICKER = /^[A-Z]{1,6}([.\-][A-Z]{1,3})?$/

export function detectMode(raw: string): QueryMode | null {
  const text = (raw || '').trim()
  if (!text) return null

  // 全大写代号：XBI / ARKG / 0700.HK —— 明确是实体
  if (TICKER.test(text)) return 'entity'

  // 公司后缀：宁德时代 / 辉瑞制药 / Moderna Inc.
  if (ENTITY_SUFFIX.test(text)) return 'entity'

  // 英文公司名后缀
  if (/\b(inc|corp|corporation|company|ltd|limited|llc|plc|gmbh|holdings|group)\b/i.test(text)) {
    return 'entity'
  }

  // 明显的话题词
  if (TOPIC_WORD.test(text)) return 'topic'

  // 带空格的短语、问句式输入按话题处理
  if (/\s/.test(text)) return 'topic'

  // 中文短名词：可能是话题也可能是公司名 —— 不猜，问一句
  if (/^[\u4e00-\u9fa5]{2,8}$/.test(text)) return null

  // 首字母大写的英文单词：同样两种都成立 —— 不猜，问一句
  if (/^[A-Z][a-z]{2,}$/.test(text)) return null

  // 其余（小写英文、数字混排）按话题处理
  return 'topic'
}

export function modeLabel(mode: QueryMode): string {
  return mode === 'entity' ? strings.mode.entity : strings.mode.topic
}
