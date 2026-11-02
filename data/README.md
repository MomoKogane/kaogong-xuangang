# data 目录说明

- `manifest.toml`：声明每个数据文件属于哪场考试、哪一年、什么分数制式。相对路径以项目根目录为准。
- `incoming/positions/`：放当年岗位表（`.xlsx` / `.xlsm` / `.xls` / `.csv`）。
- `incoming/history/`：放往年进面分数线（民间整理也可以，同样支持 `.xls`）。
- `sample/`：内置仿真数据，含国考与广东省考两套，可以直接跑演示。
- `manual_links.csv`：人工岗位对应表，修正自动匹配错误；优先级最高。
- `imported/`：网页界面上传的文件暂存目录（自动生成，不建议手工编辑）。

真实数据文件不要提交到公开仓库（`.gitignore` 已忽略 `incoming/` 与 `imported/`）。
