"""Validate public assessment references and generate its shared reading assets."""
from __future__ import annotations

import hashlib
import json
import re


def load_assessment(root):
    return json.loads((root / 'data/assessment.json').read_text(encoding='utf-8'))


def definition_snapshot(data, questions=None, learning=None, roadmap=None, catalog=None):
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    snapshot = {**data, 'content_hash': hashlib.sha256(canonical.encode('utf-8')).hexdigest()}
    if questions is not None:
        base = 'https://github.com/taosin/ai-engineering-interview-handbook/blob/main/'
        topics = {t['id']: t['file'] for t in catalog['topics']}
        urls = {q['id']: base + topics[q['topic']] + '#' + q['id'].lower() for q in questions}
        for key, directory in (('guides', 'guides'), ('labs', 'labs')):
            for item in learning[key]:
                urls[item['id']] = base + f"learning/{directory}/{item['slug']}.md"
        for milestone in roadmap['milestones']:
            for item in [milestone, *milestone['acceptance']]:
                urls[item['id']] = base + 'roadmap/milestones.md#' + item['id'].lower()
        snapshot['reference_urls'] = urls
    return snapshot


def validate_assessment(data, questions, learning, roadmap, catalog):
    def require(condition, message):
        if not condition:
            raise ValueError('Assessment: ' + message)

    def text(value):
        return isinstance(value, str) and bool(value.strip())

    require(type(data.get('schema_version')) is int and data['schema_version'] == 1, 'unsupported schema')
    require(data.get('status') == 'self_check_trial', 'must identify trial status')
    for field in ('assessment_version', 'rubric_version'):
        require(text(data.get(field)) and re.fullmatch(r'\d+\.\d+\.\d+', data[field]), f'invalid {field}')
    require('content_hash' not in data, 'content hash is generated, not authored')
    roles = data.get('roles')
    require(isinstance(roles, list) and len(roles) == len(set(roles))
            and set(roles) == {r['id'] for r in catalog['roles']}, 'roles must match catalog')
    dimensions = data.get('dimensions')
    require(isinstance(dimensions, list) and [d.get('id') for d in dimensions] == [f'D{i}' for i in range(1,7)],
            'six dimensions must keep a fixed order')
    priorities = data.get('role_priorities')
    require(isinstance(priorities, dict) and set(priorities) == set(roles), 'role priorities must cover all roles')
    for order in priorities.values():
        require(isinstance(order, list) and len(order) == 6 and set(order) == {d['id'] for d in dimensions},
                'each role priority must contain all dimensions once')
    tasks = data.get('tasks')
    require(isinstance(tasks, list) and len(tasks) == 12, 'twelve original tasks are required')
    task_map = {task.get('id'): task for task in tasks}
    require(set(task_map) == {f'AT{i:02}' for i in range(1,13)}, 'task IDs must be unique AT01–AT12')
    require(all(text(task.get('task_version')) for task in tasks), 'every task needs a version')
    assigned = []
    criteria = []
    exposure_keys = []
    for dimension in dimensions:
        require(text(dimension.get('name')), 'missing dimension name')
        for field in ('scenario_task_id', 'practice_task_id'):
            require(dimension.get(field) in task_map, 'unknown dimension task')
            assigned.append(dimension[field])
        scenario = task_map[dimension['scenario_task_id']]
        practice = task_map[dimension['practice_task_id']]
        variants = scenario.get('variants')
        require(isinstance(variants, list) and len(variants) == 2, 'scenario needs two declared variants')
        require(len({variant.get('id') for variant in variants}) == 2, 'duplicate variant')
        for variant in variants:
            for field in ('id', 'exposure_key', 'comparison_group', 'prompt'):
                require(text(variant.get(field)), f'missing variant {field}')
            exposure_keys.append(variant['exposure_key'])
            require(isinstance(variant.get('criteria'), list) and variant['criteria'], 'empty scenario criteria')
            criteria.extend(variant['criteria'])
        require(isinstance(practice.get('criteria'), list) and practice['criteria'], 'empty practice criteria')
        transfer = practice.get('transfer')
        require(isinstance(transfer, dict) and text(transfer.get('constraint'))
                and isinstance(transfer.get('criteria'), list) and transfer['criteria'], 'missing transfer conditions')
        criteria.extend(practice['criteria'])
        criteria.extend(transfer['criteria'])
    require(len(set(assigned)) == 12, 'each task must belong to exactly one dimension')
    require(len(set(exposure_keys)) == 12, 'each variant needs a distinct exposure identity')
    known = {
        'question_ids': {q['id'] for q in questions},
        'guide_ids': {g['id'] for g in learning['guides']},
        'lab_ids': {lab['id'] for lab in learning['labs']},
        'milestone_ids': {m['id'] for m in roadmap['milestones']},
        'acceptance_ids': {a['id'] for m in roadmap['milestones'] for a in m['acceptance']},
    }
    ids = []
    for criterion in criteria:
        cid = criterion.get('id')
        require(text(cid) and re.fullmatch(r'AT\d{2}-[A-Za-z0-9-]+', cid), 'invalid criterion ID')
        ids.append(cid)
        require(text(criterion.get('label')) and text(criterion.get('explanation')), f'{cid}: missing criterion context')
        require(type(criterion.get('critical')) is bool, f'{cid}: critical must be boolean')
        kind = criterion.get('input_type')
        require(kind in {'choice', 'number', 'text', 'self'}, f'{cid}: unsupported input type')
        if kind == 'choice':
            options = criterion.get('options')
            require(isinstance(options, list) and len(options) >= 2
                    and all(isinstance(o, dict) and text(o.get('value')) and text(o.get('label')) for o in options),
                    f'{cid}: missing answer options')
            require(len({o['value'] for o in options}) == len(options)
                    and criterion.get('expected') in {o['value'] for o in options}, f'{cid}: invalid expected choice')
        elif kind == 'number':
            require(type(criterion.get('expected')) in (int, float), f'{cid}: expected must be numeric')
        elif kind == 'text':
            require(text(criterion.get('expected')), f'{cid}: expected text missing')
        recommendation = criterion.get('recommendation')
        require(isinstance(recommendation, dict), f'{cid}: missing recommendation')
        for field in ('reason', 'action', 'deliverable'):
            require(text(recommendation.get(field)), f'{cid}: missing {field}')
        for field, allowed in known.items():
            values = recommendation.get(field)
            require(isinstance(values, list) and all(text(v) for v in values)
                    and len(values) == len(set(values)) and set(values) <= allowed, f'{cid}: invalid {field}')
        require(all(a.split('-')[0] in recommendation['milestone_ids'] for a in recommendation['acceptance_ids']),
                f'{cid}: acceptance must belong to referenced milestone')
    require(len(ids) == len(set(ids)), 'duplicate criterion ID')


def render_assessment(data):
    """Handbook view from the exact public rules used by the interactive client."""
    tasks = {t['id']: t for t in data['tasks']}
    lines = ['# 六维任务自检 · 手工版', '',
             f"规则版本：{data['assessment_version']} · 自检试用版，尚未完成真实用户试评。", '',
             '[打开交互自检](https://privacy.iamtaoxin.com/ai-engineering-interview-handbook/) · '
             '[本地运行与记录说明](README.md) · [设计依据](../docs/assessment-design.md)', '',
             '这是原创学习任务，不增加面经题数。档位是自行记录、未独立核验的任务结果，不能认证整个领域或自动通过 M 阶段。', '',
             '先选一个领域和未看解答的变式，独立记录情境回答，再填写实践与变式证据。'
             '实践未运行应明确写出；不要仅填写“通过”。先保存完整尝试，再查看答案。', '',
             '规则：基础必要项全过为 1；加上实践必要项与具体运行记录为 2；'
             '再满足改变约束、原用例回归及取舍证据为 3。基础失败为 0；未完成为未测。'
             '辅助完成或已暴露变式仅作练习；最新完整有效记录可以降档，不取历史最高分。', '',
             '基础通过后，基础实践或变式中任一关键断言失败，均会阻止二档和三档，本次最多保留 1。'
             '没有关键失败且基础与实践必要条件全过时，变式未运行或非关键条件未满足可以保留 2。'
             '未运行表示缺口，不是通过，也不等同于已观察到关键失败。', '',
             '以下折叠区包含参考要点。已经看过某变式解答，再做该变式时必须声明为练习；'
             '实践和改变约束后的实践共用本领域的核心解法，查看其中任一参考区后，本领域 A/B 均按已暴露处理。'
             '此前已保存的首次完整独立记录不倒改；此后的同题重做只作练习。'
             '手工版不能自动记录展开行为，请自行保留暴露记录。开源页面不能阻止清空记录或不实填报。', '']

    def render_criteria(items):
        result = []
        for item in items:
            result += [f"- **{item['id']}**：{item['label']}" + ('（关键断言）' if item['critical'] else '')]
            options = item.get('options', [])
            for option in options:
                result.append('  - ' + (str(option.get('label', option)) if isinstance(option, dict) else str(option)))
        return result

    def render_practice_answers(items, dimension_id):
        result = ['', '<details>',
                  f'<summary>保存完整作答后再展开预期与判断准则（{dimension_id} 的 A/B 此后均按已暴露处理）</summary>', '',
                  '**展开前先保存完整尝试。** 以下是共享实践的参考要点；展开后请记录本领域 A/B 均已暴露，'
                  '不能将之后重复完成的任务再记作独立复测。', '',
                  '可计算项核对本人实际填报的观测值；开放项按判据、本人解释和证据逐项自检。'
                  '答案或字段符合要求不证明代码实际运行，也不代替证据归属和真实性核验。', '']
        for item in items:
            if item['input_type'] == 'self':
                expected = '开放自检：按上述必要判据判断满足、未满足或无法确认，并保留具体理由与证据。'
            else:
                value = item['expected']
                if item['input_type'] == 'choice':
                    label = next(option['label'] for option in item['options'] if option['value'] == value)
                    expected = f'预期观测：{label}（`{value}`）。'
                else:
                    expected = f'预期观测：`{json.dumps(value, ensure_ascii=False)}`。'
            result += [f"- **{item['id']}**：{expected}{item['explanation']}"]
        return result + ['', '</details>', '']

    for dimension in data['dimensions']:
        scenario = tasks[dimension['scenario_task_id']]
        practice = tasks[dimension['practice_task_id']]
        lines += [f"<a id=\"{dimension['id'].lower()}\"></a>", f"## {dimension['id']} · {dimension['name']}", '']
        for variant in scenario['variants']:
            lines += [f"### {scenario['id']} · 情境 {variant['id']}", '', variant['prompt'], '']
            lines += render_criteria(variant['criteria'])
            lines += ['', '<details>', '<summary>作答后再展开参考要点（该变式此后按练习记录）</summary>', '']
            for criterion in variant['criteria']:
                expected = json.dumps(criterion.get('expected'), ensure_ascii=False)
                lines += [f"- {criterion['id']}：`{expected}`。{criterion['explanation']}"]
            lines += ['', '</details>', '']
        lines += [f"### {practice['id']} · 实践", '', str(practice.get('prompt', practice.get('title', '按下列必要项提交实践记录。'))), '']
        lines += render_criteria(practice['criteria'])
        lines += render_practice_answers(practice['criteria'], dimension['id'])
        lines += ['', '**改变约束后的实践**：' + practice['transfer']['constraint'], '']
        lines += render_criteria(practice['transfer']['criteria'])
        lines += render_practice_answers(practice['transfer']['criteria'], dimension['id'])
        lines += ['', '每项证据记录输入/条件、预期与实际、是否运行、定位与摘录、日期/环境/版本及本人解释；'
                  '解释判断是本人记录，格式检查不等于真实性核验。', '']
    return {'assessment/manual.md': lines}
