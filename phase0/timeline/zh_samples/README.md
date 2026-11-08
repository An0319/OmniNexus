```bash
python -c "import json;from collections import Counter;A={x['id']:x['is_event'] for x in json.load(open('labels_a.json',encoding='utf-8'))['labels']};B={x['id']:x['is_event'] for x in json.load(open('labels_b.json',encoding='utf-8'))};ids=sorted(set(A)&set(B));n=len(ids);agree=sum(A[i]==B[i] for i in ids);ca=Counter(A[i] for i in ids);cb=Counter(B[i] for i in ids);pe=sum(ca[v]*cb[v] for v in set(ca)|set(cb))/n**2;print('n=%d agree=%d rate=%.4f kappa=%.4f'%(n,agree,agree/n,(agree/n-pe)/(1-pe)));print('matrix',{(x,y):sum(1 for i in ids if A[i]==x and B[i]==y) for x in ['是','不是','说不清'] for y in ['是','不是','说不清']})"
```

在 `zh_samples/` 目录执行上一行，即得 n、一致条数、一致率、κ 与三值混淆矩阵（当前输出 `n=80 agree=67 rate=0.8375 kappa=0.6602`）。这是 80 条中文新闻标题（A/B/C/D 各 20）的双侧标注：A 侧按 [event_definition_zh.md](../event_definition_zh.md)，B 侧只凭常识，用来测判据的**可复现性**，不是准确率。基准线（全判「不是」）＝ 57/80 ≈ 71%，任何一致率都要与它并排。

> **封存（2026-11-08）**：这 80 条取自归纳规则用的那 420 条，属**开发集**。从此只作回归检查，不再承当任何「准确率」；扩动词表不得看着这 80 条的失败项往里加。要谈准确率必须另采独立样本。

| 文件 | 内容 |
|---|---|
| `items.json` | 80 条样本（标题、URL、类别），审计冻结，SHA-256 见 `manifest.json` |
| `labels_a.json` / `labels_b.json` | 两侧逐条 `is_event` 判定与理由 |
| `manifest.json` | 冻结时刻、条数、各文件 SHA-256 |
| `agreement.md` | 结果：混淆矩阵、一致率、κ、13 条分歧归因、天花板 |
| `source_recon.md` | 结构化事件源实测清单（只侦察，未接入） |
| `blind_notes.md` | B 侧盲标说明 |
