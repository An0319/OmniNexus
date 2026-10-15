/**
 * C14 证伪导航（需求清单 §11.2 断点②处置 · 2026-10-15 落地）。
 * 判定完成后不停在结论上：按判定类型给出结构化解读与下一步选项。
 * 证伪是正常产出，不是事故——本块视觉必须保持「导航」观感，绝不与报错共用样式。
 * 纪律：文案为静态查表（展示层零计算）；「方向对、强度不够」的分流只读指标
 * status 字段（greyzone = 越过噪声带未达判定线，口径卡已定义），不做数值比较；
 * 选项只导航不执行——重跑消耗尝试预算，必须人工拍板（纪律停机型断点）。
 */

import type { ChainView } from '../types'

interface NavBlock {
  reading: string
  options: string[]
  ledgerNote?: string
}

const NAV_FALSIFIED: NavBlock = {
  reading:
    '证伪成立：最优位置在判定窗口之外（或为不可交易的共动位）——数值再高，也不满足「领先且可交易」的预注册前提。',
  options: [
    '接受证伪并收工：本结论是正常产出；窗口外的强相关留作诊断线索',
    '要继续＝另立新链：新假设、新预注册、新预算；在原链上「挪窗口」重试＝改判定参数，禁止',
    '把前视诊断（如同周共动位）作为新假设的输入，走发现引擎立项',
  ],
  ledgerNote: '本次死法已入时间线账本；后续新链立项前先查同型死法，避免重蹈。',
}

const NAV_NOT_PASSED_GRAYZONE: NavBlock = {
  reading:
    '方向对、强度不够：窗口内最优 ρ 已越过噪声带，但未达预注册判定线——统计上不足以下结论，也不是失败。',
  options: [
    '接受证伪并收工：按预注册口径，弱于判定线＝无结论，宁缺毋滥',
    '换更聚焦指标重试：消耗 1 次尝试预算，先在修订账本登记动机再动手',
    '禁止事项：不动判定线、不动窗口——那是改判定参数，不是换思路',
  ],
  ledgerNote: '本次死法已入时间线账本；后续新链立项前先查同型死法，避免重蹈。',
}

const NAV_NOT_PASSED_NOISE: NavBlock = {
  reading:
    '纯噪声区间：窗口内无一指标触达弱信号带，最优值与噪声不可区分——这条假设在本样本上不成立。',
  options: [
    '接受证伪并收工：证伪本身是可发表的结论，防的是把噪声包装成发现',
    '要继续＝另立新链：换假设或换样本期，新预算、新预注册；不在本链续跑',
    '禁止事项：不动判定线、不动窗口——那是改判定参数，不是换思路',
  ],
  ledgerNote: '本次死法已入时间线账本；后续新链立项前先查同型死法，避免重蹈。',
}

const NAV_GREYZONE: NavBlock = {
  reading:
    '候选 ≠ 结论：指标最优 ρ 落在弱信号带（越过噪声带、未达判定线），按预注册口径不算通过。',
  options: [
    '复看不耗预算：重读本链剖面与 z 曲线，换理解角度，不改任何参数',
    '若决定重试：属新尝试，消耗预算并登记修订，禁止静默改判定线',
  ],
}

export function VerdictNav({ view }: { view: ChainView }) {
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
    <div className="verdict-nav" role="note" aria-label="证伪导航">
      <span className="verdict-nav-eyebrow">
        FALSIFICATION NAV · 证伪导航（下一步选项；重跑消耗预算，须人工拍板）
      </span>
      <p className="verdict-nav-reading">{block.reading}</p>
      <ul className="verdict-nav-options">
        {block.options.map((option) => (
          <li key={option}>{option}</li>
        ))}
      </ul>
      {block.ledgerNote && <p className="verdict-nav-ledger">{block.ledgerNote}</p>}
    </div>
  )
}
