/**
 * C14 证伪导航（需求清单 §11.2 断点②处置 · 2026-10-15 落地）。
 * 判定完成后不停在结论上：按判定类型给出结构化解读与下一步选项。
 * 证伪是正常产出，不是事故——本块视觉必须保持「导航」观感，绝不与报错共用样式。
 * 纪律：文案为静态查表（展示层零计算）；「方向对、强度不够」的分流只读指标
 * status 字段（greyzone = 越过噪声带未达判定线，口径卡已定义），不做数值比较；
 * 选项只导航不执行——重跑消耗尝试预算，必须人工拍板（纪律停机型断点）。
 */

import { useI18n } from '../i18n/I18nProvider'
import type { MessageKey } from '../i18n/messages.zh'
import type { ChainView } from '../types'

interface NavBlock {
  readingKey: MessageKey
  optionKeys: MessageKey[]
  ledgerNoteKey?: MessageKey
}

const NAV_FALSIFIED: NavBlock = {
  readingKey: 'verdictNav.falsified.reading',
  optionKeys: [
    'verdictNav.falsified.option1',
    'verdictNav.falsified.option2',
    'verdictNav.falsified.option3',
  ],
  ledgerNoteKey: 'verdictNav.deadLedger',
}

const NAV_NOT_PASSED_GRAYZONE: NavBlock = {
  readingKey: 'verdictNav.notPassedGray.reading',
  optionKeys: [
    'verdictNav.notPassedGray.option1',
    'verdictNav.notPassedGray.option2',
    'verdictNav.notPassedGray.option3',
  ],
  ledgerNoteKey: 'verdictNav.deadLedger',
}

const NAV_NOT_PASSED_NOISE: NavBlock = {
  readingKey: 'verdictNav.notPassedNoise.reading',
  optionKeys: [
    'verdictNav.notPassedNoise.option1',
    'verdictNav.notPassedNoise.option2',
    'verdictNav.notPassedNoise.option3',
  ],
  ledgerNoteKey: 'verdictNav.deadLedger',
}

const NAV_GREYZONE: NavBlock = {
  readingKey: 'verdictNav.greyzone.reading',
  optionKeys: ['verdictNav.greyzone.option1', 'verdictNav.greyzone.option2'],
}

export function VerdictNav({ view }: { view: ChainView }) {
  const { t } = useI18n()
  let block: NavBlock | null = null
  if (view.verdict === 'falsified') {
    block = NAV_FALSIFIED
  } else if (view.verdict === 'not_passed') {
    const hasGrayzone = view.metrics.some((metric) => metric.status === 'greyzone')
    block = hasGrayzone ? NAV_NOT_PASSED_GRAYZONE : NAV_NOT_PASSED_NOISE
  } else if (view.verdict === 'greyzone') {
    block = NAV_GREYZONE
  }
  if (block === null) return null

  return (
    <div className="verdict-nav" role="note" aria-label={t('verdictNav.aria')}>
      <span className="verdict-nav-eyebrow">{t('verdictNav.eyebrow')}</span>
      <p className="verdict-nav-reading">{t(block.readingKey)}</p>
      <ul className="verdict-nav-options">
        {block.optionKeys.map((optionKey) => (
          <li key={optionKey}>{t(optionKey)}</li>
        ))}
      </ul>
      {block.ledgerNoteKey && <p className="verdict-nav-ledger">{t(block.ledgerNoteKey)}</p>}
    </div>
  )
}
