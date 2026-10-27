/**
 * 说明页（清单 §2.4）：传播层复用——方法论速览 / 术语 / 复现指引 / 免责声明。
 * 数据依赖为零，全是常量文案。
 */

import { SignalBadge } from '../components/SignalBadge'
import { fmtFixed3 } from '../format'

const GLOSSARY: { term: string; plain: string }[] = [
  { term: 'k = 1（滞后位）', plain: '领先面序列向前平移 1 周后，与滞后面对齐比较；k=1 即领先一周。' },
  { term: 'ρ（相关系数）', plain: '两条序列同向/反向变动的程度，取值 −1 至 +1；本看板一律三位小数带符号。' },
  { term: '判定线 0.300', plain: '协议事先写死的通过门槛；窗口内最优 |ρ| 达不到它，就是未通过。' },
  { term: '弱信号带 ±0.190', plain: '描述性的过渡区间，不是通过标准；落在带内不改变判定，只说明值得复看。' },
  { term: '噪声中位（零分布）', plain: '把序列相位打乱后重算出的「无关系基准线」；只有链 20 做了这项标定。' },
  { term: 'k = 0（前视位）', plain: '同一周共动，收盘时间上不可交易，只作诊断保留，不计入结论。' },
]

export function About() {
  return (
    <>
      <section className="lede">
        <h1>这套流水线在做什么</h1>
        <p>
          一句话：<strong>把「先锁定、后结算、公开留痕」做成可审计的流程</strong>
          。所有结论都在见数据之前把判定线写死，之后只允许登记修订、不允许静默改参。
        </p>
      </section>

      <section aria-labelledby="why-title">
        <h2 className="section-title" id="why-title">
          为什么判定线是 0.300，不是 0.05
        </h2>
        <div className="detail-card prose">
          <p>
            0.05 是「单次假设检验」的显著性习惯值。在扫描大量候选关系、反复试滞后位的场景里，它会把噪声当成发现：
            试得越多，撞出「显著」的概率越高。这正是 p-hacking 的入口，也是 Kaggle 里 public LB 分数好看、private
            LB 结算打回的原因。
          </p>
          <p>
            我们的做法是两件事叠加：<strong>把门槛抬高到 {fmtFixed3(0.3)}</strong>
            ，并且<strong>把尝试次数直接做成预算</strong>——全项目只有 3 次换链额度，用掉一次就少一次，不许看结果后改参数重跑。
            门槛拦掉大部分噪声，预算拦掉「反复试直到好看」。
          </p>
          <p>
            代价是：真实但微弱的关系会被判为未通过。这是可接受的——宁可漏掉弱信号，也不把噪声包装成结论。
          </p>
        </div>
      </section>

      <section aria-labelledby="loop-title">
        <h2 className="section-title" id="loop-title">
          三步：先锁定 · 后结算 · 公开留痕
        </h2>
        <div className="about-grid">
          <article className="about-card">
            <span className="eyebrow">STEP 1 · 先锁定</span>
            <div className="panel-title">判定参数写死在见数据之前</div>
            <p>滞后窗口、判定线、弱信号带在一次尝试开始前登记入链配置，并留下配置指纹。</p>
          </article>
          <article className="about-card">
            <span className="eyebrow">STEP 2 · 后结算</span>
            <div className="panel-title">按锁定的口径出具判定</div>
            <p>达标才叫通过；未达标是未通过；作者可裁定整链证伪。证伪是好消息，不是事故。</p>
          </article>
          <article className="about-card">
            <span className="eyebrow">STEP 3 · 公开留痕</span>
            <div className="panel-title">尝试、修订、运维事件全部可查</div>
            <p>每次改动登记原因与是否消耗预算；运行账本 append-only，账户外操作在物理上不存在。</p>
          </article>
        </div>
      </section>

      <section aria-labelledby="states-title">
        <h2 className="section-title" id="states-title">
          六态徽章 · 三通道冗余
        </h2>
        <div className="detail-card">
          <p className="prose-lead">
            每个状态都同时用<strong>颜色 + 图形/图案 + 文字</strong>
            表达，因此截图、灰度打印、色觉差异下都不丢信息。
          </p>
          <div className="badge-showcase">
            <SignalBadge state="verified" />
            <SignalBadge state="falsified" />
            <SignalBadge state="grayzone" />
            <SignalBadge state="nodata" />
            <SignalBadge state="notpassed" />
            <SignalBadge state="forward" />
          </div>
          <p className="chart-caption">
            证伪使用冷色的「完成勾 + 印章边框」，与运行失败严格区分——判定是正常产出，故障才是红色警告。
          </p>
        </div>
      </section>

      <section aria-labelledby="glossary-title">
        <h2 className="section-title" id="glossary-title">
          术语速览
        </h2>
        <div className="detail-card">
          <dl className="glossary">
            {GLOSSARY.map((item) => (
              <div className="glossary-row" key={item.term}>
                <dt>{item.term}</dt>
                <dd>{item.plain}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section aria-labelledby="repro-title">
        <h2 className="section-title" id="repro-title">
          复现指引
        </h2>
        <div className="detail-card prose">
          <ol className="repro-steps">
            <li>申请一个免费的 OpenAlex API key，写入本地 <code>openalex_key.local</code>（已被 .gitignore 拦截，绝不入库）。</li>
            <li>安装依赖后运行阶段 0 流水线，产出各链的周频缓存与交叉相关表。</li>
            <li>运行物化脚本，生成看板所需快照（profile / zseries / revisions）。</li>
            <li>启动看板 dev 服务，对着本仓库的 data/ 与 chains/ 只读渲染。</li>
            <li>全部数据源、判定参数与修订记录均随仓库公开，可逐位复核。</li>
          </ol>
          <p className="chart-caption">
            本页为方法论演示与公开留痕，不构成任何投资建议；历史表现不代表未来结果。
          </p>
        </div>
      </section>
    </>
  )
}
