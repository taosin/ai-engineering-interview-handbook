"""Editorial coverage planning and mock interviews; never measures market frequency."""
from __future__ import annotations

from collections import Counter
import datetime as dt
import json
import re


def load_curriculum(root):
    return tuple(json.loads((root / 'data' / f'{name}.json').read_text(encoding='utf-8'))
                 for name in ('coverage', 'interviews'))


def validate_curriculum(coverage, interviews, questions, learning, catalog):
    def require(condition, message):
        if not condition:
            raise ValueError('Curriculum: ' + message)

    def nonempty(value):
        return isinstance(value, str) and bool(value.strip())

    def texts(values):
        return isinstance(values, list) and bool(values) and all(nonempty(v) for v in values)

    def refs(values, allowed, required=False):
        return (isinstance(values, list) and (bool(values) or not required)
                and all(isinstance(v, str) for v in values)
                and len(values) == len(set(values)) and set(values) <= allowed)

    roles = {r['id'] for r in catalog['roles']}
    qids = {q['id'] for q in questions}
    lids = {l['id'] for l in learning['labs']}
    for data, kind in ((coverage, '编者覆盖规划'), (interviews, '原创岗位模拟面试')):
        require(type(data.get('schema_version')) is int and data['schema_version'] == 1, 'unsupported schema')
        require(data.get('kind') == kind, 'invalid provenance')
        require(dt.date.fromisoformat(data['updated']) <= dt.date.fromisoformat(catalog['curated_through']), 'future update')
    require(set(coverage['levels']) == {'基础', '进阶', '综合'} and all(nonempty(v) for v in coverage['levels'].values()), 'invalid levels')
    modules = coverage['modules']
    require(isinstance(modules, list) and modules, 'empty modules')
    mids = {m['id'] for m in modules}
    require(len(mids) == len(modules), 'duplicate module')
    require(all(re.fullmatch(r'[a-z][a-z0-9-]*', m['id']) and nonempty(m['name']) for m in modules), 'invalid module')
    requirements = coverage['requirements']
    require(isinstance(requirements, list) and requirements, 'empty requirements')
    require(len({r['id'] for r in requirements}) == len(requirements), 'duplicate coverage id')
    pairs = [(r['role_id'], r['module_id']) for r in requirements]
    require(len(set(pairs)) == len(pairs) and set(pairs) == {(r, m) for r in roles for m in mids}, 'role/module matrix must be explicit and complete')
    for item in requirements:
        require(re.fullmatch(r'COV-\d{3}', item['id']), 'invalid coverage id')
        require(item['priority'] in {'核心', '拓展'} and item['target_level'] in coverage['levels'], 'invalid target')
        require(refs(item['required_types'], set(catalog['question_types']), True), 'invalid required types')
        require(refs(item['question_ids'], qids), 'invalid question reference')
        require(refs(item['lab_ids'], lids), 'invalid lab reference')
        require(nonempty(item['gap']), 'missing explicit gap')
    sessions = interviews['sessions']
    require(isinstance(sessions, list) and len(sessions) == len(roles), 'one mock per role required')
    require({s['role_id'] for s in sessions} == roles, 'missing mock role')
    require(len({s['id'] for s in sessions}) == len(sessions), 'duplicate mock id')
    all_blocks = set()
    for session in sessions:
        require(re.fullmatch(r'MOCK-[A-Z]+', session['id']) and nonempty(session['title']), 'invalid mock identity')
        blocks = session['blocks']
        require(isinstance(blocks, list) and len(blocks) >= 3, 'insufficient mock blocks')
        require(type(session['duration_minutes']) is int and session['duration_minutes'] > 0, 'invalid duration')
        require(all(type(b['minutes']) is int and b['minutes'] > 0 for b in blocks), 'invalid block minutes')
        require(sum(b['minutes'] for b in blocks) == session['duration_minutes'], 'duration mismatch')
        for b in blocks:
            require(re.fullmatch(r'[A-Z]+\d+', b['id']) and b['id'] not in all_blocks, 'invalid/duplicate block id')
            all_blocks.add(b['id'])
            require(all(nonempty(b[k]) for k in ('name', 'prompt', 'deliverable', 'follow_up')), 'incomplete mock prompt')
            require(texts(b['criteria']) and texts(b['red_flags']), 'missing review criteria')
            require(refs(b['question_ids'], qids, True) and refs(b['lab_ids'], lids), 'invalid mock reference')


def render_curriculum(coverage, interviews, questions, learning, catalog, answers, qlink, llink):
    roles = {r['id']: r['name'] for r in catalog['roles']}
    modules = {m['id']: m['name'] for m in coverage['modules']}
    question_map = {q['id']: q for q in questions}
    answer_map = {a['question_id']: a for a in answers['answers']}
    lab_map = {l['id']: l for l in learning['labs']}
    views = {}
    file = 'docs/coverage-matrix.md'
    lines = ['# 岗位与内容覆盖矩阵', '', f"核对日期：{coverage['updated']}。本表是编者准备规划，不是招聘要求调查、题目频率或能力评分。", '',
             '每个格子列出一组相关题作为检查入口，不表示它们涵盖模块全部知识。岗位选题与核心/拓展、目标难度均为编者判断；同一题可在多行出现，禁止相加当作独立题数。', '',
             '“目标层次”描述应准备到的程度，不是给所有关联题批量标难度。题型缺口按这些题的现有主要题型核对；同题可能涉及多种能力，缺口不等于该领域全库没有类似内容。逐题解析数由答案文件关联计算，指南不自动折算为逐题解析。', '',
             '| 目标层次 | 准备要求 |', '| --- | --- |']
    lines += [f'| {k} | {v} |' for k, v in coverage['levels'].items()]
    counts = Counter(q['question_type'] for q in questions)
    lines += ['', '## 当前全库分布', '', ' · '.join(f"{catalog['question_types'][k]} {counts[k]}" for k in catalog['question_types']), '',
              f"来源归纳题 {len(questions)} 道；逐题解析 {len(answer_map)} 道。这些数目不表示完整度百分比或读者通过率。", '']
    for role_id, role_name in roles.items():
        lines += [f'<a id="{role_id}"></a>', f'## {role_name}', '', '| 模块 / 优先级 / 目标层次 | 题目与逐题解析 | 目标题型 / 当前缺口 | 实践入口 |', '| --- | --- | --- | --- |']
        items = [r for r in coverage['requirements'] if r['role_id'] == role_id]
        for item in items:
            qids = item['question_ids']
            present = {question_map[q]['question_type'] for q in qids}
            missing = [catalog['question_types'][k] for k in item['required_types'] if k not in present]
            answered = [q for q in qids if q in answer_map]
            links = ' · '.join(qlink(file, q) for q in qids) or '待补题干'
            answer_links = ' · '.join(f"[{q} 解析](../learning/answers/{answer_map[q]['slug']}.md)" for q in answered) or '待补逐题解析'
            practical = ' · '.join(llink(file, lid) + ('（有实现）' if lab_map[lid]['status'] == 'reference-implementation' else '（规范）') for lid in item['lab_ids']) or '尚无对应 L 实验'
            target_types = '、'.join(catalog['question_types'][k] for k in item['required_types'])
            type_status = '缺：' + '、'.join(missing) if missing else '所列主要题型已出现；仍需审查深度'
            lines += [f"| {modules[item['module_id']]} / {item['priority']} / {item['target_level']} | {links}<br>解析 {len(answered)}/{len(qids)}：{answer_links} | {target_types}<br>{type_status} | {practical} |"]
        lines += ['', '具体待补内容：', '']
        lines += [f"- **{modules[item['module_id']]}**：{item['gap']}" for item in items]
        lines += ['', f'[进入本岗位模拟面试](../interviews/{role_id}/candidate.md)', '']
    lines += ['## 如何维护', '', '新增原帖问题仍走 Q/S 流程；原创问题留在模拟练习或新内容类型中。新增解析只提升对应题的讲解深度，不能消除整个模块的待补项。补齐某格后仍要检查反例、测试与证据；不设置“所有格子有题即完整”的自动标记。', '',
              '[逐题解析](../learning/answers/README.md) · [岗位模拟面试](../interviews/README.md) · [实施状态](completion-status.md)']
    views[file] = lines
    lines = ['# 四套岗位模拟面试', '', '每套 60 分钟，均为编者原创编排，不声称复现某公司一场面试。关联 Q 只指明练习知识点，新增条件、代码要求、追问与判据不归入原帖实问。', '',
             '建议两人配合：答题者先看候选人页，练习主持人另看复盘页。开源文件不能强制隐藏答案；已经看过判据的重复练习如实记为辅助复习。单人可录音计时后自查。', '',
             '本轮默认关键思路与编码独立完成，可查语法；如使用 AI 或他人帮助，记录帮助发生的时刻与内容。不把辅助完成冒充独立能力。时间不足可停在当前产物并复盘，不补写虚构完成。', '']
    for session in interviews['sessions']:
        role = session['role_id']
        lines += [f"- **{roles[role]}**：[{session['title']}]({role}/candidate.md) · [主持与复盘页]({role}/reviewer.md)"]
        candidate = f'interviews/{role}/candidate.md'
        reviewer = f'interviews/{role}/reviewer.md'
        common = [f"# {session['title']}", '', '**原创模拟面试**，不是企业真实试卷。岗位、时长与难度为编者练习建议。', '']
        c = common + [f"共 {session['duration_minutes']} 分钟。只记录实际完成内容；先作答，再读主持页。允许查语法，关键帮助需记为辅助。", '', '| 环节 | 分钟 |', '| --- | --- |']
        c += [f"| {b['name']} | {b['minutes']} |" for b in session['blocks']]
        c += ['']
        r = common + ['## 主持与记录', '', '不要提前给关键解法。到时记录已完成的产物、需要的提示、具体错误和证据；开放设计接受符合约束的替代方案。每个检查点记“有证据 / 部分证据 / 未体现 / 未观察”，不相加成招聘分数或六维自检档位。', '',
                      '提示是教学行为，不是失败羞辱；提示后保留独立与辅助部分的边界。遇到关键业务失败先指出风险，下一轮围绕一个产物修复。', '']
        for b in session['blocks']:
            c += [f"## {b['id']} · {b['name']}（{b['minutes']} 分钟）", '', b['prompt'], '', '**交付**：' + b['deliverable'], '']
            r += [f"## {b['id']} · {b['name']}（{b['minutes']} 分钟）", '', '**检查点**：', ''] + ['- ' + v for v in b['criteria']]
            r += ['', '**递进追问（编者设计）**：' + b['follow_up'], '', '**错误信号与后续核对**：', ''] + ['- ' + v for v in b['red_flags']]
            r += ['', '补课题：' + ' · '.join(qlink(reviewer, q) for q in b['question_ids']), '']
            if b['lab_ids']:
                r += ['验证练习：' + ' · '.join(llink(reviewer, lid) for lid in b['lab_ids']), '']
        c += ['[作答后复盘](reviewer.md) · [空白记录](../../templates/mock-interview-record.md) · [模拟面试入口](../README.md)']
        r += ['## 收尾', '', '选一个最影响正确性的缺口，写“错误观察 → 对应 Q/G/L → 下一次可检查产物”。仅有口述时不登记代码或实验通过；参考实验通过也不自动通过整个 M 阶段。', '',
              '[回到候选人页](candidate.md) · [空白记录](../../templates/mock-interview-record.md) · [逐题解析](../../learning/answers/README.md)']
        views[candidate] = c
        views[reviewer] = r
    lines += ['', '[空白记录模板](../templates/mock-interview-record.md) · [覆盖矩阵](../docs/coverage-matrix.md) · [逐题解析](../learning/answers/README.md) · [返回首页](../README.md)']
    views['interviews/README.md'] = lines
    return views
