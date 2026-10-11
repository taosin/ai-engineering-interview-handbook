import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createState, createAttempt, updateDraft, evaluateAttempt, completeAttempt,
  currentAxes, recommendation, exportBackup, mergeBackup, validateBackup } from '../assessment/core.mjs';

const definition = JSON.parse(readFileSync(new URL('../data/assessment.json', import.meta.url), 'utf8'));
const clone = value => JSON.parse(JSON.stringify(value));
const started = '2026-10-11T08:00:00Z';
const finished = '2026-10-11T08:05:00Z';
function setup({ dimension = 'D5', variant = 'A', id = 'first', state = createState(), now = started, def = definition } = {}) {
  const d = def.dimensions.find(item => item.id === dimension);
  const scenario = def.tasks.find(item => item.id === d.scenario_task_id);
  const practical = def.tasks.find(item => item.id === d.practice_task_id);
  const v = scenario.variants.find(item => item.id.endsWith('-' + variant));
  const created = createAttempt(state, def, { id, now, dimensionId: dimension, variantId: v.id, roleId: def.roles[0] });
  return { ...created, scenario, practical, variant: v, def };
}
function evidence(criteria) {
  return Object.fromEntries(criteria.map(c => [c.id, {
    run_status: 'ran', ...(c.input_type === 'self' ? { judgment: 'pass' } : { observed: c.expected }),
    input: 'run fixture case boundary-1', actual: 'stdout: case=boundary-1, outcome recorded',
    evidence_ref: 'local:artifacts/run.log', locator: 'lines 10-18',
    excerpt: 'case=boundary-1; trace persisted; result inspected',
    explanation: '按给定输入运行并把实际输出与该项判据逐项比较。',
  }]));
}
function filled(fixture, level = 3) {
  const context = { run_at: '2026-10-11', environment: 'Node.js local fixture', version: 'commit:test', model_mode: 'stub' };
  const patch = {
    answers: Object.fromEntries(fixture.variant.criteria.map(c => [c.id, level === 0 ? null : c.expected])),
    practice: level >= 2 ? { status: 'reported', context, criteria: evidence(fixture.practical.criteria) } : { status: 'not_run', context: {}, criteria: {} },
    transfer: level >= 3 ? { status: 'reported', context, criteria: evidence(fixture.practical.transfer.criteria), prediction: '先按不同约束预测实际状态与次数。', tradeoff: '记录成本与恢复边界，原用例仍回归。' } : { status: 'not_run', context: {}, criteria: {}, prediction: '', tradeoff: '' },
  };
  const state = updateDraft(fixture.state, fixture.attempt.id, patch);
  return { ...fixture, state, attempt: state.attempts.find(item => item.id === fixture.attempt.id) };
}
function done(f, now = finished) { return completeAttempt(f.state, f.def, f.attempt.id, { now }); }
function assess(f) { return evaluateAttempt(f.def, f.attempt, f.state.exposures); }

test('definition has six axes, twelve tasks and two different comparable scenario constraints per axis', () => {
  assert.equal(definition.dimensions.length, 6); assert.equal(definition.tasks.length, 12);
  const criterionIds = new Set(); const exposureKeys = new Set();
  for (const d of definition.dimensions) {
    const scenario = definition.tasks.find(t => t.id === d.scenario_task_id);
    const p = definition.tasks.find(t => t.id === d.practice_task_id);
    assert.equal(scenario.variants.length, 2);
    assert.notEqual(scenario.variants[0].prompt, scenario.variants[1].prompt);
    assert.equal(scenario.variants[0].comparison_group, scenario.variants[1].comparison_group);
    for (const v of scenario.variants) { assert(!exposureKeys.has(v.exposure_key)); exposureKeys.add(v.exposure_key); }
    for (const c of [...scenario.variants.flatMap(v => v.criteria), ...p.criteria, ...p.transfer.criteria]) {
      assert(!criterionIds.has(c.id)); criterionIds.add(c.id);
      assert(c.recommendation.action && c.recommendation.deliverable);
      if (c.input_type === 'choice') assert(c.options.some(o => o.value === c.expected));
    }
  }
});

test('all missing axes are null, never implicit zero', () => {
  assert.deepEqual(currentAxes(createState(), definition).map(item => item.level), Array(6).fill(null));
  assert.equal(assess(setup()).complete, false);
  const f = filled(setup(), 0);
  assert.equal(assess(f).level, 0); assert.equal(assess(f).complete, true);
});

for (const d of definition.dimensions) for (const level of [0, 1, 2, 3]) {
  test(`${d.id}: cumulative level ${level} is computed from records, not a declared grade`, () => {
    const f = filled(setup({ dimension: d.id }), level);
    const result = assess(f);
    assert.equal(result.level, level); assert.equal(result.validity, 'valid');
    const completed = done(f);
    assert.equal(currentAxes(completed.state, definition).find(a => a.dimensionId === d.id).level, level);
    assert.equal(validateBackup(completed.state), true);
  });
}

test('wrong foundation blocks practice level; noncritical transfer fail retains level 2', () => {
  const f = filled(setup({ dimension: 'D1' }));
  f.attempt.answers[f.variant.criteria[0].id] = null;
  assert.equal(assess(f).level, 0);
  f.attempt.answers[f.variant.criteria[0].id] = f.variant.criteria[0].expected;
  const open = f.practical.transfer.criteria.find(c => c.input_type === 'self' && !c.critical);
  f.attempt.transfer.criteria[open.id].judgment = 'fail';
  assert.equal(assess(f).level, 2);
});

test('a critical transfer failure blocks levels 2 and 3 and remains visible', () => {
  const f = filled(setup());
  f.attempt.transfer.criteria[f.practical.transfer.criteria[0].id].observed = 2;
  const r = assess(f); assert.equal(r.level, 1); assert.equal(r.criticalFailures.length, 1);
});

test('number comparison requires a number, not a numeric string; null is explicit unknown', () => {
  const f = filled(setup(), 1);
  const c = f.variant.criteria.find(c => c.input_type === 'number');
  f.attempt.answers[c.id] = String(c.expected); assert.equal(assess(f).level, 0);
  f.attempt.answers[c.id] = null; assert.equal(assess(f).complete, true);
  delete f.attempt.answers[c.id]; assert.equal(assess(f).complete, false);
});

test('a URL and pass checkbox do not complete evidence; raw output and locator are required', () => {
  const f = filled(setup()); const entry = f.attempt.practice.criteria[f.practical.criteria[0].id];
  delete entry.excerpt; assert.equal(assess(f).complete, false);
  entry.excerpt = '通过'; assert.equal(assess(f).complete, false);
  entry.excerpt = 'effects_count=1'; entry.actual = 'ok'; assert.equal(assess(f).complete, false);
  entry.actual = 'effects_count=1'; assert.equal(assess(f).level, 3);
});

test('already correct boundary outputs are acceptable; no invented initial bug required', () => {
  const f = filled(setup());
  for (const e of Object.values(f.attempt.practice.criteria)) e.explanation = '原实现已满足边界，首次运行即得到所示结果。';
  assert.equal(assess(f).level, 3);
});

test('explicitly not running a practice criterion is complete but cannot confer practice level', () => {
  const f = filled(setup());
  f.attempt.practice.criteria[f.practical.criteria[0].id] = { run_status: 'not_run' };
  assert.equal(assess(f).complete, true); assert.equal(assess(f).level, 1);
});

test('first completion exposes answers only after saving and does not invalidate itself', () => {
  const f = filled(setup(), 1); assert.equal(f.state.exposures.length, 0);
  const completed = done(f); assert.equal(completed.state.exposures.length, 1);
  assert.equal(evaluateAttempt(definition, completed.state.attempts[0], completed.state.exposures).validity, 'valid');
  const repeat = setup({ state: completed.state, id: 'repeat' }); assert.equal(repeat.attempt.mode, 'practice');
  const b = setup({ state: completed.state, id: 'unexposed', variant: 'B' }); assert.equal(b.attempt.mode, 'assessment');
});

test('simultaneously opened draft cannot bypass exposure caused by another completed attempt', () => {
  const a = filled(setup(), 1);
  const simultaneous = setup({ state: a.state, id: 'second' });
  const state = completeAttempt(simultaneous.state, definition, 'first', { now: finished }).state;
  const f = filled({ ...simultaneous, state }, 3);
  assert.equal(assess(f).validity, 'invalid'); assert(assess(f).reasons.includes('answer_exposed'));
});

test('substantial assistance or external exposure persists after abandoning/changing the draft', () => {
  for (const patch of [{ assistance: 'substantial' }, { external_answer_seen: true }]) {
    const f = setup(); let state = updateDraft(f.state, f.attempt.id, patch);
    state = updateDraft(state, f.attempt.id, { assistance: 'independent', external_answer_seen: false });
    assert.equal(state.exposures.length, 1);
    const fresh = setup({ state, id: 'fresh' }); assert.equal(fresh.attempt.mode, 'practice');
    const original = filled({ ...f, state }, 1); assert.equal(assess(original).validity, 'invalid');
  }
});

test('syntax-only help remains eligible; practice mode never updates the current chart', () => {
  const f = filled(setup(), 3); f.state = updateDraft(f.state, f.attempt.id, { assistance: 'syntax_only' });
  assert.equal(done(f).result.validity, 'valid');
  f.state = updateDraft(f.state, f.attempt.id, { mode: 'practice' });
  const r = done(f); assert.equal(r.result.level, 3); assert.equal(r.result.validity, 'invalid');
  assert.equal(currentAxes(r.state, definition)[4].level, null);
});

test('latest valid reassessment can downgrade; newer drafts retain previous date and level', () => {
  const first = done(filled(setup(), 1));
  const b = filled(setup({ state: first.state, id: 'b', variant: 'B', now: '2026-10-12T08:00:00Z' }), 0);
  const interim = currentAxes(b.state, definition)[4];
  assert.equal(interim.level, 1); assert.equal(interim.completedAt, finished); assert.equal(interim.hasNewerDraft, true);
  const second = done(b, '2026-10-12T08:05:00Z'); assert.equal(currentAxes(second.state, definition)[4].level, 0);
  const repeat = filled(setup({ state: second.state, id: 'again', now: '2026-10-13T08:00:00Z' }), 3);
  const practice = done(repeat, '2026-10-13T08:05:00Z'); assert.equal(currentAxes(practice.state, definition)[4].level, 0);
  assert.throws(() => updateDraft(second.state, 'b', { answers: {} }), /仅草稿/);
});

test('actual shared practical feedback exposes both variants but preserves the original valid record', () => {
  const completed = done(filled(setup(), 2)).state;
  assert.equal(completed.exposures.length, 2);
  assert.equal(currentAxes(completed, definition)[4].level, 2);
  assert.equal(setup({ state: completed, id: 'b', variant: 'B' }).attempt.mode, 'practice');
  const f = filled(setup(), 3); f.attempt.practice.status = 'not_run';
  f.state = updateDraft(f.state, f.attempt.id, { practice: f.attempt.practice });
  assert.equal(done(f).state.exposures.length, 2); // attempted transfer is sufficient
});

test('reported section with every criterion explicitly not_run does not expose the other variant', () => {
  const f = filled(setup(), 2);
  for (const id of Object.keys(f.attempt.practice.criteria)) f.attempt.practice.criteria[id] = { run_status: 'not_run' };
  f.state = updateDraft(f.state, f.attempt.id, { practice: f.attempt.practice });
  const completed = done(f).state;
  assert.equal(completed.exposures.length, 1);
  assert.equal(setup({ state: completed, id: 'b', variant: 'B' }).attempt.mode, 'assessment');
});

test('schema-1 import restores shared practical exposure omitted by older backups', () => {
  const completed = done(filled(setup(), 3)).state;
  const legacy = clone(completed); legacy.exposures = legacy.exposures.filter(e => e.exposure_key === legacy.attempts[0].exposure_key);
  assert.equal(validateBackup(legacy), true);
  const imported = mergeBackup(createState(), exportBackup(legacy), definition);
  assert.equal(imported.exposures.length, 2);
  assert.equal(currentAxes(imported, definition)[4].level, 3);
  assert.equal(setup({ state: imported, id: 'b', variant: 'B' }).attempt.mode, 'practice');
});

test('completed practice critical failure remains until an explicit pass; not_run and drafts cannot clear it', () => {
  const first = done(filled(setup(), 1)).state;
  const bad = filled(setup({ state: first, id: 'bad', now: '2026-10-12T08:00:00Z' }), 3);
  const criterion = bad.practical.criteria[0].id;
  bad.attempt.practice.criteria[criterion].observed = 2;
  bad.state = updateDraft(bad.state, 'bad', { practice: bad.attempt.practice });
  const failed = done(bad, '2026-10-12T08:05:00Z').state;
  let rec = recommendation(failed, definition, { foundation: 'passed' });
  assert.equal(rec.kind, 'critical'); assert.equal(rec.criterionId, criterion); assert.equal(rec.fromPractice, true);
  assert.equal(currentAxes(failed, definition)[4].level, 1);
  const notRun = done(filled(setup({ state: failed, id: 'not-run', now: '2026-10-13T08:00:00Z' }), 1), '2026-10-13T08:05:00Z').state;
  assert.equal(recommendation(notRun, definition, { foundation: 'passed' }).criterionId, criterion);
  const fixed = filled(setup({ state: notRun, id: 'fixed', now: '2026-10-14T08:00:00Z' }), 3);
  assert.equal(recommendation(fixed.state, definition, { foundation: 'passed' }).criterionId, criterion);
  const passed = done(fixed, '2026-10-14T08:05:00Z').state;
  assert.notEqual(recommendation(passed, definition, { foundation: 'passed' }).kind, 'critical');
  assert.equal(currentAxes(passed, definition)[4].level, 1);
});

test('rubric, task or content revision cannot silently contribute to a current chart', () => {
  const completed = done(filled(setup(), 3)).state;
  for (const change of [d => d.assessment_version = '0.2.0', d => d.rubric_version = '0.2.0', d => d.content_hash = 'new-hash', d => d.tasks.find(t => t.id === 'AT09').task_version = '2']) {
    const next = clone(definition); change(next);
    assert.equal(currentAxes(completed, next)[4].level, null);
    assert.equal(mergeBackup(createState(), exportBackup(completed), next).attempts.length, 1);
  }
});

test('a role preference changes recommendation priority, never the recorded axis level', () => {
  const completed = done(filled(setup(), 2)).state;
  const before = currentAxes(completed, definition);
  recommendation(completed, definition, { roleId: 'agent-infra', foundation: 'passed' });
  assert.deepEqual(currentAxes(completed, definition), before);
});

test('draft choices do not leak correctness through recommendations', () => {
  const right = filled(setup(), 1); const wrong = filled(setup(), 0);
  assert.deepEqual(recommendation(right.state, definition), recommendation(wrong.state, definition));
});

test('submission completeness errors do not reveal foundation correctness', () => {
  const right = filled(setup(), 3); const wrong = filled(setup(), 3);
  wrong.attempt.answers[wrong.variant.criteria[0].id] = null;
  delete right.attempt.practice.criteria[right.practical.criteria[0].id].excerpt;
  delete wrong.attempt.practice.criteria[wrong.practical.criteria[0].id].excerpt;
  assert.equal(assess(right).complete, false); assert.equal(assess(wrong).complete, false);
  assert.deepEqual(assess(right).missing, assess(wrong).missing);
  for (const f of [right, wrong]) { f.attempt.practice.status = 'unselected'; f.attempt.transfer.status = 'unselected'; }
  assert.deepEqual(assess(right).missing, assess(wrong).missing);
});

test('critical completed failure outranks missing axes; foundation gate is independent', () => {
  const completed = done(filled(setup(), 0)).state;
  const r = recommendation(completed, definition, { roleId: 'ai-fullstack', foundation: 'unknown' });
  assert.equal(r.kind, 'critical'); assert.equal(r.foundationReminder, true);
  assert.deepEqual(r.question_ids, ['Q027']); assert.deepEqual(r.acceptance_ids, ['M4-C1']);
  assert.equal(recommendation(createState(), definition).kind, 'foundation');
  assert.equal(recommendation(createState(), definition, { foundation: 'passed' }).kind, 'diagnostic');
});

test('backup round trip recomputes records and old backup cannot erase exposure', () => {
  const f = filled(setup(), 3); const old = exportBackup(f.state); const completed = done(f).state;
  const merged = mergeBackup(completed, old, definition);
  assert.deepEqual(merged, completed);
  assert.deepEqual(mergeBackup(createState(), exportBackup(completed), definition), completed);
  assert.equal(setup({ state: merged, id: 'later' }).attempt.mode, 'practice');
});

test('cross-device later feedback does not invalidate an earlier completed independent record', () => {
  const day1 = done(filled(setup({ id: 'day1' }), 1)).state;
  const day2 = done(filled(setup({ id: 'day2', now: '2026-10-12T08:00:00Z' }), 3), '2026-10-12T08:05:00Z').state;
  const merged = mergeBackup(day1, exportBackup(day2), definition);
  assert.equal(currentAxes(merged, definition)[4].attemptId, 'day1');
  assert.equal(currentAxes(merged, definition)[4].level, 1);
  assert.equal(evaluateAttempt(definition, merged.attempts.find(a => a.id === 'day2'), merged.exposures).validity, 'invalid');
});

test('an exposed draft cannot regain independence through an earlier completion timestamp', () => {
  const f = filled(setup({ id: 'draft' }), 3);
  const other = setup({ state: f.state, id: 'feedback' });
  const completed = done(filled(other, 1), '2026-10-11T08:10:00Z').state;
  const late = completeAttempt(completed, definition, 'draft', { now: finished });
  assert.equal(late.state.attempts.find(a => a.id === 'draft').mode, 'practice');
  assert.equal(currentAxes(late.state, definition)[4].attemptId, 'feedback');
});

test('local draft wins draft conflict, completed supersedes draft, identities must match', () => {
  const f = setup(); const local = filled(f, 1).state;
  const imported = filled(f, 3).state;
  assert.deepEqual(mergeBackup(local, exportBackup(imported), definition).attempts, local.attempts);
  const completed = done(filled(f, 3)).state;
  assert.equal(mergeBackup(local, exportBackup(completed), definition).attempts[0].attempt_status, 'completed');
  const wrong = clone(imported); wrong.attempts[0].dimension_id = 'D1';
  assert.throws(() => mergeBackup(local, exportBackup(wrong), definition), /身份冲突/);
});

test('same-ID completed conflict, invented grade and missing exposure are rejected without mutation', () => {
  const state = done(filled(setup(), 1)).state; const original = clone(state);
  const collision = clone(state); collision.attempts[0].answers[Object.keys(collision.attempts[0].answers)[0]] = null;
  assert.throws(() => mergeBackup(state, JSON.stringify(collision), definition), /同 ID/);
  const grade = clone(state); grade.attempts[0].level = 3;
  assert.throws(() => mergeBackup(state, JSON.stringify(grade), definition), /不支持字段/);
  const missing = clone(state); missing.exposures = [];
  assert.throws(() => mergeBackup(state, JSON.stringify(missing), definition), /暴露历史/);
  assert.deepEqual(state, original);
});

test('merge preserves completion order and incompatible ordering is rejected', () => {
  const first = done(filled(setup(), 3)).state;
  const second = done(filled(setup({ state: first, variant: 'B', id: 'b', now: '2026-10-12T08:00:00Z' }), 0), '2026-10-12T08:05:00Z').state;
  assert.deepEqual(mergeBackup(second, exportBackup(first), definition).completed_order, ['first', 'b']);
  const reversed = clone(second); reversed.completed_order.reverse();
  assert.throws(() => mergeBackup(second, JSON.stringify(reversed), definition), /反馈不能保护|顺序冲突/);
});

test('malformed and hostile backups are bounded and rejected', () => {
  for (const input of ['{', '{"__proto__":{}}', ' '.repeat(5 * 1024 * 1024 + 1), JSON.stringify({ ...createState(), attempts: [{ level: 3 }] })]) {
    assert.throws(() => mergeBackup(createState(), input, definition));
  }
});

test('all recommendation references exist in the shared question, learning and roadmap sources', () => {
  const questions = JSON.parse(readFileSync(new URL('../data/questions.json', import.meta.url), 'utf8'));
  const learning = JSON.parse(readFileSync(new URL('../data/learning.json', import.meta.url), 'utf8'));
  const roadmap = JSON.parse(readFileSync(new URL('../data/roadmap.json', import.meta.url), 'utf8'));
  const refs = {
    question_ids: new Set(questions.map(q => q.id)), guide_ids: new Set(learning.guides.map(g => g.id)), lab_ids: new Set(learning.labs.map(l => l.id)),
    milestone_ids: new Set(roadmap.milestones.map(m => m.id)),
    acceptance_ids: new Set(roadmap.milestones.flatMap(m => m.acceptance.map(c => c.id))),
  };
  for (const task of definition.tasks) for (const c of (task.type === 'scenario' ? task.variants.flatMap(v => v.criteria) : [...task.criteria, ...task.transfer.criteria])) {
    for (const [key, available] of Object.entries(refs)) for (const id of c.recommendation[key]) assert(available.has(id), `${c.id}: missing ${key} ${id}`);
  }
});
