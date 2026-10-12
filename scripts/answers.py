"""Original question-level explanations, deliberately separate from interview evidence."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


def load_answers(root):
    return json.loads((Path(root) / 'data/answers.json').read_text(encoding='utf-8'))


def validate_answers(data, questions, learning, catalog):
    def require(condition, message):
        if not condition:
            raise ValueError('Answers: ' + message)

    def nonempty(value):
        return isinstance(value, str) and bool(value.strip())

    def obj(value, required, label):
        require(isinstance(value, dict) and set(required) <= set(value), label + ': missing fields')

    def date(value, label):
        require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value), label + ': invalid date')
        try:
            return dt.date.fromisoformat(value)
        except ValueError as error:
            raise ValueError('Answers: ' + label + ': invalid date') from error

    def text_fields(value, fields, label):
        obj(value, fields, label)
        require(all(nonempty(value[field]) for field in fields), label + ': empty text')

    def records(value, fields, label, minimum=1):
        require(isinstance(value, list) and len(value) >= minimum, label + ': too few entries')
        for item in value:
            text_fields(item, fields, label)

    def ids(value, available, label, required=False):
        require(isinstance(value, list) and all(nonempty(item) for item in value), label + ': invalid ids')
        require(not required or bool(value), label + ': empty ids')
        require(len(value) == len(set(value)), label + ': duplicate ids')
        require(set(value) <= available, label + ': unknown ids')

    obj(data, ['schema_version', 'kind', 'updated', 'references', 'answers'], 'root')
    require(type(data['schema_version']) is int and data['schema_version'] == 1, 'unsupported schema version')
    require(data['kind'] == '原创逐题解析', 'invalid provenance')
    updated = date(data['updated'], 'updated')
    require(updated <= date(catalog['curated_through'], 'catalog.curated_through'), 'future update')
    require(isinstance(data['references'], list) and data['references'], 'empty references')
    references = set()
    urls = set()
    for source in data['references']:
        text_fields(source, ['id', 'title', 'url', 'checked_on', 'supports'], 'reference')
        require(re.fullmatch(r'ARef\d{2,}', source['id']), 'invalid reference id')
        require(source['id'] not in references, 'duplicate reference id')
        references.add(source['id'])
        url = source['url']
        try:
            parsed = urlsplit(url)
            valid_url = parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password
        except ValueError:
            valid_url = False
        require(valid_url and not re.search(r'\s', url), 'reference must use a valid HTTPS URL')
        require(url not in urls, 'duplicate reference URL')
        urls.add(url)
        require(date(source['checked_on'], source['id']) <= updated, 'future source check')

    qmap = {question['id']: question for question in questions}
    guide_ids = {item['id'] for item in learning['guides']}
    lab_ids = {item['id'] for item in learning['labs']}
    require(isinstance(data['answers'], list) and data['answers'], 'empty answers')
    seen_questions, slugs, used_references = set(), set(), set()
    for answer in data['answers']:
        obj(answer, ['question_id', 'slug', 'title', 'level', 'short_answer', 'deep_dive', 'follow_ups',
                     'counterexample', 'rubric', 'exercise', 'reference_ids', 'guide_ids', 'lab_ids'], 'answer')
        qid = answer['question_id']
        require(isinstance(qid, str) and qid in qmap, 'unknown question')
        require(qid not in seen_questions, 'duplicate question answer')
        seen_questions.add(qid)
        require(answer['title'] == qmap[qid]['question'], qid + ': title differs from question source')
        slug = answer['slug']
        require(isinstance(slug, str) and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug), qid + ': unsafe slug')
        require(slug != 'readme' and slug not in slugs, qid + ': duplicate or reserved slug')
        slugs.add(slug)
        require(isinstance(answer['level'], str) and answer['level'] in {'基础', '进阶', '综合'}, qid + ': unknown editorial level')
        require(nonempty(answer['short_answer']), qid + ': empty short answer')
        records(answer['deep_dive'], ['title', 'body'], qid + ': deep_dive', 2)
        records(answer['follow_ups'], ['question', 'answer'], qid + ': follow_ups', 2)
        text_fields(answer['counterexample'], ['wrong', 'why', 'better'], qid + ': counterexample')
        records(answer['rubric'], ['criterion', 'evidence'], qid + ': rubric', 2)
        obj(answer['exercise'], ['task', 'checks'], qid + ': exercise')
        require(nonempty(answer['exercise']['task']), qid + ': empty exercise task')
        checks = answer['exercise']['checks']
        require(isinstance(checks, list) and len(checks) >= 2 and all(nonempty(item) for item in checks), qid + ': empty exercise checks')
        for key, available, mandatory in [('reference_ids', references, True), ('guide_ids', guide_ids, False), ('lab_ids', lab_ids, False)]:
            ids(answer[key], available, qid + ': ' + key, mandatory)
        used_references.update(answer['reference_ids'])
    require(used_references == references, 'unreferenced technical source')


def answer_path(answer):
    return f"learning/answers/{answer['slug']}.md"


def render_answers(data, qlink, glink, llink):
    """Return unwrapped Markdown lines; build owns banners and writes all views."""
    sources = {source['id']: source for source in data['references']}
    views = {}
    provenance = ('**内容类型：原创逐题解析**。不是面试官原答案，也不是唯一标准答案；'
                  '开放题允许满足约束的替代设计。难度仅为编者建议，不代表市场难度或出现频率。')
    for answer in data['answers']:
        file = answer_path(answer)
        lines = [f"# {answer['question_id']} · {answer['title']}", '', provenance, '',
                 f"编者建议：{answer['level']} · 更新：{data['updated']}", '',
                 '面经题目与来源：' + qlink(file, answer['question_id']), '',
                 '## 先给出自己的回答', '', answer['short_answer'], '', '## 深入展开', '']
        for point in answer['deep_dive']:
            lines += ['### ' + point['title'], '', point['body'], '']
        lines += ['机制依据：' + ' · '.join(f"[{rid}]({sources[rid]['url']})" for rid in answer['reference_ids']), '',
                  '## 继续追问', '']
        for index, follow_up in enumerate(answer['follow_ups'], 1):
            lines += [f"### {index}. {follow_up['question']}", '', follow_up['answer'], '']
        example = answer['counterexample']
        lines += ['## 一个容易答错的版本', '', '**错误说法：** ' + example['wrong'], '',
                  '**问题在哪里：** ' + example['why'], '', '**更好的组织方式：** ' + example['better'], '',
                  '## 用什么证据评议回答', '',
                  '下面是编者提供的复盘判据，不是招聘评分；能给出有效替代设计与相应证据，同样成立。', '']
        for item in answer['rubric']:
            lines += [f"- **{item['criterion']}**：{item['evidence']}"]
        lines += ['', '## 动手练习', '', answer['exercise']['task'], '', '验收时检查：', '']
        lines += ['- ' + item for item in answer['exercise']['checks']]
        lines += ['', '本页提出练习要求，不声称学习者已执行或通过。使用桩服务、真实服务或仅提交设计时应分别注明，未验证项如实保留。', '']
        related = [glink(file, gid) for gid in answer['guide_ids']] + [llink(file, lid) for lid in answer['lab_ids']]
        if related:
            lines += ['继续研习：' + ' · '.join(related), '']
        lines += ['## 技术依据与边界', '',
                  '下列一手资料支持机制说明；示例、答题组织、练习与判据由编者独立设计。技术资料不能证明企业出过本题，面经依据请回到 Q 编号。', '']
        for rid in answer['reference_ids']:
            source = sources[rid]
            lines += [f"- [{rid} · {source['title']}]({source['url']})：{source['supports']} 核实于 {source['checked_on']}。"]
        lines += ['', '[逐题解析目录](README.md) · [原创研习入口](../README.md) · [学习路线](../../roadmap/README.md)']
        views[file] = lines

    file = 'learning/answers/README.md'
    lines = ['# 原创逐题解析', '', provenance, '',
             f"首批 {len(data['answers'])} 题 · {len(data['references'])} 条技术资料 · 更新：{data['updated']}", '',
             '先用自己的语言口述，再看解析中的边界与反例；最后按练习留下可检查的证据。解析补充学习材料，不增加面经题目或面经来源数量。', '',
             '| 题目 | 编者建议 | 解析 |', '| --- | --- | --- |']
    for answer in data['answers']:
        title = answer['title'].replace('|', '\\|')
        lines += [f"| {qlink(file, answer['question_id'])} | {answer['level']} | [{title}]({answer['slug']}.md) |"]
    lines += ['', '## 阅读顺序', '',
              '先选与你正在实现的功能相连的一题；概念不清时追踪数据与状态，设计题要说明取舍，编码与模型题要用小输入验证不变量。无需一次背完全部解析。', '',
              '[原创研习入口](../README.md) · [学习与成长路线](../../roadmap/README.md) · [复习机制](../../roadmap/review.md) · [返回首页](../../README.md)']
    views[file] = lines
    return views
