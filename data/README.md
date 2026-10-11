# 数据字段

文件使用 UTF-8 编码，顶层均为 JSON 数组。

## questions.json

| 字段 | 含义 |
| --- | --- |
| id | 稳定题号，例如 Q001；删除后不复用 |
| topic | 主题标识，对应 questions 目录文件名 |
| question | 编辑归纳后的题目，不是逐字引述 |
| roles | 编者建议的适用岗位，不是原帖岗位事实 |
| source_ids | 来源编号数组，对应 sources.json |
| type | 当前均为“面经问题归纳” |
| temporal_scope | 仅 S03 支持的题目为“边界补充”，其他为“检索范围内材料”；不表示面试精确日期均已确认 |
| last_curated | 题目整理日期，不是面试日期 |

## sources.json

| 字段 | 含义 |
| --- | --- |
| id | 稳定来源编号，例如 S01 |
| title / platform / url | 来源标题、发布平台与原链接 |
| date_label | 可读日期或月份范围，不保证为 ISO 日期 |
| date_kind | 面试日期、发布时间、编辑时间或范围 |
| notes | 来源特有局限 |
| last_checked | 本次资料检索检查日期 |
| evidence | 内容核实范围，不是对面试真实性的认证 |
| date_caveat | 年份判断的统一说明 |
