/*
 * 状态映射（唯一一处）
 * 目的：把 CLI 产物里的 status / reason_code 翻成界面可读的档位与文案。
 * 纪律：failed 与 unknown 一律 blocked，不许当结果渲染；partial 必须显眼提示；
 *       undetermined 必须露出 reason_code，不许只显示一个词。
 */
(function (global) {
  'use strict';

  // ── 时间线：6 个展示档（由 status + 逐源统计推导） ─────────────
  var TIMELINE_TIERS = {
    ok: {
      key: 'ok',
      label: '正常完成',
      tone: 'ok',
      blocked: false,
      title: '已产出结果',
      rule: '源覆盖完整且有可用事件；可以当结果读。'
    },
    empty: {
      key: 'empty',
      label: '真无数据',
      tone: 'neutral',
      blocked: false,
      title: '真无数据（不是采集失败）',
      rule: '所有源都可达、返回 0 条；这是「确实没有匹配」，不是「抓取失败」。'
    },
    unjudged: {
      key: 'unjudged',
      label: '判不了',
      tone: 'info',
      blocked: false,
      title: '有数据，但没有抽出可用事件',
      rule: '源返回了条目，但全部被拒；必须展开拒绝原因，不能读成「没发生」。'
    },
    partial: {
      key: 'partial',
      label: '部分覆盖',
      tone: 'warn',
      blocked: false,
      title: '只覆盖部分源（退出码 0，但结果不完整）',
      rule: '有源失败、有源成功；退出码 0 不代表完整，必须显式提示缺失源。'
    },
    failed: {
      key: 'failed',
      label: '失败',
      tone: 'neg',
      blocked: true,
      title: '本次不是结果（已拦截）',
      rule: '全部源失败或状态为 failed；不得当结果展示，也不得渲染成「暂无事件」。'
    },
    unknown: {
      key: 'unknown',
      label: '状态未知',
      tone: 'purple',
      blocked: true,
      title: '产物缺 status 字段（已拦截）',
      rule: '旧产物或字段缺失；无法证明是 ok，按纪律不得当结果读。'
    }
  };

  function numberOrZero(value) {
    return typeof value === 'number' && isFinite(value) ? value : 0;
  }

  function unique(list) {
    var seen = {};
    var out = [];
    for (var i = 0; i < list.length; i += 1) {
      var key = String(list[i]);
      if (!seen[key]) {
        seen[key] = true;
        out.push(list[i]);
      }
    }
    return out;
  }

  /**
   * 时间线产物 → 展示档。
   * 输入：events.json 解析后的对象（顶层应有 status / meta / events / rejects）。
   * 输出：{tier, tierMeta, blocked, statusRaw, hasStatus, ...}，不修改入参。
   */
  function classifyTimeline(doc) {
    var meta = doc && typeof doc === 'object' ? doc.meta : null;

    if (!meta || typeof meta !== 'object') {
      return {
        tier: 'unknown',
        tierMeta: TIMELINE_TIERS.unknown,
        blocked: true,
        statusRaw: doc && doc.status ? String(doc.status) : null,
        hasStatus: !!(doc && doc.status),
        invalid: true,
        mode: null,
        query: null,
        requested: [],
        failedSources: [],
        coveredCount: 0,
        fetchedCount: 0,
        stats: {},
        events: [],
        rejects: [],
        rejectReasons: {},
        coverageText: '产物结构不完整（缺 meta），无法确认覆盖',
        exitCode: null,
        notes: ['产物缺 meta：不能当结果读。']
      };
    }

    var stats = meta.sources_stats && typeof meta.sources_stats === 'object'
      ? meta.sources_stats
      : {};
    var requested = Array.isArray(meta.sources) ? unique(meta.sources) : Object.keys(stats);
    var events = Array.isArray(doc.events) ? doc.events : [];
    var rejects = Array.isArray(doc.rejects) ? doc.rejects : [];
    var summary = meta.stats && typeof meta.stats === 'object' ? meta.stats : {};
    var rejectReasons = summary.reject_reasons && typeof summary.reject_reasons === 'object'
      ? summary.reject_reasons
      : {};

    var failedSources = requested.filter(function (source) {
      var entry = stats[source];
      return !!(entry && entry.error);
    });

    var fetchedCount = requested.filter(function (source) {
      return numberOrZero(stats[source] && stats[source].fetched) > 0;
    }).length;

    var coveredCount = requested.filter(function (source) {
      var entry = stats[source];
      return !(entry && entry.error);
    }).length;

    var allFetchedZero = requested.length > 0 &&
      requested.every(function (source) {
        return numberOrZero(stats[source] && stats[source].fetched) === 0;
      }) && failedSources.length === 0;

    var statusRaw = typeof doc.status === 'string' ? doc.status : null;
    var hasStatus = !!statusRaw;
    var notes = [];

    // 防御：status 与逐源统计不一致时，以更保守的一档展示。
    var effectiveStatus = statusRaw;
    if (statusRaw === 'ok' && failedSources.length > 0) {
      effectiveStatus = 'partial';
      notes.push('status 写的是 ok，但逐源统计里有失败源；壳按「部分覆盖」保守展示。');
    }
    if (statusRaw === 'partial' && failedSources.length === 0) {
      notes.push('status 写的是 partial，但逐源统计里没有失败源；仍按部分覆盖展示，并请回仓库核对。');
    }

    var tier = 'unknown';
    var emptyKind = null;

    if (!hasStatus) {
      tier = 'unknown';
      notes.push('产物没有 status 字段（旧产物），无法证明是 ok；事件区已拦截，仅供排障计数。');
    } else if (effectiveStatus === 'failed') {
      tier = 'failed';
    } else if (effectiveStatus === 'partial') {
      tier = 'partial';
    } else if (effectiveStatus === 'ok') {
      if (events.length > 0) {
        tier = 'ok';
      } else if (allFetchedZero) {
        tier = 'empty';
        emptyKind = meta.mode === 'entity' ? 'entity-zero' : 'topic-empty';
        if (emptyKind === 'entity-zero') {
          notes.push('实体模式零命中：源已覆盖但没抓到条目；不能读成「该主体没有事件」。');
        }
      } else {
        tier = 'unjudged';
        notes.push('源有返回，但抽出的事件为 0；拒绝原因必须展开。');
      }
    } else {
      tier = 'unknown';
      notes.push('无法识别的 status：' + String(statusRaw));
    }

    if (requested.length === 0) {
      tier = 'unknown';
      notes.push('产物没有记录请求过哪些源，无法确认覆盖。');
    }

    var tierMeta = TIMELINE_TIERS[tier];
    // 实体模式零命中与「主题无匹配」结论不同：前者不能说成「该主体没有事件」。
    if (emptyKind === 'entity-zero') {
      tierMeta = {
        key: 'entity-zero',
        label: '实体零命中',
        tone: 'neutral',
        blocked: false,
        title: '实体零命中（不是「该主体没有事件」）',
        rule: '源已覆盖、返回 0 条；只能说明没抓到可判定条目，不能读成结论。'
      };
    }
    var coverageText;
    if (tier === 'failed') {
      coverageText = '源覆盖 0/' + requested.length + '；全部失败：' + failedSources.join('、');
    } else if (tier === 'unknown' && !hasStatus) {
      coverageText = '旧产物无 status；逐源记录：' + requested.length + ' 源，失败 ' + failedSources.length + ' 源';
    } else if (tier === 'partial') {
      coverageText = '源覆盖 ' + coveredCount + '/' + requested.length + '；失败源：' +
        (failedSources.length ? failedSources.join('、') : '（逐源记录不一致）');
    } else {
      coverageText = '源覆盖 ' + coveredCount + '/' + requested.length + '；失败源 0';
    }

    var exitCode = null;
    if (hasStatus) {
      if (tierMeta.key === 'failed') exitCode = 3;
      else if (tierMeta.key === 'partial') exitCode = 0;
      else exitCode = 0;
    }

    return {
      tier: tier,
      tierMeta: tierMeta,
      blocked: tierMeta.blocked,
      statusRaw: statusRaw,
      hasStatus: hasStatus,
      invalid: false,
      mode: meta.mode || null,
      query: meta.query || null,
      windowStart: meta.window_start || null,
      windowEnd: meta.window_end || null,
      generatedAtUtc: meta.generated_at_utc || null,
      requested: requested,
      failedSources: failedSources,
      coveredCount: coveredCount,
      fetchedCount: fetchedCount,
      allFetchedZero: allFetchedZero,
      stats: {
        raw: numberOrZero(summary.raw_items),
        events: numberOrZero(summary.events),
        rejects: numberOrZero(summary.rejects),
        merged: numberOrZero(summary.merged_duplicates)
      },
      events: events,
      rejects: rejects,
      rejectReasons: rejectReasons,
      coverageText: coverageText,
      exitCode: exitCode,
      emptyKind: emptyKind,
      notes: notes
    };
  }

  // ── 账本：reason_code → 可读原因 ───────────────────────────────
  var REASON_BUCKETS = {
    no_data: {
      label: '缺数据',
      tone: 'warn',
      meaning: '数据没拿到或不够；不能读成「没发生」。'
    },
    unreachable: {
      label: '取不到',
      tone: 'neg',
      meaning: '源不可用；本次无法判定。'
    },
    undefined: {
      label: '数学无定义',
      tone: 'info',
      meaning: '不是源的问题，是定义本身算不出值。'
    },
    unknown: {
      label: '未登记原因码',
      tone: 'purple',
      meaning: '原样展示，不做解释，需回仓库核对。'
    },
    missing: {
      label: '缺 reason_code',
      tone: 'neg',
      meaning: '状态是无法判定却没带原因码；按异常处理，不能猜。'
    }
  };

  var REASON_CODES = {
    NO_OBSERVATIONS_IN_WINDOW: {
      bucket: 'no_data',
      label: '窗口内无观测',
      explain: '窗口内一条观测都没有。'
    },
    SOURCE_EMPTY: {
      bucket: 'no_data',
      label: '清洗后为空',
      explain: '源有响应，但清洗后没有可用观测。'
    },
    INSUFFICIENT_OBSERVATIONS: {
      bucket: 'no_data',
      label: '观测不足',
      explain: '观测条数少于判据要求的最小条数。'
    },
    WINDOW_NOT_COVERED: {
      bucket: 'no_data',
      label: '窗口未被覆盖',
      explain: '窗口末与最后一个观测的间隔超过允许的天数。'
    },
    SOURCE_UNREACHABLE: {
      bucket: 'unreachable',
      label: '源不可达',
      explain: '连接或代理失败，取不到数据。'
    },
    SOURCE_HTTP: {
      bucket: 'unreachable',
      label: '源返回 HTTP 错误',
      explain: '源返回的状态码不是成功响应。'
    },
    SOURCE_PARSE: {
      bucket: 'unreachable',
      label: '响应解析失败',
      explain: '返回内容不是可解析的数据格式。'
    },
    SOURCE_FIELD_MISSING: {
      bucket: 'unreachable',
      label: '响应缺字段',
      explain: '返回结构里缺判据需要的字段。'
    },
    AGGREGATE_UNDEFINED: {
      bucket: 'undefined',
      label: '聚合无定义',
      explain: '数据齐全，但聚合在数学上无定义（例如首条观测为 0 时算涨跌幅）。'
    }
  };

  /**
   * reason_code → {code, known, bucket, bucketMeta, label, explain}
   * 未登记代码不猜，原样展示并标记。
   */
  function reasonInfo(code) {
    if (!code) {
      var missingBucket = REASON_BUCKETS.missing;
      return {
        code: null,
        known: false,
        bucket: 'missing',
        bucketMeta: missingBucket,
        label: missingBucket.label,
        explain: missingBucket.meaning
      };
    }
    var raw = String(code);
    var entry = REASON_CODES[raw];
    if (!entry) {
      var unknownBucket = REASON_BUCKETS.unknown;
      return {
        code: raw,
        known: false,
        bucket: 'unknown',
        bucketMeta: unknownBucket,
        label: unknownBucket.label,
        explain: '该原因码未在壳内登记；原样展示，不做解释，需回仓库核对。'
      };
    }
    var bucketMeta = REASON_BUCKETS[entry.bucket];
    return {
      code: raw,
      known: true,
      bucket: entry.bucket,
      bucketMeta: bucketMeta,
      label: entry.label,
      explain: entry.explain
    };
  }

  // ── 账本：判定状态映射 ──────────────────────────────────────────
  var VERIFY_STATUSES = {
    hit: {
      key: 'hit',
      label: '命中',
      tone: 'pos',
      countsInHitRate: true,
      note: '命题成立。'
    },
    miss: {
      key: 'miss',
      label: '未命中',
      tone: 'neg',
      countsInHitRate: true,
      note: '命题不成立。'
    },
    undetermined: {
      key: 'undetermined',
      label: '无法判定',
      tone: 'warn',
      countsInHitRate: false,
      note: '源不可达、数据缺失窗口未覆盖、聚合无定义三种失败态共用此值；必须看 reason_code 才能区分。'
    },
    not_due: {
      key: 'not_due',
      label: '未到期',
      tone: 'neutral',
      countsInHitRate: false,
      note: '还没到结算时点。'
    },
    frozen: {
      key: 'frozen',
      label: '已冻结',
      tone: 'neutral',
      countsInHitRate: false,
      note: '参数与判据已冻结，不再改。'
    }
  };

  /**
   * 判定状态 → 展示信息；空值表示「账本里还没有判定记录」。
   */
  function mapVerifyStatus(status) {
    if (status === null || status === undefined || status === '') {
      return {
        key: 'pending',
        label: '未结算',
        tone: 'neutral',
        countsInHitRate: false,
        note: '账本里还没有判定记录（未到期或尚未核验）。',
        raw: null
      };
    }
    var entry = VERIFY_STATUSES[String(status)];
    if (!entry) {
      return {
        key: 'unknown',
        label: '未登记状态',
        tone: 'purple',
        countsInHitRate: false,
        note: '该判定状态未在壳内登记；原样展示。',
        raw: String(status)
      };
    }
    return {
      key: entry.key,
      label: entry.label,
      tone: entry.tone,
      countsInHitRate: entry.countsInHitRate,
      note: entry.note,
      raw: String(status)
    };
  }

  function summarizeRegistry(rows) {
    var summary = {
      total: 0,
      hit: 0,
      miss: 0,
      undetermined: 0,
      pending: 0,
      frozen: 0,
      other: 0
    };
    (Array.isArray(rows) ? rows : []).forEach(function (row) {
      summary.total += 1;
      var mapped = mapVerifyStatus(row ? row.verdict : null);
      if (mapped.key === 'hit') summary.hit += 1;
      else if (mapped.key === 'miss') summary.miss += 1;
      else if (mapped.key === 'undetermined') summary.undetermined += 1;
      else if (mapped.key === 'pending') summary.pending += 1;
      else if (mapped.key === 'frozen') summary.frozen += 1;
      else summary.other += 1;
    });
    return summary;
  }

  global.MNXStatus = {
    TIMELINE_TIERS: TIMELINE_TIERS,
    REASON_BUCKETS: REASON_BUCKETS,
    REASON_CODES: REASON_CODES,
    VERIFY_STATUSES: VERIFY_STATUSES,
    classifyTimeline: classifyTimeline,
    reasonInfo: reasonInfo,
    mapVerifyStatus: mapVerifyStatus,
    summarizeRegistry: summarizeRegistry
  };
})(window);
