# 标注流程卡（第三批直接用）

> 目的：防止标注者读到分数 / 一致率 / 审计文件，污染判断。
> 适用：A/B 两条独立标注会话。**照步骤做，不是原则口号。**

## 0. 上次实际发生了什么（必须记住）

B 侧读 `event_definition_zh.md`（约 64KB）时一次性读取失败；改为分段读取，其中一段撞上 **§12.1 分数表**。此后 B 的判断被分数锚定，不能算独立标注。

结论：不是「读得不够」，是「读到了不该读的东西」。

## 1. 开场自述（每个标注会话第一件事）

开始标注前，先输出一段自述：

- **我将读**：`phase0/timeline/event_definition_zh.md` 的 **§0–§11**，以及 `phase0/timeline/annotation_rules_extract.md`（§13 判定规则的摘录，仅规则）。
- **我不读**：`event_definition_zh.md` 的 **§12（含 §12.1 分数表）与 §13 全节（13.1–13.9 及开头数字）**、`agreement.md`、`criteria_audit.md`、`labels_a.json`、`labels_b.json`、任何含准确率 / 一致率 / 审计结论的文件。
- 我只用标题与同条目原文片段判，**不用引擎结果**。

没有这段自述，不许开始。

## 2. 读文件规则（防跳段）

1. 先列出「我要读的文件清单」（路径 + 允许的章节），再打开。
2. 一次读不全（超时 / 截断 / 报错）→ 重试或换方式（带 offset/limit），必须覆盖到文件末尾；**不许跳段**。
3. 读到 **§11 末尾停下**；**§12 与 §13 一律不读**（§13 的判定规则已摘录到 `annotation_rules_extract.md`）。
4. **硬禁打开**：
   - `phase0/timeline/zh_fresh_20261128/agreement.md`
   - `phase0/timeline/zh_fresh_20261128/criteria_audit.md`
   - `phase0/timeline/zh_fresh_20261128/labels_a.json`
   - `phase0/timeline/zh_fresh_20261128/labels_b.json`
   - 任何文件名含 `agreement` / `audit` / `score` / `kappa` 的文件
   - `eval_zh_rules.py` 的输出
5. **节级硬禁**：`event_definition_zh.md` 的 §12、§13（含 §13.9 差异清单）。
6. 若误开上述文件或节：**立即停止标注**，声明「已污染」，本批作废，换新会话重来。

## 2.1 允许清单自检（开场必做）

逐条核对，全部为「是」才能开始：

- [ ] 要读的正文都在 **§0–§11** 内？
- [ ] 补充规则只来自 `annotation_rules_extract.md`，**不是 §13 原文**？
- [ ] 自述里没有 **§12、§13** 的任何节号？
- [ ] 没有 `agreement` / `audit` / `labels` / `score` 文件？
- [ ] 自述写了**文件路径与节号**？

任一为「否」→ 停下，重列清单。

## 3. 标注步骤（照做）

1. 新会话 → 开场自述（§1）。
2. 读判据 §0–§11 与 `annotation_rules_extract.md`；**不读 §12、§13**。
3. 读 `items.json`；只读标题 / 来源 / 时间 / 片段，不读任何引擎字段（该文件本身不应有）。
4. 逐条写 `id`、`is_event`（是 / 不是 / 说不清）、`reason`；理由必须指向标题里的词或结构。
5. 自检：id 全覆盖、无重复、三态计数与按来源计数。
6. 写 `labels_x.json`；**不打开对方的 `labels_*.json`**。
7. 报告三态计数、按来源计数、自述三问。

## 4. 隔离

- A/B 两条会话互不相见、不共享上下文、不交换中间结果。
- 任何一方不得读对方的 `labels_*.json`。
- 不跑 `eval_zh_rules.py`，不看引擎判定。

## 5. 一句话

**读错一个文件或一节，整批标注作废；宁可重读，不许跳段。**
