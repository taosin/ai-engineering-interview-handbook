"""Validate and render the original learning roadmap, without scheduling work."""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit


def load_roadmap(root):
    return json.loads((Path(root) / 'data/roadmap.json').read_text(encoding='utf-8'))


def validate_roadmap(data, questions, catalog, learning):
    """Check the roadmap's references and progression before rendering any view."""
    def require(condition, message):
        if not condition:
            raise ValueError('Roadmap: ' + message)

    def obj(value, label):
        require(isinstance(value, dict), f'{label} must be an object')
        return value

    def text(value, label):
        require(isinstance(value, str) and bool(value.strip()), f'empty {label}')
        return value

    def strings(value, label, allow_empty=False):
        require(isinstance(value, list), f'{label} must be a list')
        require(allow_empty or bool(value), f'empty {label}')
        for item in value:
            text(item, label)
        return value

    def items(value, label):
        require(isinstance(value, list) and bool(value), f'empty {label}')
        for item in value:
            obj(item, label)
        return value

    def unique(values, label):
        require(len(values) == len(set(values)), f'duplicate {label}')

    def date(value, label):
        require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value), f'invalid {label}')
        try:
            return dt.date.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f'Roadmap: invalid {label}: {value}') from error

    def number(value, label):
        require(type(value) in (int, float) and math.isfinite(value) and value > 0, f'invalid {label}')
        return value

    def ids(value, known, label, allow_empty=True):
        values = strings(value, label, allow_empty=allow_empty)
        unique(values, label)
        require(set(values) <= known, f'unknown {label}: {sorted(set(values) - known)}')

    obj(data, 'data')
    require(type(data.get('schema_version')) is int and data['schema_version'] == 1, 'unsupported schema version')
    require(data.get('kind') == '原创学习与成长规划', 'invalid provenance')
    updated = date(data.get('updated'), 'update date')
    require(updated <= date(catalog.get('curated_through'), 'catalog date'), 'future update')
    for field in ('intro', 'start_body', 'sprint_body', 'role_positioning', 'role_evidence_rule', 'growth_boundary'):
        text(data.get(field), field)
    strings(data.get('assumptions'), 'assumptions')
    strings(data.get('growth_after_first_portfolio'), 'growth after first portfolio')
    project = obj(data.get('through_project'), 'through project')
    for field in ('suggestion', 'why', 'scope_guard'):
        text(project.get(field), f'through project {field}')
    rule = obj(data.get('progression_rule'), 'progression rule')
    for field in ('entry', 'gate', 'review_loop'):
        text(rule.get(field), f'progression {field}')
    statuses = strings(rule.get('evidence_statuses'), 'evidence statuses')
    unique(statuses, 'evidence status')

    known_refs = {
        'question_ids': {q['id'] for q in questions},
        'guide_ids': {g['id'] for g in learning['guides']},
        'lab_ids': {lab['id'] for lab in learning['labs']},
    }

    def references(value, label):
        obj(value, label)
        for field, known in known_refs.items():
            ids(value.get(field), known, f'{label} {field}', allow_empty=field != 'question_ids')

    resources = items(data.get('resources'), 'resources')
    resource_ids = []
    for resource in resources:
        rid = text(resource.get('id'), 'resource id')
        require(re.fullmatch(r'R\d{2,}', rid), f'invalid resource id: {rid}')
        resource_ids.append(rid)
        for field in ('kind', 'title', 'supports', 'limits'):
            text(resource.get(field), f'{rid} {field}')
        url = text(resource.get('url'), f'{rid} URL')
        try:
            parsed = urlsplit(url)
        except ValueError as error:
            raise ValueError(f'Roadmap: invalid {rid} URL') from error
        require(parsed.scheme == 'https' and bool(parsed.netloc) and not re.search(r'\s', url), f'{rid} must use an absolute HTTPS URL')
        require(date(resource.get('checked_on'), f'{rid} check date') <= updated, f'{rid} future check date')
    unique(resource_ids, 'resource id')

    milestones = items(data.get('milestones'), 'milestones')
    require([m.get('id') for m in milestones] == [f'M{i}' for i in range(7)], 'milestones must be M0–M6 in order')
    earlier = set()
    for milestone in milestones:
        mid = milestone['id']
        for field in ('title', 'fallback'):
            text(milestone.get(field), f'{mid} {field}')
        require(type(milestone.get('optional')) is bool, f'{mid} optional must be boolean')
        require(milestone['optional'] == (mid == 'M0'), 'only M0 is conditional; M1–M6 form the main route')
        strings(milestone.get('entry_conditions'), f'{mid} entry conditions')
        strings(milestone.get('learning_and_building_steps'), f'{mid} learning steps')
        artifact = obj(milestone.get('artifact'), f'{mid} artifact')
        text(artifact.get('name'), f'{mid} artifact name')
        strings(artifact.get('contents'), f'{mid} artifact contents')
        acceptance = items(milestone.get('acceptance'), f'{mid} acceptance')
        require(len(acceptance) == 3, f'{mid} must have three observable acceptance checks')
        require({check.get('id') for check in acceptance} == {f'{mid}-C{i}' for i in range(1,4)},
                f'{mid} acceptance IDs must be stable, unique C1–C3')
        for check in acceptance:
            text(check.get('observable'), f'{mid} observable check')
            text(check.get('evidence'), f'{mid} acceptance evidence')
        references(milestone.get('references'), f'{mid} references')
        hours = obj(milestone.get('hours'), f'{mid} hours')
        lower = number(hours.get('min'), f'{mid} minimum hours')
        upper = number(hours.get('max'), f'{mid} maximum hours')
        require(lower <= upper, f'{mid} hours must be ordered')
        text(hours.get('basis'), f'{mid} estimate basis')
        ids(milestone.get('depends_on'), earlier, f'{mid} dependency (must be an earlier milestone)')
        ids(milestone.get('resource_ids'), set(resource_ids), f'{mid} resource reference')
        if 'reference_note' in milestone:
            text(milestone['reference_note'], f'{mid} reference note')
        earlier.add(mid)

    entries = items(data.get('entries'), 'entries')
    require(len(entries) == 3, 'three entry routes are required')
    entry_ids = []
    for entry in entries:
        eid = text(entry.get('id'), 'entry id')
        require(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', eid), f'invalid entry id: {eid}')
        entry_ids.append(eid)
        for field in ('title', 'condition', 'action'):
            text(entry.get(field), f'{eid} {field}')
        require(entry.get('start') in {'M0', 'M1', 'review'}, f'{eid} invalid start')
    unique(entry_ids, 'entry id')
    require({e['start'] for e in entries} == {'M0', 'M1', 'review'}, 'entry routes must cover M0, M1 and review')

    modes = items(data.get('pace_modes'), 'pace modes')
    names = []
    for mode in modes:
        name = text(mode.get('name'), 'pace name')
        names.append(name)
        hours = number(mode.get('hours'), f'{name} weekly hours')
        activities = items(mode.get('activities'), f'{name} activities')
        activity_names = []
        for activity in activities:
            activity_names.append(text(activity.get('name'), f'{name} activity name'))
            require(type(activity.get('minutes')) is int and activity['minutes'] > 0, f'{name} activity minutes must be positive integers')
        unique(activity_names, f'{name} activity')
        require(sum(a['minutes'] for a in activities) == hours * 60, f'{name} minutes must sum to weekly hours × 60')
        text(mode.get('advice'), f'{name} advice')
    unique(names, 'pace name')

    catalog_roles = {role['id']: role['name'] for role in catalog['roles']}
    roles = items(data.get('roles'), 'roles')
    role_ids = [text(role.get('id'), 'role id') for role in roles]
    unique(role_ids, 'role id')
    require(set(role_ids) == set(catalog_roles), 'roles must match catalog')
    checkpoint_ids = []
    for role in roles:
        rid = role['id']
        require(role.get('name') == catalog_roles[rid], f'{rid} name must match catalog')
        for field in ('project', 'reuse_from_main', 'focus', 'entry_check', 'return_to_main', 'm5_comparison'):
            text(role.get(field), f'{rid} {field}')
        checkpoints = items(role.get('checkpoints'), f'{rid} checkpoints')
        local_ids = []
        for checkpoint in checkpoints:
            cid = text(checkpoint.get('id'), f'{rid} checkpoint id')
            require(re.fullmatch(r'[A-Z][A-Z0-9]*-[1-9]\d*', cid), f'invalid checkpoint id: {cid}')
            local_ids.append(cid)
            checkpoint_ids.append(cid)
            for field in ('stage', 'title', 'do', 'review_prompt'):
                text(checkpoint.get(field), f'{cid} {field}')
            strings(checkpoint.get('artifacts'), f'{cid} artifacts')
            strings(checkpoint.get('verification'), f'{cid} verification')
            references(checkpoint, f'{cid} references')
        unique(local_ids, f'{rid} checkpoint id')
        require(role.get('minimum_checkpoint') == local_ids[0], f'{rid} minimum checkpoint must be its first checkpoint')
    unique(checkpoint_ids, 'checkpoint id across roles')

    review_sections = items(data.get('review_sections'), 'review sections')
    section_titles = []
    for section in review_sections:
        section_titles.append(text(section.get('title'), 'review section title'))
        text(section.get('body'), 'review section body')
    unique(section_titles, 'review section title')

    levels = items(data.get('growth_levels'), 'growth levels')
    level_ids = []
    for level in levels:
        lid = text(level.get('id'), 'growth level id')
        require(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', lid), f'invalid growth level id: {lid}')
        level_ids.append(lid)
        for field in ('name', 'description', 'next_step'):
            text(level.get(field), f'{lid} {field}')
        strings(level.get('observable_evidence'), f'{lid} observable evidence')
        signals = obj(level.get('role_signals'), f'{lid} role signals')
        require(set(signals) == set(catalog_roles), f'{lid} role signals must match catalog')
        for rid, signal in signals.items():
            text(signal, f'{lid} {rid} signal')
    unique(level_ids, 'growth level id')


def _bullets(values):
    return ['- ' + value for value in values]


def _cell(value):
    return str(value).replace('|', r'\|').replace('\n', '<br>')


def _hours(value):
    return f'{value:g}'


def _range(hours):
    return f"{_hours(hours['min'])}–{_hours(hours['max'])} 小时"


def _anchor(identifier):
    return f'<a id="{identifier.lower()}"></a>'


def _navigation():
    return '[路线总览](README.md) · [入口自测](start.md) · [能力阶段](milestones.md) · [学习与复习](review.md) · [面试前冲刺](interview-sprint.md) · [长期成长](growth.md) · [学习资料](resources.md)'


def _related(file, refs, qlink, guide_link, lab_link):
    lines = []
    for field, label, callback in (
        ('question_ids', '自测题目', qlink),
        ('guide_ids', '机制指南', guide_link),
        ('lab_ids', '故障练习', lab_link),
    ):
        if refs[field]:
            lines += [label + '：' + ' · '.join(callback(file, item_id) for item_id in refs[field]), '']
    return lines


def _role_table(data):
    lines = ['| 岗位 | 本轮最低交付点 | 深化目标 |', '| --- | --- | --- |']
    for role in data['roles']:
        checkpoint = next(c for c in role['checkpoints'] if c['id'] == role['minimum_checkpoint'])
        path = f"../paths/{role['id']}.md"
        lines.append(f"| [{_cell(role['name'])}]({path}) | [{checkpoint['id']} · {_cell(checkpoint['title'])}]({path}#{checkpoint['id'].lower()}) | {_cell(role['focus'])} |")
    return lines


def render_role_growth(data, role_id, qlink, guide_link, lab_link):
    """Return a section for an existing role page, including stable checkpoint anchors."""
    role = next((role for role in data['roles'] if role['id'] == role_id), None)
    if role is None:
        raise ValueError(f'Roadmap: unknown role to render: {role_id}')
    file = f'paths/{role_id}.md'
    minimum = role['minimum_checkpoint']
    lines = [
        _anchor('growth-delivery'), '## 岗位成长交付', '',
        data['role_positioning'], '',
        f"**持续项目：** {role['project']}", '',
        f"**深化目标：** {role['focus']}", '',
        f"**进入条件：** {role['entry_check']}", '',
        f"**复用主线：** {role['reuse_from_main']}", '',
        f'本轮最低交付点：[{minimum}](#{minimum.lower()})。完成该点，并满足 [M5 的三项对照验收](../roadmap/milestones.md#m5)，再进入 [M6 作品验收](../roadmap/milestones.md#m6)。', '',
        role['m5_comparison'], '', data['role_evidence_rule'], '',
    ]
    for checkpoint in role['checkpoints']:
        cid = checkpoint['id']
        lines += [_anchor(cid), f"### {cid} · {checkpoint['title']}", '', f"**用途：** {checkpoint['stage']}", '', checkpoint['do'], '', '**提交产物**', '']
        lines += _bullets(checkpoint['artifacts'])
        lines += ['', '**如何验证**', '']
        lines += [f'{index}. {check}' for index, check in enumerate(checkpoint['verification'], 1)]
        lines += ['', '**用于补缺与复习**', '']
        lines += _related(file, checkpoint, qlink, guide_link, lab_link)
        lines += [f"**闭卷复盘：** {checkpoint['review_prompt']}", '']
    lines += [role['return_to_main'], '', '[能力阶段主线](../roadmap/milestones.md) · [学习与复习方法](../roadmap/review.md) · [长期成长](../roadmap/growth.md)', '']
    return lines


def render_roadmap(data, qlink, guide_link, lab_link):
    """Return seven unwrapped Markdown views; the caller owns file generation."""
    views = {}
    milestones = data['milestones']
    roles = data['roles']
    resources = {resource['id']: resource for resource in data['resources']}
    core = [milestone for milestone in milestones if not milestone['optional']]
    conditional = [milestone for milestone in milestones if milestone['optional']]
    core_hours = {key: sum(m['hours'][key] for m in core) for key in ('min', 'max')}
    all_hours = {key: sum(m['hours'][key] for m in milestones) for key in ('min', 'max')}
    estimate_note = '工时是编者对阅读、实现和首次调试的估计，不包含间隔复习、返工、等待、投递或零基础编程学习；不按累计工时自动通过，也不保证就业结果。'

    def page(title):
        return [f'# {title}', '', f"**内容类型：{data['kind']}** · 更新于 {data['updated']}。", '', _navigation(), '']

    def finish(file, lines):
        views[file] = lines + ['', _navigation(), '', '[返回题库](../README.md) · [学习计划模板](../templates/study-plan.md) · [项目证据模板](../templates/project-evidence.md)']

    lines = page('学习与成长路线')
    lines += [data['intro'], '',
              f"{len(conditional)} 个条件式补课阶段 · {len(core)} 个主线里程碑 · {len(roles)} 个岗位分支 · {sum(len(role['checkpoints']) for role in roles)} 个岗位交付点。", '',
              '本路线独立编写，以可观察的能力和交付证据推进。Q 是有来源的面试问题，G 是原创指南，L 是原创故障练习；路线与练习建议不增加面试题数量，也不代表企业统一要求。', '',
              '## 从哪里开始', '', '| 入口 | 适用情况 | 下一步 |', '| --- | --- | --- |']
    for entry in data['entries']:
        target = 'review.md' if entry['start'] == 'review' else f"milestones.md#{entry['start'].lower()}"
        lines += [f"| [{_cell(entry['title'])}](start.md#{entry['id']}) | {_cell(entry['condition'])} | [{entry['start']}]({target})：{_cell(entry['action'])} |"]
    lines += ['', '先做[入口自测](start.md)，再按证据选择起点。M0 可以用等价工程证据跳过，已掌握的主线阶段也应先核对验收后再跳过。', '',
              '## 能力如何累积', '', '```mermaid', 'flowchart TD']
    for milestone in milestones:
        label = milestone['title'].split('：', 1)[0].replace('"', '&quot;')
        lines.append(f'    {milestone["id"]}["{milestone["id"]} {label}"]')
    for milestone in milestones:
        for dependency in milestone['depends_on']:
            lines.append(f'    {dependency} --> {milestone["id"]}')
    lines += ['    M6 --> R["新场景、复习与后续深化"]', '```', '',
              '图中箭头表示能力前置关系；M0 是条件式补课，具有等价证据即可进入 M1。遇到失败按验收缺口回退，不按学习天数升级。', '',
              '## 一直改进同一个项目', '', data['through_project']['suggestion'], '', data['through_project']['why'], '', data['through_project']['scope_guard'], '',
              '## 用证据决定是否前进', '', data['progression_rule']['entry'], '', data['progression_rule']['gate'], '',
              '产物状态：' + '、'.join(data['progression_rule']['evidence_statuses']) + '。这些是记录标签，失败时可以回到“需返工”。', '',
              data['progression_rule']['review_loop'], '',
              f"M1–M6 主线的首次专注投入合计为 **{_range(core_hours)}**；若 M0 也全部需要，合计为 **{_range(all_hours)}**。", '', estimate_note, '',
              _anchor('pace'), '## 每周可用时间怎么分配', '', '以下是可调整的时间预算示例，不是自动日历或统一完成期限。一个里程碑可以跨越多周，复习与验证也需要单独预留时间。', '',
              '| 节奏 | 每周预算 | 活动分配 | 调整建议 |', '| --- | --- | --- | --- |']
    for mode in data['pace_modes']:
        allocation = '；'.join(f"{a['name']} {a['minutes']} 分钟" for a in mode['activities'])
        lines += [f"| {_cell(mode['name'])} | {_hours(mode['hours'])} 小时 / {sum(a['minutes'] for a in mode['activities'])} 分钟 | {_cell(allocation)} | {_cell(mode['advice'])} |"]
    lines += ['', '## 岗位选择', '', data['role_positioning'], ''] + _role_table(data)
    lines += ['', '## 使用边界', ''] + _bullets(data['assumptions'])
    lines += ['', '完整能力阶段见[主线](milestones.md)；完成一次作品后继续使用[复习方法](review.md)与[长期成长](growth.md)。面试临近时参考[冲刺示例](interview-sprint.md)。']
    finish('roadmap/README.md', lines)

    lines = page('入口自测：按已有证据选择起点')
    lines += ['## 先独立尝试，再确定路线', '', data['start_body'], '', '## 入口速查与行动', '']
    for entry in data['entries']:
        target = 'review.md' if entry['start'] == 'review' else f"milestones.md#{entry['start'].lower()}"
        lines += [_anchor(entry['id']), f"### {entry['title']}", '', entry['condition'], '', entry['action'], '', f"前往：[{entry['start']}]({target})。", '']
    lines += ['选定起点后，复制[学习计划模板](../templates/study-plan.md)，对照[每周预算示例](README.md#pace)安排可用时段。保留失败证据，下一次复查时允许调整起点。']
    finish('roadmap/start.md', lines)

    file = 'roadmap/milestones.md'
    lines = page('能力阶段：从最小应用到可复核作品')
    lines += [data['through_project']['suggestion'], '', data['progression_rule']['gate'], '', estimate_note, '',
              f"M1–M6 合计 **{_range(core_hours)}**；包含全部 M0 补课时为 **{_range(all_hours)}**。选择一个岗位分支，不把其长期深化点都计入本轮。", '',
              '| 阶段 | 提交产物 | 专注工时估计 | 前置能力 |', '| --- | --- | --- | --- |']
    for milestone in milestones:
        dependencies = ' · '.join(f'[{mid}](#{mid.lower()})' for mid in milestone['depends_on']) or '入口自测暴露的工程缺口'
        lines += [f"| [{milestone['id']} · {_cell(milestone['title'])}](#{milestone['id'].lower()}) | {_cell(milestone['artifact']['name'])} | {_range(milestone['hours'])} | {dependencies} |"]
    lines += ['', 'M1 的 M0 前置要求也可由已有的等价工程证据满足；工时不是阶段准入或通过条件。', '']
    for milestone in milestones:
        mid = milestone['id']
        lines += [_anchor(mid), f"## {mid} · {milestone['title']}", '',
                  f"**阶段性质：** {'条件式补课，可用等价证据跳过' if milestone['optional'] else '能力主线'}。**专注投入估计：** {_range(milestone['hours'])}。", '', milestone['hours']['basis'], '',
                  '### 入门条件', ''] + _bullets(milestone['entry_conditions'])
        lines += ['', '### 学习与动手', ''] + [f'{index}. {step}' for index, step in enumerate(milestone['learning_and_building_steps'], 1)]
        lines += ['', f"### 一个可提交产物：{milestone['artifact']['name']}", ''] + _bullets(milestone['artifact']['contents'])
        lines += ['', '### 三项可观察验收', '', '| 需要观察到的结果 | 留下的证据 |', '| --- | --- |']
        lines += [f"| <a id=\"{check['id'].lower()}\"></a>**{check['id']}** · {_cell(check['observable'])} | {_cell(check['evidence'])} |" for check in milestone['acceptance']]
        lines += ['', '### 未通过时怎么回退', '', milestone['fallback'], '', '### 相关题目、指南与练习', '']
        if milestone.get('reference_note'):
            lines += [milestone['reference_note'], '']
        lines += _related(file, milestone['references'], qlink, guide_link, lab_link)
        if milestone['resource_ids']:
            lines += ['学习资料：' + ' · '.join(f"[{rid} · {resources[rid]['title']}](resources.md#{rid.lower()})" for rid in milestone['resource_ids']), '']
        if mid == 'M5':
            lines += ['### 只选择一个岗位分支', '', data['role_positioning'], ''] + _role_table(data) + ['']
    lines += [data['role_evidence_rule'], '', '验收记录可放入[项目证据模板](../templates/project-evidence.md)；完成后按[学习与复习](review.md)安排下一次闭卷检查。']
    finish(file, lines)

    lines = page('学习与复习：让知识经得起间隔和变式')
    lines += ['这些步骤和状态是编者的可调整实践建议，不是招聘标准或对个人学习效果的保证。研究依据的支持范围与限制见[学习资料](resources.md)。', '']
    for section in data['review_sections']:
        lines += [f"## {section['title']}", '', section['body'], '']
    research = [resource for resource in data['resources'] if resource['kind'] == '研究依据']
    if research:
        lines += ['研究依据：' + ' · '.join(f"[{resource['id']} · {resource['title']}](resources.md#{resource['id'].lower()})" for resource in research)]
    finish('roadmap/review.md', lines)

    lines = page('面试前冲刺：用证据修补关键缺口')
    lines += [data['sprint_body'], '', '把模拟面试暴露的缺口放回[复习记录](../templates/review-log.csv)，实践问题回到对应[能力阶段](milestones.md)的验收条件。已有但讲不清的作品，使用[项目证据模板](../templates/project-evidence.md)整理责任、取舍与原始记录。']
    finish('roadmap/interview-sprint.md', lines)

    lines = page('长期成长：从做出功能到负责系统')
    lines += [data['growth_boundary'], '', data['role_positioning'], '', '## 岗位深化入口', ''] + _role_table(data)
    lines += ['', '完成最低交付点与 M5 对照验收后先进入 M6；下列成长描述和岗位后续交付点用于继续迭代，不是本轮全部必修。', '']
    for level in data['growth_levels']:
        lines += [_anchor(level['id']), f"## {level['name']}", '', level['description'], '', '**可观察证据**', ''] + _bullets(level['observable_evidence'])
        lines += ['', '| 岗位 | 在该方向上观察什么 |', '| --- | --- |']
        lines += [f"| [{_cell(role['name'])}](../paths/{role['id']}.md#growth-delivery) | {_cell(level['role_signals'][role['id']])} |" for role in roles]
        lines += ['', '**下一步：** ' + level['next_step'], '']
    lines += ['## 第一份作品之后', ''] + _bullets(data['growth_after_first_portfolio'])
    lines += ['', data['role_evidence_rule']]
    finish('roadmap/growth.md', lines)

    lines = page('学习资料与适用边界')
    lines += ['R 编号用于本路线的研究依据、基础课程与可选框架资料；它们不证明任何企业出过某道面试题。技术机制的 T 编号资料另见[研习技术档案](../learning/REFERENCES.md)。', '',
              '资料支持范围与限制分别列出；工时、阶段验收、复习日期和岗位交付方式仍是编者设计。外部课程和框架不是必须全部完成的清单。', '']
    for resource in data['resources']:
        rid = resource['id']
        lines += [_anchor(rid), f"## {rid} · {resource['title']}", '', f"**类别：** {resource['kind']}。**核实日期：** {resource['checked_on']}。", '',
                  f"[{resource['title']}]({resource['url']})", '', '**支持的内容：** ' + resource['supports'], '', '**适用边界：** ' + resource['limits'], '']
        linked = [m for m in milestones if rid in m['resource_ids']]
        if linked:
            lines += ['阶段入口：' + ' · '.join(f"[{m['id']}](milestones.md#{m['id'].lower()})" for m in linked), '']
        elif resource['kind'] == '研究依据':
            lines += ['用于：[学习与复习](review.md)。', '']
    finish('roadmap/resources.md', lines)
    return views
