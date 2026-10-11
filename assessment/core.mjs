/** Pure self-check rules. No DOM, storage, networking, clock or random identifiers. */
const KIND = 'ai-interview-self-check-backup';
const MAX_BYTES = 5 * 1024 * 1024;
const MAX_RECORDS = 2000;
const copy = value => JSON.parse(JSON.stringify(value));
const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
const text = value => typeof value === 'string' && value.trim().length > 0;
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const same = (a, b) => canonical(a) === canonical(b);
const nonAnswer = value => /^(通过|成功|pass|passed|ok)$/i.test(value.trim());

function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
  return JSON.stringify(value);
}

function iso(value) {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value) && Number.isFinite(Date.parse(value));
}

function definitions(definition, dimensionId, variantId) {
  const dimension = definition.dimensions.find(item => item.id === dimensionId);
  assert(dimension, '未知领域');
  const scenario = definition.tasks.find(item => item.id === dimension.scenario_task_id);
  const practice = definition.tasks.find(item => item.id === dimension.practice_task_id);
  const variant = scenario.variants.find(item => item.id === variantId);
  assert(variant, '未知情境变式');
  return { dimension, scenario, practice, variant };
}

function hasActualPractice(attempt) {
  return ['practice', 'transfer'].some(name => attempt[name]?.status === 'reported' &&
    Object.values(attempt[name].criteria || {}).some(entry => ['ran', 'failed'].includes(entry?.run_status)));
}

function addRelatedFeedback(state, definition, attempt, baseEvent) {
  if (!hasActualPractice(attempt)) return;
  const { scenario } = definitions(definition, attempt.dimension_id, attempt.scenario_variant_id);
  for (const variant of scenario.variants) {
    if (state.exposures.some(event => event.source === 'feedback' && event.trigger_attempt_id === attempt.id && event.exposure_key === variant.exposure_key)) continue;
    state.exposures.push({ ...copy(baseEvent), id: 'feedback:' + attempt.id + ':' + variant.id, exposure_key: variant.exposure_key });
  }
}

export function createState() {
  return { schema_version: 1, kind: KIND, attempts: [], completed_order: [], exposures: [], invalidations: [] };
}

export function createAttempt(state, definition, { id, now, dimensionId, variantId, roleId, mode = 'assessment' }) {
  assert(text(id) && !state.attempts.some(item => item.id === id), '尝试 ID 缺失或重复');
  assert(iso(now), '开始时间必须是 ISO 时间');
  assert(definition.roles.includes(roleId), '未知岗位');
  assert(['assessment', 'practice'].includes(mode), '未知记录模式');
  const { scenario, practice, variant } = definitions(definition, dimensionId, variantId);
  const exposed = state.exposures.some(item => item.exposure_key === variant.exposure_key);
  const attempt = {
    id, assessment_version: definition.assessment_version, rubric_version: definition.rubric_version,
    definition_hash: definition.content_hash || null, dimension_id: dimensionId,
    scenario_variant_id: variantId, exposure_key: variant.exposure_key,
    task_versions: { [scenario.id]: scenario.task_version, [practice.id]: practice.task_version },
    started_at: now, completed_at: null, attempt_status: 'draft', role_id: roleId,
    mode: exposed ? 'practice' : mode, assistance: 'independent', external_answer_seen: false,
    answers: {}, practice: { status: 'unselected', context: {}, criteria: {} },
    transfer: { status: 'unselected', context: {}, criteria: {}, prediction: '', tradeoff: '' },
  };
  const next = copy(state); next.attempts.push(attempt);
  return { state: next, attempt: copy(attempt) };
}

export function updateDraft(state, id, patch) {
  const next = copy(state);
  const attempt = next.attempts.find(item => item.id === id);
  assert(attempt && attempt.attempt_status === 'draft', '仅草稿可以修改');
  const fields = new Set(['answers', 'practice', 'transfer', 'assistance', 'external_answer_seen', 'mode', 'role_id']);
  assert(patch && typeof patch === 'object' && !Array.isArray(patch), '草稿更新必须是对象');
  assert(Object.keys(patch).every(key => fields.has(key)), '不能改写尝试身份、版本或完成时间');
  Object.assign(attempt, copy(patch));
  // External answers/major assistance are remembered even if this draft is abandoned or changed back.
  if ((attempt.external_answer_seen || attempt.assistance === 'substantial') &&
      !next.exposures.some(event => event.id === 'external:' + id)) {
    next.exposures.push({ id: 'external:' + id, exposure_key: attempt.exposure_key, source: 'external',
      at: attempt.started_at, trigger_attempt_id: null, protected_attempt_ids: [...next.completed_order] });
  }
  return next;
}

function answerMatches(criterion, value) {
  if (value === null) return false; // explicit “不知道”, distinct from an absent answer
  if (criterion.input_type === 'number') return typeof value === 'number' && Number.isFinite(value) && value === criterion.expected;
  if (criterion.input_type === 'text') return typeof value === 'string' && value.trim() === criterion.expected;
  if (criterion.input_type === 'choice') return typeof value === 'string' && criterion.options.some(option => option.value === value) && value === criterion.expected;
  return false;
}

function resultFor(criterion, stage, status, source, missing = []) {
  return { criterionId: criterion.id, label: criterion.label, stage, status, source,
    critical: Boolean(criterion.critical), missing, explanation: criterion.explanation,
    recommendation: criterion.recommendation };
}

function inspectEvidence(section, criteria, stage) {
  const missing = [];
  const entries = section?.criteria || {};
  const results = criteria.map(criterion => {
    const entry = entries[criterion.id];
    if (!entry || !['ran', 'failed', 'not_run'].includes(entry.run_status)) {
      missing.push(criterion.id + ':run_status');
      return resultFor(criterion, stage, 'missing', 'self_record', ['run_status']);
    }
    if (entry.run_status === 'not_run') return resultFor(criterion, stage, 'not_run', 'self_record');
    const absent = ['input', 'actual', 'evidence_ref', 'locator', 'excerpt', 'explanation'].filter(field => !text(entry[field]));
    if (text(entry.actual) && nonAnswer(entry.actual)) absent.push('actual:需要原始输出');
    if (text(entry.excerpt) && nonAnswer(entry.excerpt)) absent.push('excerpt:需要具体片段');
    if (criterion.input_type === 'self') {
      if (!['pass', 'fail', 'unknown'].includes(entry.judgment)) absent.push('judgment');
    } else if (!own(entry, 'observed')) absent.push('observed');
    missing.push(...absent.map(field => criterion.id + ':' + field));
    const passed = entry.run_status === 'ran' && (criterion.input_type === 'self' ? entry.judgment === 'pass' : answerMatches(criterion, entry.observed));
    const status = entry.run_status === 'failed' || (!absent.length && !passed) ? 'fail' : absent.length ? 'missing' : 'pass';
    return resultFor(criterion, stage, status, criterion.input_type === 'self' ? 'self_judgment' : 'reported_value_comparison', absent);
  });
  if (Object.values(entries).some(entry => entry && ['ran', 'failed'].includes(entry.run_status))) {
    for (const field of ['run_at', 'environment', 'version', 'model_mode']) {
      if (!text(section.context?.[field])) missing.push(stage + ':context.' + field);
    }
    if (text(section.context?.run_at) && !/^\d{4}-\d{2}-\d{2}(T.*)?$/.test(section.context.run_at)) missing.push(stage + ':context.run_at');
    if (text(section.context?.model_mode) && !['stub', 'real', 'none'].includes(section.context.model_mode)) missing.push(stage + ':context.model_mode');
  }
  return { results, missing, passed: results.every(item => item.status === 'pass') && !missing.length };
}

export function evaluateAttempt(definition, attempt, exposures = []) {
  const reasons = [];
  const missing = [];
  if (attempt.assessment_version !== definition.assessment_version || attempt.rubric_version !== definition.rubric_version ||
      attempt.definition_hash !== (definition.content_hash || null)) {
    return { complete: false, validity: 'invalid', level: null, criteria: [], criticalFailures: [], reasons: ['definition_mismatch'], missing: [] };
  }
  let resolved;
  try { resolved = definitions(definition, attempt.dimension_id, attempt.scenario_variant_id); }
  catch { return { complete: false, validity: 'invalid', level: null, criteria: [], criticalFailures: [], reasons: ['unknown_task'], missing: [] }; }
  const { scenario, practice, variant } = resolved;
  if (attempt.task_versions?.[scenario.id] !== scenario.task_version || attempt.task_versions?.[practice.id] !== practice.task_version) reasons.push('task_version_mismatch');
  if (attempt.exposure_key !== variant.exposure_key) reasons.push('exposure_key_mismatch');
  if (attempt.mode !== 'assessment') reasons.push('practice_mode');
  if (!['independent', 'syntax_only'].includes(attempt.assistance)) reasons.push('assisted');
  if (attempt.external_answer_seen !== false) reasons.push('external_answer_seen');
  if (exposures.some(item => item.exposure_key === variant.exposure_key &&
      !(item.protected_attempt_ids || []).includes(attempt.id) &&
      // A later event from another device must not retrospectively expose an earlier completed record.
      !(attempt.attempt_status === 'completed' && Date.parse(attempt.completed_at) < Date.parse(item.at)))) reasons.push('answer_exposed');
  const criteria = variant.criteria.map(criterion => {
    const answered = own(attempt.answers || {}, criterion.id);
    if (!answered) missing.push(criterion.id + ':answer');
    return resultFor(criterion, 'foundation', !answered ? 'missing' : answerMatches(criterion, attempt.answers[criterion.id]) ? 'pass' : 'fail', 'answer_check');
  });
  const foundationPassed = criteria.every(item => item.status === 'pass');
  const practiceReported = attempt.practice?.status === 'reported';
  const practical = practiceReported ? inspectEvidence(attempt.practice, practice.criteria, 'practice') : {
    results: practice.criteria.map(criterion => resultFor(criterion, 'practice', 'not_run', 'self_record')), missing: [], passed: false,
  };
  criteria.push(...practical.results);
  const transferReported = attempt.transfer?.status === 'reported';
  const transfer = transferReported ? inspectEvidence(attempt.transfer, practice.transfer.criteria, 'transfer') : {
    results: practice.transfer.criteria.map(criterion => resultFor(criterion, 'transfer', 'not_run', 'self_record')), missing: [], passed: false,
  };
  criteria.push(...transfer.results);
  // Completeness must not depend on correctness: submission errors must not become an answer oracle.
  if (!['not_run', 'reported'].includes(attempt.practice?.status)) missing.push('practice:choose_status');
  if (practiceReported) missing.push(...practical.missing);
  if (!['not_run', 'reported'].includes(attempt.transfer?.status)) missing.push('transfer:choose_status');
  if (transferReported) {
    missing.push(...transfer.missing);
    if (!text(attempt.transfer.prediction)) missing.push('transfer:prediction');
    if (!text(attempt.transfer.tradeoff)) missing.push('transfer:tradeoff');
  }
  const criticalFailures = criteria.filter(item => item.critical && item.status === 'fail');
  let level = foundationPassed ? 1 : 0;
  if (foundationPassed && practical.passed && !criticalFailures.length) {
    level = 2;
    if (transfer.passed && text(attempt.transfer.prediction) && text(attempt.transfer.tradeoff)) level = 3;
  }
  const complete = missing.length === 0;
  return { complete, validity: complete ? (reasons.length ? 'invalid' : 'valid') : 'pending',
    level: complete ? level : null, criteria, criticalFailures, reasons, missing,
    source: level > 1 ? '本人实践自记，未独立核验' : '情境答案自动核对；独立条件由本人声明' };
}

export function completeAttempt(state, definition, id, { now }) {
  assert(iso(now), '完成时间必须是 ISO 时间');
  const next = copy(state);
  const attempt = next.attempts.find(item => item.id === id);
  assert(attempt?.attempt_status === 'draft', '尝试不存在或已经完成');
  assert(Date.parse(now) >= Date.parse(attempt.started_at), '完成时间早于开始时间');
  const result = evaluateAttempt(definition, attempt, next.exposures);
  assert(result.complete, '尚有未填写项：' + result.missing.join('、'));
  // Preserve the eligibility decision made before submission, including after a local clock rollback.
  if (result.validity !== 'valid') attempt.mode = 'practice';
  attempt.attempt_status = 'completed'; attempt.completed_at = now;
  next.completed_order.push(id);
  const { variant } = definitions(definition, attempt.dimension_id, attempt.scenario_variant_id);
  const event = { id: 'feedback:' + id, exposure_key: variant.exposure_key, source: 'feedback',
    at: now, trigger_attempt_id: id, protected_attempt_ids: [...next.completed_order] };
  next.exposures.push(event);
  // Shared practical answers overlap both scenario variants. Treat their feedback conservatively.
  addRelatedFeedback(next, definition, attempt, event);
  return { state: next, result };
}

export function currentAxes(state, definition) {
  const positions = new Map(state.completed_order.map((id, index) => [id, index]));
  const invalid = new Set(state.invalidations.map(item => item.attempt_id));
  return definition.dimensions.map(dimension => {
    const candidates = state.attempts.filter(item => item.dimension_id === dimension.id && item.attempt_status === 'completed' && !invalid.has(item.id))
      .map(attempt => ({ attempt, result: evaluateAttempt(definition, attempt, state.exposures) }))
      .filter(item => item.result.complete && item.result.validity === 'valid')
      .sort((a, b) => positions.get(b.attempt.id) - positions.get(a.attempt.id));
    const selected = candidates[0];
    const draft = state.attempts.filter(item => item.dimension_id === dimension.id && item.assessment_version === definition.assessment_version && item.rubric_version === definition.rubric_version && item.definition_hash === (definition.content_hash || null) && item.attempt_status === 'draft')
      .filter(item => !selected || Date.parse(item.started_at) >= Date.parse(selected.attempt.completed_at));
    return { dimensionId: dimension.id, name: dimension.name, level: selected?.result.level ?? null,
      attemptId: selected?.attempt.id ?? null, completedAt: selected?.attempt.completed_at ?? null,
      hasNewerDraft: draft.length > 0, draftIds: draft.map(item => item.id), source: selected?.result.source ?? '未测',
      criteria: selected?.result.criteria ?? [], criticalFailures: selected?.result.criticalFailures ?? [],
      assessmentVersion: definition.assessment_version };
  });
}

export function recommendation(state, definition, { roleId, foundation = 'unknown' } = {}) {
  const axes = currentAxes(state, definition);
  const results = axes.flatMap(axis => axis.criteria.map(item => ({ ...item, dimensionId: axis.dimensionId })));
  // Do not derive feedback from unfinished answers: that would expose the current scenario before submission.
  // A completed practice can reveal a real failure even though it cannot replace the radar value.
  // Only an explicit later pass of that stable criterion clears it; not_run is not a repair.
  const criticalEvents = new Map();
  const invalid = new Set(state.invalidations.map(item => item.attempt_id));
  for (const id of state.completed_order) {
    const attempt = state.attempts.find(item => item.id === id);
    if (!attempt || invalid.has(id)) continue;
    const result = evaluateAttempt(definition, attempt, state.exposures);
    if (!result.complete || result.reasons.some(reason => ['definition_mismatch', 'unknown_task', 'task_version_mismatch', 'exposure_key_mismatch'].includes(reason))) continue;
    for (const item of result.criteria) if (item.critical && ['pass', 'fail'].includes(item.status)) {
      criticalEvents.set(item.criterionId, { ...item, dimensionId: attempt.dimension_id, attemptId: id, practice: result.validity !== 'valid' });
    }
  }
  const critical = [...criticalEvents.values()].find(item => item.status === 'fail');
  if (critical) return { kind: 'critical', criterionId: critical.criterionId, dimensionId: critical.dimensionId,
    attemptId: critical.attemptId, fromPractice: critical.practice, pending: false,
    ...critical.recommendation, foundationReminder: foundation !== 'passed' };
  if (foundation !== 'passed') return { kind: 'foundation', action: foundation === 'failed' ? '先补 A1/A2 暴露的工程缺口' : '先完成 A1/A2 局部自测', reason: '入口基础不由雷达档位豁免。', deliverable: '保留代码、启动说明和一个错误路径的实际输出。', milestone_ids: ['M0'], question_ids: ['Q047', 'Q058'], guide_ids: [], lab_ids: [], acceptance_ids: ['M0-C1', 'M0-C3'] };
  const priority = definition.role_priorities[roleId] || definition.dimensions.map(item => item.id);
  const missing = priority.map(id => axes.find(axis => axis.dimensionId === id)).find(axis => axis?.level === null);
  if (missing) return { kind: 'diagnostic', dimensionId: missing.dimensionId, action: '先完成' + missing.name + '的情境诊断', reason: '缺测表示尚无记录，不表示能力低。', deliverable: '一次完整、如实记录辅助方式的情境尝试。', question_ids: [], guide_ids: [], lab_ids: [], milestone_ids: [], acceptance_ids: [] };
  for (const id of priority) {
    const item = results.find(result => result.dimensionId === id && ['fail', 'not_run'].includes(result.status));
    if (item) return { kind: 'gap', dimensionId: id, criterionId: item.criterionId, ...item.recommendation };
  }
  return { kind: 'maintain', action: '带一个新的约束回到作品验收', reason: '本轮条件已满足不代表完整领域或里程碑已通过。', deliverable: '一个新场景、实际运行记录和取舍说明。', milestone_ids: ['M6'], acceptance_ids: ['M6-C3'], question_ids: ['Q058', 'Q069'], guide_ids: ['G03'], lab_ids: [] };
}

function checkShape(value, depth = 0) {
  assert(depth <= 16, '备份嵌套过深');
  if (typeof value === 'string') assert(value.length <= 50000, '单项文本过长');
  if (typeof value === 'number') assert(Number.isFinite(value), '无效数值');
  if (Array.isArray(value)) { assert(value.length <= 20000, '数组过长'); value.forEach(item => checkShape(item, depth + 1)); }
  else if (value && typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) {
      assert(!['__proto__', 'prototype', 'constructor'].includes(key), '备份含保留字段');
      checkShape(item, depth + 1);
    }
  }
}

function allowed(object, fields, label) {
  assert(object && typeof object === 'object' && !Array.isArray(object), label + '须为对象');
  assert(Object.keys(object).every(key => fields.includes(key)), label + '含不支持字段');
}

export function validateBackup(value) {
  checkShape(value);
  allowed(value, ['schema_version', 'kind', 'attempts', 'completed_order', 'exposures', 'invalidations'], '备份');
  assert(value.schema_version === 1 && value.kind === KIND, '不支持的备份格式');
  for (const key of ['attempts', 'completed_order', 'exposures', 'invalidations']) assert(Array.isArray(value[key]) && value[key].length <= MAX_RECORDS, key + '数量过多或格式错误');
  const ids = new Set();
  for (const item of value.attempts) {
    allowed(item, ['id', 'assessment_version', 'rubric_version', 'definition_hash', 'dimension_id', 'scenario_variant_id', 'exposure_key', 'task_versions', 'started_at', 'completed_at', 'attempt_status', 'role_id', 'mode', 'assistance', 'external_answer_seen', 'answers', 'practice', 'transfer'], '尝试');
    for (const field of ['id', 'assessment_version', 'rubric_version', 'dimension_id', 'scenario_variant_id', 'exposure_key', 'role_id']) assert(text(item[field]), '尝试缺少 ' + field);
    assert(!ids.has(item.id), '重复尝试 ID'); ids.add(item.id);
    assert(item.definition_hash === null || text(item.definition_hash), '定义哈希无效');
    assert(iso(item.started_at) && ['draft', 'completed'].includes(item.attempt_status), '尝试日期或状态无效');
    assert(item.attempt_status === 'completed' ? iso(item.completed_at) && Date.parse(item.completed_at) >= Date.parse(item.started_at) : item.completed_at === null, '完成时间无效');
    assert(['assessment', 'practice'].includes(item.mode) && ['independent', 'syntax_only', 'substantial'].includes(item.assistance) && typeof item.external_answer_seen === 'boolean', '作答条件无效');
    for (const field of ['task_versions', 'answers']) assert(item[field] && typeof item[field] === 'object' && !Array.isArray(item[field]), field + '须为对象');
    for (const answer of Object.values(item.answers)) assert(answer === null || ['string', 'number', 'boolean'].includes(typeof answer), '答案类型无效');
    for (const sectionName of ['practice', 'transfer']) {
      const section = item[sectionName];
      allowed(section, ['status', 'context', 'criteria', ...(sectionName === 'transfer' ? ['prediction', 'tradeoff'] : [])], sectionName);
      assert(['unselected', 'not_run', 'reported'].includes(section.status), '实践状态无效');
      allowed(section.context, ['run_at', 'environment', 'version', 'model_mode'], '环境');
      assert(Object.values(section.context).every(v => typeof v === 'string'), '环境字段须为文本');
      assert(section.criteria && typeof section.criteria === 'object' && !Array.isArray(section.criteria), '实践判据须为对象');
      if (sectionName === 'transfer') assert(typeof section.prediction === 'string' && typeof section.tradeoff === 'string', '变式解释须为文本');
      for (const entry of Object.values(section.criteria)) {
        allowed(entry, ['run_status', 'observed', 'judgment', 'input', 'actual', 'evidence_ref', 'locator', 'excerpt', 'explanation'], '判据记录');
        assert(['ran', 'failed', 'not_run'].includes(entry.run_status), '运行状态无效');
        for (const field of ['input', 'actual', 'evidence_ref', 'locator', 'excerpt', 'explanation']) if (own(entry, field)) assert(typeof entry[field] === 'string', '证据字段须为文本');
        if (own(entry, 'observed')) assert(entry.observed === null || ['string', 'number', 'boolean'].includes(typeof entry.observed), '观测类型无效');
        if (own(entry, 'judgment')) assert(['pass', 'fail', 'unknown'].includes(entry.judgment), '自判状态无效');
      }
    }
  }
  const completed = new Set(value.attempts.filter(item => item.attempt_status === 'completed').map(item => item.id));
  assert(value.completed_order.length === completed.size && new Set(value.completed_order).size === completed.size && value.completed_order.every(id => completed.has(id)), '完成顺序与记录不一致');
  const exposureIds = new Set();
  for (const event of value.exposures) {
    allowed(event, ['id', 'exposure_key', 'source', 'at', 'trigger_attempt_id', 'protected_attempt_ids'], '暴露记录');
    assert(text(event.id) && !exposureIds.has(event.id) && text(event.exposure_key) && iso(event.at), '暴露记录身份或日期无效'); exposureIds.add(event.id);
    assert(['feedback', 'external'].includes(event.source), '暴露来源无效');
    assert(event.trigger_attempt_id === null || completed.has(event.trigger_attempt_id), '暴露事件未关联完整记录');
    assert(Array.isArray(event.protected_attempt_ids) && new Set(event.protected_attempt_ids).size === event.protected_attempt_ids.length && event.protected_attempt_ids.every(id => completed.has(id)), '暴露历史引用无效');
    if (event.source === 'feedback') assert(completed.has(event.trigger_attempt_id) && event.protected_attempt_ids.includes(event.trigger_attempt_id), '反馈必须发生于首次提交后');
  }
  for (const item of value.attempts.filter(attempt => attempt.attempt_status === 'completed')) {
    assert(value.exposures.some(event => event.source === 'feedback' && event.trigger_attempt_id === item.id && event.exposure_key === item.exposure_key && event.at === item.completed_at), '完整记录缺少对应答案暴露历史');
  }
  const positions = new Map(value.completed_order.map((id, i) => [id, i]));
  for (const event of value.exposures.filter(event => event.source === 'feedback')) {
    assert(event.protected_attempt_ids.every(id => positions.get(id) <= positions.get(event.trigger_attempt_id)), '反馈不能保护其后才完成的尝试');
  }
  const correctionIds = new Set();
  for (const item of value.invalidations) {
    allowed(item, ['id', 'attempt_id', 'at', 'reason'], '失效记录');
    assert(text(item.id) && !correctionIds.has(item.id) && completed.has(item.attempt_id) && iso(item.at) && text(item.reason), '失效记录无效'); correctionIds.add(item.id);
  }
  return true;
}

export function exportBackup(state) {
  validateBackup(state);
  const encoded = JSON.stringify(state, null, 2);
  assert(new TextEncoder().encode(encoded).length <= MAX_BYTES, '备份超过 5 MiB');
  return encoded;
}

function unionById(left, right, label) {
  const result = new Map(left.map(item => [item.id, copy(item)]));
  for (const item of right) {
    if (result.has(item.id)) {
      const previous = result.get(item.id);
      if (same(previous, item)) continue;
      if (label === '尝试') {
        for (const key of ['id', 'assessment_version', 'rubric_version', 'definition_hash', 'dimension_id', 'scenario_variant_id', 'exposure_key', 'task_versions', 'started_at']) {
          assert(same(previous[key], item[key]), '尝试同 ID 身份冲突，未导入：' + item.id);
        }
        if (previous.attempt_status === 'draft' && item.attempt_status === 'draft') continue; // local draft wins
      }
      // A saved draft may be followed by its immutable completed version.
      if (label === '尝试' && previous.attempt_status === 'draft' && item.attempt_status === 'completed') { result.set(item.id, copy(item)); continue; }
      if (label === '尝试' && previous.attempt_status === 'completed' && item.attempt_status === 'draft') continue;
      throw new Error(label + '同 ID 内容冲突，未导入：' + item.id);
    }
    result.set(item.id, copy(item));
  }
  return [...result.values()];
}

function mergeOrder(left, right, attempts) {
  const ids = new Set([...left, ...right]);
  const edges = new Map([...ids].map(id => [id, new Set()]));
  const indegree = new Map([...ids].map(id => [id, 0]));
  for (const list of [left, right]) for (let i = 1; i < list.length; i++) {
    if (!edges.get(list[i - 1]).has(list[i])) { edges.get(list[i - 1]).add(list[i]); indegree.set(list[i], indegree.get(list[i]) + 1); }
  }
  const dates = new Map(attempts.map(item => [item.id, item.completed_at || '']));
  const result = [];
  while (result.length < ids.size) {
    const available = [...ids].filter(id => indegree.get(id) === 0).sort((a, b) => dates.get(a).localeCompare(dates.get(b)) || a.localeCompare(b));
    assert(available.length, '备份完成顺序冲突，未导入');
    const id = available[0]; indegree.set(id, -1); result.push(id);
    for (const target of edges.get(id)) indegree.set(target, indegree.get(target) - 1);
  }
  return result;
}

export function mergeBackup(state, encoded, definition) {
  assert(typeof encoded === 'string' && new TextEncoder().encode(encoded).length <= MAX_BYTES, '备份超过 5 MiB 或不是文本');
  let imported;
  try { imported = JSON.parse(encoded); } catch { throw new Error('无法解析备份 JSON；当前记录未改变'); }
  validateBackup(state); validateBackup(imported);
  const next = createState();
  next.attempts = unionById(state.attempts, imported.attempts, '尝试');
  next.exposures = unionById(state.exposures, imported.exposures, '暴露');
  next.invalidations = unionById(state.invalidations, imported.invalidations, '失效');
  next.completed_order = mergeOrder(state.completed_order, imported.completed_order, next.attempts);
  // Imported grades are not accepted. Known-version records are recomputed; unknown versions remain readable history.
  for (const attempt of next.attempts) {
    const result = evaluateAttempt(definition, attempt, next.exposures);
    if (attempt.attempt_status === 'completed' && !result.reasons.includes('definition_mismatch') && !result.reasons.includes('unknown_task')) {
      assert(result.complete, '完整记录存在未填项：' + attempt.id);
      // Compatible schema-1 backups can predate the conservative shared-feedback rule.
      // Restore missing related exposure from the immutable completed record, never erase old events.
      if (!result.reasons.includes('task_version_mismatch') && !result.reasons.includes('exposure_key_mismatch')) {
        const base = next.exposures.find(event => event.source === 'feedback' && event.trigger_attempt_id === attempt.id && event.exposure_key === attempt.exposure_key);
        addRelatedFeedback(next, definition, attempt, base);
      }
    }
  }
  validateBackup(next);
  return next;
}
