# AI Engineering Interview Handbook

面向 **AI 全栈、Agent 工程师、LLM 应用开发、Agent Infra** 的中文面试题单。

首版收录 **48 道归纳题、8 个主题、12 个来源条目**。每道题保留稳定编号和来源引用；既可按主题阅读，也可使用 JSON 做个人复习工具。

> **资料范围说明**：首版检索于 **2026-10-08**，目标窗口为 **2026-04-08—2026-10-08**；可核实材料主要集中在 8—9 月。另保留一篇 6 月发布的 4—5 月社招复盘作为边界补充，不能确认其中每场面试均落在窗口内。仓库创建于 **2026-10-11**，不代表资料已检索至该日。
>
> 本项目整理的是公开个人面经中的问题，并非企业官方题库。问题经过编辑归纳，未收录原帖全文或商业题库答案；不做未经统计支持的“最高频”“必考”承诺。

## 题单目录

| 主题 | 编号 | 建议重点岗位 |
| --- | --- | --- |
| [Agent 架构与执行机制](questions/01-agent-architecture.md) | Q001—Q006 | AI 全栈、Agent 工程师 |
| [记忆与上下文](questions/02-memory-context.md) | Q007—Q012 | Agent 工程师、Agent Infra |
| [MCP、Skill 与权限](questions/03-tools-permissions.md) | Q013—Q018 | Agent 工程师、Agent Infra |
| [RAG 与知识质量](questions/04-rag-knowledge.md) | Q019—Q024 | LLM 应用开发、AI 全栈 |
| [故障处理与运行可靠性](questions/05-reliability.md) | Q025—Q030 | Agent 工程师、Agent Infra |
| [全栈交互与后端基础](questions/06-fullstack.md) | Q031—Q036 | AI 全栈、Agent 工程师 |
| [AI Coding、评测与交付](questions/07-ai-coding-evaluation.md) | Q037—Q042 | AI 全栈、Agent Infra |
| [现场编码](questions/08-coding.md) | Q043—Q048 | AI 全栈、Agent 工程师 |

## 从哪里开始

以下是本项目的复习建议，不代表全网统计频率。

- **AI 全栈**：先练全栈交互、AI Coding 和现场编码，再补 Agent 架构及 RAG。
- **Agent 工程师**：先练执行机制、记忆、工具权限和故障恢复，同时保留后端基础训练。
- **LLM 应用开发**：先练检索策略、知识质量和评测，结合实际业务解释方案取舍。
- **Agent Infra**：重点解释状态持久化、并发与隔离、性能诊断、运行恢复和评测环境。

项目回答可按“业务目标 → 约束条件 → 方案选择 → 实现细节 → 失败案例 → 验证结果”组织。准备一次效果不佳、一次执行失败、一次成本或延迟优化的真实经历。没有测量过的数据请明确说明，不要编造指标。

## 来源与局限

阅读 [来源索引](SOURCES.md) 和 [整理方法](METHODOLOGY.md)，了解日期口径、平台覆盖和边界材料。

本次可核实来源以牛客为主，辅以 LINUX DO；小红书部分链接受登录或失效影响，脉脉未找到满足本次条件的明确题源。因此不能把这份题单视为对全部社交平台或整个招聘市场的代表性统计。

仓库内“小红书”可能是应聘公司名称，发布平台以来源索引为准。

## 数据与使用

- [`data/questions.json`](data/questions.json)：稳定题号、题目、主题、岗位标签、来源编号。
- [`data/sources.json`](data/sources.json)：原帖链接、日期及口径、核实范围、备注。
- [`data/README.md`](data/README.md)：字段说明。

首版提供问题清单，不提供统一“标准答案”。参考回答、延伸练习如有新增，必须与有来源的面经问题明确区分。

## 参与贡献

欢迎补充原帖、修正日期、报告失效链接或提交原创参考回答。请先阅读 [贡献指南](CONTRIBUTING.md)，也可以 [提交 Issue](https://github.com/taosin/ai-engineering-interview-handbook/issues/new/choose)。

## 许可与署名

本仓库原创整理、结构化编排及代码（如有）采用 [MIT License](LICENSE)。外链文章、作者原文、商标及其他第三方内容仍归各自权利人所有，不因本仓库引用而变更许可。

如作者希望更正署名、调整引用或删除相关条目，请提交 Issue；不要在公开 Issue 中提供个人敏感信息。
