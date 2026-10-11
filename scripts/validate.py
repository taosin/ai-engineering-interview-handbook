#!/usr/bin/env python3
"""Validate the handbook's references and editorial metadata (standard library only)."""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
import re
import sys
from learning import load_learning, validate_learning
from roadmap import load_roadmap, validate_roadmap

ROOT = Path(__file__).resolve().parents[1]
STATUSES = {'historical', 'original', 'platform-index', 'search-index'}
PRECISIONS = {'day', 'range', 'month-day-year-inferred', 'historical-label'}

def load_data():
    return tuple(json.loads((ROOT / 'data' / f'{name}.json').read_text(encoding='utf-8'))
                 for name in ('questions', 'sources', 'catalog'))

def require(condition, message):
    if not condition:
        raise ValueError(message)

def iso_date(value):
    return dt.date.fromisoformat(value)

def validate_data(questions, sources, catalog):
    require(catalog['schema_version'] == 2, 'Unsupported schema version')
    for items, pattern, name in ((questions, r'Q\d{3,}', 'question'), (sources, r'S\d{2,}', 'source')):
        ids = [item['id'] for item in items]
        require(len(ids) == len(set(ids)), f'Duplicate {name} id')
        require(all(re.fullmatch(pattern, i) for i in ids), f'Invalid {name} id')
    source_map = {s['id']: s for s in sources}
    topic_map = {t['id']: t for t in catalog['topics']}
    roles = {role['name'] for role in catalog['roles']}
    require(len(roles) == len(catalog['roles']), 'Duplicate role name')
    role_ids = [role['id'] for role in catalog['roles']]
    require(len(role_ids) == len(set(role_ids)), 'Duplicate role id')
    require(all(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', i) for i in role_ids), 'Invalid role slug')
    require(len(topic_map) == len(catalog['topics']), 'Duplicate topic')
    require(len({t['file'] for t in catalog['topics']}) == len(topic_map), 'Duplicate topic file')
    require(all(re.fullmatch(r'questions/[a-z0-9][a-z0-9-]*\.md', t['file']) for t in catalog['topics']), 'Invalid topic output path')
    require(all(t['file'] != 'questions/README.md' for t in catalog['topics']), 'Reserved topic output path')
    seen = set()
    for q in questions:
        label = q['id']
        require(q['topic'] in topic_map, f'{label}: unknown topic')
        require(q['question_type'] in catalog['question_types'], f'{label}: unknown question type')
        require(q['roles'] and set(q['roles']) <= roles, f'{label}: unknown or missing roles')
        require(len(q['roles']) == len(set(q['roles'])), f'{label}: duplicate role')
        require(q['type'] == '面经问题归纳', f'{label}: unsupported provenance; update schema before adding original exercises')
        require(q['temporal_scope'] in {'检索范围内材料', '边界补充'}, f'{label}: invalid temporal scope')
        require(q['source_ids'] and set(q['source_ids']) <= source_map.keys(), f'{label}: missing source')
        require(len(q['source_ids']) == len(set(q['source_ids'])), f'{label}: duplicate source')
        require(set(q['source_locators']) == set(q['source_ids']), f'{label}: source locator mismatch')
        require(all(v.strip() for v in q['source_locators'].values()), f'{label}: empty source locator')
        require(q['question'].strip() and '\n' not in q['question'], f'{label}: question must be one nonempty line')
        normalized = re.sub(r'\W+', '', q['question']).lower()
        require(normalized not in seen, f'{label}: exact duplicate question')
        seen.add(normalized)
        require(iso_date(q['last_curated']) <= iso_date(catalog['curated_through']), f'{label}: future curation')
        require(iso_date(q['metadata_updated']) <= iso_date(catalog['curated_through']), f'{label}: future metadata update')
        for follow_up in q.get('follow_ups', []):
            require(follow_up['source_id'] in source_map, f'{label}: unknown follow-up source')
            require(follow_up['question'].strip() and follow_up['locator'].strip(), f'{label}: empty follow-up')
            require(follow_up['origin'] == '来源支持的追问变体', f'{label}: unsupported follow-up provenance')
    for s in sources:
        label = s['id']
        require(s['url'].startswith('https://'), f'{label}: source must use HTTPS')
        require(s['date_kind'] and s['date_label'] and s['date_evidence']['year_basis'], f'{label}: missing date provenance')
        require(s['date_evidence']['precision'] in PRECISIONS, f'{label}: invalid date precision')
        v = s['verification']
        require(v['status'] in STATUSES, f'{label}: invalid verification status')
        require(v['checked_on'] == s['last_checked'], f'{label}: conflicting check dates')
        require(iso_date(v['checked_on']) <= iso_date(catalog['curated_through']), f'{label}: future check')
        require(v['evidence_url'].startswith('https://'), f'{label}: missing evidence URL')
    by_id = {q['id']: q for q in questions}
    for role in catalog['roles']:
        for stage in role['stages']:
            require(stage['goal'] and stage['ids'], f"Empty stage: {role['id']}")
            for qid in stage['ids']:
                require(qid in by_id, f'Unknown route question: {qid}')
                require(role['name'] in by_id[qid]['roles'], f'{qid}: route role missing from tags')
    for file, ids in catalog.get('legacy_anchors', {}).items():
        require(file in {t['file'] for t in catalog['topics']}, f'Unknown legacy file: {file}')
        require(set(ids) <= by_id.keys(), f'{file}: unknown legacy question')
    require({f'Q{i:03}' for i in range(1,49)} <= by_id.keys(), 'Original question ids must be retained')
    require({f'S{i:02}' for i in range(1,13)} <= source_map.keys(), 'Original source ids must be retained')
    return True

def check_markdown_links():
    for path in ROOT.rglob('*.md'):
        if '.git' in path.parts:
            continue
        text = path.read_text(encoding='utf-8')
        for link in re.findall(r'\]\(([^\s)]+)\)', text):
            if re.match(r'[a-z]+://', link) or link.startswith('mailto:'):
                continue
            name, _, anchor = link.partition('#')
            target = (path.parent / name).resolve() if name else path
            require(target.is_relative_to(ROOT), f'{path.name}: path escapes repository: {link}')
            require(target.exists(), f'{path.name}: missing link: {link}')
            if anchor:
                body = target.read_text(encoding='utf-8')
                # Generated links use stable ASCII Q/S ids; no locale-sensitive heading algorithm.
                require(re.search(r'^#+ ' + re.escape(anchor) + r'\s*$', body, re.M | re.I)
                        or f'id="{anchor}"' in body, f'{path.name}: missing anchor: {link}')

if __name__ == '__main__':
    try:
        qs, ss, cat = load_data()
        validate_data(qs, ss, cat)
        learning = load_learning(ROOT)
        validate_learning(learning, qs, cat)
        roadmap = load_roadmap(ROOT)
        validate_roadmap(roadmap, qs, cat, learning)
        check_markdown_links()
        print(f"Validated {len(qs)} questions, {len(ss)} interview sources, {len(learning['guides'])} guides, {len(learning['labs'])} labs, {len(roadmap['milestones'])} milestones, metadata, routes and local links.")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f'Validation failed: {exc}', file=sys.stderr)
        sys.exit(1)
