# 字段与处理约定

这份说明记录当前 RGB 开发包的实现。`cape-rgb-episode-v0.1-draft` 是文档版本，不强行给已归档 JSON 增加字段。未来破坏兼容的修改应另起版本，并保留转换记录。

## 1. 一题的身份与点号

`sample_id` 是题号，同题 input、evaluation、audit 必须一致。文件名为 `<sample_id>.json`；答案文件额外带坐标版本。ID 只使用字母、数字、下划线和连字符。

每个 support 点有一个正整数 `id`。它只在这一题内有意义：support 的 `id=3` 与 query 答案/预测的 `id=3` 指向同一个语义点；另一题的 3 不保证相同。列表顺序可不同，必须按 ID 对齐。重复 ID 非法。不能通过全库固定点号暗中提供类别或点名。

当前 RGB 结构配置要求 K≥5，K 不是固定的 10；通用模型输入 schema 允许 K≥1。验证工具 `check` 按当前配置要求至少 5 点。support/query 应为不同字节图像；不同 CAD 模板不能证明不同实物身份。

## 2. 输入：存档版与模型版

| 字段 | 类型 | 含义 |
|---|---|---|
| `sample_id` | string | 题号 |
| `support.image` / `query.image` | string | 相对于当前 JSON 所在目录的图像路径，如 `images/example_support.png` |
| `support.size` / `query.size` | `[W,H]` | 当前输入图像宽、高，正整数 |
| `support.points` | array | 匿名请求点列表，含 `id,u,v` |
| `u,v` | number | 当前输入图像中的有限像素坐标；左上为原点，u 向右、v 向下 |

当前记录沿用原标注数值后进行 full→crop 换算，不额外减 1。输入域为 `0≤u<W, 0≤v<H`；这是连续像素坐标，不是 [0,1] 归一化坐标。不要在不同模块中自行增加/减去半个像素。若对接模块有不同像素中心约定，在适配器中明确转换。

存档版 `inputs/` 另外保存：

- `budget="gt_box_crop"`、`budget_declaration`：裁剪使用 GT 框及原→crop 变换。
- support 点的 `visible=true`、`raw_status=1`：当前已核配置只选该 support 自己原标注中 status-1、有限且 crop 内的点。status-1 的含义来自本数据源，不外推到其他数据源。

**交给模型的是白名单导出版本**：只保留上表字段，删除 budget、裁剪参数、visible/raw_status 等额外信息。模型版顶层只能有 `sample_id/support/query`，query 只能有 image/size。类别、点名、CAD、pose、query 的 2D/3D、query 有效点掩码、GT 中心/RMS 均不得加入。

兼容性提醒：现有题号如 `chair_A01` 带有类别词，导出工具为保持预测对账不改题号，因此不能宣称它已满足严格的类别盲输入。当前导出不提供独立 class 字段；若以后要求类别盲，应另做不含类别词的题号/文件名和评测映射，不能只删 class 字段。

路径不得是绝对路径、包含 `..`、指向目录外的软链接或远程 URL。工具会检查路径与内容哈希；图片实际解码和语义对应仍需另做 QA。

## 3. 裁剪记录

当前预算：GT bbox、正方形裁剪、padding=1.25、256×256 RGB，PIL 浮点 EXTENT/BILINEAR。该实现不是官方 cv2 affine 的逐位复现。裁剪框可超出原图边界。

当前存档结构有历史不对称性：`budget_declaration.crop` 本身是 support 裁剪参数，内部的 `query_crop` 才是 query 参数。两者都含 `box_float=[left,top,right,bottom]`、原裁剪 `size=[width,height]`、`scale_x/scale_y`、`rounding`。新版可选 `resample="PIL BILINEAR (not cv2.warpAffine)"`，旧版可省略；存在时校验器按这一实现声明检查，不接受不同重采样方式冒充同一配置。

```text
u_crop = (u_full - left) * scale_x
v_crop = (v_full - top)  * scale_y
scale_x = W_crop / (right-left)
scale_y = H_crop / (bottom-top)
```

support 二维由自身原 MAT 的完整精度坐标变换后四舍五入到 2 位小数。query 原生二维保留父包的原图坐标，不是 crop 坐标；可视化/二维评分时必须使用 query_crop 换算。缺原生二维不画假点。

## 4. 答案：evaluation

| 字段 | 当前取值/含义 |
|---|---|
| `sample_id` | 对应输入题号 |
| `coordinate_version` | 下节两个版本之一 |
| `unit` | `cad_normalised`，CAD 任意归一化尺度，非米/毫米 |
| `gt_kind` / `metric` | `cad_aligned` / `false` |
| `answers[].id` | 与 support 请求点一一对应，不能按列表位置猜 |
| `answers[].xyz_camera` | 3 个有限数，**存储的是未做逐题中心/RMS 归一化的相机坐标** |
| `annotation_valid_3d` | 该点三维标注是否有效；当前 r1 全部 true |
| `annotation_valid_2d` | 是否有可用原生 query 二维标注 |
| `query_2d_native` | 原图像素 `[u,v]`；缺标为 null |
| `query_2d_origin` | `native_annotation` 或 `missing`，与上两字段一致 |
| `visible_in_rgb` / `present_on_instance` | true / false / null；null 是未知，不能当 false |
| `normalisation` | 当前坐标版本、当前有效点集的 center、rms、n_valid |

`normalisation` 保留已有拼写。XYZ 保留 6 位小数，元数据容差为 2e-6；必须从**本版本实际写入的 XYZ**计算中心和 RMS，不能从另一个版本复制中心。当前配置要求所有请求点有有效 3D，工具明确拒绝超出该配置的无效 3D；以后若支持缺 3D 要另定 mask 契约。

JSON 禁止 NaN、Infinity、重复对象 key。缺二维以 null 表示，不用 [0,0]；缺三维不造 [0,0,0]。三维有效、可见性未知的点不因此取消三维评分。

## 5. 两种三维坐标版本

| 版本 | 说明 |
|---|---|
| `pascal_source_pretheta_v1` | 官方投影流程的中间相机坐标，y 向上，图像 roll 在后续二维投影中使用 |
| `image_camera_cv_candidate_v1` | x 向右、y 向下、z 向前，已纳入图像 roll；当前包临时默认 |

采用列向量，theta 单位为度，Rz 是右手系 z 轴旋转：

```text
Y_source = R (X - C)
Y_cv     = diag(1,-1,-1) Rz(theta) Y_source
Y_source = Rz(theta)^T diag(1,-1,-1) Y_cv
```

不是只翻转 y/z；必须使用该观察记录真实的 theta，不能默认为 0。模型输出必须声明坐标版本，评测选择的版本与预测不一致时拒绝。`candidate` 表明协议仍待定，不代表它是 canonical 物体坐标。

## 6. manifest、split、audit

`manifest.json` 记录 dataset/version/status/n_samples、coordinate_versions、provisional_defaults 和 samples。samples 中的 class、template、审查信息仅用于管理。`splits/<name>.json` 为 `{name,frozen,members:[sample_id,...]}`，成员不重复且都在 manifest 内。

split 可选 `note` 为说明文字，不能用它替代 members 或逐题审查状态。

当前 A/B 是开发侧，不等于训练/测试划分。`screened` 只说明完成 agent 看图且未发现明显问题，不代表人审、三维 GT 验证或正式测试集。

**兼容旧字段**：r1 manifest 的 samples[].status 仍有 `not_reviewed` 占位，但实际记录在 `agent_review_status` 和版本化逐题 CSV。读取时以后两者为准，不把旧占位当成当前结论；本次没有反写旧包。

三类 v0.3 的 `samples[].status` 与 `agent_review_status` 已同步；读取具体包时仍须核查版本，不把 r1 的旧字段兼容说明外推为所有版本都不一致。针对性用户反馈可单独存为 overlay，不代表整题人审通过。

audit 保存原图/原标注引用、SHA256、object_index、点号→点名、CAD/template、theta 和选择规则。audit 不进模型。来源许可与身份核查由数据卡记录；格式检查不证明标签语义或来源许可正确。

## 7. 预测与现有评分行为

单题预测：`{sample_id, coordinate_version, points:[{id,xyz:[x,y,z]}]}`，可选 `unit="scale_free"` 或 `"cad_normalised"`；批量为 `{predictions:[单题预测,...]}`。本目录示例和 schema 要求有限数。完整预测点集必须与 support 请求集合一致。

现有结构评分实现：对有效 GT 集合分别中心化预测和 GT、分别除以各自 RMS，**不做旋转、反射、点重配或对称等价对齐**：

```text
c = mean_i(X_i)
r = sqrt(mean_i(||X_i-c||²))
X'_i = (X_i-c)/r
d_i = ||prediction'_i-GT'_i||
```

- MPJPE：d_i 的均值，单位为 RMS 相对单位；失败题不填有限 MPJPE，单列成功/失败数。
- PCK：严格 `d_i < t`，当前 t=0.05/0.1/0.2。
- AUC@0.2：200 个 `linspace(1e-6,0.2,200)` 阈值的 PCK 算术均值，是当前离散实现。
- 每题先平均；跨题报告 query 等权，并另报逐类与类别等权，不能混用分母。
- 缺题、缺点、零 RMS 和历史兼容输入中的非有限预测记失败，PCK/AUC=0，保留分母。标准 JSON 导出不得写 NaN；这是严格接口与旧评分器失败路径的区别。
- 重复 ID、未知 ID、错误维度、错误版本、所选清单外样本属于格式错误，拒绝评分。

**调用时显式指定 `--split screened`**。r1 `scoring_cli.py` 实际参数默认 `dev_all`，虽然其帮助文字写 screened；r1 两清单恰好相同；后续三类 v0.3 已修为默认 screened，其 screened 与 dev_all 不同。不要依赖旧帮助文字。这里的格式工具不复制或改变评分器。

## 8. 校验边界与扩展

JSON Schema 检查单文件字段类型；tools 另查唯一 ID、两侧同图字节、路径、跨文件点集、版本、center/RMS、split 成员。工具没有重跑原始 MAT/pose 转换，没有自动视觉审查、图片解码、隐藏三维精度或实物身份验证。

现有样例是纯虚构的 1 题/5 点，不是新增研究数据。未来加入 RGB-D、不同单位、不同 GT 类型、缺 3D mask、米制输出或新的裁剪预算时，先定义对应配置及版本，再扩 schema 和测试，不能用当前配置悄悄容纳不同含义。
