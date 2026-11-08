# 脉络 · 桌面壳（F 片）

中文 | [English](README.en.md)

> 这是一个**本机**运行的桌面壳：把仓库里已有的命令行流水线（`phase0/timeline/`、`phase0/registry/`）搬到界面上，
> 让你能输入一个话题、跑一次抓取、把判断登记下来、到期再核对。
> 壳只负责搬运参数与结果，**不做任何状态判定**——判定在 `desktop/ui/src/lib/status-map.ts` 一处完成。

## 先看这一条：它依赖你本机的东西

跑之前必须自备两样，装完就跑不起来不是 bug：

| 依赖 | 说明 |
|---|---|
| **本机 Python 3** | 壳不打包解释器；它直接调用一个已装好的 Python，并需要 `requests`（`pip install requests`，或按仓库根 `requirements.txt` 安装） |
| **WebView2（Windows）** | Tauri 的前端运行时。Windows 10/11 一般自带；没有需自行安装 |

另外两个现实约束，先写清楚：

- **Python 路径是写死的**：`desktop/ui/src/lib/bridge.ts` 的 `PYTHON_PATH` 与 `desktop/src-tauri/src/main.rs` 的 `PYTHON_FALLBACK` 都是作者机器上的绝对路径。换机器必须把这两处改成你自己的 `python.exe`，否则界面只会报「Python 解释器不存在」。
- **仓库根靠猜**：壳优先读环境变量 `MNX_REPO_ROOT`，否则从当前目录向上找 `phase0/timeline/timeline.py`。移动了这个目录结构就需要显式设置该变量。

## 现在能做什么

- 输入一个**话题**，或一家**公司 / 一只代号**，选时间范围、消息源、每源上限，跑一次抓取与抽取。
- 结果按档展示：正常完成 / 真无数据 / 实体零命中 / 判不了 / 部分覆盖 / 失败 / 状态未知。**这七档不合并**，因为「没抓到」和「抓到了但认不出」是两件事。
- 每条线索都带来源地址，点一下交给系统默认浏览器打开原文；打不开会如实报错，不假装成功。
- 把一句话判断连同判据一起登记进「我的记录」，到期项可以一键核对。判据在登记时冻结，被拒不会留下半条。

## 现在不能做什么（别指望）

- **抽取引擎仍是英文口径，中文话题搜不到可用结果。** 具体是：动作词表 `rules_v2` 全英文；「不是事件」的规则只匹配英文开头；Google 新闻源写死 `hl=en-US&gl=US&ceid=US:en`；另外两个源（临床试验登记、美国联邦公报）本身就是英文库。用中文话题去搜，多数结果是**认不出来**，不是「没有事件」。
- **界面只有中文。** 文案已集中到 `desktop/ui/src/i18n/`，为将来加英文留了位，但英文词表**还没做**。
- **没有安装包。** `tauri.conf.json` 里 `bundle.active` 为 `false`，没有签名、没有自动更新，只能自己编译运行。
- **不是后台服务。** 关机期间不核验；到期项在打开时补核一次。
- **只在 Windows 上实际跑过。** Tauri 本身跨平台，但窗口配置与「隐藏子进程控制台」都按 Windows 写的，其他系统未验证。

## 怎么跑起来

前置：Node.js（Vite 8 要求 `^20.19.0 || >=22.12.0`）、Rust 工具链、上面那两个依赖。

```bash
# 1. 先构建前端（产物会被 cargo 打进二进制，改前端后必须重跑这一步）
cd desktop/ui
npm install
npm run build

# 2. 再构建并启动桌面壳
cd ../src-tauri
cargo run
```

只想调界面布局时，可以 `cd desktop/ui && npm run dev` 在普通浏览器里看；此时**没有进程桥**，界面会显示「进程桥未接入」，这是预期行为，不是坏了。

## 目录

```
desktop/
├── README.md / README.en.md   本文件
├── src-tauri/                 Rust 壳：spawn Python、逐行转发进度、回传 exitCode/stdout/stderr/data
├── ui/                        React + Vite + Tailwind 前端
│   ├── src/components/        与设计系统对齐的基础组件
│   ├── src/pages/             两个页面：看什么 / 我的判断
│   ├── src/lib/               bridge（进程桥）、status-map（唯一判定点）、records（记录分组）
│   └── src/i18n/              界面文案表（当前只有中文）与术语对照表
└── tools/build_dev_data.py    生成本地回放用的 dev-data（不入库）
```

## 与仓库其他部分的关系

这个桌面壳只是把根目录 `phase0/` 的流水线搬到界面上，不新增判定口径、不复制状态词表。项目要做什么、不做什么，见[仓库根 README](../README.md)。
