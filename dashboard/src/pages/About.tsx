/**
 * 说明页（清单 §2.4）：传播层复用——方法论速览 / 术语 / 复现指引 / 免责声明。
 * 数据依赖为零，全是常量文案。
 */

import { SignalBadge } from '../components/SignalBadge'
import { fmtFixed3 } from '../format'
import { useI18n } from '../i18n/I18nProvider'
import type { MessageKey } from '../i18n/messages.zh'

const GLOSSARY: { termKey: MessageKey; plainKey: MessageKey }[] = [
  { termKey: 'about.glossary.g1.term', plainKey: 'about.glossary.g1.plain' },
  { termKey: 'about.glossary.g2.term', plainKey: 'about.glossary.g2.plain' },
  { termKey: 'about.glossary.g3.term', plainKey: 'about.glossary.g3.plain' },
  { termKey: 'about.glossary.g4.term', plainKey: 'about.glossary.g4.plain' },
  { termKey: 'about.glossary.g5.term', plainKey: 'about.glossary.g5.plain' },
  { termKey: 'about.glossary.g6.term', plainKey: 'about.glossary.g6.plain' },
]

export function About() {
  const { t } = useI18n()
  return (
    <>
      <section className="lede">
        <h1>{t('about.lede.title')}</h1>
        <p>
          {t('about.lede.prefix')}
          <strong>{t('about.lede.strong')}</strong>
          {t('about.lede.tail')}
        </p>
      </section>

      <section aria-labelledby="why-title">
        <h2 className="section-title" id="why-title">
          {t('about.why.title')}
        </h2>
        <div className="detail-card prose">
          <p>{t('about.why.p1')}</p>
          <p>
            {t('about.why.p2.prefix')}
            <strong>{t('about.why.p2.strong1', { pass: fmtFixed3(0.3) })}</strong>
            {t('about.why.p2.mid')}
            <strong>{t('about.why.p2.strong2')}</strong>
            {t('about.why.p2.tail')}
          </p>
          <p>{t('about.why.p3')}</p>
        </div>
      </section>

      <section aria-labelledby="loop-title">
        <h2 className="section-title" id="loop-title">
          {t('about.loop.title')}
        </h2>
        <div className="about-grid">
          <article className="about-card">
            <span className="eyebrow">{t('about.loop.step1.eyebrow')}</span>
            <div className="panel-title">{t('about.loop.step1.title')}</div>
            <p>{t('about.loop.step1.body')}</p>
          </article>
          <article className="about-card">
            <span className="eyebrow">{t('about.loop.step2.eyebrow')}</span>
            <div className="panel-title">{t('about.loop.step2.title')}</div>
            <p>{t('about.loop.step2.body')}</p>
          </article>
          <article className="about-card">
            <span className="eyebrow">{t('about.loop.step3.eyebrow')}</span>
            <div className="panel-title">{t('about.loop.step3.title')}</div>
            <p>{t('about.loop.step3.body')}</p>
          </article>
        </div>
      </section>

      <section aria-labelledby="states-title">
        <h2 className="section-title" id="states-title">
          {t('about.states.title')}
        </h2>
        <div className="detail-card">
          <p className="prose-lead">
            {t('about.states.prefix')}
            <strong>{t('about.states.strong')}</strong>
            {t('about.states.tail')}
          </p>
          <div className="badge-showcase">
            <SignalBadge state="verified" />
            <SignalBadge state="falsified" />
            <SignalBadge state="grayzone" />
            <SignalBadge state="nodata" />
            <SignalBadge state="notpassed" />
            <SignalBadge state="forward" />
          </div>
          <p className="chart-caption">{t('about.states.caption')}</p>
        </div>
      </section>

      <section aria-labelledby="glossary-title">
        <h2 className="section-title" id="glossary-title">
          {t('about.glossary.title')}
        </h2>
        <div className="detail-card">
          <dl className="glossary">
            {GLOSSARY.map((item) => (
              <div className="glossary-row" key={item.termKey}>
                <dt>{t(item.termKey)}</dt>
                <dd>{t(item.plainKey)}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section aria-labelledby="repro-title">
        <h2 className="section-title" id="repro-title">
          {t('about.repro.title')}
        </h2>
        <div className="detail-card prose">
          <ol className="repro-steps">
            <li>
              {t('about.repro.step1.prefix')}
              <code>{t('about.repro.step1.code')}</code>
              {t('about.repro.step1.tail')}
            </li>
            <li>{t('about.repro.step2')}</li>
            <li>{t('about.repro.step3')}</li>
            <li>{t('about.repro.step4')}</li>
            <li>{t('about.repro.step5')}</li>
          </ol>
          <p className="chart-caption">{t('about.repro.caption')}</p>
        </div>
      </section>
    </>
  )
}
