"""Validate and render original study material separately from interview evidence."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import re


def load_learning(root):
    return json.loads((root / 'data/learning.json').read_text(encoding='utf-8'))


def validate_learning(data, questions, catalog):
    def require(condition, message):
        if not condition:
            raise ValueError('Learning: ' + message)

    def nonempty(value):
        return isinstance(value, str) and bool(value.strip())

    def strings(values, label):
        require(isinstance(values, list) and values and all(nonempty(v) for v in values), label)

    require(data['schema_version'] == 1, 'unsupported schema version')
    require(data['kind'] == '原创研习内容', 'invalid provenance')
    updated = dt.date.fromisoformat(data['updated'])
    require(updated <= dt.date.fromisoformat(catalog['curated_through']), 'future update')
    qids = {q['id'] for q in questions}
    for key, pattern in [('technical_sources', r'T\d{2,}'), ('guides', r'G\d{2,}'), ('labs', r'L\d{2,}')]:
        items = data[key]
        require(isinstance(items, list) and items, f'empty {key}')
        ids = [item['id'] for item in items]
        require(len(ids) == len(set(ids)), f'duplicate id in {key}')
        require(all(re.fullmatch(pattern, i) for i in ids), f'invalid id in {key}')
    tids = {s['id'] for s in data['technical_sources']}
    gids = {g['id'] for g in data['guides']}
    used_sources = set()
    for source in data['technical_sources']:
        require(source['url'].startswith('https://'), 'technical source must use HTTPS')
        require(nonempty(source['title']) and nonempty(source['supports']), 'missing technical source context')
        require(dt.date.fromisoformat(source['checked_on']) <= updated, 'future source check')
    for key in ('guides', 'labs'):
        slugs = [item['slug'] for item in data[key]]
        require(len(slugs) == len(set(slugs)), f'duplicate slug in {key}')
        require(all(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug) for slug in slugs), 'unsafe output slug')
        for item in data[key]:
            require(nonempty(item['title']), 'empty title')
            require(item['question_ids'] and set(item['question_ids']) <= qids, 'unknown related question')
            require(len(item['question_ids']) == len(set(item['question_ids'])), 'duplicate related question')
            if key == 'guides':
                require(nonempty(item['intro']) and nonempty(item['short_answer']), 'empty guide introduction')
                for field in ('key_points', 'pitfalls', 'drill'):
                    strings(item[field], f'empty {field}')
                require(item['reference_ids'] and set(item['reference_ids']) <= tids, 'unknown technical reference')
                require(len(item['reference_ids']) == len(set(item['reference_ids'])), 'duplicate technical reference')
                used_sources.update(item['reference_ids'])
            else:
                require(nonempty(item['scenario']), 'empty scenario')
                require(item['status'] == 'specification', 'unsupported lab execution status')
                require(item['guide_ids'] and set(item['guide_ids']) <= gids, 'unknown lab guide')
                for field in ('setup', 'inject', 'deliverables', 'checks'):
                    strings(item[field], f'empty lab {field}')
                require(item['rubric'], 'empty rubric')
                require(all(type(r['points']) is int and r['points'] > 0 and nonempty(r['dimension']) and nonempty(r['full_credit']) for r in item['rubric']), 'invalid rubric')
                require(sum(r['points'] for r in item['rubric']) == 10, 'rubric must total 10')
    require(used_sources == tids, 'unreferenced technical source')


def guide_path(guide):
    return f"learning/guides/{guide['slug']}.md"


def lab_path(lab):
    return f"learning/labs/{lab['slug']}.md"


def render_learning(data, qlink):
    """Return unwrapped views; caller adds the common generated-file banner."""
    views = {}
    guides = {g['id']: g for g in data['guides']}
    sources = {s['id']: s for s in data['technical_sources']}

    def bullets(values):
        return ['- ' + value for value in values]

    for guide in data['guides']:
        file = guide_path(guide)
        lines = [f"# {guide['id']} · {guide['title']}", '', '**内容类型：原创答题指南** · 技术资料核实日期见文末。', '', guide['intro'], '',
                 '关联题目：' + ' · '.join(qlink(file, qid) for qid in guide['question_ids']), '',
                 '## 先讲清楚', '', guide['short_answer'], '', '## 展开时需要说明', '']
        lines += bullets(guide['key_points'])
        lines += ['', '## 容易答偏的地方', ''] + bullets(guide['pitfalls'])
        lines += ['', '## 用证据检查回答', ''] + bullets(guide['drill'])
        linked = [lab for lab in data['labs'] if guide['id'] in lab['guide_ids']]
        if linked:
            lines += ['', '练习：' + ' · '.join(f"[{lab['id']} · {lab['title']}](../labs/{lab['slug']}.md)" for lab in linked)]
        lines += ['', '## 技术依据', '', '以下资料支持机制解释；回答组织、取舍建议和练习是编者设计。它们不能证明相关问题曾在某场面试出现。', '']
        for tid in guide['reference_ids']:
            source = sources[tid]
            lines += [f"- [{tid} · {source['title']}]({source['url']})：{source['supports']} 核实于 {source['checked_on']}。"]
        lines += ['', '[研习入口](../README.md) · [技术资料档案](../REFERENCES.md) · [项目复盘模板](../../templates/project-evidence.md)']
        views[file] = lines

    for lab in data['labs']:
        file = lab_path(lab)
        lines = [f"# {lab['id']} · {lab['title']}", '', '**内容类型：原创故障练习**。场景、数据与评分均为编者设计；不计入面经题数。', '', '**执行状态：练习规范（specification）**。本页提供要求与预期断言，尚未附可运行参考实现，也未宣称这些故障用例已经执行通过。', '', lab['scenario'], '',
                 '关联题目：' + ' · '.join(qlink(file, qid) for qid in lab['question_ids']), '',
                 '阅读准备：' + ' · '.join(f"[{gid} · {guides[gid]['title']}](../guides/{guides[gid]['slug']}.md)" for gid in lab['guide_ids']), '',
                 '## 给定条件', '']
        lines += bullets(lab['setup'])
        lines += ['', '## 注入故障', ''] + [f'{i}. {v}' for i, v in enumerate(lab['inject'], 1)]
        lines += ['', '## 提交什么', ''] + bullets(lab['deliverables'])
        lines += ['', '## 验证断言', ''] + bullets(lab['checks'])
        lines += ['', '## 自评参考', '', '每项有对应证据且满足描述可得满分；只有口述或证据不全得部分分，反例仍可触发则该项为 0。满分 10 分仅用于练习复盘，不代表招聘评分或生产验收。', '',
                  '| 维度 | 分值 | 满分依据 |', '| --- | --- | --- |']
        lines += [f"| {r['dimension']} | {r['points']} | {r['full_credit']} |" for r in lab['rubric']]
        lines += ['', '可以用本地桩服务、伪代码加测试表或可运行实现完成。注明采用的方式；未运行的断言应写“待验证”，不得填写虚构通过结果。', '',
                  '[研习入口](../README.md) · [复盘记录模板](../../templates/project-evidence.md)']
        views[file] = lines

    lines = ['# 原创研习：从回答到验证', '',
             f"{len(data['guides'])} 份答题指南 · {len(data['labs'])} 个故障练习 · [项目复盘模板](../templates/project-evidence.md)", '',
             '先选一道已有题，口述自己的方案；再读对应指南，用故障练习检查方案能否成立，最后记下证据与尚未验证的假设。', '',
             '这里的讲解、练习场景和评分是本项目独立撰写的学习材料。面经问题仍保留 Q 编号及 S 来源；指南用 G 编号，练习用 L 编号，技术依据用 T 编号。后者不增加“面试题”或“面经来源”数量。', '',
             '## 答题指南', '', '| 指南 | 关联题目 |', '| --- | --- |']
    file = 'learning/README.md'
    for guide in data['guides']:
        lines += [f"| [{guide['id']} · {guide['title']}](guides/{guide['slug']}.md) | " + ' · '.join(qlink(file, qid) for qid in guide['question_ids']) + ' |']
    lines += ['', '## 故障练习', '']
    lines += [f"- [{lab['id']} · {lab['title']}](labs/{lab['slug']}.md)：{lab['scenario']}" for lab in data['labs']]
    lines += ['', '## 一次练习怎么完成', '',
              '1. 先写目标、已知条件和需要澄清的假设，记录未看指南时的方案。',
              '2. 画出状态变化或数据流，指出最可能失效的位置。',
              '3. 对每条验证断言提供日志、测试输出或未验证说明，分析一个仍然存在的限制。',
              '4. 根据证据更新方案，用同一组输入复测；把前后差异写入复盘模板。', '',
              '[技术资料档案](REFERENCES.md) · [参考项目与致谢](../ACKNOWLEDGEMENTS.md) · [返回题库](../README.md)']
    views[file] = lines
    lines = ['# 技术资料档案', '', '这些一手技术资料用于解释机制，不能证明企业出过某道题。产品行为以所链接版本和当前官方文档为准；本项目的设计取舍与练习判据属于编者建议。', '']
    for source in data['technical_sources']:
        lines += [f"## {source['id']}", '', f"[{source['title']}]({source['url']})", '', source['supports'], '', f"核实日期：{source['checked_on']}。", '',
                  '用于：' + ' · '.join(f"[{g['id']}](guides/{g['slug']}.md)" for g in data['guides'] if source['id'] in g['reference_ids']), '']
    lines += ['[研习入口](README.md) · [面经来源](../SOURCES.md)']
    views['learning/REFERENCES.md'] = lines
    return views
