# 追踪状态 · 数据结构（应用层）

> 裁决日：2026-11-28 ｜ 性质：用户裁决，不是技术结论 ｜ 本轮只落数据结构，不实现任何后续行为

## 1. 分层

| 层 | 字段 | 谁写 | 谁读 | 是否影响 `is_event` |
|---|---|---|---|---|
| 判定层（`timeline.py` / `rulesets/zh.json`） | `future`（布尔） | 引擎 | 下游/界面 | **否**；`future=true` 仍由 D1 判为 `is_event=是` |
| 应用层（`data/tracking_state.json`） | `tracking`（布尔） | 用户手动开关 | 界面；将来的「已开追踪」处理（本轮不实现） | **否**；与判定完全隔离 |

`tracking` **不写进** `rulesets/zh.json`，不进 `is_event`，不进任何判据。

## 2. 持久化位置与结构

- 位置：`data/tracking_state.json`
- 结构：

```json
{
  "version": 1,
  "layer": "application",
  "default_tracking": false,
  "items": {
    "<event_id>": {
      "tracking": true,
      "updated_at_utc": "2026-11-28T12:00:00Z"
    }
  }
}
```

- 键：`event_id`（引擎输出的 16 位十六进制，稳定）。
- 值：`tracking` 布尔；`updated_at_utc` 最后一次切换时刻。
- **默认值**：`items` 里没有该 `event_id` → 视为 `tracking=false`（`default_tracking=false`）。

## 3. 可逆怎么保证

1. 只改布尔值，不删除记录；关掉写 `false`，不抹掉历史。
2. 开关是幂等的：同一状态重复写不产生副作用。
3. `updated_at_utc` 只用于 last-write-wins，不参与判定。
4. 没有任何级联删除、没有「一旦开启就锁定」的字段。

## 4. 本轮明确不做

- 不做提醒、不做兑现核验、不做状态机、不排期「承诺兑现」检查。
- 不实现「已开追踪之后系统做什么」——该行为**尚未裁决**。
- 追踪状态由用户手动开关，系统不自作主张。
