# 设计说明

## 1. 模块地图

```
xuangang/
├─ cli.py             命令：init / doctor / import / run / links / serve
├─ config.py          配置与预设加载（包内默认 + config/ 覆盖）
├─ models.py          dataclass：Position / ScoreRecord / Profile / Link / MatchOutcome / Evaluation
├─ pipeline.py        一次分析的编排：读取 → 对应 → 判定 → 评分 → 报告
├─ scoring.py         历史分统计、预测、分档、推荐指数
├─ ingest/
│  ├─ excel.py        读 xlsx/csv，按 sheet 输出字符串二维表（含合并单元格处理）
│  ├─ columns.py      列别名匹配与表头探测
│  ├─ positions.py    岗位表 → Position
│  ├─ history.py      分数线表 → ScoreRecord（民间表容错）
│  ├─ inspect.py      上传后的自动识别（表头/年份/分数制式/列映射）
│  ├─ majors.py       专业目录与专业匹配
│  └─ values.py       全角/分数/人数/比例等清洗原语
├─ rules/
│  ├─ education.py    学历 + 学位
│  ├─ politics.py     政治面貌
│  ├─ ethnicity.py    民族
│  ├─ fresh.py        应届身份
│  ├─ grassroots.py   基层年限 + 服务基层项目
│  ├─ certs.py        执业资格证书
│  ├─ extras.py       户籍/性别/年龄/院校/特殊身份 + 软提醒
│  ├─ notes.py        从备注抽取附加要求的正则规则
│  └─ composite.py    汇总成符合/存疑/不符合
├─ match/
│  ├─ identity.py     实体键归一与相似度
│  ├─ linker.py       分数线 → 岗位的分层匹配
│  └─ overrides.py    人工对应表
├─ report/
│  ├─ common.py       报告共用派生文本与 JSON payload
│  ├─ csv_output.py   标准化 CSV 输出
│  ├─ excel_report.py 9 个 sheet 的 xlsx
│  ├─ html_report.py  自包含 HTML（内联数据与脚本）
│  └─ text_report.py  终端摘要
├─ server.py          标准库 HTTP 服务（仅 127.0.0.1）：上传即识别、一键分析、下载报告
└─ web/               index.html（三步上传+条件+结果）与 report.html（报告模板）
```

## 2. 数据流

```
岗位表 xlsx/csv ──> read_table ──> 表头探测 ──> Position ──┐
                                                          ├─> 规则判定 ──> MatchOutcome
分数线 xlsx/csv ──> read_table ──> 表头探测 ──> ScoreRecord ┴─> 实体匹配 ──> Link
                                                                    │
                                                     accepted 链接 ──┴─> 历史分 ──> Evaluation
                                                                                │
                          ReportRow（岗位 + 判定 + 评分） ──> xlsx / html / txt / csv
```

## 3. 判定规则的三态

| 结果 | 含义 | 例子 |
|---|---|---|
| 符合 | 所有已解析的硬条件都满足 | 学历、专业、政治面貌、应届、基层、证书、户籍、性别都通过 |
| 存疑 | 有条件无法从表里自动判定 | 专业表述含糊、备注提到证书但识别不出具体证书、学历只写「本科」而考生学历更高 |
| 不符合 | 明确违反硬条件 | 学历低于要求、专业不在要求范围、政治面貌不符、缺证书、限男性而考生为女 |

软条件（最低服务年限、经常出差、体能测评等）只作为提醒，不淘汰岗位。

## 4. 评分

```
预测进面分 = Σ(权重 × 每年最低进面分) / Σ权重     权重默认 0.5 / 0.3 / 0.2
分档       = 预估分 - 预测分 ≥10 保；≥4 稳；≥0 冲；<0 风险
推荐指数   = 45×适配度 + 20×(1-热度分位) + 15×招录容量
           + 10×意向地区 + 10×竞争壁垒
```

- 热度分位：该岗位当年最低进面分在当年所有岗位中的相对位置，跨年可比，缓解试卷难度波动。
- 意向地区：个人条件里的 `preferred_regions`（逗号分隔的城市/省份关键词），以及勾选 `prefer_hometown` 时自动加入户籍/生源省份；命中 1 分，未命中 0 分，没设置偏好给中性 0.5。
- 竞争壁垒：岗位限制对符合条件者形成的壁垒，按维度加权（性别/民族/特殊身份 1.0，户籍/基层项目 0.8，证书 0.6，政治面貌/应届 0.5，专业 0.4，学历 0.3，学位 0.2），归一化到 0~1；「不限」不算壁垒。
- 权重与阈值：`config/scoring.toml` 可覆盖。

## 5. 扩展点

- **新省份**：复制一份 `resources/presets/*.toml`，写列别名，必要时 `extends = "shengkao_generic"`。
- **新证书**：在 `resources/certs.toml` 加 `[[cert]]`（id/name/aliases/levels）。
- **新备注规则**：在 `config/notes_patterns.toml` 加 `[[rule]]`（dimension / kind / pattern / group）。
- **壁垒权重**：`config/scoring.toml` 的 `[barrier]` 表，维度名与判定结果一致。
- **专业目录**：`--major-catalog 文件.xlsx`，或用 `scripts/build_major_catalog.py` 重新生成内置目录。
- **报告列**：`report/excel_report.py` 的 `BASE_COLUMNS` 与 `report/common.py` 的 `row_payload`。
