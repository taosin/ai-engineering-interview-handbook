import * as Core from './core.mjs';

const STORAGE_KEY = 'ai-handbook-self-check-v1';
const PREFERENCES_KEY = STORAGE_KEY + ':preferences';
const GITHUB = 'https://github.com/taosin/ai-engineering-interview-handbook/blob/main/';
const ROLE_NAMES = { 'ai-fullstack': 'AI 全栈', 'agent-engineer': 'Agent 工程师', 'llm-application': 'LLM 应用开发', 'agent-infra': 'Agent Infra' };
const LEVEL_NAMES = ['基础条件未满足', '基础判断通过', '实现与自检', '变式、取舍与复检'];
const SHORT_NAMES = ['工程交付', '模型上下文', 'Agent 工具', '知识检索', '可靠性权限', '评测优化'];
const FIELD_NAMES = { input: '输入与条件', actual: '原始输出或关键观测', evidence_ref: '证据文件或链接', locator: '行号 / 事件 ID / 具体定位', excerpt: '相关日志或代码片段', explanation: '判断理由、本人职责与未验证边界' };
let definition;
let state = Core.createState();
let preferences = { roleId: 'agent-engineer', foundation: 'unknown' };
let activeDimensionId = null;
let activeAttemptId = null;
let lastStored = null;
let storageBlocked = false;
let originalUnreadable = null;

const byId = id => document.getElementById(id);
const currentAttempt = () => state.attempts.find(item => item.id === activeAttemptId);
const now = () => new Date().toISOString();
const uid = () => globalThis.crypto?.randomUUID?.() || 'attempt-' + Date.now() + '-' + Math.random().toString(36).slice(2);
const has = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

function node(tag, properties = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(properties)) {
    if (key.startsWith('on')) element.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'class') element.className = value;
    else if (key === 'text') element.textContent = value;
    else if (key === 'value' || key === 'checked' || key === 'disabled' || key === 'hidden') element[key] = value;
    else element.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child !== undefined && child !== null && child !== false) element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}

function replace(id, ...children) { byId(id).replaceChildren(...children); }
function paragraph(text, className = '') { return node('p', { class: className }, text); }
function display(value) { return value === null ? '不知道 / 未确认' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value ?? '未填写'); }
function dateLabel(value) {
  if (!value) return '尚未完成';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '日期不可读' : new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date);
}
function message(text, error = false, focus = false) {
  const box = byId('flash');
  box.classList.toggle('is-error', error);
  box.setAttribute('role', error ? 'alert' : 'status');
  box.textContent = text;
  if (focus) box.focus();
}
function storageNotice(text) {
  const box = byId('storage-notice');
  box.replaceChildren(document.createTextNode(text));
  box.hidden = !text;
  if (originalUnreadable) box.append(node('button', { type: 'button', class: 'button secondary', onClick: () => download('self-check-unreadable-backup.json', originalUnreadable) }, '先下载原始备份'));
}
function persist() {
  if (storageBlocked) { byId('save-status').textContent = '本次修改仅在内存中，请下载备份。'; return; }
  try {
    const disk = localStorage.getItem(STORAGE_KEY);
    if (disk && disk !== lastStored) state = Core.mergeBackup(state, disk, definition);
    const encoded = Core.exportBackup(state);
    localStorage.setItem(STORAGE_KEY, encoded);
    lastStored = encoded;
    byId('save-status').textContent = '已保存在当前浏览器 · ' + dateLabel(now());
    storageNotice('');
  } catch (error) {
    storageNotice('本次记录尚未保存到浏览器，内存中的填写仍保留。请先下载备份。原因：' + error.message);
    byId('save-status').textContent = '保存失败，不等于已经备份。';
  }
}
function persistPreferences() {
  try { localStorage.setItem(PREFERENCES_KEY, JSON.stringify(preferences)); }
  catch { message('方向选择仅在本次页面有效；个人答卷仍可下载备份。'); }
}
function patchDraft(patch, rerender = false) {
  try {
    state = Core.updateDraft(state, activeAttemptId, patch);
    persist();
    if (rerender) renderWorkspace();
    else renderModeLabel();
  } catch (error) { message(error.message, true); }
}
function resolve(dimensionId, variantId) {
  const dimension = definition.dimensions.find(item => item.id === dimensionId);
  const scenario = definition.tasks.find(item => item.id === dimension.scenario_task_id);
  const practice = definition.tasks.find(item => item.id === dimension.practice_task_id);
  return { dimension, scenario, practice, variant: scenario.variants.find(item => item.id === variantId) };
}
function exposed(variant) { return state.exposures.some(item => item.exposure_key === variant.exposure_key); }
function practiceOnly(attempt) {
  const exposureKey = attempt.exposure_key || resolve(attempt.dimension_id, attempt.scenario_variant_id).variant?.exposure_key;
  const hasExposure = state.exposures.some(item => item.exposure_key === exposureKey && !(item.protected_attempt_ids || []).includes(attempt.id));
  return attempt.mode === 'practice' || attempt.assistance === 'substantial' || attempt.external_answer_seen || hasExposure;
}
function hasPracticalAttempt(attempt) {
  return ['practice', 'transfer'].some(name => attempt[name]?.status === 'reported' && Object.values(attempt[name].criteria || {}).some(entry => ['ran', 'failed'].includes(entry.run_status)));
}
function feedbackScope(attempt) {
  return hasPracticalAttempt(attempt)
    ? '本次展示实践解析后，本领域 A/B 情境均记为已暴露，后续只能练习。'
    : '实践与变式全部未运行时，只曝光本次情境；另一未暴露情境仍可独立尝试。';
}
function renderModeLabel() {
  const attempt = currentAttempt();
  const target = byId('attempt-mode-note');
  if (target && attempt) target.textContent = practiceOnly(attempt) ? '本轮作为辅助或已暴露练习保留，不替换当前图。' : '本轮按独立自检记录；提交后才显示反馈。';
  const scope = byId('feedback-scope-note');
  if (scope && attempt) scope.textContent = feedbackScope(attempt);
}

function svgNode(tag, attributes, text) {
  const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  if (text !== undefined) element.textContent = text;
  return element;
}
function renderRadar(axes) {
  const chart = svgNode('svg', { viewBox: '0 0 420 365', role: 'img', 'aria-labelledby': 'radar-title radar-description' });
  chart.append(svgNode('title', { id: 'radar-title' }, '六维任务自检图'));
  chart.append(svgNode('desc', { id: 'radar-description' }, axes.map(axis => axis.name + '：' + (axis.level === null ? '未测' : axis.level + ' 档')).join('；') + '。完整文字见下方表格。'));
  const center = [210, 183], radius = 116;
  const point = (index, distance) => [center[0] + Math.cos((index * 60 - 90) * Math.PI / 180) * distance, center[1] + Math.sin((index * 60 - 90) * Math.PI / 180) * distance];
  for (let ring = 1; ring <= 3; ring++) {
    chart.append(svgNode('polygon', { points: axes.map((_, i) => point(i, radius * ring / 3).join(',')).join(' '), class: 'radar-grid' }));
    chart.append(svgNode('text', { x: 218, y: center[1] - radius * ring / 3 + 3, class: 'radar-tick' }, String(ring)));
  }
  axes.forEach((axis, index) => {
    const end = point(index, radius);
    chart.append(svgNode('line', { x1: center[0], y1: center[1], x2: end[0], y2: end[1], class: 'radar-axis' }));
    const label = point(index, radius + 33);
    const anchor = index === 0 || index === 3 ? 'middle' : index < 3 ? 'start' : 'end';
    chart.append(svgNode('text', { x: label[0], y: label[1] - 4, 'text-anchor': anchor, class: 'radar-label' }, SHORT_NAMES[index]));
    chart.append(svgNode('text', { x: label[0], y: label[1] + 13, 'text-anchor': anchor, class: 'radar-status' }, axis.level === null ? '未测' : axis.level + ' 档'));
  });
  if (axes.every(axis => axis.level !== null)) chart.append(svgNode('polygon', { points: axes.map((axis, i) => point(i, radius * axis.level / 3).join(',')).join(' '), class: 'radar-shape' }));
  axes.forEach((axis, index) => {
    if (axis.level !== null) {
      const value = point(index, radius * axis.level / 3);
      chart.append(svgNode('circle', { cx: value[0], cy: value[1], r: 4.5, class: 'radar-point' }));
    }
  });
  replace('radar', chart);
  byId('radar').setAttribute('aria-busy', 'false');
}

function fixedLink(id) {
  const value = definition.reference_urls?.[id];
  if (typeof value === 'string' && value.startsWith(GITHUB)) return value;
  if (/^M\d/.test(id)) return GITHUB + 'roadmap/milestones.md#' + id.split('-')[0].toLowerCase();
  if (/^Q\d+$/.test(id)) return GITHUB + 'questions/README.md';
  if (/^[GL]\d+$/.test(id)) return GITHUB + 'learning/README.md';
  return null;
}
function renderRecommendation() {
  const recommendation = Core.recommendation(state, definition, preferences);
  const labels = { critical: '先处理关键失败', foundation: '入口依赖', diagnostic: '补一项诊断', gap: '针对缺口补强', maintain: '继续验证边界' };
  const content = [node('span', { class: 'tag' }, labels[recommendation.kind] || '学习建议'), node('h3', {}, recommendation.action), paragraph(recommendation.reason, 'next-reason')];
  if (recommendation.kind === 'critical') content.push(paragraph((recommendation.fromPractice ? '来自已完成练习的本人记录；不改变当前图档位。' : '') + '未运行不能清除已记录的关键失败，需后续完整记录明确通过同一判据。', 'next-reason'));
  if (recommendation.foundationReminder) content.push(paragraph('同时核对 A1 / A2 先修；保留这个故障作为待复测目标。', 'next-reason'));
  content.push(node('div', { class: 'next-deliverable' }, node('h4', {}, '这次留下的产物'), paragraph(recommendation.deliverable)));
  const ids = [...(recommendation.question_ids || []).slice(0, 4), ...(recommendation.guide_ids || []).slice(0, 2), ...(recommendation.lab_ids || []).slice(0, 1), ...(recommendation.milestone_ids || []), ...(recommendation.acceptance_ids || [])];
  const links = node('div', { class: 'next-links' });
  for (const id of [...new Set(ids)]) if (fixedLink(id)) links.append(node('a', { href: fixedLink(id) }, id + ' ↗'));
  if (links.childNodes.length) content.push(links);
  if (recommendation.dimensionId) content.push(node('button', { type: 'button', class: 'button', style: 'margin-top:22px', onClick: () => chooseDimension(recommendation.dimensionId) }, '进入这个领域', ' →'));
  else content.push(node('a', { class: 'button', style: 'margin-top:22px', href: GITHUB + 'roadmap/start.md' }, '查看入口自测 ↗'));
  replace('next-step', ...content);
}
function renderOverview() {
  const axes = Core.currentAxes(state, definition);
  renderRadar(axes);
  byId('coverage').textContent = axes.filter(axis => axis.level !== null).length + ' / 6 领域';
  byId('version-label').textContent = '规则 ' + definition.assessment_version + ' · 当前只展示同版本完整有效自检';
  replace('dimension-table-body', ...axes.map(axis => {
    const attempt = state.attempts.find(item => item.id === axis.attemptId);
    const note = [axis.level === null ? '尚无完整独立记录' : dateLabel(axis.completedAt) + ' · 情境 ' + attempt.scenario_variant_id];
    if (axis.hasNewerDraft) note.push('有较新的草稿；旧档位暂时保留');
    if (axis.criticalFailures.length) note.push('关键失败：' + axis.criticalFailures.map(item => item.label).join('；'));
    return node('tr', {}, node('td', {}, axis.name, node('span', { class: 'table-note' }, axis.dimensionId)), node('td', {}, node('span', { class: 'level-text' }, axis.level === null ? '— 未测' : axis.level + ' · ' + LEVEL_NAMES[axis.level])), node('td', {}, ...note.map((text, index) => node('span', { class: index === note.length - 1 && axis.criticalFailures.length ? 'table-note critical-note' : 'table-note' }, text)), axis.level !== null ? node('span', { class: 'table-note' }, axis.source) : null));
  }));
  replace('dimension-cards', ...axes.map(axis => node('button', { type: 'button', class: 'dimension-card' + (axis.dimensionId === activeDimensionId ? ' is-active' : ''), onClick: () => chooseDimension(axis.dimensionId) }, node('span', { class: 'card-top' }, axis.dimensionId, node('span', {}, axis.level === null ? '尚无独立记录' : '当前 ' + axis.level + ' 档')), node('h3', {}, axis.name), paragraph(axis.hasNewerDraft ? '有未完成草稿，可继续填写；不会提前显示答题反馈。' : axis.criticalFailures.length ? '有关键条件未满足，先从具体故障补强。' : '两个情境变式，逐项记录实践；不必一次完成全部领域。'), node('span', { class: 'card-link' }, axis.hasNewerDraft ? '继续草稿' : '查看任务', node('span', { 'aria-hidden': 'true' }, '↗')))));
  renderRecommendation();
}

function chooseDimension(id) {
  activeDimensionId = id;
  const drafts = state.attempts.filter(item => item.dimension_id === id && item.attempt_status === 'draft' && item.definition_hash === definition.content_hash);
  activeAttemptId = drafts.at(-1)?.id || null;
  renderOverview();
  renderWorkspace();
  byId('workspace').scrollIntoView({ block: 'start' });
  byId('workspace-heading').focus({ preventScroll: true });
}
function makeSelect(id, choices, value, onChange) {
  const select = node('select', { id, onChange: event => onChange(event.target.value) });
  for (const [optionValue, label] of choices) select.append(node('option', { value: optionValue, disabled: optionValue === '' }, label));
  select.value = value ?? '';
  return select;
}
function newAttempt(variantId) {
  try {
    const created = Core.createAttempt(state, definition, { id: uid(), now: now(), dimensionId: activeDimensionId, variantId, roleId: preferences.roleId });
    state = created.state; activeAttemptId = created.attempt.id;
    persist(); renderAll();
    message(created.attempt.mode === 'practice' ? '这个变式已看过反馈，本轮将作为练习保存。' : '独立自检已开始。完整提交前不会显示答案；可随时保留草稿。');
  } catch (error) { message(error.message, true); }
}
function renderStart() {
  const { dimension, scenario, practice } = resolve(activeDimensionId);
  const selected = scenario.variants.find(item => !exposed(item)) || scenario.variants[0];
  const select = makeSelect('variant-select', scenario.variants.map(item => [item.id, (item.label || '情境 ' + item.id) + (exposed(item) ? ' · 已暴露，仅练习' : ' · 可独立尝试')]), selected.id, () => {});
  byId('workspace-heading').textContent = dimension.name;
  byId('workspace-status').textContent = '先看任务，再开始';
  replace('task-workspace', node('div', { class: 'task-intro' }, node('div', { class: 'task-meta' }, node('span', { class: 'tag' }, scenario.id + ' 情境'), node('span', { class: 'tag' }, practice.id + ' 实践')), node('h3', {}, scenario.title), paragraph(scenario.prompt || '按给定约束作答，再记录自己的实践。', 'task-description'), node('div', { class: 'task-resources' }, node('h4', {}, '允许资源与记录方式'), paragraph('可查语法；主要解法由 AI 或他人提供时须标记为辅助练习。已看过该变式核心解答，也应如实声明。'), paragraph('先完成情境，再明确选择本轮是否运行实践与变式。全部提交后才显示反馈。'))), node('div', { class: 'answer-field' }, node('label', { for: 'variant-select' }, '选择情境变式'), select, paragraph('同变式反馈已看过后，重复作答只能练习；不同约束的未暴露变式可以形成新的独立记录。', 'field-help')), node('div', { class: 'task-resources' }, node('h4', {}, '本轴实践：' + practice.title), paragraph(practice.prompt || ''), paragraph('未运行实践也可以如实完成基础自检，不需要为了填表伪造证据。')), node('div', { class: 'form-actions' }, node('button', { type: 'button', class: 'button', onClick: () => newAttempt(select.value) }, '开始本轴记录 →')));
}

function answerControl(criterion, value, present, onChange, prefix) {
  const group = node('fieldset', { class: 'question' }, node('legend', {}, criterion.label));
  const fieldId = prefix + '-' + criterion.id;
  if (criterion.input_type === 'choice') {
    for (const option of criterion.options) group.append(node('label', { class: 'option' }, node('input', { type: 'radio', name: fieldId, value: option.value, checked: present && value === option.value, onChange: () => onChange(option.value) }), node('span', { class: 'option-text' }, option.label)));
    group.append(node('label', { class: 'option' }, node('input', { type: 'radio', name: fieldId, value: '__unknown', checked: present && value === null, onChange: () => onChange(null) }), node('span', { class: 'option-text' }, '不知道 / 本轮无法确认')));
  } else {
    const control = node('input', { id: fieldId, type: criterion.input_type === 'number' ? 'number' : 'text', ...(criterion.input_type === 'number' ? { step: 'any' } : { maxlength: 12000 }), value: value ?? '', disabled: present && value === null, 'aria-label': criterion.label, onInput: event => onChange(event.target.value === '' ? undefined : criterion.input_type === 'number' ? Number(event.target.value) : event.target.value) });
    group.append(control, node('label', { class: 'option', style: 'margin-top:8px' }, node('input', { type: 'checkbox', checked: present && value === null, onChange: event => { const unknown = event.target.checked; control.disabled = unknown; if (unknown) control.value = ''; onChange(unknown ? null : undefined); } }), node('span', { class: 'option-text' }, '不知道 / 本轮无法确认')));
  }
  return group;
}
function changeAnswer(id, value) {
  const answers = { ...currentAttempt().answers };
  if (value === undefined) delete answers[id]; else answers[id] = value;
  patchDraft({ answers });
}
function updateSection(sectionName, change, rerender = false) {
  const section = { ...currentAttempt()[sectionName], ...change };
  patchDraft({ [sectionName]: section }, rerender);
}
function updateEntry(sectionName, criterionId, change, rerender = false) {
  const section = currentAttempt()[sectionName];
  const entry = { ...section.criteria[criterionId], ...change };
  for (const key of Object.keys(entry)) if (entry[key] === undefined) delete entry[key];
  updateSection(sectionName, { criteria: { ...section.criteria, [criterionId]: entry } }, rerender);
}
function textField(id, label, value, onInput, { large = false, placeholder = '' } = {}) {
  const control = node(large ? 'textarea' : 'input', { id, ...(large ? { rows: 3 } : { type: 'text' }), maxlength: 12000, placeholder, value: value || '', onInput: event => onInput(event.target.value) });
  return node('div', { class: 'answer-field' }, node('label', { for: id }, label), control);
}
function renderContext(sectionName, section) {
  const context = section.context || {};
  const update = (field, value) => updateSection(sectionName, { context: { ...currentAttempt()[sectionName].context, [field]: value } });
  return node('div', { class: 'criterion-grid' },
    node('div', { class: 'answer-field' }, node('label', { for: sectionName + '-run-at' }, '运行日期'), node('input', { id: sectionName + '-run-at', type: 'date', value: context.run_at || '', onInput: event => update('run_at', event.target.value) })),
    textField(sectionName + '-environment', '环境（语言 / 工具 / 运行方式）', context.environment, value => update('environment', value)),
    textField(sectionName + '-version', '代码、数据与配置版本', context.version, value => update('version', value)),
    node('div', { class: 'answer-field' }, node('label', { for: sectionName + '-model-mode' }, '模型与数据条件'), makeSelect(sectionName + '-model-mode', [['', '请选择'], ['stub', '本地桩 / 模拟数据'], ['real', '实际模型调用'], ['none', '不涉及模型']], context.model_mode || '', value => update('model_mode', value))));
}
function renderEvidenceCriterion(sectionName, criterion, section) {
  const entry = section.criteria[criterion.id] || {};
  const statusId = sectionName + '-' + criterion.id + '-status';
  const article = node('article', { class: 'criterion' }, node('h4', {}, criterion.label, criterion.critical ? node('span', { class: 'tag', style: 'margin-left:8px' }, '关键断言') : null), paragraph('请根据题内条件自行推导预期，并记录真实观测。固定预期与解释在完整提交后展示。', 'field-help'), node('div', { class: 'answer-field' }, node('label', { for: statusId }, '这个条件实际运行了吗？'), makeSelect(statusId, [['', '请选择'], ['not_run', '本轮未运行'], ['ran', '已运行，有实际观测'], ['failed', '运行失败，保留错误记录']], entry.run_status || '', value => { if (value) updateEntry(sectionName, criterion.id, { run_status: value }, true); })));
  if (!entry.run_status || entry.run_status === 'not_run') return article;
  if (criterion.input_type === 'self') {
    const id = sectionName + '-' + criterion.id + '-judgment';
    article.append(node('div', { class: 'answer-field' }, node('label', { for: id }, '本人按规范判断（系统不做语义核验）'), makeSelect(id, [['', '请选择'], ['pass', '满足此断言'], ['fail', '未满足此断言'], ['unknown', '无法确认']], entry.judgment || '', value => { if (value) updateEntry(sectionName, criterion.id, { judgment: value }); })));
  } else article.append(answerControl({ ...criterion, label: '结构化观测值（用于题内规则比对）' }, entry.observed, has(entry, 'observed'), value => updateEntry(sectionName, criterion.id, { observed: value }), sectionName + '-observation'));
  const fields = node('div', { class: 'criterion-grid' });
  for (const [field, label] of Object.entries(FIELD_NAMES)) {
    const large = ['input', 'actual', 'excerpt', 'explanation'].includes(field);
    const box = textField(sectionName + '-' + criterion.id + '-' + field, label, entry[field], value => updateEntry(sectionName, criterion.id, { [field]: value }), { large, placeholder: field === 'actual' ? '记录原始值或具体输出，不只填写“通过”' : field === 'evidence_ref' ? '仅作文字记录，不会自动访问外链' : '' });
    if (large) box.classList.add('full-width');
    fields.append(box);
  }
  article.append(fields);
  return article;
}
function expectedLabel(criterion) {
  if (criterion.input_type === 'choice') return criterion.options.find(item => item.value === criterion.expected)?.label || display(criterion.expected);
  return display(criterion.expected);
}
function practiceSection(sectionName, task) {
  const transfer = sectionName === 'transfer';
  const section = currentAttempt()[sectionName];
  const criteria = transfer ? task.transfer.criteria : task.criteria;
  const content = node('section', { class: 'form-step' }, node('div', { class: 'step-heading' }, node('span', { class: 'step-number' }, transfer ? '3' : '2'), node('div', {}, node('h3', {}, transfer ? '不同约束下的尝试' : task.title), paragraph(transfer ? task.transfer.constraint : task.prompt || '记录实际运行的输入、输出与边界。'))));
  content.append(node('fieldset', { class: 'question' }, node('legend', {}, transfer ? '本轮是否运行变式与回归？' : '本轮是否运行这项实践？'), ...[['not_run', '本轮未运行；如实保留这一缺口'], ['reported', '已尝试；逐项填写运行或失败记录']].map(([value, label]) => node('label', { class: 'option' }, node('input', { type: 'radio', name: sectionName + '-status', value, checked: section.status === value, onChange: () => updateSection(sectionName, { status: value }, true) }), node('span', { class: 'option-text' }, label)))));
  if (section.status !== 'reported') {
    const details = node('details', { class: 'criterion' }, node('summary', {}, '查看必要产物与记录项'), paragraph('每项需说明是否运行；有运行时保留输入条件、原始输出、证据定位与片段、判断理由及环境版本。请从题内条件自行推导预期，提交前不显示固定答案。', 'field-help'));
    for (const criterion of criteria) details.append(node('h4', { style: 'margin-top:14px' }, criterion.label));
    content.append(details);
    return content;
  }
  content.append(renderContext(sectionName, section));
  if (transfer) content.append(textField('transfer-prediction', '先前预测与改变的约束（如在运行后补写，请注明）', section.prediction, value => updateSection(sectionName, { prediction: value }), { large: true }), textField('transfer-tradeoff', '结果与代价：改了什么，增加了什么成本，哪些仍未验证？', section.tradeoff, value => updateSection(sectionName, { tradeoff: value }), { large: true }));
  content.append(node('div', { class: 'criteria-list' }, criteria.map(criterion => renderEvidenceCriterion(sectionName, criterion, section))));
  return content;
}
function renderDraft(attempt) {
  const { dimension, scenario, variant, practice } = resolve(attempt.dimension_id, attempt.scenario_variant_id);
  byId('workspace-heading').textContent = dimension.name;
  byId('workspace-status').textContent = '草稿 · 不显示对错';
  const intro = node('div', { class: 'task-intro' }, node('div', { class: 'task-meta' }, node('span', { class: 'tag' }, scenario.id + ' / ' + variant.id), node('span', { class: 'tag' }, '规则 ' + attempt.assessment_version)), node('h3', {}, scenario.title), paragraph(variant.prompt, 'task-description'), node('div', { class: 'task-resources' }, node('h4', {}, '本轮资源与边界'), paragraph('可查语法；请先独立处理情境。主要方案由 AI 或他人提供、或已见核心解答时，记录为辅助练习。完整提交后不能修改。')));
  const foundation = node('section', { class: 'form-step' }, node('div', { class: 'step-heading' }, node('span', { class: 'step-number' }, '1'), node('div', {}, node('h3', {}, '按给定情境作答'), paragraph('空白保留为草稿；明确选择“不知道”可以形成完整的失败记录。'))), variant.criteria.map(criterion => answerControl(criterion, attempt.answers[criterion.id], has(attempt.answers, criterion.id), value => changeAnswer(criterion.id, value), 'scenario')));
  const assistance = node('section', { class: 'form-step' }, node('h3', {}, '如实记录辅助方式'), node('div', { class: 'answer-field' }, node('label', { for: 'assistance-select' }, '这次怎样完成关键判断与解释？'), makeSelect('assistance-select', [['independent', '独立完成关键判断与解释'], ['syntax_only', '仅查语法或 API 用法'], ['substantial', 'AI / 他人提供关键解法或针对性提示']], attempt.assistance, value => patchDraft({ assistance: value }))), node('label', { class: 'option' }, node('input', { type: 'checkbox', checked: attempt.external_answer_seen, onChange: event => patchDraft({ external_answer_seen: event.target.checked }) }), node('span', { class: 'option-text' }, '我已经在其他地方看过这个变式的核心解答')), paragraph('', 'practice-message'));
  assistance.lastElementChild.id = 'attempt-mode-note';
  const actions = node('div', { class: 'form-actions' }, node('button', { type: 'button', class: 'button', onClick: submitAttempt }, '完整提交，查看反馈 →'), node('button', { type: 'button', class: 'button secondary', onClick: () => { persist(); message('草稿已保留；请同时确认下方保存状态。'); } }, '保留草稿'), node('div', { class: 'microcopy' }, paragraph('提交会冻结本次记录并展示解答。只有最新完整有效自检进入图。'), node('p', { id: 'feedback-scope-note' })));
  replace('task-workspace', intro, foundation, practiceSection('practice', practice), practiceSection('transfer', practice), assistance, actions);
  renderModeLabel();
}
function submitAttempt() {
  const attempt = currentAttempt();
  if (attempt.practice.status === 'unselected' || attempt.transfer.status === 'unselected') {
    message('请先明确选择本轮是否运行实践与变式；没有运行可以如实选择“本轮未运行”。', true, true);
    return;
  }
  try {
    const completed = Core.completeAttempt(state, definition, attempt.id, { now: now() });
    state = completed.state;
    persist(); renderAll();
    message((completed.result.validity === 'valid' ? '本轴已完整提交。' : '已保存练习反馈，本轮不替换当前图。') + feedbackScope(attempt), false);
    byId('workspace-heading').focus({ preventScroll: true });
    byId('workspace').scrollIntoView({ block: 'start' });
  } catch (error) { message(error.message, true, true); }
}
function renderLegacy(attempt) {
  const dimension = definition.dimensions.find(item => item.id === attempt.dimension_id);
  byId('workspace-heading').textContent = (dimension?.name || attempt.dimension_id) + ' · 历史记录';
  byId('workspace-status').textContent = '定义不一致 · 只读';
  const originalHash = typeof attempt.definition_hash === 'string' ? attempt.definition_hash.slice(0, 8) : '未记录';
  const currentHash = typeof definition.content_hash === 'string' ? definition.content_hash.slice(0, 8) : '未记录';
  replace('task-workspace', node('h3', {}, '保留原始记录，不套用当前定义'), paragraph('版本、定义内容或任务不匹配时，不能静默重算、继续编辑或混入当前图。同版本号的内容修订也会隔离；原始草稿或完成记录仍保留在备份中。'), paragraph('记录规则：' + attempt.assessment_version + ' / 定义 ' + originalHash + '；当前规则：' + definition.assessment_version + ' / 定义 ' + currentHash + '。', 'microcopy'), node('pre', { class: 'record-json' }, JSON.stringify(attempt, null, 2)));
}
function renderCompleted(attempt) {
  const result = Core.evaluateAttempt(definition, attempt, state.exposures);
  const dimension = definition.dimensions.find(item => item.id === attempt.dimension_id);
  byId('workspace-heading').textContent = (dimension?.name || attempt.dimension_id) + ' · 本次反馈';
  byId('workspace-status').textContent = '已完成 · 不可编辑';
  if (result.reasons.includes('definition_mismatch') || result.reasons.includes('unknown_task')) {
    renderLegacy(attempt);
    return;
  }
  const { variant, practice } = resolve(attempt.dimension_id, attempt.scenario_variant_id);
  const criteria = [...variant.criteria, ...practice.criteria, ...practice.transfer.criteria];
  const independent = result.validity === 'valid';
  const content = [paragraph(dateLabel(attempt.completed_at) + ' · 情境 ' + attempt.scenario_variant_id + ' · ' + (ROLE_NAMES[attempt.role_id] || attempt.role_id), 'microcopy'), node('div', { class: 'result-banner' }, node('span', { class: 'result-value' }, String(result.level)), node('div', {}, node('h3', {}, independent ? LEVEL_NAMES[result.level] : '练习反馈 · 不进入当前图'), paragraph(independent ? result.source : '本次填报符合 ' + result.level + ' 档条件，但不满足独立自检条件。'), paragraph('自行记录，未独立核验。'))), paragraph('记录已冻结。查看解答不会倒改这次首次提交。' + feedbackScope(attempt), 'field-help')];
  const feedback = node('div', { class: 'feedback-list', style: 'margin-top:22px' });
  const statusLabels = { pass: '满足', fail: '未满足', not_run: '未运行', missing: '缺少记录' };
  for (const item of result.criteria) {
    const criterion = criteria.find(value => value.id === item.criterionId);
    const card = node('article', { class: 'feedback-item' + (item.status === 'pass' ? '' : ' is-failed') }, node('h4', {}, (statusLabels[item.status] || item.status) + ' · ' + item.label));
    if (item.stage !== 'foundation' && item.status === 'not_run') {
      card.append(paragraph('本轮未运行，不展示此项解答。后续实践请保留输入条件、原始输出、证据定位与判断理由。', 'microcopy'));
      feedback.append(card);
      continue;
    }
    card.append(paragraph(item.explanation));
    if (item.stage === 'foundation') {
      const answer = attempt.answers[item.criterionId];
      const answerText = criterion?.input_type === 'choice' ? criterion.options.find(option => option.value === answer)?.label || display(answer) : display(answer);
      card.append(paragraph('你的作答：' + answerText, 'answer'), paragraph('情境预期：' + expectedLabel(criterion), 'answer'));
    } else {
      if (criterion && criterion.input_type !== 'self') card.append(paragraph('固定预期：' + expectedLabel(criterion), 'answer'));
      card.append(paragraph(item.source === 'self_judgment' ? '来源：本人按规范判断；系统未作语义或真实性核验。' : '来源：本人填报观测值；规则比较不证明真实运行。', 'microcopy'));
    }
    if (item.critical && item.status === 'fail') card.append(paragraph('关键断言未满足；不能被旧档位或其他成功项抵消。', 'critical-note'));
    feedback.append(card);
  }
  content.push(feedback, node('details', { class: 'criterion', style: 'margin-top:20px' }, node('summary', {}, '查看本次完整实践记录'), node('pre', { class: 'record-json' }, JSON.stringify({ practice: attempt.practice, transfer: attempt.transfer, assistance: attempt.assistance, external_answer_seen: attempt.external_answer_seen }, null, 2))), node('div', { class: 'form-actions' }, node('button', { type: 'button', class: 'button', onClick: () => { activeAttemptId = null; renderStart(); } }, '选择其他变式 / 练习 →'), node('a', { href: '#next-heading', class: 'button secondary' }, '看本轮下一步 ↑')));
  replace('task-workspace', ...content);
}
function renderWorkspace() {
  if (!activeDimensionId) return;
  byId('task-workspace').classList.remove('empty-workspace');
  const attempt = currentAttempt();
  if (!attempt) renderStart();
  else if (attempt.assessment_version !== definition.assessment_version || attempt.rubric_version !== definition.rubric_version || attempt.definition_hash !== definition.content_hash || !definition.dimensions.some(item => item.id === attempt.dimension_id)) renderLegacy(attempt);
  else if (Core.evaluateAttempt(definition, attempt, state.exposures).reasons.includes('unknown_task')) renderLegacy(attempt);
  else if (attempt.attempt_status === 'completed') renderCompleted(attempt);
  else renderDraft(attempt);
}
function renderHistory() {
  if (!state.attempts.length) { replace('history-list', paragraph('尚无个人记录。一次完整尝试，会同时留下反馈和答案暴露记录。', 'muted')); return; }
  const records = [...state.attempts].reverse();
  replace('history-list', ...records.map(attempt => {
    const dimension = definition.dimensions.find(item => item.id === attempt.dimension_id);
    const result = attempt.attempt_status === 'completed' ? Core.evaluateAttempt(definition, attempt, state.exposures) : null;
    const label = !result ? '草稿' : result.reasons.includes('definition_mismatch') ? '旧版本' : result.validity === 'valid' ? result.level + ' 档自检' : '练习反馈';
    return node('article', { class: 'history-item' }, node('div', { class: 'history-item-top' }, node('button', { type: 'button', onClick: () => { activeAttemptId = attempt.id; activeDimensionId = attempt.dimension_id; renderWorkspace(); byId('workspace').scrollIntoView({ block: 'start' }); byId('workspace-heading').focus({ preventScroll: true }); } }, (dimension?.name || attempt.dimension_id) + ' / ' + attempt.scenario_variant_id), node('span', { class: 'tag' }, label)), paragraph(dateLabel(attempt.completed_at || attempt.started_at) + ' · 规则 ' + attempt.assessment_version, 'microcopy'));
  }));
}
function renderAll() { renderOverview(); renderWorkspace(); renderHistory(); }
function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json;charset=utf-8' }));
  const link = node('a', { href: url, download: name });
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function setupControls() {
  replace('role-select', ...definition.roles.map(id => node('option', { value: id }, ROLE_NAMES[id] || id)));
  if (!definition.roles.includes(preferences.roleId)) preferences.roleId = definition.roles[0];
  byId('role-select').value = preferences.roleId;
  byId('foundation-select').value = preferences.foundation === 'passed' ? 'ready' : preferences.foundation === 'failed' ? 'needs-foundation' : 'unknown';
  byId('role-select').addEventListener('change', event => { preferences.roleId = event.target.value; persistPreferences(); renderRecommendation(); });
  byId('foundation-select').addEventListener('change', event => { preferences.foundation = event.target.value === 'ready' ? 'passed' : event.target.value === 'needs-foundation' ? 'failed' : 'unknown'; persistPreferences(); renderRecommendation(); });
  byId('export-button').addEventListener('click', () => {
    try { download('self-check-backup-' + now().slice(0, 10) + '.json', Core.exportBackup(state)); message('备份已生成，含个人答案与证据。请确认浏览器下载完成并妥善保管。'); }
    catch (error) { message(error.message, true, true); }
  });
  byId('import-button').addEventListener('click', () => byId('import-file').click());
  byId('import-file').addEventListener('change', async event => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      if (file.size > 5 * 1024 * 1024) throw new Error('备份超过 5 MiB，未导入。');
      const merged = Core.mergeBackup(state, await file.text(), definition);
      state = merged; persist(); renderAll();
      message('备份已合并；已完成记录与答案暴露保留。导入的档位不会直接信任，当前版本按同一规则读取。', false, true);
    } catch (error) { message('导入未完成，当前记录未被替换。' + error.message, true, true); }
    finally { event.target.value = ''; }
  });
  byId('clear-button').addEventListener('click', () => {
    if (!confirm('将清除当前浏览器的全部答卷、草稿和暴露记录。请确认已下载备份。清除不会让已看过的答案变成独立尝试。继续吗？')) return;
    try { localStorage.removeItem(STORAGE_KEY); }
    catch (error) { message('无法清除本地保存的数据，未重置页面：' + error.message, true); return; }
    state = Core.createState(); activeAttemptId = null; activeDimensionId = null; lastStored = null; storageBlocked = false; originalUnreadable = null;
    storageNotice(''); persist(); renderAll();
    byId('workspace-heading').textContent = '本次任务'; byId('workspace-status').textContent = '尚未开始';
    replace('task-workspace', paragraph('已清除本机记录。请选择一个领域重新开始；已在外部看过的解答仍须如实声明。', 'muted'));
    message('本机自检记录已清除。', false, true);
  });
  for (const id of ['role-select', 'foundation-select', 'export-button', 'import-button', 'clear-button']) byId(id).disabled = false;
  window.addEventListener('storage', event => {
    if (event.key !== STORAGE_KEY || !event.newValue) return;
    try { state = Core.mergeBackup(state, event.newValue, definition); lastStored = event.newValue; renderAll(); message('已合并另一个页面保存的记录。'); }
    catch (error) { storageNotice('另一个页面的记录发生冲突；没有覆盖当前填写。请分别下载备份后核对。' + error.message); }
  });
}

async function boot() {
  try {
    const response = await fetch('./definition.json', { cache: 'no-cache' });
    if (!response.ok) throw new Error('任务定义读取失败（' + response.status + '）');
    definition = await response.json();
    if (!Array.isArray(definition.dimensions) || definition.dimensions.length !== 6) throw new Error('任务定义不是有效的六维版本。');
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        try { state = Core.mergeBackup(Core.createState(), raw, definition); lastStored = raw; }
        catch (error) { originalUnreadable = raw; storageBlocked = true; storageNotice('本地记录无法读取，原始内容未被覆盖。可先下载原始备份再核对：' + error.message); }
      }
      const savedPreferences = JSON.parse(localStorage.getItem(PREFERENCES_KEY) || '{}');
      if (definition.roles.includes(savedPreferences.roleId)) preferences.roleId = savedPreferences.roleId;
      if (['unknown', 'passed', 'failed'].includes(savedPreferences.foundation)) preferences.foundation = savedPreferences.foundation;
    } catch (error) { storageNotice('浏览器暂不允许持久保存。本次仍可填写与下载备份；不要依赖刷新后保留。' + error.message); }
    setupControls(); renderAll();
    byId('save-status').textContent = storageBlocked ? '原始记录不可读，当前只在内存填写。' : lastStored ? '已读取当前浏览器的本地记录。' : '还没有个人记录；首次填写后自动保存。';
  } catch (error) {
    message('页面未能启动：' + error.message + '。请通过静态网站地址或本地 HTTP 服务访问，直接打开文件可能无法读取定义。', true);
    byId('radar').setAttribute('aria-busy', 'false');
    replace('radar', paragraph('任务定义尚未载入，未生成个人结果。', 'loading'));
    byId('save-status').textContent = '未开始保存。';
  }
}

boot();
