/*
 * 桌面壳 F · 最小操作页逻辑
 * 原则：只展示真实产物；桥未接入时显示「未接入」，不造结果。
 */
(function () {
  'use strict';

  var DEV = window.__MNX_DEV_DATA__ || null;
  var ST = window.MNXStatus;
  var BR = window.MNXBridge;

  // ── 小工具 ────────────────────────────────────────────────────
  function $(id) { return document.getElementById(id); }

  function esc(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function num(value) {
    if (typeof value === 'number' && isFinite(value)) {
      return value.toLocaleString('en-US');
    }
    return '—';
  }

  function nowUtc() {
    return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
  }

  function isoDate(date) {
    return date.toISOString().slice(0, 10);
  }

  function safeUrl(url) {
    var text = String(url || '');
    return /^https?:\/\//i.test(text) ? text : null;
  }

  function setChip(el, tone, text, title) {
    if (!el) return;
    el.className = 'chip chip--' + tone;
    el.innerHTML = '<span class="chip__dot"></span>' + esc(text);
    if (title) el.title = title;
  }

  function chip(text, tone, mono) {
    return '<span class="chip' + (mono ? ' chip--mono' : '') + ' chip--' + (tone || 'neutral') + '">' +
      '<span class="chip__dot"></span>' + esc(text) + '</span>';
  }

  function monoChip(text, tone) {
    return '<span class="chip chip--mono chip--' + (tone || 'neutral') + '">' + esc(text) + '</span>';
  }

  function stubBox(outcome) {
    var title;
    if (outcome.code === 'BRIDGE_NOT_AVAILABLE') {
      title = '进程桥未接入（本轮只定形）';
    } else if (outcome.code === 'INVALID_REQUEST') {
      title = '请求未通过壳内预检';
    } else {
      title = '桥调用失败';
    }
    return '<div class="stub">' +
      '<p class="stub__title">' + esc(title) + '</p>' +
      '<p class="stub__text">' + esc(outcome.message || '') + '</p>' +
      '<code class="stub__code">' + esc(outcome.code || '') + ' · ' + esc(outcome.command || '') + '</code>' +
      '</div>';
  }

  function cliFailedHtml(outcome) {
    var tail = String(outcome.stderr || '').trim().slice(0, 600);
    return '<div class="banner banner--warn">' +
      '<div class="banner__row">' + chip('已执行', 'warn') +
      monoChip('退出码 ' + (outcome.exitCode === null ? '未知' : outcome.exitCode), 'warn') + '</div>' +
      '<div class="banner__title">命令执行了，但没有产出可读结果</div>' +
      '<p class="banner__rule">下面是 Python 的原样输出；壳不改写，也不把它当结果。</p>' +
      (tail ? '<pre class="log" style="margin-top: 8px;">' + esc(tail) + '</pre>' : '') +
      '</div>';
  }

  // ── 导航 ──────────────────────────────────────────────────────
  function initTabs() {
    var buttons = Array.prototype.slice.call(document.querySelectorAll('[data-tab]'));
    buttons.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var name = btn.getAttribute('data-tab');
        buttons.forEach(function (other) {
          other.setAttribute('aria-selected', other === btn ? 'true' : 'false');
        });
        ['timeline', 'register', 'verify'].forEach(function (key) {
          var panel = $('panel-' + key);
          if (panel) panel.classList.toggle('is-active', key === name);
        });
      });
    });
  }

  // ── 时间线：横幅/结果 ──────────────────────────────────────────
  function bannerHtml(c, context) {
    var tier = c.tierMeta;
    var rows = [];
    rows.push('<span class="banner__badge">' + esc(tier.label) + '</span>');
    rows.push(chip('status: ' + (c.hasStatus ? c.statusRaw : '缺失'), c.hasStatus ? tier.tone : 'purple', true));
    rows.push(chip('退出码 ' + (c.exitCode === null ? '未知' : c.exitCode), c.exitCode === 3 ? 'neg' : (c.exitCode === 0 ? 'ok' : 'neutral'), true));
    if (c.mode) rows.push(chip('mode: ' + c.mode, 'neutral', true));
    if (c.windowStart || c.windowEnd) {
      rows.push(chip(c.windowStart + ' → ' + c.windowEnd, 'neutral', true));
    }
    if (context && context.label) {
      rows.push(chip('回放：' + context.label, 'purple'));
    }

    var hot = '';
    if (c.tier === 'partial') {
      hot = '<div class="banner__hot">退出码 0 ≠ 完整：只覆盖 ' + c.coveredCount + '/' + c.requested.length +
        ' 个源' + (c.failedSources.length ? '（失败：' + esc(c.failedSources.join('、')) + '）' : '') +
        '。缺失源不参与结果，不能把这次当作完整时间线。</div>';
    } else if (c.tier === 'empty') {
      hot = '<div class="banner__hot">' +
        (c.emptyKind === 'entity-zero'
          ? '实体零命中 ≠ 该主体没有事件：源已覆盖，但没抓到可判定条目。'
          : '真无数据 ≠ 采集失败：源可达、返回 0 条；「没匹配」不是「没抓到」。') +
        '</div>';
    } else if (c.tier === 'unjudged') {
      hot = '<div class="banner__hot">判不了 ≠ 没发生：源有返回，但事件全部被拒；拒绝原因见下方。</div>';
    }

    var notes = c.notes && c.notes.length
      ? '<ul class="banner__rule" style="margin: 8px 0 0; padding-left: 18px;">' +
        c.notes.map(function (n) { return '<li>' + esc(n) + '</li>'; }).join('') + '</ul>'
      : '';

    return '<div class="banner banner--' + tier.tone + '">' +
      '<div class="banner__row">' + rows.join('') + '</div>' +
      '<div class="banner__title">' + esc(tier.title) + '</div>' +
      '<p class="banner__rule">' + esc(tier.rule) + '</p>' +
      '<p class="banner__rule" style="margin-top: 6px;">' + esc(c.coverageText) + '</p>' +
      notes + hot +
      '</div>';
  }

  function coverageTableHtml(c) {
    var stats = c.stats || {};
    var sourcesStats = (c.rawMeta && c.rawMeta.sources_stats) || {};
    var rows = c.requested.map(function (source) {
      var entry = sourcesStats[source] || {};
      var isFailed = !!(entry.error);
      return '<tr class="' + (isFailed ? 'is-hot' : '') + '">' +
        '<td class="mono">' + esc(source) + '</td>' +
        '<td class="mono">' + num(entry.fetched) + '</td>' +
        '<td class="mono">' + num(entry.accepted) + '</td>' +
        '<td class="mono">' + num(entry.rejected) + '</td>' +
        '<td class="mono" title="' + esc(entry.error || '') + '">' +
          (isFailed ? chip('失败', 'neg') + ' ' : '') +
          '<span class="muted">' + esc(entry.error ? String(entry.error).slice(0, 60) : '—') + '</span>' +
        '</td>' +
        '</tr>';
    });
    return '<div class="table-wrap"><table>' +
      '<thead><tr><th>源</th><th>fetched</th><th>accepted</th><th>rejected</th><th>error</th></tr></thead>' +
      '<tbody>' + rows.join('') + '</tbody></table></div>';
  }

  function metricsHtml(c) {
    var s = c.stats || {};
    return '<div class="metrics">' +
      '<div class="metric"><div class="metric__label">RAW ITEMS</div><div class="metric__value">' + num(s.raw) + '</div></div>' +
      '<div class="metric"><div class="metric__label">EVENTS</div><div class="metric__value">' + num(s.events) + '</div></div>' +
      '<div class="metric"><div class="metric__label">REJECTS</div><div class="metric__value">' + num(s.rejects) + '</div></div>' +
      '<div class="metric"><div class="metric__label">MERGED</div><div class="metric__value">' + num(s.merged) + '</div></div>' +
      '</div>';
  }

  function eventsHtml(c) {
    var limit = 80;
    var shown = c.events.slice(0, limit);
    var items = shown.map(function (event) {
      var value = event && event.value && typeof event.value === 'object' ? event.value : {};
      var valueText = value.number !== null && value.number !== undefined
        ? value.number + (value.unit ? ' ' + value.unit : '')
        : '';
      var url = safeUrl(event && event.source_url);
      var sourcesCount = Array.isArray(event && event.sources) ? event.sources.length : 0;
      return '<div class="event">' +
        '<div class="event__head">' +
          '<span class="event__time">' + esc(event.time || '—') + '</span>' +
          '<span class="event__subject">' + esc(event.subject || '—') + '</span>' +
          '<span class="event__action">' + esc(event.action || '—') + (event.action_text ? ' · ' + esc(event.action_text) : '') + '</span>' +
          (valueText ? chip(valueText, 'info', true) : '') +
        '</div>' +
        '<p class="event__excerpt">' + esc(event.excerpt || '（无原文片段）') + '</p>' +
        '<div class="event__foot">' +
          '<span>' + esc(event.source_name || '—') + '</span>' +
          '<span>' + esc(event.fetched_at_utc || '—') + '</span>' +
          (sourcesCount > 1 ? '<span>合并来源 ' + sourcesCount + ' 家</span>' : '') +
          (url ? '<a href="' + esc(url) + '" target="_blank" rel="noreferrer">来源链接</a>' : '<span>来源链接缺失</span>') +
        '</div>' +
        '</div>';
    }).join('');
    var more = c.events.length > limit
      ? '<div class="field__hint" style="margin-top: 8px;">仅展示前 ' + limit + ' 条；共 ' + c.events.length + ' 条。</div>'
      : '';
    return '<div class="events">' + items + '</div>' + more;
  }

  function rejectsHtml(c) {
    var keys = Object.keys(c.rejectReasons || {});
    if (!keys.length) {
      if (c.rejects.length) {
        return '<div class="field__hint" style="margin-top: 12px;">被拒 ' + c.rejects.length + ' 条；产物未带原因汇总。</div>';
      }
      return '';
    }
    var chips = keys.map(function (key) {
      return chip(key + ' × ' + c.rejectReasons[key], key === 'not_an_event' ? 'info' : 'warn', true);
    }).join(' ');
    return '<div style="margin-top: 12px;"><div class="field__label" style="margin-bottom: 6px;">拒绝原因汇总</div>' +
      '<div class="row" style="margin-top: 0;">' + chips + '</div></div>';
  }

  function blockedHtml(c) {
    var stats = (c.rawMeta && c.rawMeta.sources_stats) || {};
    var errorRows = c.requested.map(function (source) {
      var entry = stats[source] || {};
      return '<tr class="' + (entry.error ? 'is-hot' : '') + '">' +
        '<td class="mono">' + esc(source) + '</td>' +
        '<td class="mono">' + num(entry.fetched) + '</td>' +
        '<td class="mono" title="' + esc(entry.error || '') + '">' + esc(entry.error ? String(entry.error).slice(0, 80) : '—') + '</td>' +
        '</tr>';
    });
    var reason = c.tier === 'failed'
      ? '全部源失败：这份产物不是结果，不能进结果区，也不能写成「暂无事件」。'
      : '产物缺 status 字段：无法证明是 ok，按纪律拦截；下面只列逐源计数，供排障。';
    return '<div class="blocked">' +
      '<p class="blocked__title">已拦截 · 本次不是结果</p>' +
      '<p class="blocked__text">' + esc(reason) + '</p>' +
      '</div>' +
      '<div class="table-wrap"><table>' +
      '<thead><tr><th>源</th><th>fetched</th><th>error</th></tr></thead>' +
      '<tbody>' + errorRows.join('') + '</tbody></table></div>' +
      '<div class="field__hint" style="margin-top: 8px;">原始事件计数：' + num(c.events.length) +
      '（不展开；状态未确认前展示事件等于把失败当结果）。</div>';
  }

  function renderTimeline(doc, context) {
    var c = ST.classifyTimeline(doc);
    // 保留逐源原始记录，供覆盖表使用
    c.rawMeta = doc && doc.meta ? doc.meta : null;

    $('tl-banner').innerHTML = bannerHtml(c, context || null);
    var body = $('tl-body');

    if (c.blocked) {
      body.innerHTML = blockedHtml(c);
      return;
    }

    var parts = [];
    parts.push(metricsHtml(c));
    parts.push(coverageTableHtml(c));
    if (c.rejects.length) parts.push(rejectsHtml(c));

    if (c.tier === 'empty') {
      parts.push('<div class="empty-note">' + (
        c.emptyKind === 'entity-zero'
          ? '源已覆盖、零命中。不能把这一条读成「该主体没有事件」。'
          : '源可达、无匹配条目。这是真无数据，不是采集失败。'
      ) + '</div>');
    } else if (c.tier === 'unjudged') {
      parts.push('<div class="empty-note">源有返回但事件为 0；请按上面的拒绝原因排查，不要把它读成「没发生」。</div>');
    } else if (c.events.length) {
      parts.push(eventsHtml(c));
    }

    body.innerHTML = parts.join('');
  }

  // ── 时间线：表单/回放 ─────────────────────────────────────────
  function initTimeline() {
    var startEl = $('tl-start');
    var endEl = $('tl-end');
    var today = new Date();
    endEl.value = isoDate(today);
    startEl.value = isoDate(new Date(today.getTime() - 20 * 86400000));

    $('tl-mode').addEventListener('change', function () {
      var entity = $('tl-mode').value === 'entity';
      $('tl-query-label').textContent = entity ? '主体词' : '主题词';
      $('tl-query').placeholder = entity ? '如 XBI 或公司名' : '如 clinical trial';
    });

    $('tl-form').addEventListener('submit', function (event) {
      event.preventDefault();
      var mode = $('tl-mode').value;
      var sources = Array.prototype.slice.call($('tl-sources').querySelectorAll('input:checked'))
        .map(function (input) { return input.value; });
      var request = {
        mode: mode,
        topic: mode === 'topic' ? $('tl-query').value : null,
        entity: mode === 'entity' ? $('tl-query').value : null,
        start: $('tl-start').value.trim(),
        end: $('tl-end').value.trim(),
        sources: sources,
        maxPerSource: Number($('tl-max').value),
        outDir: $('tl-outdir').value.trim()
      };

      setProgress('running', '已提交（等待桥接）');
      $('tl-log').textContent = '';

      BR.runTimeline(request).then(function (outcome) {
        var doc = outcome && outcome.ok && outcome.data ? outcome.data.eventsDoc : null;
        if (doc) {
          $('tl-stub').innerHTML = '';
          renderTimeline(doc, { label: '本次运行 · 退出码 ' + (outcome.exitCode === null ? '未知' : outcome.exitCode) });
          setProgress('done', '已结束 · 退出码 ' + (outcome.exitCode === null ? '未知' : outcome.exitCode));
          return;
        }
        if (outcome.available && outcome.exitCode !== null && outcome.exitCode !== 0) {
          $('tl-stub').innerHTML = cliFailedHtml(outcome);
          setProgress('done', '已结束 · 退出码 ' + outcome.exitCode);
          return;
        }
        $('tl-stub').innerHTML = stubBox(outcome);
        if (outcome.available) {
          setProgress('done', '已结束 · 未拿到产物');
        } else {
          setProgress('idle', '未接入');
          $('tl-log').textContent = '进程桥未接入：本轮只定形，不产生任何结果。';
        }
      });
    });

    // 桥逐行转发 timeline.py 的 stdout：长任务要能看到在跑，而不是像卡死。
    if (typeof BR.onTimelineProgress === 'function') {
      BR.onTimelineProgress(function (payload) {
        if (!payload || !payload.kind) return;
        if (payload.kind === 'line') {
          var log = $('tl-log');
          if (log) {
            log.textContent += (log.textContent ? '\n' : '') + payload.line;
            log.scrollTop = log.scrollHeight;
          }
          setProgress('running', '正在跑 · 第 ' + (payload.seq || 0) + ' 行输出');
        } else if (payload.kind === 'exit') {
          var code = payload.exitCode;
          setProgress('done', '已结束 · 退出码 ' + (code === null || code === undefined ? '未知' : code));
        }
      });
    }

    renderDemoButtons();
  }

  function setProgress(state, label) {
    var panel = $('tl-progress');
    var chipEl = $('tl-progress-chip');
    if (panel) panel.setAttribute('data-state', state);
    if (chipEl) {
      var tone = state === 'running' ? 'warn' : (state === 'done' ? 'ok' : 'neutral');
      chipEl.className = 'chip chip--' + tone;
      chipEl.innerHTML = '<span class="chip__dot"></span>' + esc(label);
    }
  }

  function renderDemoButtons() {
    var list = $('tl-demo-list');
    var note = $('tl-demo-note');
    if (!DEV || !Array.isArray(DEV.timeline) || !DEV.timeline.length) {
      list.innerHTML = '<span class="field__hint">本地真实产物回放未生成。</span>';
      note.textContent = '运行 python desktop/tools/build_dev_data.py 可生成；产物只留在本地，不入库。';
      return;
    }
    note.textContent = '生成于 ' + (DEV.generated_at_utc || '未知时刻') + '；共 ' + DEV.timeline.length +
      ' 组。路径与 sha256 见 dev-data.js，全部来自真实运行。';

    DEV.timeline.forEach(function (item) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn--sm';
      var toneHint = item.missing ? '（产物不存在）' : '';
      btn.textContent = (item.label || item.key) + toneHint;
      if (item.missing) btn.disabled = true;
      btn.addEventListener('click', function () {
        if (item.missing || !item.data) {
          $('tl-banner').innerHTML = '<div class="empty-note">该回放产物不存在：' +
            esc(item.source_path || '') + '；不会用假数据补位。</div>';
          $('tl-body').innerHTML = '';
          return;
        }
        renderTimeline(item.data, {
          label: item.label + ' · status=' + (item.data.status || '缺失')
        });
      });
      list.appendChild(btn);
    });
  }

  // ── 注册 ─────────────────────────────────────────────────────
  function payloadFromForm() {
    var criterionText = $('reg-criterion').value.trim();
    var criterion = null;
    var parseError = null;
    if (criterionText) {
      try {
        criterion = JSON.parse(criterionText);
      } catch (err) {
        parseError = err && err.message ? err.message : String(err);
      }
    }
    var payload = {
      id: $('reg-id').value.trim(),
      claim: $('reg-claim').value.trim(),
      registered_at: $('reg-at').value.trim(),
      expires_on: $('reg-expires').value.trim(),
      criterion: criterion
    };
    return { payload: payload, parseError: parseError };
  }

  function updateRegisterPreview() {
    var collected = payloadFromForm();
    var preview = $('reg-preview');
    if (collected.parseError) {
      preview.textContent = 'criterion JSON 解析失败：' + collected.parseError;
      return;
    }
    preview.textContent = JSON.stringify(collected.payload, null, 2);
  }

  function renderRegisterOutcome(outcome) {
    var box = $('reg-stub');
    if (!outcome.available) {
      box.innerHTML = stubBox(outcome);
      return;
    }
    if (!outcome.ok) {
      box.innerHTML = stubBox(outcome);
      return;
    }
    if (outcome.exitCode === 0) {
      box.innerHTML = '<div class="banner banner--ok">' +
        '<div class="banner__row">' + chip('已写入', 'ok') + monoChip('退出码 0', 'ok') + '</div>' +
        '<div class="banner__title">注册成功</div>' +
        '<p class="banner__rule">账本已追加一条记录；写入时刻来自壳显式传入的 --at。</p>' +
        '</div>';
      return;
    }
    if (outcome.exitCode === 2) {
      var match = /rejected \[([^\]]+)\]:\s*([\s\S]*)/.exec(outcome.stderr || '');
      var code = match ? match[1] : 'UNPARSED';
      var message = match ? match[2].trim() : (outcome.stderr || '（stderr 为空）');
      box.innerHTML = '<div class="banner banner--neg">' +
        '<div class="banner__row">' + chip('注册被拒', 'neg') + monoChip(code, 'neg') +
        monoChip('退出码 2', 'neg') + chip('账本零新增', 'neutral') + '</div>' +
        '<div class="banner__title">未写入</div>' +
        '<p class="banner__rule">' + esc(message) + '</p>' +
        '</div>';
      return;
    }
    box.innerHTML = '<div class="banner banner--warn">' +
      '<div class="banner__row">' + chip('未知退出码', 'warn') + monoChip(String(outcome.exitCode), 'warn') + '</div>' +
      '<p class="banner__rule">' + esc(outcome.stderr || outcome.stdout || '（无输出）') + '</p>' +
      '</div>';
  }

  function initRegister() {
    $('reg-at').value = nowUtc();
    $('reg-now').addEventListener('click', function () {
      $('reg-at').value = nowUtc();
      updateRegisterPreview();
    });

    ['reg-id', 'reg-claim', 'reg-at', 'reg-expires', 'reg-criterion'].forEach(function (id) {
      $(id).addEventListener('input', updateRegisterPreview);
    });

    $('reg-example').addEventListener('click', function () {
      var example = DEV && DEV.payloads ? DEV.payloads.register : null;
      if (!example) {
        $('reg-stub').innerHTML = stubBox({
          code: 'NO_EXAMPLE',
          message: '本地没有可载入的真实示例（dev-data.js 未生成或 payload_register.json 不存在）。',
          command: 'load_example'
        });
        return;
      }
      $('reg-id').value = example.id || '';
      $('reg-claim').value = example.claim || '';
      $('reg-at').value = example.registered_at || nowUtc();
      $('reg-expires').value = example.expires_on || '';
      $('reg-criterion').value = JSON.stringify(example.criterion || null, null, 2);
      updateRegisterPreview();
    });

    $('reg-form').addEventListener('submit', function (event) {
      event.preventDefault();
      var collected = payloadFromForm();
      if (collected.parseError) {
        $('reg-stub').innerHTML = stubBox({
          code: 'INVALID_CRITERION_JSON',
          message: 'criterion JSON 解析失败：' + collected.parseError,
          command: 'registry_register'
        });
        return;
      }
      BR.registerPrediction({
        payload: collected.payload,
        at: collected.payload.registered_at,
        ledger: BR.DEFAULTS.ledger
      }).then(renderRegisterOutcome);
    });

    updateRegisterPreview();
    renderRegisterRejections();
  }

  function renderRegisterRejections() {
    var box = $('reg-rejections');
    if (!DEV || !Array.isArray(DEV.register_rejections) || !DEV.register_rejections.length) {
      box.innerHTML = '<div class="empty-note">本地真实拒绝输出未生成；不会用编造的拒绝码补位。</div>';
      return;
    }
    var rows = DEV.register_rejections.map(function (item) {
      return '<div class="reason">' +
        '<div class="reason__top">' + monoChip(item.code || 'UNPARSED', 'neg') +
        monoChip('退出码 ' + item.exit_code, 'neutral') +
        chip('账本零新增', 'neutral') + '</div>' +
        '<div class="reason__explain">' + esc(item.message || '（无消息）') + '</div>' +
        '<div class="reason__code">来源：' + esc(item.payload || '—') + '</div>' +
        '</div>';
    }).join('');
    box.innerHTML = '<div class="row" style="margin-top: 0; align-items: stretch;">' + rows + '</div>';
  }

  // ── 核验 ─────────────────────────────────────────────────────
  function renderVerifyOutcome(outcome) {
    var box = $('ver-stub');
    if (!outcome.available) {
      box.innerHTML = stubBox(outcome);
      $('ver-result').innerHTML = '';
      return;
    }
    if (!outcome.ok) {
      box.innerHTML = stubBox(outcome);
      $('ver-result').innerHTML = '';
      return;
    }
    var okExit = outcome.exitCode === 0;
    var tone = okExit ? 'ok' : 'warn';
    box.innerHTML = '<div class="banner banner--' + tone + '">' +
      '<div class="banner__row">' + chip('已执行', tone) + monoChip('退出码 ' + outcome.exitCode, tone) + '</div>' +
      '<div class="banner__title">' + (okExit ? '核验完成（判定已写入账本）' : '核验未完成（退出码 ' + outcome.exitCode + '）') + '</div>' +
      '<p class="banner__rule">undetermined 必须同时展示 reason_code，壳不在这里做二次判定。</p>' +
      (outcome.stderr ? '<pre class="log" style="margin-top: 8px;">' + esc(outcome.stderr) + '</pre>' : '') +
      (outcome.stdout ? '<pre class="log" style="margin-top: 8px;">' + esc(outcome.stdout) + '</pre>' : '') +
      '</div>';
  }

  function renderLedger() {
    var metricsBox = $('reg-metrics');
    var body = $('reg-table-body');
    var chainBox = $('chain-box');

    if (!DEV || !DEV.registry || !Array.isArray(DEV.registry.list)) {
      metricsBox.innerHTML = '';
      body.innerHTML = '<tr><td colspan="6" class="muted">本地真实账本回放未生成；不会用编造记录补位。</td></tr>';
      chainBox.textContent = '链校验：无本地回放数据。';
      return;
    }

    var rows = DEV.registry.list;
    var summary = ST.summarizeRegistry(rows);
    metricsBox.innerHTML =
      '<div class="metric"><div class="metric__label">TOTAL</div><div class="metric__value">' + summary.total + '</div></div>' +
      '<div class="metric"><div class="metric__label">HIT</div><div class="metric__value">' + summary.hit + '</div></div>' +
      '<div class="metric"><div class="metric__label">MISS</div><div class="metric__value">' + summary.miss + '</div></div>' +
      '<div class="metric"><div class="metric__label">UNDETERMINED</div><div class="metric__value">' + summary.undetermined + '</div></div>';

    body.innerHTML = rows.map(function (row) {
      var mapped = ST.mapVerifyStatus(row.verdict);
      var reasonCell;
      if (mapped.key === 'undetermined') {
        var reason = ST.reasonInfo(row.reason_code);
        reasonCell = '<div class="reason">' +
          '<div class="reason__top">' + monoChip(reason.code || '（缺）', reason.bucketMeta.tone) +
          chip(reason.bucketMeta.label, reason.bucketMeta.tone) + '</div>' +
          '<div class="reason__explain">' + esc(reason.explain) + '</div>' +
          '</div>';
      } else if (mapped.key === 'hit' || mapped.key === 'miss') {
        reasonCell = '<span class="muted">—（有判定，无原因码）</span>';
      } else {
        reasonCell = '<span class="muted">—（尚无原因）</span>';
      }
      return '<tr class="' + (mapped.key === 'undetermined' ? 'is-hot' : '') + '">' +
        '<td class="mono">' + esc(row.id) + '</td>' +
        '<td>' + chip(mapped.label, mapped.tone) + '</td>' +
        '<td class="mono">' + esc(row.reason_code || '—') + '</td>' +
        '<td>' + reasonCell + '</td>' +
        '<td class="mono">' + esc(row.expires_on || '—') + '</td>' +
        '<td><span class="muted" title="' + esc(row.claim_canonical || '') + '">' +
          esc(String(row.claim_canonical || '').slice(0, 70)) +
          (String(row.claim_canonical || '').length > 70 ? '…' : '') + '</span></td>' +
        '</tr>';
    }).join('');

    var chain = DEV.registry.chain_check;
    if (chain) {
      chainBox.innerHTML = '链校验：' + chip(chain.ok ? '通过' : '失败', chain.ok ? 'ok' : 'neg') +
        ' ' + monoChip('条数 ' + chain.count, 'neutral') +
        ' ' + monoChip('head ' + String(chain.head_sha256 || '').slice(0, 12) + '…', 'neutral') +
        ' ' + '<span class="muted">（只读；账本路径 ' + esc(DEV.registry.ledger_path || '') + '）</span>';
    } else {
      chainBox.textContent = '链校验：无本地回放数据。';
    }
  }

  function renderLegend() {
    var statusBox = $('status-legend');
    var reasonBox = $('reason-legend');

    var statusItems = Object.keys(ST.VERIFY_STATUSES).map(function (key) {
      var mapped = ST.mapVerifyStatus(key);
      return '<div class="reason" style="flex: 1 1 180px;">' +
        '<div class="reason__top">' + chip(mapped.label, mapped.tone) + monoChip(key, 'neutral') + '</div>' +
        '<div class="reason__explain">' + esc(mapped.note) + '</div>' +
        '</div>';
    });
    var pending = ST.mapVerifyStatus(null);
    statusItems.push('<div class="reason" style="flex: 1 1 180px;">' +
      '<div class="reason__top">' + chip(pending.label, pending.tone) + monoChip('null', 'neutral') + '</div>' +
      '<div class="reason__explain">' + esc(pending.note) + '</div>' +
      '</div>');
    statusBox.innerHTML = statusItems.join('');

    var reasonItems = Object.keys(ST.REASON_BUCKETS).map(function (key) {
      var bucket = ST.REASON_BUCKETS[key];
      return '<div class="reason" style="flex: 1 1 180px;">' +
        '<div class="reason__top">' + chip(bucket.label, bucket.tone) + monoChip(key, 'neutral') + '</div>' +
        '<div class="reason__explain">' + esc(bucket.meaning) + '</div>' +
        '</div>';
    });
    reasonBox.innerHTML = reasonItems.join('');
  }

  function initVerify() {
    $('ver-at').value = nowUtc();
    $('ver-now').addEventListener('click', function () {
      $('ver-at').value = nowUtc();
    });

    $('ver-form').addEventListener('submit', function (event) {
      event.preventDefault();
      BR.verifyDue({
        at: $('ver-at').value.trim(),
        id: $('ver-id').value.trim() || null,
        ledger: $('ver-ledger').value.trim()
      }).then(renderVerifyOutcome);
    });

    $('ver-reconcile').addEventListener('click', function () {
      BR.reconcile({ ledger: $('ver-ledger').value.trim() }).then(function (outcome) {
        $('ver-stub').innerHTML = stubBox(outcome);
        if (outcome.available && outcome.ok) {
          $('ver-result').innerHTML = '<div class="banner banner--info">' +
            '<div class="banner__row">' + chip('对账', 'info') + monoChip('退出码 ' + outcome.exitCode, 'neutral') + '</div>' +
            '<p class="banner__rule">累计命中率只报区间；样本不足时不报点估计。</p>' +
            (outcome.stdout ? '<pre class="log" style="margin-top: 8px;">' + esc(outcome.stdout) + '</pre>' : '') +
            '</div>';
        }
      });
    });

    renderLedger();
    renderLegend();
  }

  // ── 顶栏状态 ──────────────────────────────────────────────────
  function initHeader() {
    if (!BR) {
      setChip($('chip-bridge'), 'neg', '进程桥：脚本未加载');
      return;
    }
    if (BR.available()) {
      setChip($('chip-bridge'), 'ok', '进程桥：已接入', BR.CONTRACT_VERSION);
    } else {
      setChip($('chip-bridge'), 'warn', '进程桥：未接入（待 Rust 批准）', BR.CONTRACT_VERSION);
    }

    var pythonChip = $('chip-python');
    if (pythonChip && BR.PYTHON_PATH) {
      pythonChip.textContent = 'Python312 · ' + BR.PYTHON_PATH.split('\\').pop();
      pythonChip.title = BR.PYTHON_PATH;
    }

    if (DEV && Array.isArray(DEV.timeline)) {
      setChip($('chip-devdata'), 'ok', '真实产物回放：已加载 ' + DEV.timeline.length + ' 组',
        '生成于 ' + (DEV.generated_at_utc || '未知时刻') + '；不入库');
    } else {
      setChip($('chip-devdata'), 'neutral', '真实产物回放：未生成', '运行 python desktop/tools/build_dev_data.py');
    }
  }

  function init() {
    initTabs();
    initHeader();
    initTimeline();
    initRegister();
    initVerify();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
