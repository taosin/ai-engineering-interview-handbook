# 数据结构（题库 v2；研习 v1；成长路线 v1）

UTF-8 JSON 文件是题目、来源、分类、研习、成长、自检、逐题解析与模拟面试的内容源。`scripts/build.py` 生成 Markdown；`scripts/validate.py` 检查引用与局部结构；`scripts/build.py --check` 检查视图是否同步。`templates/` 中的 Markdown 和 CSV 模板直接编辑。

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

## learning.json

独立 schema v1，不改变 Q/S 题库结构或计数。顶层 `kind` 固定为“原创研习内容”，`updated` 表示本次内容更新时间。

| 数组 | 必需字段与含义 |
| --- | --- |
| technical_sources | T 编号、title、url、checked_on、supports；技术资料及所支持的具体机制 |
| guides | G 编号、slug、title、intro、question_ids、short_answer、key_points、pitfalls、drill、reference_ids |
| labs | L 编号、slug、title、status、scenario、question_ids、guide_ids、setup、inject、deliverables、checks、rubric |

指南的 `question_ids` 只能引用已有 Q 题，`reference_ids` 只能引用 T 技术资料。练习的 `guide_ids` 只能引用 G 指南。`status` 支持两种状态：

- `specification`：提供练习规范，没有可运行参考实现，禁止声明 `implementation`。当前四个练习均已附实现，保留此状态用于未来只有规范的新练习。
- `reference-implementation`：附可运行的本地参考实现，必须提供 `implementation` 对象。当前 L01–L04 均属于此类；状态表示存在实现，不代替实际执行记录或学习者能力验收。

`implementation` 仅含 `path`、`run_command`、`test_command`。`path` 是仓库根目录下 `examples/` 内已存在文件的相对路径，不得使用绝对路径、目录穿越或指向目录外的符号链接；命令是在仓库根目录运行的单行说明，由页面展示，数据校验与构建不会执行它们。CI 单独运行明确配置的标准库测试。`rubric` 的每项含 `dimension`、正整数 `points`、`full_credit`，合计 10 分。

文件路径从 slug 生成，不能用任意路径或目录穿越。ID 和同类型 slug 唯一，引用必须存在；技术资料须被至少一份指南引用，检查日期不得晚于内容更新时间。页面、题目与指南的双向链接以及首页数量由生成器维护。

技术资料不进入 S 面经来源统计；指南与练习不进入 Q 题数。编辑指导与真实面经的边界见[整理方法](../METHODOLOGY.md)。

## roadmap.json

独立 schema v1，`kind` 固定为“原创学习与成长规划”。阶段、投入时间、验收和复习规则都是编者建议，不是企业要求或研究结论。

| 字段 | 含义 |
| --- | --- |
| entries / start_body | 三类起点摘要，以及行为自测和分流正文 |
| through_project / assumptions / progression_rule | 贯穿项目、适用前提和证据推进规则 |
| milestones | M0 条件式补课与 M1–M6 主线；入门条件、步骤、产物、验收、回退、专注工时区间及引用 |
| milestones.acceptance.id | 稳定验收 ID（如 M4-C1），不可因重排数组而换号；测评建议可精确关联 |
| milestones.depends_on | 指向数组中更早的阶段；已有等价证据可免做重复学习，不表示免除依赖能力 |
| pace_modes | 每周投入小时和活动分钟数；活动合计必须与小时一致 |
| roles | 与 catalog 同 ID、同名称的岗位；这里维护项目交付点，catalog 继续维护精选题目 |
| roles.minimum_checkpoint | 本轮 M5 的最低交付点；还需满足主线 M5 的对照验收，其他交付点用于后续成长 |
| review_sections / sprint_body | 复习、回退、间隔回看和面试前两周的 Markdown 正文，由数据生成页面 |
| growth_levels | 可观察的成长能力、各岗位表现、下一步；不对应固定年限或职级 |
| resources | R 编号的研究与入门资料；记录精确链接、支持范围、局限和核实日期 |

`references` 中的 Q/G/L 必须存在，`resource_ids` 对应 R 学习资料。R 不进入 S 面经源或 T 研习技术资料的计数。M5 的岗位安排由 `roles` 生成链接，避免重复维护两份分支内容。里程碑、岗位交付点和总览中的工时与数量从结构化数据计算。

新增或修改自测/复习正文后，需人工核对行为门槛、日期含义和模板字段是否一致。CI 能检查结构、依赖、时间预算、引用与生成同步，不能证明路线对任意学习者有效，也不安排个人提醒。

## 本地筛选

```sh
python3 scripts/practice.py --role 'Agent 工程师' --type evaluation --limit 5
python3 scripts/practice.py --topic memory-context --sample 4 --seed 42
python3 scripts/practice.py --query SSE
```

相同数据、筛选条件与 seed 会得到相同抽样结果。不指定 sample 时按稳定题号顺序输出；脚本只读取本地题库，不访问模型或外部服务。

## assessment.json

独立 schema v1，内容类型为原创自检试用规则，不混入 Q/S 来源计数。`assessment_version`、`rubric_version` 记录规则版本；六个 `dimensions` 按 D1–D6 固定排序，每轴关联情境与实践两个任务，共 AT01–AT12。

情境包含两个明确改变约束的 `variants`，保留稳定 `exposure_key` 与可比组；实践包含基础断言和 `transfer` 的变化约束/回归/取舍断言。每条 `criterion` 有固定 ID、判据、关键失败标记及 `recommendation`，建议只引用已存在的 Q/G/L/M 和阶段验收 ID。

Python 校验内容引用后，从同一源生成 `assessment/manual.md` 与 `assessment/definition.json`。后者附源定义规范 JSON（UTF-8、键排序、无额外空格）的 SHA-256，以及由现有目录计算的可信 GitHub 导航链接；导航链接不参与评分规则哈希。JS 核心负责作答校验、派生档位、历史和个人备份导入，不读取导入文件声明的分数作为依据。个人记录与公开定义使用不同结构，不能将备份作为公开规则导入。


## answers.json

原创逐题解析独立保存，关联现有 question_id，不改变 Q/S 计数。每题包含短答、深入要点、追问及回答、错误反例、按证据判断的检查点和小练习；level 是编者难度建议。ARef 技术引用只支持机制解释，不证明原帖实际作答。通过 scripts/answers.py 校验和生成，原 Q 页面反向链接。

## coverage.json

schema v1、kind 为“编者覆盖规划”。modules 定义模块，requirements 显式列出每个岗位/模块组合、核心或拓展、目标层次、目标题型、相关 Q/L 及具体缺口。题型统计与逐题解析数从实际关联生成，不把指南或实验自动折算为题解，不生成完整度百分比。

## interviews.json

schema v1、kind 为“原创岗位模拟面试”。每个岗位一套，各环节有正整数分钟、题面、产物、关联 Q/L、主持检查点、追问和错误信号；分钟总和必须等于总时长。候选页不渲染主持追问与判据，但公开仓库不能保证答案未被提前看过。

新增模块用 scripts/curriculum.py 校验引用、角色覆盖、稳定编号、难度和时长，再统一生成覆盖矩阵及模拟页面。个人填过的记录模板与备份不进入数据文件。
