# CAPE RGB episode 数据格式

格式说明版本：`cape-rgb-episode-v0.1-draft`，2026-11-25 更新。整理自已实现的 Chair-AB preview-r1 与 ThreeClass v0.3 preview；这是开发接口说明，不是正式 benchmark 协议。

**一题就是：给一张示例图和图上的几个点，再给另一张图，要求输出后一张图中相同语义部位的三维坐标。** 模型输入没有 query 的二维点或三维答案。

## 先看这几份

| 文件 | 用途 |
|---|---|
| [FORMAT.md](FORMAT.md) | 字段、路径、点号、坐标、缺标及评分约定 |
| [examples/](examples/) | 一题完整虚构样例，可以直接读取；不含原数据集的图片或标注 |
| [schemas/](schemas/) | JSON Schema Draft 2020-12，供编辑器或数据工具使用 |
| [tools/format_tools.py](tools/format_tools.py) | 检查现有包、导出纯模型输入；仅用 Python 标准库 |
| [tests/test_format_tools.py](tests/test_format_tools.py) | 正常读取及错误输入测试 |

## 最小使用方式

在本目录下运行，Python 3.8+，无需 GPU 或额外依赖：

```bash
python3 tools/format_tools.py check examples
python3 tools/format_tools.py export examples /tmp/cape-inputs-example --split screened
python3 tools/format_tools.py check-inputs /tmp/cape-inputs-example
python3 tools/format_tools.py check-prediction examples examples/prediction.json
python3 -m unittest discover -s tests -v
```

导出目录必须尚不存在。模型只接收导出目录里的 JSON 和 RGB，不把整个数据包交给模型。导出目录是文件层面的隔离；运行进程还需限制工作目录/可读路径，它本身不是安全沙箱。

检查真实小包时将 `examples` 替换为包路径。这里的工具不评分、不改标签，也不修改原数据包。`check-prediction` 检查完整预测的格式和 ID，不代替评分器对缺点等失败情况的处理。

## 包内分工

```text
dataset-package/
  manifest.json                # 样本索引、坐标版本、开发状态；不给模型
  inputs/<sample_id>.json       # RGB 引用、support 点及裁剪声明
  inputs/images/*               # support/query RGB
  evaluation/<id>.<version>.json # query 答案；仅训练监督/独立评测端读取
  audit/<sample_id>.json        # 点名、来源、CAD、pose 等追溯信息；不给模型
  splits/*.json                # 明确的样本清单；不给模型
```

现有包还包含 `inspection/`、`CHECKSUMS.json`、评分工具和逐题复核记录。它们不是每题模型接口的一部分。本目录没有复制旧评分器，避免产生两个不同实现；当前评分行为见 FORMAT 第 7 节。

## 当前实现覆盖到哪

- 已实现：单张 support RGB + 有效 support 2D 点 + 单张 query RGB，K 可变、点号在每题内匿名，query 3D 答案独立存放。
- 当前兼容：椅子 r1（20 题/181 点）和三类 v0.3 preview（361 题/2598 点）。这些是格式兼容检查的来源包，不随本目录发布。A/B 图像不重叠、模板可重叠，属于开发分组，不是正式 train/test。
- 三维是 CAD 对齐代理、非米制。看图候选不等于三维已验证，也不能据此报告毫米误差或真实抓取精度。
- RGB-D、米制 XYZ、正式划分和最终评分协议尚未在这个格式配置中实现/定案。

原始数据接入协议继续负责保存原来源记录；本目录说明的是处理后供模型/评测使用的 episode。两层应分别保存，不反写原标注。
