# 数据结构（schema v2）

三个 UTF-8 JSON 文件是题目、来源与阅读视图的内容源。`scripts/build.py` 生成 Markdown；`scripts/validate.py` 检查引用与局部结构；`scripts/build.py --check` 检查视图是否同步。

## questions.json

顶层是数组。原有字段保留，题号稳定。

| 字段 | 含义 |
| --- | --- |
| id | 稳定题号，例如 Q001，不因分类改变而重排 |
| topic | catalog 中的一个知识主题 |
| question | 改写归纳的一行题干，非逐字引述 |
| question_type | concept / design / debugging / project / evaluation / coding |
| roles | 逐题适用岗位，属于编者建议 |
| type | 来源性质；目前只能是“面经问题归纳”，与题型不同 |
| source_ids | 支持主问题的来源编号 |
| source_locators | source_id → 原帖章节或题号；键必须与 source_ids 一致 |
| temporal_scope | 检索范围内材料或边界补充；不保证实际面试日期已精确确认 |
| last_curated | 主问题内容或追问的整理日期 |
| metadata_updated | 分类、标签、定位等元数据的调整日期 |
| follow_ups | 可选数组；有来源的近邻问法，不增加题数 |

每个 follow_up 包含 `question`、`source_id`、`locator`、`origin`，其中 origin 固定为“来源支持的追问变体”。这不一定是同一次面试的追问。

## sources.json

顶层是数组。每个来源可支持多题；每题也可以引用多源。

| 字段 | 含义 |
| --- | --- |
| id / title / platform / url | 稳定来源号、标题、发布平台、原帖链接 |
| date_label / date_kind | 可读日期或范围，以及日期口径；date_label 不保证 ISO 格式 |
| date_evidence.raw_label | 原页面显示的日期或公开时间记录 |
| date_evidence.year_basis | 年份的实际证据或推定说明 |
| date_evidence.precision | day / range / month-day-year-inferred / historical-label（首版未保存原始时间） |
| interview_date | 明确的面试日期或 null；不能用发布日期填充 |
| published_at / edited_at | 部分新来源另有公开元数据时间；未知可缺省 |
| verification.status | historical / original / platform-index / search-index |
| verification.checked_on | 内容核实日期，必须与 last_checked 相同 |
| verification.evidence_url | 实际读到公开材料的位置，可能与原帖 URL 不同 |
| verification.note | 核实方法、具体阅读范围或限制 |
| notes / evidence / date_caveat | 来源局限、内容范围与日期说明 |
| reported_role / recruitment_type | 可选；原帖明确的岗位／招聘信息，未知应说明 |

历史条目的核实状态不因本轮重新生成文档而升级。来源号和题号不是公司、作者或独立面试数量。

## catalog.json

包含 schema 版本、首版与当前检索窗口、主题及稳定文件路径、题型名称、岗位路线和旧锚点兼容关系。岗位路线只维护精选题号；全部适用题由题目 roles 自动生成。

新增主题、题型或来源性质时，须同时调整校验规则和文档，不要通过随意新增字段绕过数据约束。

## 本地筛选

```sh
python3 scripts/practice.py --role 'Agent 工程师' --type evaluation --limit 5
python3 scripts/practice.py --topic memory-context --sample 4 --seed 42
python3 scripts/practice.py --query SSE
```

相同数据、筛选条件与 seed 会得到相同抽样结果。不指定 sample 时按稳定题号顺序输出；脚本只读取本地题库，不访问模型或外部服务。
