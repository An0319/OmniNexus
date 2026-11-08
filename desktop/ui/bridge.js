/*
 * 进程桥 · 接口契约（先定形，不实现）
 *
 * 本轮没有 Rust 工具链，桥只声明签名与参数约定；所有调用都会返回
 * BRIDGE_NOT_AVAILABLE，界面不得据此伪造任何结果。
 *
 * 契约版本：mnx-shell-bridge/v1
 * 实现侧（Rust/Tauri 2）需要把同名命令暴露给前端：
 *   run_timeline         → spawn python phase0/timeline/timeline.py
 *   registry_register    → spawn python phase0/registry/cli.py register
 *   registry_verify      → spawn python phase0/registry/cli.py verify
 *   registry_list        → spawn python phase0/registry/cli.py list
 *   registry_chain_check → spawn python phase0/registry/cli.py chain-check
 *   registry_reconcile   → spawn python phase0/registry/cli.py reconcile --json
 * 进度事件名：timeline-progress（Rust 逐行转发 timeline.py 的 stdout）
 *
 * 时间纪律：--at 由壳显式传入；前端在本模块校验后才发请求，
 * 不允许把「系统时间隐式默认」留给 Python。
 */
(function (global) {
  'use strict';

  var CONTRACT_VERSION = 'mnx-shell-bridge/v1';

  // 作者已定：直接使用系统 Python 3.12；冻进工具属于打包阶段，不在 F 这一片。
  var PYTHON_PATH = 'C:\\Users\\24063\\AppData\\Local\\Programs\\Python\\Python312\\python.exe';

  // 默认路径与 CLI 默认保持一致；界面上可改，调用时显式传给 Python。
  var DEFAULTS = {
    outDir: 'phase0/timeline/out',
    ledger: 'phase0/registry/registry.ledger.jsonl',
    maxPerSource: 60,
    sources: ['google_news', 'bing_news', 'clinicaltrials', 'federal_register']
  };

  // CLI 参数对照表：给实现侧照着接，避免前端猜参数。
  var COMMANDS = {
    run_timeline: {
      cli: 'phase0/timeline/timeline.py',
      args: ['--topic|--entity', '--start', '--end', '--sources', '--max-per-source', '--out-dir'],
      returns: ['exit_code', 'stdout_lines', 'events_json']
    },
    registry_register: {
      cli: 'phase0/registry/cli.py',
      args: ['--ledger', 'register', '--payload', '--at'],
      returns: ['exit_code', 'stdout', 'stderr']
    },
    registry_verify: {
      cli: 'phase0/registry/cli.py',
      args: ['--ledger', 'verify', '--at', '--id?'],
      returns: ['exit_code', 'stdout', 'stderr']
    },
    registry_list: {
      cli: 'phase0/registry/cli.py',
      args: ['--ledger', 'list'],
      returns: ['exit_code', 'stdout_json']
    },
    registry_chain_check: {
      cli: 'phase0/registry/cli.py',
      args: ['--ledger', 'chain-check'],
      returns: ['exit_code', 'stdout_json']
    },
    registry_reconcile: {
      cli: 'phase0/registry/cli.py',
      args: ['--ledger', 'reconcile', '--json'],
      returns: ['exit_code', 'stdout_json']
    }
  };

  var ISO_AT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;
  var ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

  function tauriCore() {
    return global.__TAURI__ && global.__TAURI__.core ? global.__TAURI__.core : null;
  }

  function tauriEvent() {
    return global.__TAURI__ && global.__TAURI__.event ? global.__TAURI__.event : null;
  }

  function available() {
    var core = tauriCore();
    return !!(core && typeof core.invoke === 'function');
  }

  function unavailable(command, message) {
    return {
      ok: false,
      available: false,
      code: 'BRIDGE_NOT_AVAILABLE',
      message: message || '进程桥未接入：等待 Rust 工具链批准后实现（本轮只定形，不产假结果）。',
      command: command,
      exitCode: null,
      stdout: '',
      stderr: '',
      data: null
    };
  }

  function invalid(command, message) {
    return {
      ok: false,
      available: available(),
      code: 'INVALID_REQUEST',
      message: message,
      command: command,
      exitCode: null,
      stdout: '',
      stderr: '',
      data: null
    };
  }

  function normalize(command, raw) {
    var payload = raw && typeof raw === 'object' ? raw : {};
    return {
      ok: true,
      available: true,
      code: null,
      message: null,
      command: command,
      exitCode: typeof payload.exitCode === 'number' ? payload.exitCode : null,
      stdout: typeof payload.stdout === 'string' ? payload.stdout : '',
      stderr: typeof payload.stderr === 'string' ? payload.stderr : '',
      data: payload.data === undefined ? null : payload.data
    };
  }

  function invoke(command, args) {
    var core = tauriCore();
    if (!core || typeof core.invoke !== 'function') {
      return Promise.resolve(unavailable(command));
    }
    try {
      return Promise.resolve(core.invoke(command, args)).then(function (raw) {
        return normalize(command, raw);
      }).catch(function (err) {
        return {
          ok: false,
          available: true,
          code: 'BRIDGE_ERROR',
          message: err && err.message ? String(err.message) : String(err),
          command: command,
          exitCode: null,
          stdout: '',
          stderr: '',
          data: null
        };
      });
    } catch (err) {
      return Promise.resolve({
        ok: false,
        available: true,
        code: 'BRIDGE_ERROR',
        message: String(err && err.message ? err.message : err),
        command: command,
        exitCode: null,
        stdout: '',
        stderr: '',
        data: null
      });
    }
  }

  function validateAt(value) {
    if (!value || !ISO_AT.test(String(value).trim())) {
      return { ok: false, message: '--at 必须是 ISO-8601 UTC 时刻，例如 2026-11-08T09:00:00Z（必须带 Z）' };
    }
    return { ok: true };
  }

  function validateDate(value, label) {
    if (!value || !ISO_DATE.test(String(value).trim())) {
      return { ok: false, message: label + ' 必须是 YYYY-MM-DD' };
    }
    return { ok: true };
  }

  /**
   * 出时间线。
   * request: {mode:'topic'|'entity', topic?, entity?, start:'YYYY-MM-DD',
   *           end:'YYYY-MM-DD', sources?:string[], maxPerSource?:number,
   *           outDir?:string, pythonPath?:string}
   * 返回：{ok, available, exitCode, stdout, stderr, data:{eventsJson}}
   */
  function runTimeline(request) {
    var req = request || {};
    var mode = req.mode === 'entity' ? 'entity' : 'topic';
    var query = mode === 'entity' ? req.entity : req.topic;
    if (!query || !String(query).trim()) {
      return Promise.resolve(invalid('run_timeline', mode === 'entity' ? '主体词不能为空' : '主题词不能为空'));
    }
    var start = validateDate(req.start, 'start');
    if (!start.ok) return Promise.resolve(invalid('run_timeline', start.message));
    var end = validateDate(req.end, 'end');
    if (!end.ok) return Promise.resolve(invalid('run_timeline', end.message));
    if (String(req.start) > String(req.end)) {
      return Promise.resolve(invalid('run_timeline', 'start 不能晚于 end'));
    }
    var max = req.maxPerSource === undefined ? DEFAULTS.maxPerSource : Number(req.maxPerSource);
    if (!isFinite(max) || max < 1 || max > 200) {
      return Promise.resolve(invalid('run_timeline', 'maxPerSource 必须是 1–200 的整数'));
    }
    return invoke('run_timeline', {
      request: {
        mode: mode,
        topic: mode === 'topic' ? String(req.topic).trim() : null,
        entity: mode === 'entity' ? String(req.entity).trim() : null,
        start: String(req.start).trim(),
        end: String(req.end).trim(),
        sources: Array.isArray(req.sources) && req.sources.length ? req.sources : null,
        maxPerSource: Math.floor(max),
        outDir: String(req.outDir || DEFAULTS.outDir),
        pythonPath: String(req.pythonPath || PYTHON_PATH)
      }
    });
  }

  /**
   * 注册一条预测。
   * request: {payload:object, at:string, ledger?:string, pythonPath?:string}
   * 退出码 0 = 已写入；2 = 被拒（stderr: rejected [CODE]: message），账本零新增。
   */
  function registerPrediction(request) {
    var req = request || {};
    var atCheck = validateAt(req.at);
    if (!atCheck.ok) return Promise.resolve(invalid('registry_register', atCheck.message));
    if (!req.payload || typeof req.payload !== 'object') {
      return Promise.resolve(invalid('registry_register', 'payload 必须是 JSON 对象'));
    }
    return invoke('registry_register', {
      request: {
        payload: req.payload,
        at: String(req.at).trim(),
        ledger: String(req.ledger || DEFAULTS.ledger),
        pythonPath: String(req.pythonPath || PYTHON_PATH)
      }
    });
  }

  /**
   * 核验到期。
   * request: {at:string, id?:string, ledger?:string, pythonPath?:string}
   * 判定三值：hit / miss / undetermined；undetermined 必须配 reason_code。
   */
  function verifyDue(request) {
    var req = request || {};
    var atCheck = validateAt(req.at);
    if (!atCheck.ok) return Promise.resolve(invalid('registry_verify', atCheck.message));
    return invoke('registry_verify', {
      request: {
        at: String(req.at).trim(),
        id: req.id ? String(req.id).trim() : null,
        ledger: String(req.ledger || DEFAULTS.ledger),
        pythonPath: String(req.pythonPath || PYTHON_PATH)
      }
    });
  }

  function listRegistry(request) {
    var req = request || {};
    return invoke('registry_list', {
      request: { ledger: String(req.ledger || DEFAULTS.ledger), pythonPath: String(req.pythonPath || PYTHON_PATH) }
    });
  }

  function chainCheck(request) {
    var req = request || {};
    return invoke('registry_chain_check', {
      request: { ledger: String(req.ledger || DEFAULTS.ledger), pythonPath: String(req.pythonPath || PYTHON_PATH) }
    });
  }

  function reconcile(request) {
    var req = request || {};
    return invoke('registry_reconcile', {
      request: { ledger: String(req.ledger || DEFAULTS.ledger), pythonPath: String(req.pythonPath || PYTHON_PATH) }
    });
  }

  /**
   * 订阅时间线进度（Rust 逐行转发 stdout）。
   * 返回 unsubscribe；未接入时返回空函数。
   */
  function onTimelineProgress(callback) {
    var evt = tauriEvent();
    if (!evt || typeof evt.listen !== 'function' || typeof callback !== 'function') {
      return function () {};
    }
    var unlisten = null;
    evt.listen('timeline-progress', function (event) {
      callback(event && event.payload ? event.payload : event);
    }).then(function (fn) {
      unlisten = fn;
    }).catch(function () {
      unlisten = null;
    });
    return function () {
      if (typeof unlisten === 'function') unlisten();
    };
  }

  global.MNXBridge = {
    CONTRACT_VERSION: CONTRACT_VERSION,
    PYTHON_PATH: PYTHON_PATH,
    DEFAULTS: DEFAULTS,
    COMMANDS: COMMANDS,
    available: available,
    validateAt: validateAt,
    validateDate: validateDate,
    runTimeline: runTimeline,
    registerPrediction: registerPrediction,
    verifyDue: verifyDue,
    listRegistry: listRegistry,
    chainCheck: chainCheck,
    reconcile: reconcile,
    onTimelineProgress: onTimelineProgress
  };
})(window);
