# 真实数据适配清单

拿到「27 国考岗位表 + 26 国考分数线」后按这个顺序走一遍；省考同理。

## 零、最省事的路径（网页端，推荐）

1. 双击 `start.cmd`，浏览器自动打开。
2. 上传岗位表（支持 `.xlsx / .xls / .csv`）→ 看识别结果（sheet、表头行、行数、命中的列）。
3. 上传分数线 → 年份和满分自动识别，识别错了在文件旁改。
4. 填条件 → 开始筛选 → 下载报告。

不需要写 manifest，也不需要编辑 config；浏览器会记住条件。识别结果不放心时，再按下面的命令行步骤细查。

## 一、国考（第一批真实数据）

1. **建目录**：`run.cmd init`，把岗位表和分数线分别放进 `data/incoming/positions/`、`data/incoming/history/`。
2. **看列映射**：
   ```bat
   run.cmd import --inspect data\incoming\positions
   run.cmd import --inspect data\incoming\history --kind history
   ```
   确认「部门名称 / 职位名称 / 职位代码 / 专业 / 学历 / 最低进面分」都命中了；国家公务员职位表可能拆成「中央党群机关、中央国家行政机关、省级以下直属机构、参公单位」多个文件或 sheet，全部放进来即可。
3. **写 manifest**：每个分数线文件写 `year`、`scale = 200`、`kind = 笔试最低进面分`；岗位表写 `year = 2027`。
4. **填个人条件**：`config/bob.toml`，专业建议同时填 `major_code`，并确认 `estimated_score` 与 `score_scale`。
5. **首次运行**：
   ```bat
   run.cmd run --config config\bob.toml --positions data\incoming\positions --history data\incoming\history --out out\2027
   ```
6. **看四个地方**：
   - `out/2027/issues.csv`：有没有 error（整表读不出）或大量 warn（分数/人数解析失败）。
   - `out/2027/links_review.csv`：待人工核对的分数线对应；用 `data/manual_links.csv` 修正后重跑。
   - `out/2027/links_unmatched.csv`：历史中找不到今年岗位的记录（岗位取消/改名），确认是否要人工指向新岗位。
   - `out/2027/report.html` 的「数据质量」和「匹配链路」。
7. **沉淀预设**：把 `import --inspect` 打印的 `[positions.fields]` / `[history.fields]` 片段贴进 `config/presets/guokao.toml`，下次换年份也不用再改代码。
8. **回归**：把这次遇到的特殊写法补成 `tests/` 里的用例，避免以后改坏。

## 二、省考

1. **选预设**：广东 / 江苏 / 山东已内置；其他省份先用 `shengkao_generic`。
2. **指定考试与省份**：
   ```bat
   run.cmd run --config config\bob.toml --positions ... --history ... ^
     --preset guangdong --exam shengkao --province 广东省 --year 2026 ^
     --history-year 2025 --history-scale 300
   ```
3. **专业目录**：省考通常有本省专业指导目录，用 `--major-catalog 目录.xlsx` 导入；确认表头含「专业名称 / 专业代码 / 专业类 / 门类」之类。
4. **分数制式**：广东等 300 分制，务必在 manifest 或 `--history-scale` 里写死；省考还有 150/200 分制。
5. **学历表述**：「本科以上」「研究生」「仅限本科」等会按解析结果判定；不确定的会标存疑。
6. **户籍/民族/性别/服务年限**：省考备注里这类限制更多，跑完先看「存疑核对」页。

## 三、建议的检查命令

```bat
:: 环境与依赖
run.cmd doctor

:: 只看列映射，不写文件
run.cmd import --inspect <文件> --kind positions
run.cmd import --inspect <文件> --kind history

:: 看某次运行的待核对匹配
run.cmd links --out out\2027 --limit 30
```

## 四、人工修正模板

```csv
history_source,history_year,dept,post_name,position_id,action,note
2026国考进面分数线.xlsx,2026,国家税务总局广东省税务局,一级行政执法员（一）,2027-guokao-全国-100110001001,link,岗位合并，人工指向
2026国考进面分数线.xlsx,2026,某已撤销单位,某已撤销岗位,,ignore,岗位取消
```

改完重跑 `run`，人工对应优先于自动匹配。
