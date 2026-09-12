const STATUS = Object.freeze({
  pass: {icon: '✓', label: '通過', overall: '本案件審查通過'},
  error: {icon: '✕', label: '不一致', overall: '本案件未通過'},
  pending: {icon: '⚠', label: '待人工確認', overall: '本案件待人工確認'},
  missing: {icon: '−', label: '缺資料', overall: '本案件資料尚未齊全'},
});

const STATUS_PRIORITY = Object.freeze({pass: 0, missing: 1, pending: 2, error: 3});
const SCOPE_LABELS = Object.freeze({individual: '個別因素', regional: '區域因素'});

function normalizeStatus(status) {
  return Object.hasOwn(STATUS, status) ? status : 'missing';
}

function mostSevere(statuses) {
  return statuses
    .map(normalizeStatus)
    .reduce((current, status) => (
      STATUS_PRIORITY[status] > STATUS_PRIORITY[current] ? status : current
    ), 'pass');
}

function checkValue(value) {
  return value === null || value === undefined || value === '' ? null : value;
}

function scopeLabel(scope) {
  return SCOPE_LABELS[scope] || scope || '未提供範圍';
}

export function getReviewStatus(status) {
  return STATUS[normalizeStatus(status)];
}

export function buildReviewViewModel({caseData, review, ruleset}) {
  const counts = {
    pass: Number(review?.counts?.pass || 0),
    error: Number(review?.counts?.error || 0),
    pending: Number(review?.counts?.pending || 0),
    missing: Number(review?.counts?.missing || 0),
  };
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
  const overallStatus = review?.complete
    ? 'pass'
    : mostSevere(Object.entries(counts).flatMap(([status, count]) => count ? [status] : []));
  const checks = Array.isArray(review?.checks) ? review.checks : [];
  const rules = Array.isArray(ruleset?.rules) ? ruleset.rules : [];
  const factors = Array.isArray(caseData?.factors) ? caseData.factors : [];
  const factorById = new Map(factors.map(factor => [factor.id, factor]));
  const ruleById = new Map(rules.map(rule => [rule.id, rule]));
  const factorIds = [...new Set([...rules.map(rule => rule.id), ...factors.map(factor => factor.id)])];

  const factorRows = factorIds.map(id => {
    const factor = factorById.get(id) || null;
    const rule = ruleById.get(id) || null;
    const factorChecks = checks.filter(check => check.factor_id === id);
    const status = factorChecks.length
      ? mostSevere(factorChecks.map(check => check.status))
      : 'missing';
    const primaryCheck = factorChecks.find(check => check.status === status) || factorChecks[0] || null;
    const hasCaseData = [
      factor?.subject,
      factor?.comparable,
      factor?.subject_grade,
      factor?.comparable_grade,
      factor?.entered_rate,
    ].some(value => checkValue(value) !== null)
      || Boolean(factor?.note?.trim())
      || factor?.confirmed === true
      || factor?.exempt === true;
    return {
      id,
      name: rule?.name || primaryCheck?.title || id,
      group: rule?.group || rule?.scope || '未分類',
      scope: rule?.scope || null,
      scopeLabel: scopeLabel(rule?.scope),
      unit: rule?.unit || '',
      editable: Boolean(rule),
      hasCaseData,
      status,
      statusMeta: getReviewStatus(status),
      subjectValue: checkValue(factor?.subject),
      comparableValue: checkValue(factor?.comparable),
      enteredSubjectGrade: checkValue(factor?.subject_grade),
      enteredComparableGrade: checkValue(factor?.comparable_grade),
      systemSubjectGrade: checkValue(primaryCheck?.subject_grade),
      systemComparableGrade: checkValue(primaryCheck?.comparable_grade),
      enteredRate: checkValue(factor?.entered_rate),
      expectedRate: checkValue(primaryCheck?.expected),
      message: primaryCheck?.message || '目前系統未提供此因素的審查結果。',
      evidence: factor?.evidence || null,
      sourcePage: rule?.source_page || primaryCheck?.rule_page || null,
      matrixAvailable: Array.isArray(rule?.matrix) && rule.matrix.length > 0,
    };
  });

  const issues = checks
    .filter(check => normalizeStatus(check.status) !== 'pass')
    .map(check => ({
      id: check.id,
      factorId: check.factor_id || null,
      title: check.title,
      status: normalizeStatus(check.status),
      statusMeta: getReviewStatus(check.status),
      message: check.message,
      actual: checkValue(check.actual),
      expected: checkValue(check.expected),
    }));

  const groupMap = new Map();
  for (const factor of factorRows) {
    if (!groupMap.has(factor.group)) groupMap.set(factor.group, []);
    groupMap.get(factor.group).push(factor.status);
  }
  const groups = [...groupMap.entries()].map(([name, statuses]) => {
    const status = mostSevere(statuses);
    return {name, status, statusMeta: getReviewStatus(status), count: statuses.length};
  });

  const populatedFactors = factorRows.filter(factor => factor.hasCaseData);
  const emptyFactors = factorRows.filter(factor => !factor.hasCaseData);
  const emptyGroupMap = new Map();
  for (const factor of emptyFactors) {
    if (!emptyGroupMap.has(factor.group)) emptyGroupMap.set(factor.group, []);
    emptyGroupMap.get(factor.group).push(factor);
  }
  const emptyGroups = [...emptyGroupMap.entries()].map(([name, factors]) => ({name, factors}));

  return {
    case: {
      title: caseData?.title || '未命名案件',
      caseNumber: caseData?.case_number || '尚未填寫案號',
      locality: caseData?.locality || '目前無資料',
      landUse: caseData?.land_use || '目前無資料',
      valuationDate: caseData?.valuation_date || '目前無資料',
      address: caseData?.subject_address || '目前無資料',
      subjectName: caseData?.subject_name || '目前無資料',
      comparableName: caseData?.comparable_name || '目前無資料',
      revision: caseData?.revision ?? 0,
    },
    ruleset: {
      name: ruleset?.name || '目前無資料',
      version: ruleset?.version || '目前無資料',
      source: ruleset?.source || '目前系統未提供詳細規則來源',
    },
    summary: {counts, total, overallStatus, overall: getReviewStatus(overallStatus)},
    issues,
    groups,
    factors: factorRows,
    populatedFactors,
    emptyFactors,
    emptyGroups,
    map: {
      address: caseData?.subject_address || null,
      locality: caseData?.locality || null,
      coordinatesAvailable: false,
      boundaryAvailable: false,
      facilitiesAvailable: false,
    },
  };
}
