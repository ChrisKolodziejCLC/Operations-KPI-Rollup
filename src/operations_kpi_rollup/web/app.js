'use strict';

const palette = {
  teal: '#13858c', blue: '#3478ad', green: '#37856e', purple: '#826aa4',
  amber: '#df922a', red: '#bd524d', navy: '#0b2239', grid: '#d9e3e8', muted: '#607487'
};

const EARLIEST_REPORT_DATE = '2026-09-08';
const WALLBOARD_POLL_MS = 30 * 1000;
const HEALTH_POLL_MS = 5 * 1000;
const COUNTDOWN_TICK_MS = 1000;
let refreshInProgress = false;
let displayedReportDate = '';
let autoRefreshRunning = false;
let autoRefreshInProgress = false;
let nextAutoRefreshAt = null;
let serverClockOffsetMs = 0;
let activeSnapshot = null;
let selectedChartKey = 'loaded';
let selectedChartLabel = 'Carts / Pieces Loaded';

const $ = (selector) => document.querySelector(selector);
const svgNode = (name, attributes = {}) => {
  const node = document.createElementNS('http://www.w3.org/2000/svg', name);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
  return node;
};
const text = (value) => document.createTextNode(String(value ?? ''));
const integer = (value) => Number(value || 0).toLocaleString();
const wholeNumber = (value) => Math.round(Number(value || 0)).toLocaleString(undefined, {maximumFractionDigits:0});
const decimal = (value) => Number(value || 0).toLocaleString(undefined, {minimumFractionDigits:1, maximumFractionDigits:1});
const optionalInteger = (value) => value === undefined || value === null ? 'No Data' : integer(value);
const compactOptionalInteger = (value) => value === undefined || value === null ? '—' : integer(value);
const ratio = (numerator, denominator) => Number(denominator) > 0 ? Number(numerator || 0) / Number(denominator) : null;
const yieldRatio = (numerator, denominator) => {
  const top = Number(numerator || 0), bottom = Number(denominator || 0);
  return bottom > 0 && top >= 0 && top <= bottom ? top / bottom : null;
};
const percent = (value) => value === null || !Number.isFinite(value) ? 'No Data' : `${(value * 100).toFixed(1)}%`;
const average = (total, days) => Number(days) > 0 ? (Number(total || 0) / Number(days)).toFixed(1) : 'No Data';
const dateLabel = (value) => value ? new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {month: 'short', day: 'numeric'}) : '';
const localDateISO = (value = new Date()) => {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};
const shiftDate = (value, days) => {
  const shifted = new Date(`${value}T12:00:00`);
  shifted.setDate(shifted.getDate() + days);
  return localDateISO(shifted);
};
const fullDateLabel = (value) => new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {year:'numeric', month:'long', day:'numeric'});
const clockTimeLabel = (value) => value
  ? new Date(value).toLocaleTimeString(undefined, {hour:'numeric', minute:'2-digit'})
  : 'No time';

function rangeLabel(rows) {
  const dates = rows.map(row => row.date).filter(Boolean).sort();
  if (!dates.length) return 'Covered range unavailable';
  const start = new Date(`${dates[0]}T12:00:00`);
  const end = new Date(`${dates[dates.length - 1]}T12:00:00`);
  if (dates[0] === dates[dates.length - 1]) return `Covered range ${fullDateLabel(dates[0])}`;
  if (start.getFullYear() === end.getFullYear() && start.getMonth() === end.getMonth()) {
    return `Covered range ${start.toLocaleDateString(undefined, {month:'short', day:'numeric'})}–${end.getDate()}, ${end.getFullYear()}`;
  }
  if (start.getFullYear() === end.getFullYear()) {
    return `Covered range ${start.toLocaleDateString(undefined, {month:'short', day:'numeric'})}–${end.toLocaleDateString(undefined, {month:'short', day:'numeric'})}, ${end.getFullYear()}`;
  }
  return `Covered range ${fullDateLabel(dates[0])}–${fullDateLabel(dates[dates.length - 1])}`;
}

function loadSplit(row) {
  if (row.production_parts_loaded === undefined && row.service_parts_loaded === undefined) {
    return {production: row.parts_loaded, bv: 0, service: 0};
  }
  return {production: row.production_parts_loaded || 0, bv: row.bv_parts_loaded || 0, service: row.service_parts_loaded};
}

function cartSplit(row) {
  if (row.production_carts_loaded === undefined && row.service_carts_loaded === undefined) {
    return {production: row.carts_loaded, bv: 0, service: 0};
  }
  return {production: row.production_carts_loaded || 0, bv: row.bv_carts_loaded || 0, service: row.service_carts_loaded};
}

function paintCartSplit(row) {
  if (row.production_paint_carts === undefined && row.service_paint_carts === undefined) {
    return {production: row.paint_carts, bv: 0, service: 0};
  }
  return {production: row.production_paint_carts || 0, bv: row.bv_paint_carts || 0, service: row.service_paint_carts};
}

function paintPieceSplit(row) {
  if (row.production_paint_pieces_processed === undefined && row.service_paint_pieces_processed === undefined) {
    return {production: row.paint_pieces_processed, bv: 0, service: 0};
  }
  return {production: row.production_paint_pieces_processed || 0, bv: row.bv_paint_pieces_processed || 0, service: row.service_paint_pieces_processed};
}

function rateBreakdown(row, numerator, denominator) {
  const values = ['production', 'bv', 'service'].map(prefix => percent(ratio(row[`${prefix}_${numerator}`], row[`${prefix}_${denominator}`])));
  return `Prd ${values[0]} / BV ${values[1]} / Svc ${values[2]}`;
}

function shippedPieceDetail(snapshot) {
  const counts = {fuka:0, bumpers:0, n71:0, fairings:0, other:0};
  (snapshot.shipping || []).forEach(row => {
    if (row.date !== snapshot.report_date) return;
    const lineSet = String(row.line_set || '').trim().toLowerCase();
    const pieces = Number(row.pieces || 0);
    if (lineSet === 'bumpers') counts.bumpers += pieces;
    else if (lineSet === 'n71-6164') counts.n71 += pieces;
    else if (lineSet === 'fenders' || lineSet === 'fuka') counts.fuka += pieces;
    else if (lineSet === 'chassis fairings' || lineSet === 'fairings') counts.fairings += pieces;
    else if (lineSet === 'other') counts.other += pieces;
  });
  const details = [
    `${integer(counts.fuka)} FUKA`,
    `${integer(counts.bumpers)} Bumpers`,
    `${integer(counts.n71)} N71-6164`,
    `${integer(counts.fairings)} Fairings`
  ];
  if (counts.other) details.push(`${integer(counts.other)} Other`);
  return details;
}

function repaintLineSetDetail(row) {
  const fields = ['fuka_paint_fty_repaint_count', 'bumper_paint_fty_repaint_count', 'fairing_paint_fty_repaint_count'];
  if (!fields.every(field => row[field] !== undefined)) return ['Line-set detail pending refresh'];
  return [
    `${integer(row.fuka_paint_fty_repaint_count)} FUKA`,
    `${integer(row.bumper_paint_fty_repaint_count)} Bumpers`,
    `${integer(row.fairing_paint_fty_repaint_count)} Fairings`
  ];
}

function composite(row) {
  const attainment = ratio(row.paint_pieces_processed, row.pieces_scheduled);
  const quality = yieldRatio(Number(row.paint_fty_total || 0) - Number(row.paint_fty_repaint_count || 0), row.paint_fty_total);
  const coverage = ratio(row.paint_hours, row.hours_scheduled);
  if ([attainment, quality, coverage].some(value => value === null)) return null;
  return Math.min(attainment, 1) * quality * Math.min(coverage, 1);
}

function setStatus(message, error = false) {
  const node = $('#status');
  node.textContent = message;
  node.classList.toggle('error', error);
}

function metricCard(label, value, detail, color) {
  const card = document.createElement('article');
  card.className = 'metric-card';
  card.style.setProperty('--accent', color);
  const labelNode = document.createElement('span'); labelNode.append(text(label));
  const valueNode = document.createElement('strong'); valueNode.append(text(value));
  const details = Array.isArray(detail) ? detail : detail ? [detail] : [];
  const detailList = document.createElement('div'); detailList.className = 'metric-detail-list';
  details.forEach(item => {
    const detailNode = document.createElement('small'); detailNode.className = 'metric-detail-row'; detailNode.append(text(item));
    detailList.append(detailNode);
  });
  card.append(labelNode, valueNode, detailList);
  return card;
}

function splitMetricCard(label, total, unique, rows, color) {
  const card = document.createElement('article');
  card.className = 'metric-card split-count-card';
  card.style.setProperty('--accent', color);
  const labelNode = document.createElement('span'); labelNode.append(text(label));
  const totalNode = document.createElement('strong'); totalNode.className = 'metric-split-total';
  totalNode.append(text(`${integer(total)} Total / ${unique === undefined ? '—' : integer(unique)} Unique`));
  const list = document.createElement('div'); list.className = 'metric-split-list';
  rows.forEach(row => {
    const line = document.createElement('div'); line.className = 'metric-split-row';
    const rowLabel = document.createElement('span'); rowLabel.className = 'metric-split-label'; rowLabel.append(text(row.label));
    const value = document.createElement('small'); value.className = 'metric-split-value';
    const values = [`${integer(row.production)} Prd`, `${integer(row.bv)} BV`];
    values.push(`${integer(row.service)} Svc`);
    value.append(text(values.join(' / ')));
    line.append(rowLabel, value); list.append(line);
  });
  card.append(labelNode, totalNode, list);
  return card;
}

function stagedMetricCard(carts, pieces, rows, color) {
  const card = document.createElement('article');
  card.className = 'metric-card split-count-card staged-count-card';
  card.style.setProperty('--accent', color);
  const labelNode = document.createElement('span'); labelNode.append(text('Carts / Pieces staged'));
  const totalNode = document.createElement('strong'); totalNode.className = 'metric-split-total';
  totalNode.append(text(`${compactOptionalInteger(carts)} Carts / ${compactOptionalInteger(pieces)} Pieces`));
  const list = document.createElement('div'); list.className = 'metric-split-list';
  rows.forEach(row => {
    const line = document.createElement('div'); line.className = 'metric-split-row';
    const rowLabel = document.createElement('span'); rowLabel.className = 'metric-split-label'; rowLabel.append(text(row.label));
    const value = document.createElement('small'); value.className = 'metric-split-value';
    value.append(text(`${compactOptionalInteger(row.production)} Prd / ${compactOptionalInteger(row.bv)} BV / ${compactOptionalInteger(row.service)} Svc`));
    line.append(rowLabel, value); list.append(line);
  });
  card.append(labelNode, totalNode, list);
  return card;
}

function dualYieldCard(label, repaint, reject, color) {
  const card = document.createElement('article');
  card.className = 'metric-card dual-yield-card';
  card.style.setProperty('--accent', color);
  const labelNode = document.createElement('span'); labelNode.append(text(label));
  const grid = document.createElement('div'); grid.className = 'dual-yield-grid';
  [{label:'Repaint', ...repaint}, {label:'Reject', ...reject}].forEach(metric => {
    const column = document.createElement('div'); column.className = 'dual-yield-column';
    const metricLabel = document.createElement('span'); metricLabel.className = 'dual-yield-label'; metricLabel.append(text(metric.label));
    const value = document.createElement('strong'); value.className = 'dual-yield-value'; value.append(text(percent(yieldRatio(metric.numerator, metric.denominator))));
    const details = document.createElement('div'); details.className = 'dual-yield-details';
    metric.details.forEach(value => {
      const detail = document.createElement('small'); detail.className = 'dual-yield-detail'; detail.append(text(value));
      details.append(detail);
    });
    column.append(metricLabel, value, details); grid.append(column);
  });
  card.append(labelNode, grid);
  return card;
}

function inspectionYieldCard(label, numerator, denominator, rows, color) {
  const card = document.createElement('article');
  card.className = 'metric-card inspection-yield-card';
  card.style.setProperty('--accent', color);
  const labelNode = document.createElement('span'); labelNode.append(text(label));
  const valueNode = document.createElement('strong'); valueNode.append(text(percent(yieldRatio(numerator, denominator))));
  const overall = document.createElement('small'); overall.className = 'inspection-overall';
  overall.append(text(`${integer(numerator)} / ${integer(denominator)} First Decisions`));
  const list = document.createElement('div'); list.className = 'inspection-detail-list';
  rows.forEach(row => {
    const line = document.createElement('div'); line.className = 'inspection-detail-row';
    const rowLabel = document.createElement('span'); rowLabel.className = 'inspection-detail-label'; rowLabel.append(text(row.label));
    const rate = document.createElement('b'); rate.className = 'inspection-detail-rate'; rate.append(text(percent(yieldRatio(row.numerator, row.denominator))));
    const counts = document.createElement('small'); counts.className = 'inspection-detail-counts'; counts.append(text(`${optionalInteger(row.numerator)} / ${optionalInteger(row.denominator)}`));
    line.append(rowLabel, rate, counts); list.append(line);
  });
  card.append(labelNode, valueNode, overall, list);
  return card;
}

function trailerCountCard(loaded, departed, racks, color) {
  const card = document.createElement('article');
  card.className = 'metric-card trailer-count-card';
  card.style.setProperty('--accent', color);
  const labelNode = document.createElement('span'); labelNode.append(text('Trailers'));
  const grid = document.createElement('div'); grid.className = 'trailer-count-grid';
  [{label:'Loaded', value:loaded}, {label:'Departed', value:departed}].forEach(metric => {
    const column = document.createElement('div'); column.className = 'trailer-count-column';
    const metricLabel = document.createElement('span'); metricLabel.className = 'trailer-count-label'; metricLabel.append(text(metric.label));
    const value = document.createElement('strong'); value.className = 'trailer-count-value'; value.append(text(optionalInteger(metric.value)));
    column.append(metricLabel, value); grid.append(column);
  });
  const source = document.createElement('small'); source.className = 'trailer-count-source'; source.append(text('Departed = DriverLog TimeOut departures'));
  const rackList = document.createElement('div'); rackList.className = 'trailer-rack-list';
  racks.forEach(rack => {
    const row = document.createElement('div'); row.className = 'trailer-rack-row';
    const rackLabel = document.createElement('span'); rackLabel.className = 'trailer-rack-label'; rackLabel.append(text(rack.label));
    const value = document.createElement('small'); value.className = 'trailer-rack-value'; value.append(text(optionalInteger(rack.value)));
    row.append(rackLabel, value); rackList.append(row);
  });
  card.append(labelNode, grid, rackList, source);
  return card;
}

function renderCards(snapshot) {
  const current = snapshot.daily.find(row => row.date === snapshot.report_date);
  if (!current) return;
  const loaded = loadSplit(current);
  const carts = cartSplit(current);
  const paintCarts = paintCartSplit(current);
  const paintPieces = paintPieceSplit(current);
  const shippedDetail = shippedPieceDetail(snapshot);
  const hasPaintFinesse = current.paint_fty_repair_count !== undefined;
  const hasReceivingFinesse = current.finesse_repair_count !== undefined;
  const finesseRepair = Number(current.paint_fty_repair_count || 0) + Number(current.finesse_repair_count || 0);
  const finesseRejected = Number(current.reject_fty_rejected_count || 0) + Number(current.finesse_rejected_count || 0);
  const finesseDetails = hasPaintFinesse || hasReceivingFinesse ? [
    `${integer(finesseRepair)} Repaired / ${integer(finesseRejected)} Rejected`,
    `${integer(current.fuka_paint_fty_repair_count)} FUKA Repaired`,
    `${integer(Number(current.bumper_paint_fty_repair_count || 0) + Number(current.bumper_finesse_repair_count || 0))} Bumpers Repaired`,
    `${integer(Number(current.fairing_paint_fty_repair_count || 0) + Number(current.fairing_finesse_repair_count || 0))} Fairings Repaired`
  ] : ['Finesse detail unavailable'];
  if (Number(current.other_finesse_repair_count || 0) > 0) {
    finesseDetails.push(`${integer(current.other_finesse_repair_count)} Other Repaired`);
  }
  const cards = [
    ['Preliminary OEE', percent(composite(current)), 'provisional · not standard OEE', palette.purple],
    ['Complete assy sets', integer(current.complete_assy_sets), current.mic_complete_assy_sets === undefined ? 'N33 / Chassis Fairing · dated by last assembled piece' : [`${integer(current.mic_complete_assy_sets)} MIC`, `${integer(current.painted_complete_assy_sets)} Painted`], palette.teal],
    ['Assembled bumpers', integer(current.assembled_bumper_count), current.mic_assembled_bumper_count === undefined ? 'N71-6171 · AssembledDate' : [`${integer(current.mic_assembled_bumper_count)} MIC`, `${integer(current.painted_assembled_bumper_count)} Painted`], palette.blue],
    ['Pieces shipped', integer(current.parts_shipped), shippedDetail, palette.red]
  ];
  const container = $('#cards'); container.replaceChildren();
  container.append(splitMetricCard('Carts / Pieces loaded', current.parts_loaded, current.unique_pieces_loaded, [
    {label:'Carts', production:carts.production, bv:carts.bv, service:carts.service},
    {label:'Pieces', production:loaded.production, bv:loaded.bv, service:loaded.service}
  ], palette.teal));
  container.append(stagedMetricCard(current.staged_carts, current.staged_pieces, [
    {label:'Carts', production:current.production_staged_carts, bv:current.bv_staged_carts, service:current.service_staged_carts},
    {label:'Pieces', production:current.production_staged_pieces, bv:current.bv_staged_pieces, service:current.service_staged_pieces}
  ], palette.green));
  container.append(splitMetricCard('Carts / Pieces painted', current.paint_pieces_processed, current.unique_pieces_processed, [
    {label:'Carts', production:paintCarts.production, bv:paintCarts.bv, service:paintCarts.service},
    {label:'Pieces', production:paintPieces.production, bv:paintPieces.bv, service:paintPieces.service}
  ], palette.blue));
  container.append(metricCard(
    'Repaint %',
    percent(ratio(current.paint_fty_repaint_count, current.paint_fty_total)),
    [`${integer(current.paint_fty_repaint_count)} / ${integer(current.paint_fty_total)} Initial Passes`, ...repaintLineSetDetail(current)],
    palette.amber
  ));
  container.append(metricCard(
    'Finesse Effectiveness',
    percent(ratio(finesseRepair, finesseRejected)),
    finesseDetails,
    palette.green
  ));
  container.append(dualYieldCard('PPY (Paint Process Yield)', {
    numerator:current.ppy_approved, denominator:current.paint_decision_pieces,
    details:[
      `${integer(current.ppy_approved)} / ${integer(current.paint_decision_pieces)}`,
      `${integer(current.ppy_repaint_count)} ${Number(current.ppy_repaint_count) === 1 ? 'Repaint' : 'Repaints'}`,
      `${integer(current.reject_ppy_pending_count)} Pending`
    ]
  }, {
    numerator:current.reject_ppy_approved, denominator:current.reject_ppy_total,
    details:[
      `${integer(current.reject_ppy_approved)} / ${integer(current.reject_ppy_total)}`,
      `${integer(current.reject_ppy_rejected_count)} Rejected`,
      `${integer(current.reject_ppy_pending_count)} Pending`
    ]
  }, palette.amber));
  container.append(dualYieldCard('FTY (First Time Yield)', {
    numerator:current.paint_fty_approved, denominator:current.paint_fty_total,
    details:[
      `${integer(current.paint_fty_approved)} / ${integer(current.paint_fty_total)}`,
      `${integer(current.paint_fty_repaint_count)} ${Number(current.paint_fty_repaint_count) === 1 ? 'Repaint' : 'Repaints'}`,
      `${integer(current.reject_fty_pending_count)} Pending`
    ]
  }, {
    numerator:current.reject_fty_approved, denominator:current.reject_fty_total,
    details:[
      `${integer(current.reject_fty_approved)} / ${integer(current.reject_fty_total)}`,
      `${integer(current.reject_fty_rejected_count)} Rejected`,
      `${integer(current.reject_fty_pending_count)} Pending`
    ]
  }, palette.blue));
  container.append(inspectionYieldCard(
    'Receiving FTY', current.receiving_approved, current.receiving_total,
    [
      {label:'Bumpers', numerator:current.receiving_bumper_approved, denominator:current.receiving_bumper_total},
      {label:'Fairings', numerator:current.receiving_fairing_approved, denominator:current.receiving_fairing_total}
    ], palette.green
  ));
  container.append(inspectionYieldCard(
    'Final FTY', current.final_approved, current.final_total,
    [
      {label:'FUKA', numerator:current.final_fuka_approved, denominator:current.final_fuka_total},
      {label:'Bumpers', numerator:current.final_bumper_approved, denominator:current.final_bumper_total},
      {label:'Fairings', numerator:current.final_fairing_approved, denominator:current.final_fairing_total}
    ], palette.purple
  ));
  cards.forEach(card => container.append(metricCard(...card)));
  container.append(trailerCountCard(current.trailers_prepared, current.trailers_shipped, [
    {label:'Bumper racks', value:current.bumper_racks_shipped},
    {label:'FUKA racks', value:current.fuka_racks_shipped},
    {label:'Fairing racks', value:current.fairing_racks_shipped}
  ], palette.amber));
  markSelectableCards(container);
}

function chartKey(label) {
  return label.trim().toLowerCase() === 'carts / pieces loaded'
    ? 'loaded'
    : label.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

function selectMetricChart(key, label) {
  selectedChartKey = key;
  selectedChartLabel = label;
  document.querySelectorAll('.selectable-card').forEach(card => {
    const selected = card.dataset.chartKey === selectedChartKey;
    card.classList.toggle('selected-card', selected);
    card.setAttribute('aria-pressed', String(selected));
  });
  if (activeSnapshot) renderMetricCharts(activeSnapshot);
}

function markSelectableCards(container) {
  [...container.children].forEach(card => {
    const label = card.firstElementChild?.textContent?.trim() || 'Metric';
    const key = chartKey(label);
    card.classList.add('selectable-card');
    card.dataset.chartKey = key;
    card.setAttribute('role', 'button');
    card.setAttribute('tabindex', '0');
    card.setAttribute('aria-controls', 'metric-chart-panel');
    card.setAttribute('aria-label', `Show ${label} charts`);
    card.addEventListener('click', () => selectMetricChart(key, label));
    card.addEventListener('keydown', event => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      selectMetricChart(key, label);
    });
  });
  selectMetricChart(selectedChartKey, selectedChartLabel);
}

function chartLegend(items) {
  const legend = document.createElement('div'); legend.className = 'chart-legend';
  items.forEach(item => {
    const key = document.createElement('span'); key.className = 'legend-key';
    const swatch = document.createElement('span'); swatch.className = `legend-swatch${item.line ? ' line' : ''}`;
    swatch.style.background = item.color;
    swatch.style.color = item.color;
    key.append(swatch, text(item.label)); legend.append(key);
  });
  return legend;
}

function hourBucketLabel(bucket) {
  const hour = Number(String(bucket).slice(11, 13));
  if (!Number.isFinite(hour)) return '';
  if (hour === 0) return '12a';
  if (hour < 12) return `${hour}a`;
  if (hour === 12) return '12p';
  return `${hour - 12}p`;
}

function loadedLinearTrend(rows, field) {
  const firstWeek = rows.length ? Date.parse(rows[0].bucket + 'T00:00:00') : NaN;
  const points = rows.map((row, rowIndex) => ({
    rowIndex,
    weekIndex:(Date.parse(row.bucket + 'T00:00:00') - firstWeek) / (7 * 24 * 60 * 60 * 1000),
    value:Number(row[field])
  })).filter((point, index) => rows[index].data_available && !rows[index].is_partial
      && Number(rows[index].represented_days || 0) > 0
      && Number.isFinite(point.weekIndex) && Number.isFinite(point.value));
  if (points.length < 2) return null;
  const meanX = points.reduce((sum, point) => sum + point.weekIndex, 0) / points.length;
  const meanY = points.reduce((sum, point) => sum + point.value, 0) / points.length;
  const denominator = points.reduce((sum, point) => sum + Math.pow(point.weekIndex - meanX, 2), 0);
  if (!denominator) return null;
  const slope = points.reduce((sum, point) => sum + (point.weekIndex - meanX) * (point.value - meanY), 0) / denominator;
  const intercept = meanY - slope * meanX;
  return {
    slope, startIndex:points[0].rowIndex, endIndex:points[points.length - 1].rowIndex,
    startValue:intercept + slope * points[0].weekIndex,
    endValue:intercept + slope * points[points.length - 1].weekIndex
  };
}

function loadedWeeklyReferenceModel(rows, model) {
  const completed = rows.filter(row => row.data_available && !row.is_partial
    && Number(row.performance_days || 0) > 0
    && Number(row.net_loading_minutes || 0) > 0);
  const performanceDays = completed.reduce((sum, row) => sum + Number(row.performance_days || 0), 0);
  const netLoadingMinutes = completed.reduce((sum, row) => sum + Number(row.net_loading_minutes || 0), 0);
  const averageNetHours = performanceDays > 0 ? netLoadingMinutes / 60 / performanceDays : null;
  const dailyValue = rateField => {
    const rate = Number(model?.[rateField]);
    return averageNetHours !== null && Number.isFinite(rate)
      ? Number((rate * averageNetHours).toFixed(1)) : null;
  };
  return {
    performanceDays, averageNetHours,
    targetCarts:dailyValue('target_carts_per_hour'),
    goalCarts:dailyValue('goal_carts_per_hour'),
    targetPieces:dailyValue('target_pieces_per_hour'),
    goalPieces:dailyValue('goal_pieces_per_hour')
  };
}

function loadedWholeNumberScaleMaximum(values) {
  const largest = Math.max(...values.map(value => Math.max(0, Number(value))).filter(Number.isFinite), 1);
  const tickStep = Math.max(1, Math.ceil(largest * 1.18 / 4));
  return tickStep * 4;
}

function renderLoadedLineChart(container, rows, options) {
  container.replaceChildren();
  if (!rows.length) {
    const empty = document.createElement('div'); empty.className = 'empty-state';
    empty.append(text('No aggregate chart data is available for this snapshot.'));
    container.append(empty); return;
  }
  const width = 720, height = 250, left = 48, right = 14, top = 16;
  const bottom = options.verticalLabels ? 52 : 34;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const values = rows.map(row => row.data_available && row[options.field] !== null
    ? Number(row[options.field]) : null);
  const trend = options.trend ? loadedLinearTrend(rows, options.field) : null;
  const references = (options.references || []).map(reference => {
    const constantValue = Number(reference.value);
    const hasConstantValue = reference.value !== null && reference.value !== undefined
      && Number.isFinite(constantValue);
    return {
      ...reference,
      values:rows.map(row => {
        if (!row.data_available) return null;
        if (hasConstantValue) return constantValue;
        return row[reference.field] !== null && row[reference.field] !== undefined
          ? Number(row[reference.field]) : null;
      })
    };
  });
  const finiteValues = values.filter(value => value !== null && Number.isFinite(value));
  references.forEach(reference => finiteValues.push(
    ...reference.values.filter(value => value !== null && Number.isFinite(value))
  ));
  if (trend) finiteValues.push(Math.max(0, trend.startValue), Math.max(0, trend.endValue));
  const maximum = loadedWholeNumberScaleMaximum(finiteValues);
  const y = value => top + (maximum - Math.max(0, value)) * plotHeight / maximum;
  const band = plotWidth / rows.length;
  const centerX = index => left + band * index + band / 2;
  const formatValue = options.formatValue || wholeNumber;
  const svg = svgNode('svg', {viewBox:'0 0 ' + width + ' ' + height, role:'img', 'aria-label':options.ariaLabel});

  for (let index = 0; index <= 4; index += 1) {
    const value = maximum * index / 4;
    const yy = y(value);
    svg.append(svgNode('line', {x1:left, x2:width - right, y1:yy, y2:yy, stroke:palette.grid, 'stroke-width':1}));
    const label = svgNode('text', {x:left - 8, y:yy + 4, 'text-anchor':'end', fill:palette.muted, 'font-size':10, class:'loaded-scale-label'});
    label.append(text(formatValue(value))); svg.append(label);
  }

  const barChart = options.chartType === 'bar';
  const barWidth = Math.min(38, band * .62);
  let segment = [];
  const flushSegment = () => {
    if (segment.length > 1) {
      svg.append(svgNode('polyline', {
        points:segment.join(' '), fill:'none', stroke:options.color, 'stroke-width':2.7,
        'stroke-linejoin':'round', 'stroke-linecap':'round'
      }));
    }
    segment = [];
  };
  rows.forEach((row, index) => {
    const value = values[index];
    if (value === null || !Number.isFinite(value)) {
      flushSegment();
      if (!barChart) {
        svg.append(svgNode('line', {
          x1:centerX(index) - 7, x2:centerX(index) + 7, y1:y(0) - 2, y2:y(0) - 2,
          stroke:'#aebbc4', 'stroke-width':2
        }));
      }
    } else {
      const suffix = options.tooltipSuffix ? options.tooltipSuffix(row) : '';
      const title = svgNode('title');
      title.append(text(options.bucketTitle(row) + ' · ' + options.label + ': ' + formatValue(value) + suffix));
      if (barChart) {
        const bar = svgNode('rect', {
          x:centerX(index) - barWidth / 2, y:y(value), width:barWidth,
          height:Math.max(1, y(0) - y(value)), class:'loaded-bar',
          fill:row.is_partial ? '#fff3df' : options.color,
          stroke:row.is_partial ? palette.amber : options.color,
          'stroke-width':row.is_partial ? 2 : 1, opacity:row.is_partial ? .94 : .86
        });
        bar.append(title); svg.append(bar);
      } else {
        segment.push(centerX(index) + ',' + y(value));
        const circle = svgNode('circle', {
          cx:centerX(index), cy:y(value), r:3.2, fill:row.is_partial ? '#fff3df' : options.color,
          stroke:row.is_partial ? palette.amber : '#fff', 'stroke-width':row.is_partial ? 2 : 1,
          'stroke-dasharray':row.is_partial ? '2 1' : 'none'
        });
        circle.append(title); svg.append(circle);
      }
      const valueLabel = svgNode('text', {
        x:centerX(index), y:Math.max(top + 10, y(value) - 7),
        'text-anchor':'middle', class:'loaded-value-label'
      });
      valueLabel.append(text(wholeNumber(value))); svg.append(valueLabel);
    }
    if (options.showTick(index, rows.length)) {
      const labelY = height - 8;
      const attributes = {
        x:centerX(index), y:labelY, fill:palette.muted, 'font-size':10, class:'loaded-axis-label',
        'text-anchor':options.verticalLabels ? 'start' : 'middle'
      };
      if (options.verticalLabels) attributes.transform = 'rotate(-90 ' + centerX(index) + ' ' + labelY + ')';
      const label = svgNode('text', attributes);
      label.append(text(options.bucketLabel(row))); svg.append(label);
    }
  });
  flushSegment();

  if (trend) {
    const trendLine = svgNode('line', {
      x1:centerX(trend.startIndex), y1:y(trend.startValue),
      x2:centerX(trend.endIndex), y2:y(trend.endValue),
      stroke:palette.navy, 'stroke-width':2, 'stroke-dasharray':'7 5', opacity:.78
    });
    const title = svgNode('title');
    title.append(text('Linear trend: ' + (trend.slope >= 0 ? '+' : '') + decimal(trend.slope) + ' per week'));
    trendLine.append(title); svg.append(trendLine);
  }
  references.forEach(reference => {
    if (reference.spanFullWidth) {
      const referencePoints = reference.values.map((value, index) => ({value, index}))
        .filter(point => point.value !== null && Number.isFinite(point.value));
      if (referencePoints.length) {
        const points = [left + ',' + y(referencePoints[0].value)];
        referencePoints.forEach(point => points.push(centerX(point.index) + ',' + y(point.value)));
        points.push((width - right) + ',' + y(referencePoints[referencePoints.length - 1].value));
        const line = svgNode('polyline', {
          points:points.join(' '), fill:'none', stroke:reference.color,
          'stroke-width':2.2, 'stroke-dasharray':reference.dash || '5 4',
          'stroke-linejoin':'round', 'stroke-linecap':'round', opacity:.9,
          class:'loaded-reference-line loaded-reference-line-full-width'
        });
        const title = svgNode('title');
        title.append(text(reference.label + ' · horizontal 13-week average-day reference'));
        line.append(title); svg.append(line);
      }
      return;
    }
    let referenceSegment = [];
    const flushReference = () => {
      let line = null;
      if (referenceSegment.length > 1) {
        line = svgNode('polyline', {
          points:referenceSegment.join(' '), fill:'none', stroke:reference.color,
          'stroke-width':2.2, 'stroke-dasharray':reference.dash || '5 4',
          'stroke-linejoin':'round', 'stroke-linecap':'round', opacity:.9,
          class:'loaded-reference-line'
        });
      } else if (referenceSegment.length === 1) {
        const [pointX, pointY] = referenceSegment[0].split(',').map(Number);
        const halfSegment = Math.min(14, band * .34);
        line = svgNode('line', {
          x1:pointX - halfSegment, x2:pointX + halfSegment, y1:pointY, y2:pointY,
          stroke:reference.color, 'stroke-width':2.2,
          'stroke-dasharray':reference.dash || '5 4', 'stroke-linecap':'round', opacity:.9,
          class:'loaded-reference-line'
        });
      }
      if (line) {
        const title = svgNode('title'); title.append(text(reference.label));
        line.append(title); svg.append(line);
      }
      referenceSegment = [];
    };
    reference.values.forEach((value, index) => {
      if (value === null || !Number.isFinite(value)) flushReference();
      else referenceSegment.push(centerX(index) + ',' + y(value));
    });
    flushReference();
  });
  const legend = [{label:options.label, color:options.color, line:!barChart}];
  if (trend) legend.push({label:'Linear trend', color:palette.navy, line:true});
  references.forEach(reference => legend.push({label:reference.label, color:reference.color, line:true}));
  container.append(svg, chartLegend(legend));
}

function loadedHourlySummary(rows, options, performance) {
  const values = rows.map(row => Number(row[options.field])).filter(Number.isFinite);
  const total = values.reduce((sum, value) => sum + value, 0);
  const peak = rows.reduce((best, row) => {
    const value = Number(row[options.field]);
    return Number.isFinite(value) && (!best || value > best.value) ? {row, value} : best;
  }, null);
  const model = performance?.model || {};
  const day = performance?.day || {};
  const isCarts = options.field === 'carts_loaded';
  const rate = day[isCarts ? 'carts_per_net_hour' : 'pieces_per_net_hour'];
  const targetRate = model[isCarts ? 'target_carts_per_hour' : 'target_pieces_per_hour'];
  const goalRate = model[isCarts ? 'goal_carts_per_hour' : 'goal_pieces_per_hour'];
  const targetCount = day[isCarts ? 'target_carts' : 'target_pieces'];
  const goalCount = day[isCarts ? 'goal_carts' : 'goal_pieces'];
  const netHours = Number(day.net_loading_minutes || 0) / 60;
  const hasWindow = Boolean(day.first_cart_loaded_at && day.last_cart_loaded_at && netHours > 0);
  const windowDetail = hasWindow
    ? `${clockTimeLabel(day.first_cart_loaded_at)}–${clockTimeLabel(day.last_cart_loaded_at)}`
      + (Number(day.lunch_allowance_minutes || 0) > 0
        ? ` · ${integer(day.lunch_allowance_minutes)} min lunch`
        : (day.performance_scored ? ' · no lunch allowance' : ' · live span'))
    : 'Need at least two distinct-cart load times';
  const scoreDetail = (expected, label) => day.performance_scored && expected !== null && expected !== undefined
    ? `${decimal(expected)} ${label} expected for net time`
    : 'Rate shown · partial or unscored day';
  const summary = document.createElement('div');
  summary.className = 'loaded-chart-summary';
  summary.setAttribute('role', 'group');
  summary.setAttribute('aria-label', options.label + ' selected-day hourly summary');
  const items = [
    {label:'Day total', value:integer(total), detail:rows.length + ' clock-hour buckets'},
    {label:'Peak hour', value:peak ? integer(peak.value) : 'No Data', detail:peak ? hourBucketLabel(peak.row.bucket) + ' bucket' : 'No hourly data'},
    {label:day.performance_scored ? 'Net loading time' : 'Net loading time · live', value:hasWindow ? decimal(netHours) + ' h' : 'No Data', detail:windowDetail},
    {label:'Actual rate', value:rate === null || rate === undefined ? 'No Data' : decimal(rate) + '/hr', detail:hasWindow ? `${integer(total)} over ${decimal(netHours)} net hours` : 'No loading window'},
    {label:'Interim target', value:targetRate === null || targetRate === undefined ? 'No Data' : decimal(targetRate) + '/hr', detail:scoreDetail(targetCount, options.label.toLowerCase())},
    {label:'Long-term goal', value:goalRate === null || goalRate === undefined ? 'No Data' : decimal(goalRate) + '/hr', detail:scoreDetail(goalCount, options.label.toLowerCase())}
  ];
  items.forEach(item => {
    const metric = document.createElement('div'); metric.className = 'loaded-chart-summary-item';
    const label = document.createElement('span'); label.append(text(item.label));
    const value = document.createElement('strong'); value.append(text(item.value));
    const detail = document.createElement('small'); detail.append(text(item.detail));
    metric.append(label, value, detail); summary.append(metric);
  });
  return summary;
}

function loadedWeeklySummary(rows, options) {
  const completed = rows.filter(row => row.data_available && !row.is_partial
    && Number(row.represented_days || 0) > 0 && row[options.averageField] !== null);
  const representedDays = completed.reduce((sum, row) => sum + Number(row.represented_days || 0), 0);
  const total = completed.reduce((sum, row) => sum + Number(row[options.totalField] || 0), 0);
  const periodAverage = representedDays ? total / representedDays : null;
  const latest = completed.length ? completed[completed.length - 1] : null;
  const trend = loadedLinearTrend(rows, options.averageField);
  const summary = document.createElement('div');
  summary.className = 'loaded-chart-summary';
  summary.setAttribute('role', 'group');
  summary.setAttribute('aria-label', options.label + ' 13-week summary');
  const items = [
    {
      label:'Period average', value:periodAverage === null ? 'No Data' : decimal(periodAverage),
      detail:representedDays ? representedDays + ' represented days' : 'No completed production days'
    },
    {
      label:'Latest full week', value:latest ? decimal(latest[options.averageField]) : 'No Data',
      detail:latest ? dateLabel(latest.bucket) + ' · ' + latest.represented_days + ' days' : 'No completed week'
    },
    {
      label:'Trend',
      value:trend ? (Math.abs(trend.slope) < .05 ? 'Flat' : (trend.slope > 0 ? 'Up' : 'Down')) : 'No Data',
      detail:trend ? (trend.slope >= 0 ? '+' : '') + decimal(trend.slope) + ' per week' : 'Need two completed weeks'
    }
  ];
  items.forEach(item => {
    const metric = document.createElement('div'); metric.className = 'loaded-chart-summary-item';
    const label = document.createElement('span'); label.append(text(item.label));
    const value = document.createElement('strong'); value.append(text(item.value));
    const detail = document.createElement('small'); detail.append(text(item.detail));
    metric.append(label, value, detail); summary.append(metric);
  });
  return summary;
}

function loadedChartCard(title, note, rows, options) {
  const figure = document.createElement('figure'); figure.className = 'loaded-chart-card';
  const caption = document.createElement('figcaption');
  const heading = document.createElement('span'); heading.append(text(title));
  const detail = document.createElement('small'); detail.append(text(note));
  caption.append(heading, detail);
  const displayRows = options.omitNull
    ? rows.filter(row => row.data_available && Number(row.represented_days || 0) > 0 && row[options.field] !== null)
    : rows;
  const chart = document.createElement('div'); chart.className = 'loaded-chart';
  renderLoadedLineChart(chart, displayRows, options);
  figure.append(caption);
  if (options.hourlySummary) figure.append(loadedHourlySummary(displayRows, options.hourlySummary, options.performance));
  if (options.summary) figure.append(loadedWeeklySummary(displayRows, options.summary));
  figure.append(chart); return figure;
}

function metricChartSection(title, note) {
  const section = document.createElement('section'); section.className = 'metric-chart-section';
  const heading = document.createElement('div'); heading.className = 'metric-chart-section-heading';
  const titleNode = document.createElement('h3'); titleNode.append(text(title));
  const noteNode = document.createElement('p'); noteNode.append(text(note));
  heading.append(titleNode, noteNode);
  const grid = document.createElement('div'); grid.className = 'loaded-chart-grid';
  section.append(heading, grid); return {section, grid};
}

function renderLoadedCharts(snapshot) {
  const content = $('#metric-chart-content'); content.replaceChildren();
  const loaded = snapshot.chart_series?.loaded;
  if (!loaded || !Array.isArray(loaded.hourly) || !Array.isArray(loaded.weekly_13)) {
    const empty = document.createElement('div'); empty.className = 'chart-placeholder';
    empty.append(text('This saved snapshot predates the 13-week Loaded chart contract. Load or refresh this date to build its aggregate chart series.'));
    content.append(empty); return;
  }
  const hourly = loaded.hourly, weekly = loaded.weekly_13;
  const performance = {model:loaded.performance_model || {}, day:loaded.selected_day || {}};
  const weeklyReference = loadedWeeklyReferenceModel(weekly, performance.model);
  const reportDay = fullDateLabel(snapshot.report_date);
  const hourlySection = metricChartSection('Hourly · selected report day', '24 clock-hour buckets · ' + reportDay);
  hourlySection.grid.append(
    loadedChartCard('Carts loaded by hour', 'Total carts · first load event', hourly, {
      field:'carts_loaded', label:'Total carts', color:palette.teal, trend:false, formatValue:wholeNumber,
      ariaLabel:'Hourly total carts loaded with interim target and long-term goal for ' + reportDay,
      bucketLabel:row => hourBucketLabel(row.bucket), bucketTitle:row => hourBucketLabel(row.bucket),
      verticalLabels:true, showTick:() => true, performance,
      references:[
        {value:performance.model.target_carts_per_hour, label:'Interim target', color:palette.amber, dash:'6 4'},
        {value:performance.model.goal_carts_per_hour, label:'Long-term goal', color:palette.red, dash:'3 4'}
      ],
      hourlySummary:{label:'Carts', field:'carts_loaded'}
    }),
    loadedChartCard('Pieces loaded by hour', 'Total load events', hourly, {
      field:'parts_loaded', label:'Total pieces', color:palette.blue, trend:false, formatValue:wholeNumber,
      ariaLabel:'Hourly total pieces loaded with interim target and long-term goal for ' + reportDay,
      bucketLabel:row => hourBucketLabel(row.bucket), bucketTitle:row => hourBucketLabel(row.bucket),
      verticalLabels:true, showTick:() => true, performance,
      references:[
        {value:performance.model.target_pieces_per_hour, label:'Interim target', color:palette.amber, dash:'6 4'},
        {value:performance.model.goal_pieces_per_hour, label:'Long-term goal', color:palette.red, dash:'3 4'}
      ],
      hourlySummary:{label:'Pieces', field:'parts_loaded'}
    })
  );
  const weeklySection = metricChartSection(
    '13-week daily averages',
    'Sunday–Saturday · represented production days · partial selected week excluded from trend and target scoring'
  );
  const weeklyOptions = {
    formatValue:wholeNumber, trend:true, omitNull:true, verticalLabels:true, chartType:'bar',
    bucketLabel:row => dateLabel(row.bucket),
    bucketTitle:row => fullDateLabel(row.bucket) + ' through ' + fullDateLabel(row.bucket_end),
    tooltipSuffix:row => ' · ' + integer(row.represented_days) + ' represented days',
    showTick:() => true
  };
  weeklySection.grid.append(
    loadedChartCard('Carts loaded · 13 weeks', 'Average total carts per represented day', weekly, {
      ...weeklyOptions, field:'average_carts_loaded', label:'Daily average carts', color:palette.teal,
      ariaLabel:'Thirteen-week daily average carts loaded with linear trend, interim target, and long-term goal',
      references:[
        {value:weeklyReference.targetCarts, label:'Net-time interim target', color:palette.amber, dash:'6 4', spanFullWidth:true},
        {value:weeklyReference.goalCarts, label:'Net-time long-term goal', color:palette.red, dash:'3 4', spanFullWidth:true}
      ],
      summary:{label:'Carts', averageField:'average_carts_loaded', totalField:'carts_loaded_total'}
    }),
    loadedChartCard('Pieces loaded · 13 weeks', 'Average total pieces per represented day', weekly, {
      ...weeklyOptions, field:'average_parts_loaded', label:'Daily average pieces', color:palette.blue,
      ariaLabel:'Thirteen-week daily average pieces loaded with linear trend, interim target, and long-term goal',
      references:[
        {value:weeklyReference.targetPieces, label:'Net-time interim target', color:palette.amber, dash:'6 4', spanFullWidth:true},
        {value:weeklyReference.goalPieces, label:'Net-time long-term goal', color:palette.red, dash:'3 4', spanFullWidth:true}
      ],
      summary:{label:'Pieces', averageField:'average_parts_loaded', totalField:'parts_loaded_total'}
    })
  );
  content.append(hourlySection.section, weeklySection.section);
  if (weekly.some(row => row.is_partial)) {
    const note = document.createElement('span'); note.className = 'chart-partial-note';
    note.append(text('The selected week is partial and is displayed but excluded from both trendlines.'));
    weeklySection.section.append(note);
  }
  if (weeklyReference.averageNetHours !== null) {
    const comparison = document.createElement('span'); comparison.className = 'chart-unavailable-note';
    comparison.append(text(
      'Horizontal target and goal lines use one ' + decimal(weeklyReference.averageNetHours)
      + '-hour average net-loading day from ' + integer(weeklyReference.performanceDays)
      + ' completed loading days in completed weeks. The reference updates only when the 13-week window rolls.'
    ));
    weeklySection.section.append(comparison);
  }
  if (weekly.some(row => !row.data_available)) {
    const unavailable = document.createElement('span'); unavailable.className = 'chart-unavailable-note';
    unavailable.append(text('Unavailable weeks before the September 8 history boundary are omitted, not zero.'));
    weeklySection.section.append(unavailable);
  }
}

function renderMetricCharts(snapshot) {
  $('#metric-chart-title').textContent = selectedChartLabel;
  const summary = $('#metric-chart-summary');
  if (selectedChartKey === 'loaded') {
    summary.textContent = 'Hourly totals with interim-target and long-term-goal lines, followed by 13-week daily averages with horizontal average-day references and trend.';
    renderLoadedCharts(snapshot); return;
  }
  summary.textContent = 'This tile is selectable; its chart contract will be added after the Loaded pilot layout is finalized.';
  const placeholder = document.createElement('div'); placeholder.className = 'chart-placeholder';
  placeholder.append(text(`${selectedChartLabel} charts are not enabled in this first layout pilot.`));
  $('#metric-chart-content').replaceChildren(placeholder);
}

function renderTable(table, headers, rows, rowClass = () => '') {
  const thead = document.createElement('thead');
  const heading = document.createElement('tr');
  headers.forEach(item => { const th = document.createElement('th'); th.append(text(item.label)); heading.append(th); });
  thead.append(heading);
  const tbody = document.createElement('tbody');
  rows.forEach(row => {
    const tr = document.createElement('tr');
    tr.className = rowClass(row);
    headers.forEach(item => { const td = document.createElement('td'); td.append(text(item.value(row))); tr.append(td); });
    tbody.append(tr);
  });
  table.replaceChildren(thead, tbody);
}

function renderLineChart(container, rows, series, asPercent = false) {
  container.replaceChildren();
  if (rows.length < 2) {
    const empty = document.createElement('div'); empty.className = 'empty-state'; empty.append(text('Not enough production-day data to chart.')); container.append(empty); return;
  }
  const width = 720, height = 250, left = 48, right = 18, top = 18, bottom = 38;
  const values = series.flatMap(item => rows.map(row => item.value(row))).filter(value => value !== null && Number.isFinite(value));
  let minimum = asPercent ? Math.max(0, Math.floor((Math.min(...values) - 0.05) * 10) / 10) : 0;
  let maximum = asPercent ? 1 : Math.max(...values, 1) * 1.08;
  if (maximum <= minimum) maximum = minimum + 1;
  const x = index => left + (index * (width - left - right) / Math.max(rows.length - 1, 1));
  const y = value => top + (maximum - value) * (height - top - bottom) / (maximum - minimum);
  const svg = svgNode('svg', {viewBox: `0 0 ${width} ${height}`, role: 'img'});
  for (let index = 0; index <= 4; index += 1) {
    const value = minimum + ((maximum - minimum) * index / 4);
    const yy = y(value);
    svg.append(svgNode('line', {x1: left, x2: width - right, y1: yy, y2: yy, stroke: palette.grid, 'stroke-width': 1}));
    const label = svgNode('text', {x: left - 8, y: yy + 4, 'text-anchor': 'end', fill: palette.muted, 'font-size': 10});
    label.append(text(asPercent ? `${Math.round(value * 100)}%` : Math.round(value)));
    svg.append(label);
  }
  rows.forEach((row, index) => {
    const label = svgNode('text', {x: x(index), y: height - 12, 'text-anchor': 'middle', fill: palette.muted, 'font-size': 10});
    label.append(text(dateLabel(row.date))); svg.append(label);
  });
  series.forEach(item => {
    const usable = rows.map((row, index) => ({value: item.value(row), index})).filter(point => point.value !== null && Number.isFinite(point.value));
    const points = usable.map(point => `${x(point.index)},${y(point.value)}`).join(' ');
    svg.append(svgNode('polyline', {points, fill: 'none', stroke: item.color, 'stroke-width': 3, 'stroke-linecap': 'round', 'stroke-linejoin': 'round'}));
    usable.forEach(point => svg.append(svgNode('circle', {cx: x(point.index), cy: y(point.value), r: 4, fill: item.color, stroke: '#fff', 'stroke-width': 1.5})));
  });
  const legend = document.createElement('div'); legend.className = 'chart-legend';
  series.forEach(item => {
    const key = document.createElement('span'); key.className = 'legend-key';
    const swatch = document.createElement('span'); swatch.className = 'legend-swatch'; swatch.style.background = item.color;
    key.append(swatch, text(item.label)); legend.append(key);
  });
  container.append(svg, legend);
}

function renderDaily(snapshot) {
  const active = snapshot.daily.filter(row => row.production_day);
  renderLineChart($('#throughput-chart'), active, [
    {label:'Loaded', color:palette.teal, value:row => Number(row.parts_loaded)},
    {label:'Painted', color:palette.blue, value:row => Number(row.paint_pieces_processed)},
    {label:'EOL', color:palette.purple, value:row => Number(row.eol_inspected)},
    {label:'Paint shipped', color:palette.red, value:row => Number(row.painted_parts_shipped)}
  ]);
  renderLineChart($('#quality-chart'), active, [
    {label:'Repaint PPY', color:palette.teal, value:row => yieldRatio(row.ppy_approved, row.paint_decision_pieces)},
    {label:'Reject PPY', color:palette.red, value:row => yieldRatio(row.reject_ppy_approved, row.reject_ppy_total)},
    {label:'Repaint FTY', color:palette.blue, value:row => yieldRatio(row.paint_fty_approved, row.paint_fty_total)},
    {label:'Reject FTY', color:palette.purple, value:row => yieldRatio(row.reject_fty_approved, row.reject_fty_total)}
  ], true);
  renderTable($('#daily-table'), [
    {label:'Day', value:row => `${row.date}${row.production_day ? '' : ' · No production'}`},
    {label:'Loaded', value:row => integer(row.parts_loaded)},
    {label:'Paint carts', value:row => integer(row.paint_carts)},
    {label:'Paint pieces', value:row => integer(row.paint_pieces_processed)},
    {label:'EOL', value:row => integer(row.eol_inspected)},
    {label:'Paint ship', value:row => integer(row.painted_parts_shipped)},
    {label:'Total ship', value:row => integer(row.parts_shipped)}
  ], snapshot.daily, row => row.production_day ? '' : 'no-production');
}

function renderPeriods(snapshot) {
  renderTable($('#period-table'), [
    {label:'Period', value:row => row.label},
    {label:'Production days', value:row => integer(row.data_days)},
    {label:'Paint avg/day', value:row => average(row.paint_pieces_processed, row.data_days)},
    {label:'EOL avg/day', value:row => average(row.eol_inspected, row.data_days)},
    {label:'Paint ship avg/day', value:row => average(row.painted_parts_shipped, row.data_days)},
    {label:'Bumpers avg/day', value:row => average(row.bumpers_shipped, row.data_days)},
    {label:'Repaint PPY', value:row => percent(yieldRatio(row.ppy_approved, row.paint_decision_pieces))},
    {label:'Reject PPY', value:row => percent(yieldRatio(row.reject_ppy_approved, row.reject_ppy_total))},
    {label:'Repaint FTY', value:row => percent(yieldRatio(row.paint_fty_approved, row.paint_fty_total))},
    {label:'Reject FTY', value:row => percent(yieldRatio(row.reject_fty_approved, row.reject_fty_total))},
    {label:'Repaint %', value:row => percent(ratio(row.paint_fty_repaint_count, row.paint_fty_total))},
    {label:'Composite', value:row => percent(composite(row))}
  ], snapshot.periods);
}

function renderDefects(snapshot) {
  renderTable($('#defect-table'), [
    {label:'Step', value:row => row.step},
    {label:'Defect', value:row => row.description},
    {label:'Count', value:row => integer(row.count)}
  ], snapshot.top_defects);
}

function renderShipping(snapshot) {
  const grouped = new Map();
  snapshot.shipping.forEach(row => {
    if (!grouped.has(row.date)) grouped.set(row.date, []);
    grouped.get(row.date).push(row);
  });
  const totals = [...grouped.values()].map(rows => rows.reduce((sum, row) => sum + Number(row.pieces), 0));
  const maximum = Math.max(...totals, 1);
  const colors = {'FUKA':palette.teal, 'Fairings':palette.blue, 'Bumpers':palette.red, 'N71-6164':palette.amber, 'Other':palette.purple};
  const container = $('#shipping-chart'); container.replaceChildren();
  const present = new Set(snapshot.shipping.map(row => row.line_set));
  const legend = document.createElement('div'); legend.className = 'shipping-legend';
  ['FUKA', 'Fairings', 'Bumpers', 'N71-6164', 'Other'].filter(label => present.has(label)).forEach(label => {
    const item = document.createElement('span'); item.className = 'shipping-legend-item';
    const swatch = document.createElement('span'); swatch.className = 'shipping-legend-swatch'; swatch.style.background = colors[label];
    item.append(swatch, text(label)); legend.append(item);
  });
  container.append(legend);
  [...grouped.entries()].sort(([left], [right]) => left.localeCompare(right)).forEach(([day, rows]) => {
    const total = rows.reduce((sum, row) => sum + Number(row.pieces), 0);
    const line = document.createElement('div'); line.className = 'shipping-day';
    const label = document.createElement('span'); label.append(text(dateLabel(day)));
    const track = document.createElement('div'); track.className = 'shipping-track'; track.style.width = `${Math.max(total / maximum * 100, 8)}%`;
    rows.forEach(row => { const segment = document.createElement('span'); segment.className = 'shipping-segment'; segment.title = `${row.line_set}: ${integer(row.pieces)}`; segment.style.width = `${Number(row.pieces) / Math.max(total, 1) * 100}%`; segment.style.background = colors[row.line_set] || palette.amber; track.append(segment); });
    const totalNode = document.createElement('span'); totalNode.className = 'shipping-total'; totalNode.append(text(integer(total)));
    line.append(label, track, totalNode); container.append(line);
  });
}

function renderPainters(snapshot) {
  const panel = $('#painter-panel');
  panel.hidden = !snapshot.painters.length;
  if (!snapshot.painters.length) return;
  renderTable($('#painter-table'), [
    {label:'Date', value:row => row.date}, {label:'Painter', value:row => row.painter},
    {label:'Booth', value:row => integer(row.booth)}, {label:'Parts', value:row => integer(row.parts)},
    {label:'Minutes', value:row => integer(row.minutes)}, {label:'Parts/hr', value:row => Number(row.parts_per_hour).toFixed(1)}
  ], snapshot.painters);
}

function renderNotes(snapshot) {
  const notes = $('#quality-notes'); notes.replaceChildren();
  snapshot.data_quality_notes.forEach(item => { const li = document.createElement('li'); li.append(text(item)); notes.append(li); });
  const attention = $('#attention-items'); attention.replaceChildren();
  (snapshot.attention?.items || []).forEach(item => {
    const card = document.createElement('article'); card.className = 'attention-card';
    const heading = document.createElement('strong'); heading.append(text(item.title));
    const detail = document.createElement('p'); detail.append(text(item.detail));
    card.append(heading, detail); attention.append(card);
  });
}

function render(snapshot) {
  activeSnapshot = snapshot;
  displayedReportDate = snapshot.report_date;
  $('#report-date').textContent = `Report date ${fullDateLabel(snapshot.report_date)}`;
  $('#report-range').textContent = rangeLabel(snapshot.daily);
  $('#generated-at').textContent = `Snapshot ${new Date(snapshot.generated_at).toLocaleString()}`;
  $('#date-input').value = snapshot.report_date;
  updateNavigationState();
  renderCards(snapshot);
  renderMetricCharts(snapshot);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed with HTTP ${response.status}`);
  return payload;
}

function renderRefreshCountdown() {
  const node = $('#refresh-countdown');
  node.classList.toggle('refreshing', autoRefreshInProgress);
  if (autoRefreshInProgress) {
    node.textContent = 'Refreshing data…';
    return;
  }
  if (!autoRefreshRunning) {
    node.textContent = 'Auto refresh unavailable';
    return;
  }
  if (!nextAutoRefreshAt) {
    node.textContent = 'Auto refresh schedule pending';
    return;
  }
  const remainingSeconds = Math.max(0, Math.ceil((nextAutoRefreshAt.getTime() - (Date.now() + serverClockOffsetMs)) / 1000));
  if (remainingSeconds === 0) {
    node.textContent = 'Auto refresh due now';
    return;
  }
  const minutes = Math.floor(remainingSeconds / 60);
  const seconds = String(remainingSeconds % 60).padStart(2, '0');
  node.textContent = `Auto refresh in ${minutes}:${seconds}`;
}

function applyHealth(health) {
  $('#health-state').textContent = `${health.status} · ${health.mode} mode`;
  autoRefreshRunning = Boolean(health.auto_refresh_running);
  autoRefreshInProgress = Boolean(health.refresh_in_progress);
  const serverTime = health.server_time ? new Date(health.server_time) : null;
  serverClockOffsetMs = serverTime && Number.isFinite(serverTime.getTime()) ? serverTime.getTime() - Date.now() : 0;
  const parsed = health.next_auto_refresh_at ? new Date(health.next_auto_refresh_at) : null;
  nextAutoRefreshAt = parsed && Number.isFinite(parsed.getTime()) ? parsed : null;
  renderRefreshCountdown();
}

async function loadHealth() {
  try {
    applyHealth(await api('/api/health'));
  } catch (_) {
    autoRefreshRunning = false;
    autoRefreshInProgress = false;
    nextAutoRefreshAt = null;
    serverClockOffsetMs = 0;
    $('#health-state').textContent = 'Health endpoint unavailable';
    renderRefreshCountdown();
  }
}

async function loadLatest(quiet = false) {
  try {
    const snapshot = await api('/api/snapshot'); render(snapshot);
    if (!quiet) setStatus('Latest saved snapshot loaded.');
  } catch (error) {
    if (!quiet) setStatus(error.message, true);
  }
  await loadHealth();
}

async function loadCachedReport(reportDate, quiet = false) {
  try {
    const snapshot = await api(`/api/snapshot?report_date=${encodeURIComponent(reportDate)}`);
    render(snapshot);
    if (!quiet) setStatus(`${fullDateLabel(snapshot.report_date)} loaded from its saved snapshot.`);
    return true;
  } catch (error) {
    if (!quiet) setStatus(error.message, true);
    return false;
  }
}

function updateNavigationState() {
  const selected = $('#date-input').value;
  const today = localDateISO();
  $('#previous-day-button').disabled = refreshInProgress || !selected || selected <= EARLIEST_REPORT_DATE;
  $('#next-day-button').disabled = refreshInProgress || !selected || selected >= today;
  $('#today-button').disabled = refreshInProgress;
  $('#refresh-button').disabled = refreshInProgress || !selected || selected > today || selected < EARLIEST_REPORT_DATE;
}

async function refreshReport(reportDate = $('#date-input').value, quiet = false) {
  if (refreshInProgress) return false;
  if (!reportDate) { setStatus('Choose a report date.', true); return false; }
  refreshInProgress = true; updateNavigationState();
  if (!quiet) setStatus(`Loading ${fullDateLabel(reportDate)} from the bounded read-only rollup…`);
  try {
    const snapshot = await api('/api/refresh', {
      method: 'POST',
      headers: {'Content-Type':'application/json', 'X-Operations-KPI-Action':'refresh'},
      body: JSON.stringify({report_date: reportDate})
    });
    render(snapshot);
    if (!quiet) setStatus(`${fullDateLabel(snapshot.report_date)} loaded.`);
    return true;
  } catch (error) {
    if (displayedReportDate) $('#date-input').value = displayedReportDate;
    if (!quiet) setStatus(error.message, true);
    return false;
  } finally {
    refreshInProgress = false; updateNavigationState();
  }
}

async function moveReportDate(days) {
  const selected = $('#date-input').value || localDateISO();
  const target = shiftDate(selected, days);
  $('#date-input').value = target;
  updateNavigationState();
  await refreshReport(target);
}

async function initialize() {
  const today = localDateISO();
  $('#date-input').max = today;
  $('#date-input').value = today;
  $('#date-input').addEventListener('change', updateNavigationState);
  $('#refresh-button').addEventListener('click', () => refreshReport());
  $('#previous-day-button').addEventListener('click', () => moveReportDate(-1));
  $('#next-day-button').addEventListener('click', () => moveReportDate(1));
  $('#today-button').addEventListener('click', () => { $('#date-input').value = localDateISO(); refreshReport(localDateISO()); });
  $('#wallboard-button').addEventListener('click', () => { const url = new URL(location.href); url.searchParams.set('wallboard', '1'); location.href = url.toString(); });
  const wallboard = new URLSearchParams(location.search).get('wallboard') === '1';
  document.body.classList.toggle('wallboard', wallboard);
  updateNavigationState();
  if (wallboard) {
    await loadLatest(true);
    await loadCachedReport(localDateISO(), true);
    setInterval(() => loadCachedReport(localDateISO(), true), WALLBOARD_POLL_MS);
  } else {
    const loadedToday = await loadCachedReport(today);
    if (!loadedToday) await loadLatest();
  }
  setInterval(loadHealth, HEALTH_POLL_MS);
  setInterval(renderRefreshCountdown, COUNTDOWN_TICK_MS);
}

initialize();
