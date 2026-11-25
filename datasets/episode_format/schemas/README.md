# JSON Schema

这里是 JSON Schema Draft 2020-12 的自包含文件，无远程 `$ref`。

| Schema | 对应文件 |
|---|---|
| `model_input` | 导出后交给模型的单题 JSON，严格白名单 |
| `archive_input` | 当前 r1 `inputs/<id>.json`，含 crop 和 support 状态 |
| `evaluation` | 当前 CAD-aligned、全部请求点有有效 3D 的单版本答案 |
| `prediction` / `batch_prediction` | 完整预测格式；缺点的模型失败仍由评分器计分母 |
| `split` | 开发清单，不能由文件名推断 train/test |

JSON Schema 检查字段与类型，不能单独检查 ID 是否重复、两端点集是否相同、normalisation 是否算对或路径是否越界；这些由 `tools/format_tools.py` 补充。JSON 解析器还会拒绝重复 key、NaN、Infinity 和溢出为非有限值的数。

工具内置的校验函数只实现本目录 schema 用到的关键字，不是通用 JSON Schema 引擎。遇到不支持的关键字会报错。编辑器和其他项目可以直接用完整 Draft 2020-12 实现读取这些 schema。

manifest 和 audit 暂未定义封闭 schema；工具只检查本配置必需的索引、版本和连接关系，允许保留来源/审查元数据。它们不得传入模型。
