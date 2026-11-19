'use strict';

// <chart-kit>
// Shared by the wallboard and the drill-down. The two copies must stay identical (tests compare them).
const CHART_SERIES_COLORS = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#E69F00', '#56B4E9', '#6A3D9A', '#8C6D31'];
const CHART_SERIES_MARKERS = ['circle', 'square', 'triangle', 'diamond', 'cross', 'triangle-down', 'ring', 'plus'];

function chartMarker(kind, cx, cy, size, color) {
  const filled = {fill: color, stroke: '#fff', 'stroke-width': 1};
  const stroked = {fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linecap': 'round'};
  const point = (x, y) => (cx + x) + ',' + (cy + y);
  switch (kind) {
    case 'square':
      return svgNode('rect', Object.assign({x: cx - size, y: cy - size, width: size * 2, height: size * 2}, filled));
    case 'triangle':
      return svgNode('polygon', Object.assign({points: [point(0, -size * 1.25), point(size * 1.2, size * 0.95), point(-size * 1.2, size * 0.95)].join(' ')}, filled));
    case 'triangle-down':
      return svgNode('polygon', Object.assign({points: [point(0, size * 1.25), point(size * 1.2, -size * 0.95), point(-size * 1.2, -size * 0.95)].join(' ')}, filled));
    case 'diamond':
      return svgNode('polygon', Object.assign({points: [point(0, -size * 1.3), point(size * 1.3, 0), point(0, size * 1.3), point(-size * 1.3, 0)].join(' ')}, filled));
    case 'cross':
      return svgNode('path', Object.assign({d: 'M' + point(-size, -size) + ' L' + point(size, size) + ' M' + point(-size, size) + ' L' + point(size, -size)}, stroked));
    case 'plus':
      return svgNode('path', Object.assign({d: 'M' + point(-size * 1.1, 0) + ' L' + point(size * 1.1, 0) + ' M' + point(0, -size * 1.1) + ' L' + point(0, size * 1.1)}, stroked));
    case 'ring':
      return svgNode('circle', {cx: cx, cy: cy, r: size * 0.9, fill: '#fff', stroke: color, 'stroke-width': 2});
    default:
      return svgNode('circle', Object.assign({cx: cx, cy: cy, r: size}, filled));
  }
}

function chartLegendKey(item) {
  const key = document.createElement('span');
  key.className = 'legend-key';
  if (item.series !== null) {
    key.setAttribute('data-series', item.series || item.label);
    key.setAttribute('tabindex', '0');
  }
  const holder = document.createElement('span');
  holder.className = 'legend-swatch-holder';
  const width = 34;
  const svg = svgNode('svg', {width: width, height: 14, viewBox: '0 0 ' + width + ' 14', 'aria-hidden': 'true', focusable: 'false'});
  if (item.line) {
    svg.appendChild(svgNode('line', {x1: 1, y1: 7, x2: width - 1, y2: 7, stroke: item.color, 'stroke-width': item.width || 2.6, 'stroke-dasharray': item.dash || 'none', 'stroke-linecap': 'butt'}));
    if (item.marker) svg.appendChild(chartMarker(item.marker, width / 2, 7, 3.4, item.color));
  } else {
    svg.appendChild(svgNode('rect', {x: 6, y: 2, width: width - 12, height: 10, rx: 2, fill: item.color}));
  }
  holder.appendChild(svg);
  const label = document.createElement('span');
  label.textContent = item.label;
  key.append(holder, label);
  return key;
}

function bindSeriesHighlight(container) {
  container.classList.remove('has-highlight');
  container.querySelectorAll('.is-active').forEach((node) => node.classList.remove('is-active'));
  if (container.getAttribute('data-highlight-bound') === '1') return;
  container.setAttribute('data-highlight-bound', '1');
  const activate = (series) => {
    container.classList.toggle('has-highlight', series !== null);
    container.querySelectorAll('[data-series]').forEach((node) => {
      node.classList.toggle('is-active', series !== null && node.getAttribute('data-series') === series);
    });
  };
  const seriesOf = (event) => {
    const node = event.target && event.target.closest ? event.target.closest('[data-series]') : null;
    return node ? node.getAttribute('data-series') : null;
  };
  container.addEventListener('mouseover', (event) => activate(seriesOf(event)));
  container.addEventListener('mouseleave', () => activate(null));
  container.addEventListener('focusin', (event) => activate(seriesOf(event)));
  container.addEventListener('focusout', () => activate(null));
}
// </chart-kit>

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
const percentagePoint = (value) => value === null || value === undefined || !Number.isFinite(Number(value))
  ? 'No Data' : wholeNumber(value) + '%';
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

function splitMetricCard(label, total, unique, rows, color, extraDetails = []) {
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
  const details = document.createElement('div'); details.className = 'metric-detail-list';
  extraDetails.forEach(item => {
    const detail = document.createElement('small'); detail.className = 'metric-detail-row'; detail.append(text(item));
    details.append(detail);
  });
  card.append(labelNode, totalNode, list, details);
  return card;
}

function stagedMetricCard(carts, pieces, rows, color, extraDetails = []) {
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
  const details = document.createElement('div'); details.className = 'metric-detail-list';
  extraDetails.forEach(item => {
    const detail = document.createElement('small'); detail.className = 'metric-detail-row'; detail.append(text(item));
    details.append(detail);
  });
  card.append(labelNode, totalNode, list, details);
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
  const loadedColors = snapshot.chart_series?.loaded?.selected_day?.unique_colors;
  const paintedColors = snapshot.chart_series?.painted?.selected_day?.unique_colors;
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
  ], palette.teal, loadedColors === undefined ? [] : [compactOptionalInteger(loadedColors) + ' Unique Colors']));
  container.append(stagedMetricCard(current.staged_carts, current.staged_pieces, [
    {label:'Carts', production:current.production_staged_carts, bv:current.bv_staged_carts, service:current.service_staged_carts},
    {label:'Pieces', production:current.production_staged_pieces, bv:current.bv_staged_pieces, service:current.service_staged_pieces}
  ], palette.green));
  container.append(splitMetricCard('Carts / Pieces painted', current.paint_pieces_processed, current.unique_pieces_processed, [
    {label:'Carts', production:paintCarts.production, bv:paintCarts.bv, service:paintCarts.service},
    {label:'Pieces', production:paintPieces.production, bv:paintPieces.bv, service:paintPieces.service}
  ], palette.blue, paintedColors === undefined ? [] : [compactOptionalInteger(paintedColors) + ' Unique Colors']));
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
  container.append(processTimeCard(snapshot));
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
  items.forEach(item => legend.append(chartLegendKey(item)));
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

function loadedLinearTrend(rows, field, requireRepresentedDays = true) {
  const firstWeek = rows.length ? Date.parse(rows[0].bucket + 'T00:00:00') : NaN;
  const points = rows.map((row, rowIndex) => ({
    rowIndex,
    weekIndex:(Date.parse(row.bucket + 'T00:00:00') - firstWeek) / (7 * 24 * 60 * 60 * 1000),
    value:Number(row[field])
  })).filter((point, index) => rows[index].data_available && !rows[index].is_partial
      && (!requireRepresentedDays || Number(rows[index].represented_days || 0) > 0)
      && rows[index][field] !== null && rows[index][field] !== undefined
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

function loadedWeeklyReferenceModel(rows, model, minutesField = 'net_loading_minutes') {
  const completed = rows.filter(row => row.data_available && !row.is_partial
    && Number(row.performance_days || 0) > 0
    && Number(row[minutesField] || 0) > 0);
  const performanceDays = completed.reduce((sum, row) => sum + Number(row.performance_days || 0), 0);
  const netLoadingMinutes = completed.reduce((sum, row) => sum + Number(row[minutesField] || 0), 0);
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

function loadedCompletedPeriodAverages(rows) {
  const completed = rows.filter(row => row.data_available && !row.is_partial
    && Number(row.represented_days || 0) > 0);
  const representedDays = completed.reduce((sum, row) => sum + Number(row.represented_days || 0), 0);
  const performanceDays = completed.reduce((sum, row) => sum + Number(row.performance_days || 0), 0);
  const netMinutes = completed.reduce((sum, row) => sum + Number(row.net_loading_minutes || 0), 0);
  const carts = completed.reduce((sum, row) => sum + Number(row.carts_loaded_total || 0), 0);
  const pieces = completed.reduce((sum, row) => sum + Number(row.parts_loaded_total || 0), 0);
  const netHours = netMinutes / 60;
  return {
    representedDays,
    performanceDays,
    cartsPerDay:representedDays ? carts / representedDays : null,
    piecesPerDay:representedDays ? pieces / representedDays : null,
    cartsPerHour:performanceDays && netHours ? carts / netHours : null,
    piecesPerHour:performanceDays && netHours ? pieces / netHours : null
  };
}

function loadedWholeNumberScaleMaximum(values) {
  const largest = Math.max(...values.map(value => Math.max(0, Number(value))).filter(Number.isFinite), 1);
  const tickStep = Math.max(1, Math.ceil(largest * 1.18 / 4));
  return tickStep * 4;
}

function weightedQualityPercent(rows) {
  const measured = rows.filter(row => row.data_available && Number(row.quality_denominator || 0) > 0);
  const numerator = measured.reduce((sum, row) => sum + Number(row.quality_numerator || 0), 0);
  const denominator = measured.reduce((sum, row) => sum + Number(row.quality_denominator || 0), 0);
  return denominator > 0 ? numerator * 100 / denominator : null;
}

function renderLoadedLineChart(container, rows, options) {
  container.replaceChildren();
  if (!rows.length) {
    const empty = document.createElement('div'); empty.className = 'empty-state';
    empty.append(text('No aggregate chart data is available for this snapshot.'));
    container.append(empty); return;
  }
  const overlays = (options.overlays || []).map(overlay => ({
    ...overlay,
    values:rows.map(row => {
      if (!row.data_available) return null;
      const raw = overlay.value ? overlay.value(row) : row[overlay.field];
      if (raw === null || raw === undefined || raw === '') return null;
      const value = Number(raw);
      return Number.isFinite(value) ? value : null;
    })
  }));
  const hasSecondaryAxis = overlays.some(overlay => overlay.axis === 'secondary');
  const width = 720, height = 250, left = 48, right = hasSecondaryAxis ? 52 : 14, top = 16;
  const bottom = options.verticalLabels ? 52 : 34;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const values = rows.map(row => row.data_available && row[options.field] !== null
    ? Number(row[options.field]) : null);
  const trend = options.trend
    ? loadedLinearTrend(rows, options.field, options.trendRequiresRepresentedDays !== false)
    : null;
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
  overlays.filter(overlay => overlay.axis !== 'secondary').forEach(overlay => finiteValues.push(
    ...overlay.values.filter(value => value !== null && Number.isFinite(value))
  ));
  references.forEach(reference => finiteValues.push(
    ...reference.values.filter(value => value !== null && Number.isFinite(value))
  ));
  if (trend) finiteValues.push(Math.max(0, trend.startValue), Math.max(0, trend.endValue));
  const maximum = loadedWholeNumberScaleMaximum(finiteValues);
  const y = value => top + (maximum - Math.max(0, value)) * plotHeight / maximum;
  const secondaryValues = overlays.filter(overlay => overlay.axis === 'secondary')
    .flatMap(overlay => overlay.values)
    .filter(value => value !== null && Number.isFinite(value));
  const secondaryMaximum = hasSecondaryAxis ? loadedWholeNumberScaleMaximum(secondaryValues) : 1;
  const secondaryY = value => top + (secondaryMaximum - Math.max(0, value)) * plotHeight / secondaryMaximum;
  const band = plotWidth / rows.length;
  const centerX = index => left + band * index + band / 2;
  const formatValue = options.formatValue || wholeNumber;
  const targetAssessment = options.targetAssessment || null;
  const targetAssessmentLabel = targetAssessment?.label || 'interim target';
  const missedTarget = values.map((value, index) => {
    const row = rows[index];
    if (!targetAssessment || value === null || !Number.isFinite(value) || row.is_partial) return false;
    if (targetAssessment.scorePredicate && !targetAssessment.scorePredicate(row, value, index)) return false;
    const constantTarget = Number(targetAssessment.value);
    const hasConstantTarget = targetAssessment.value !== null && targetAssessment.value !== undefined
      && Number.isFinite(constantTarget);
    const target = hasConstantTarget ? constantTarget : Number(row[targetAssessment.field]);
    if (!Number.isFinite(target)) return false;
    return targetAssessment.lowerIsBetter ? value > target : value < target;
  });
  const svg = svgNode('svg', {viewBox:'0 0 ' + width + ' ' + height, role:'img', 'aria-label':options.ariaLabel});

  for (let index = 0; index <= 4; index += 1) {
    const value = maximum * index / 4;
    const yy = y(value);
    svg.append(svgNode('line', {x1:left, x2:width - right, y1:yy, y2:yy, stroke:palette.grid, 'stroke-width':1}));
    const label = svgNode('text', {x:left - 8, y:yy + 4, 'text-anchor':'end', fill:palette.muted, 'font-size':10, class:'loaded-scale-label'});
    label.append(text(formatValue(value))); svg.append(label);
    if (hasSecondaryAxis) {
      const secondaryValue = secondaryMaximum * index / 4;
      const secondaryFormat = overlays.find(overlay => overlay.axis === 'secondary')?.axisFormat || decimal;
      const secondaryLabel = svgNode('text', {
        x:width - right + 8, y:yy + 4, 'text-anchor':'start',
        fill:palette.muted, 'font-size':10, class:'loaded-scale-label loaded-scale-label-secondary'
      });
      secondaryLabel.append(text(secondaryFormat(secondaryValue))); svg.append(secondaryLabel);
    }
  }

  const barChart = options.chartType === 'bar';
  const barWidth = Math.min(38, band * .62);
  let segment = [];
  const flushSegment = () => {
    if (segment.length > 1) {
      svg.append(svgNode('polyline', {
        points:segment.join(' '), fill:'none', stroke:options.color, 'stroke-width':2.7,
        'stroke-linejoin':'round', 'stroke-linecap':'round', 'data-series':options.label
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
      const miss = missedTarget[index];
      const title = svgNode('title');
      title.append(text(options.bucketTitle(row) + ' · ' + options.label + ': ' + formatValue(value) + suffix
        + (miss ? ' · missed ' + targetAssessmentLabel : '')));
      if (barChart) {
        const bar = svgNode('rect', {
          x:centerX(index) - barWidth / 2, y:y(value), width:barWidth,
          height:Math.max(1, y(0) - y(value)), class:'loaded-bar',
          fill:row.is_partial ? '#fff3df' : (miss ? palette.red : options.color),
          stroke:row.is_partial ? palette.amber : (miss ? palette.red : options.color),
          'stroke-width':row.is_partial ? 2 : 1, opacity:row.is_partial ? .94 : .86,
          'data-series':options.label
        });
        bar.append(title); svg.append(bar);
      } else {
        const pointX = centerX(index);
        const pointY = y(value);
        if (options.stepLine && segment.length) {
          const previousY = segment[segment.length - 1].split(',')[1];
          segment.push(pointX + ',' + previousY);
        }
        segment.push(pointX + ',' + pointY);
        const circle = svgNode('circle', {
          cx:centerX(index), cy:y(value), r:miss ? 4.4 : 3.2,
          fill:row.is_partial ? '#fff3df' : (miss ? palette.red : options.color),
          stroke:row.is_partial ? palette.amber : '#fff', 'stroke-width':row.is_partial ? 2 : 1,
          'stroke-dasharray':row.is_partial ? '2 1' : 'none', 'data-series':options.label
        });
        circle.append(title); svg.append(circle);
      }
      const valueLabel = svgNode('text', {
        x:centerX(index), y:Math.max(top + 10, y(value) - 7),
        'text-anchor':'middle', class:'loaded-value-label' + (miss ? ' loaded-value-label-miss' : ''),
        'data-series':options.label
      });
      valueLabel.append(text(formatValue(value))); svg.append(valueLabel);
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

  overlays.forEach(overlay => {
    const overlayY = overlay.axis === 'secondary' ? secondaryY : y;
    const overlayFormat = overlay.formatValue || decimal;
    let overlaySegment = [];
    const flushOverlay = () => {
      if (overlaySegment.length > 1) {
        svg.append(svgNode('polyline', {
          points:overlaySegment.join(' '), fill:'none', stroke:overlay.color,
          'stroke-width':overlay.width || 2.4, 'stroke-dasharray':overlay.dash || 'none',
          'stroke-linejoin':'round', 'stroke-linecap':'round', opacity:.92,
          class:'loaded-overlay-line', 'data-series':overlay.label
        }));
      }
      overlaySegment = [];
    };
    overlay.values.forEach((value, index) => {
      if (value === null || !Number.isFinite(value)) {
        flushOverlay(); return;
      }
      overlaySegment.push(centerX(index) + ',' + overlayY(value));
      const point = svgNode('circle', {
        cx:centerX(index), cy:overlayY(value), r:2.7,
        fill:rows[index].is_partial ? '#fff3df' : overlay.color,
        stroke:rows[index].is_partial ? palette.amber : '#fff', 'stroke-width':1,
        class:'loaded-overlay-point', 'data-series':overlay.label
      });
      const title = svgNode('title');
      title.append(text(options.bucketTitle(rows[index]) + ' · ' + overlay.label + ': ' + overlayFormat(value)));
      point.append(title); svg.append(point);
    });
    flushOverlay();
  });

  if (trend) {
    const trendLine = svgNode('line', {
      x1:centerX(trend.startIndex), y1:y(trend.startValue),
      x2:centerX(trend.endIndex), y2:y(trend.endValue),
      stroke:palette.navy, 'stroke-width':2, 'stroke-dasharray':'7 5', opacity:.78,
      'data-series':'Linear trend'
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
          'stroke-width':2.2, 'stroke-dasharray':reference.dash || 'none',
          'stroke-linejoin':'round', 'stroke-linecap':'round', opacity:.9,
          class:'loaded-reference-line loaded-reference-line-full-width', 'data-series':reference.label
        });
        const title = svgNode('title');
        title.append(text(reference.label + ' · horizontal 13-week average-day reference'));
        line.append(title); svg.append(line);
        if (reference.directLabel) {
          const labelValue = referencePoints[referencePoints.length - 1].value;
          const label = svgNode('text', {
            x:width - right - 2, y:Math.max(top + 11, y(labelValue) - 4),
            'text-anchor':'end', fill:reference.color, class:'loaded-reference-label',
            'data-series':reference.label
          });
          label.append(text(reference.directLabel + ' ' + formatValue(labelValue) + (reference.directLabelSuffix || '')));
          svg.append(label);
        }
      }
      return;
    }
    let referenceSegment = [];
    const flushReference = () => {
      let line = null;
      if (referenceSegment.length > 1) {
        line = svgNode('polyline', {
          points:referenceSegment.join(' '), fill:'none', stroke:reference.color,
          'stroke-width':2.2, 'stroke-dasharray':reference.dash || 'none',
          'stroke-linejoin':'round', 'stroke-linecap':'round', opacity:.9,
          class:'loaded-reference-line', 'data-series':reference.label
        });
      } else if (referenceSegment.length === 1) {
        const [pointX, pointY] = referenceSegment[0].split(',').map(Number);
        const halfSegment = Math.min(14, band * .34);
        line = svgNode('line', {
          x1:pointX - halfSegment, x2:pointX + halfSegment, y1:pointY, y2:pointY,
          stroke:reference.color, 'stroke-width':2.2,
          'stroke-dasharray':reference.dash || 'none', 'stroke-linecap':'round', opacity:.9,
          class:'loaded-reference-line', 'data-series':reference.label
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
    if (reference.directLabel) {
      const finalValue = [...reference.values].reverse().find(value => value !== null && Number.isFinite(value));
      if (finalValue !== undefined) {
        const label = svgNode('text', {
          x:width - right - 2, y:Math.max(top + 11, y(finalValue) - 4),
          'text-anchor':'end', fill:reference.color, class:'loaded-reference-label',
          'data-series':reference.label
        });
        label.append(text(reference.directLabel + ' ' + formatValue(finalValue) + (reference.directLabelSuffix || '')));
        svg.append(label);
      }
    }
  });
  const legend = [{label:options.label, color:options.color, line:!barChart}];
  overlays.forEach(overlay => legend.push({label:overlay.label, color:overlay.color, line:true, dash:overlay.dash, width:overlay.width}));
  if (trend) legend.push({label:'Linear trend', color:palette.navy, line:true, dash:'7 5', width:2});
  references.forEach(reference => legend.push({label:reference.label, color:reference.color, line:true, dash:reference.dash, width:2.2}));
  if (missedTarget.some(Boolean)) {
    const missedLabel = 'Missed ' + targetAssessmentLabel.charAt(0).toUpperCase() + targetAssessmentLabel.slice(1);
    legend.push({label:missedLabel, color:palette.red, line:false, series:null});
  }
  container.append(svg, chartLegend(legend));
  bindSeriesHighlight(container);
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
  if (options.demandTotalField) {
    const demandDays = completed.reduce((sum, row) => sum + Number(row[options.demandDaysField] || 0), 0);
    const demandTotal = completed.reduce((sum, row) => sum + Number(row[options.demandTotalField] || 0), 0);
    items.push({
      label:'Period avg demand',
      value:demandDays ? decimal(demandTotal / demandDays) : 'No Data',
      detail:demandDays ? demandDays + ' represented production days' : 'No completed demand days'
    });
  }
  items.forEach(item => {
    const metric = document.createElement('div'); metric.className = 'loaded-chart-summary-item';
    const label = document.createElement('span'); label.append(text(item.label));
    const value = document.createElement('strong'); value.append(text(item.value));
    const detail = document.createElement('small'); detail.append(text(item.detail));
    metric.append(label, value, detail); summary.append(metric);
  });
  return summary;
}

function uniqueColorWeeklySummary(rows, options = {}) {
  const completed = rows.filter(row => row.data_available && !row.is_partial && Number.isFinite(Number(row.value)));
  const averageValue = completed.length
    ? completed.reduce((sum, row) => sum + Number(row.value), 0) / completed.length
    : null;
  const maximum = completed.reduce((best, row) => (!best || Number(row.value) > Number(best.value)) ? row : best, null);
  const minimum = completed.reduce((best, row) => (!best || Number(row.value) < Number(best.value)) ? row : best, null);
  const trend = loadedLinearTrend(rows, 'value', false);
  const format = options.formatValue || integer;
  const title = options.title || 'Unique colors painted';
  const trendUnit = options.trendUnit || 'colors/week';
  return chartSummaryPanel(title + ' 13-week summary', [
    {
      label:'Full-week average', value:averageValue === null ? 'No Data' : format(averageValue),
      detail:completed.length ? completed.length + ' completed weeks' : 'No completed available weeks'
    },
    {
      label:'Max week', value:maximum ? format(maximum.value) : 'No Data',
      detail:maximum ? dateLabel(maximum.bucket) + ' through ' + dateLabel(maximum.bucket_end) : 'No completed available week'
    },
    {
      label:'Min week', value:minimum ? format(minimum.value) : 'No Data',
      detail:minimum ? dateLabel(minimum.bucket) + ' through ' + dateLabel(minimum.bucket_end) : 'No completed available week'
    },
    {
      label:'Trend',
      value:trend ? (Math.abs(trend.slope) < .05 ? 'Flat' : (trend.slope > 0 ? 'Up' : 'Down')) : 'No Data',
      detail:trend ? (trend.slope >= 0 ? '+' : '') + decimal(trend.slope) + ' ' + trendUnit : 'Need two completed weeks'
    }
  ]);
}

function aggregateHistoryDetails(snapshot) {
  const details = snapshot.aggregate_details || {};
  const colors = Array.isArray(details.loaded_weekly_unique_colors)
    ? details.loaded_weekly_unique_colors : [];
  const piecesPerCart = Array.isArray(details.loaded_weekly_average_pieces_per_cart)
    ? details.loaded_weekly_average_pieces_per_cart : [];
  if (!colors.length && !piecesPerCart.length) return null;

  const container = document.createElement('details');
  container.className = 'aggregate-history-details';
  const summary = document.createElement('summary');
  summary.append(text('13-week aggregate history details'));
  const note = document.createElement('p');
  note.className = 'aggregate-history-note';
  note.append(text('Aggregate-only weekly history from ' + fullDateLabel(details.window_start)
    + ' through ' + fullDateLabel(details.window_end)
    + ' · no part or cart identifiers · carts above six pieces are excluded from pieces-per-cart averages.'));
  const grid = document.createElement('div');
  grid.className = 'loaded-chart-grid';

  if (colors.length) {
    grid.append(loadedChartCard(
      'Unique colors loaded · 13 weeks',
      'Distinct normalized loaded colors by week',
      colors,
      {
        field:'value', label:'Unique colors loaded', color:palette.purple, trend:true,
        trendRequiresRepresentedDays:false, omitNull:true, chartType:'bar',
        verticalLabels:true, formatValue:wholeNumber,
        ariaLabel:'Thirteen-week unique colors loaded with summary cards and trend',
        bucketLabel:row => dateLabel(row.bucket),
        bucketTitle:row => fullDateLabel(row.bucket) + ' through ' + fullDateLabel(row.bucket_end),
        showTick:() => true,
        summaryBuilder:rows => uniqueColorWeeklySummary(rows, {
          title:'Unique colors loaded', formatValue:integer, trendUnit:'colors/week'
        })
      }
    ));
  }
  if (piecesPerCart.length) {
    grid.append(loadedChartCard(
      'Average pieces per cart · 13 weeks',
      'Weekly average of represented daily eligible-cart averages',
      piecesPerCart,
      {
        field:'value', label:'Average pieces per cart', color:palette.green, trend:true,
        trendRequiresRepresentedDays:false, omitNull:true, chartType:'bar',
        verticalLabels:true, formatValue:decimal,
        ariaLabel:'Thirteen-week average pieces per eligible cart with summary cards and trend',
        bucketLabel:row => dateLabel(row.bucket),
        bucketTitle:row => fullDateLabel(row.bucket) + ' through ' + fullDateLabel(row.bucket_end),
        showTick:() => true,
        summaryBuilder:rows => uniqueColorWeeklySummary(rows, {
          title:'Average pieces per eligible cart', formatValue:decimal, trendUnit:'pieces/cart/week'
        })
      }
    ));
  }
  container.append(summary, note, grid);
  return container;
}

function loadedChartCard(title, note, rows, options) {
  const figure = document.createElement('figure'); figure.className = 'loaded-chart-card';
  const caption = document.createElement('figcaption');
  const heading = document.createElement('span'); heading.append(text(title));
  const detail = document.createElement('small'); detail.append(text(note));
  caption.append(heading, detail);
  const displayRows = options.omitNull
    ? rows.filter(row => row.data_available && row[options.field] !== null && row[options.field] !== undefined)
    : rows;
  const chart = document.createElement('div'); chart.className = 'loaded-chart';
  renderLoadedLineChart(chart, displayRows, options);
  figure.append(caption);
  if (options.summaryBuilder) figure.append(options.summaryBuilder(displayRows));
  else {
    if (options.hourlySummary) figure.append(loadedHourlySummary(displayRows, options.hourlySummary, options.performance));
    if (options.summary) figure.append(loadedWeeklySummary(displayRows, options.summary));
  }
  figure.append(chart); return figure;
}

function metricChartSection(title, note, single = false) {
  const section = document.createElement('section'); section.className = 'metric-chart-section';
  const heading = document.createElement('div'); heading.className = 'metric-chart-section-heading';
  const titleNode = document.createElement('h3'); titleNode.append(text(title));
  const noteNode = document.createElement('p'); noteNode.append(text(note));
  heading.append(titleNode, noteNode);
  const grid = document.createElement('div'); grid.className = 'loaded-chart-grid' + (single ? ' single-chart-grid' : '');
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
  const periodAverage = loadedCompletedPeriodAverages(weekly);
  const reportDay = fullDateLabel(snapshot.report_date);
  const hourlySection = metricChartSection('Hourly · selected report day', '24 clock-hour buckets · ' + reportDay);
  hourlySection.grid.append(
    loadedChartCard('Carts loaded by hour', 'Total carts · first load event', hourly, {
      field:'carts_loaded', label:'Total carts', color:palette.teal, trend:false, formatValue:wholeNumber,
      ariaLabel:'Hourly total carts loaded with interim target and long-term goal for ' + reportDay,
      bucketLabel:row => hourBucketLabel(row.bucket), bucketTitle:row => hourBucketLabel(row.bucket),
      verticalLabels:true, showTick:() => true, performance,
      references:[
        {value:performance.model.target_carts_per_hour, label:'Interim target', color:palette.amber},
        {value:performance.model.goal_carts_per_hour, label:'Long-term goal', color:palette.red},
        {value:periodAverage.cartsPerHour, label:'13-week static average', color:palette.navy, dash:'2 3', directLabel:'13-week avg', directLabelSuffix:'/hr'}
      ],
      targetAssessment:{value:performance.model.target_carts_per_hour, scorePredicate:(row, value) => value > 0},
      hourlySummary:{label:'Carts', field:'carts_loaded'}
    }),
    loadedChartCard('Pieces loaded by hour', 'Total load events', hourly, {
      field:'parts_loaded', label:'Total pieces', color:palette.blue, trend:false, formatValue:wholeNumber,
      ariaLabel:'Hourly total pieces loaded with interim target and long-term goal for ' + reportDay,
      bucketLabel:row => hourBucketLabel(row.bucket), bucketTitle:row => hourBucketLabel(row.bucket),
      verticalLabels:true, showTick:() => true, performance,
      references:[
        {value:performance.model.target_pieces_per_hour, label:'Interim target', color:palette.amber},
        {value:performance.model.goal_pieces_per_hour, label:'Long-term goal', color:palette.red},
        {value:periodAverage.piecesPerHour, label:'13-week static average', color:palette.navy, dash:'2 3', directLabel:'13-week avg', directLabelSuffix:'/hr'}
      ],
      targetAssessment:{value:performance.model.target_pieces_per_hour, scorePredicate:(row, value) => value > 0},
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
        {value:weeklyReference.targetCarts, label:'Net-time interim target', color:palette.amber, spanFullWidth:true},
        {value:weeklyReference.goalCarts, label:'Net-time long-term goal', color:palette.red, spanFullWidth:true},
        {value:periodAverage.cartsPerDay, label:'13-week static average', color:palette.navy, dash:'2 3', spanFullWidth:true, directLabel:'Period avg'}
      ],
      targetAssessment:{value:weeklyReference.targetCarts, scorePredicate:row => Number(row.represented_days || 0) > 0},
      summary:{label:'Carts', averageField:'average_carts_loaded', totalField:'carts_loaded_total'}
    }),
    loadedChartCard('Pieces loaded · 13 weeks', 'Average total pieces per represented day', weekly, {
      ...weeklyOptions, field:'average_parts_loaded', label:'Daily average pieces', color:palette.blue,
      ariaLabel:'Thirteen-week daily average pieces loaded with linear trend, interim target, and long-term goal',
      references:[
        {value:weeklyReference.targetPieces, label:'Net-time interim target', color:palette.amber, spanFullWidth:true},
        {value:weeklyReference.goalPieces, label:'Net-time long-term goal', color:palette.red, spanFullWidth:true},
        {value:periodAverage.piecesPerDay, label:'13-week static average', color:palette.navy, dash:'2 3', spanFullWidth:true, directLabel:'Period avg'}
      ],
      targetAssessment:{value:weeklyReference.targetPieces, scorePredicate:row => Number(row.represented_days || 0) > 0},
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
  const historyDetails = aggregateHistoryDetails(snapshot);
  if (historyDetails) content.append(historyDetails);
}


function chartSummaryPanel(ariaLabel, items) {
  const summary = document.createElement('div');
  summary.className = 'loaded-chart-summary';
  summary.setAttribute('role', 'group');
  summary.setAttribute('aria-label', ariaLabel);
  items.forEach(item => {
    const metric = document.createElement('div'); metric.className = 'loaded-chart-summary-item';
    const label = document.createElement('span'); label.append(text(item.label));
    const value = document.createElement('strong'); value.append(text(item.value));
    const detail = document.createElement('small'); detail.append(text(item.detail));
    metric.append(label, value, detail); summary.append(metric);
  });
  return summary;
}

function throughputHourlySummary(rows, options, performance) {
  const available = rows.filter(row => row.data_available);
  const values = available.map(row => Number(row[options.field])).filter(Number.isFinite);
  const total = values.reduce((sum, value) => sum + value, 0);
  const peak = available.reduce((best, row) => {
    const value = Number(row[options.field]);
    return Number.isFinite(value) && (!best || value > best.value) ? {row, value} : best;
  }, null);
  const model = performance?.model || {}, day = performance?.day || {};
  const type = options.type;
  const rate = day[type === 'carts' ? 'carts_per_net_hour' : 'pieces_per_net_hour'];
  const targetRate = model[type === 'carts' ? 'target_carts_per_hour' : 'target_pieces_per_hour'];
  const goalRate = model[type === 'carts' ? 'goal_carts_per_hour' : 'goal_pieces_per_hour'];
  const targetCount = day[type === 'carts' ? 'target_carts' : 'target_pieces'];
  const goalCount = day[type === 'carts' ? 'goal_carts' : 'goal_pieces'];
  const netHours = Number(day.net_activity_minutes || 0) / 60;
  const hasWindow = Boolean(day.first_activity_at && day.last_activity_at && netHours > 0);
  const windowDetail = hasWindow
    ? clockTimeLabel(day.first_activity_at) + '–' + clockTimeLabel(day.last_activity_at)
      + (Number(day.lunch_allowance_minutes || 0) > 0
        ? ' · ' + integer(day.lunch_allowance_minutes) + ' min lunch'
        : (day.performance_scored ? ' · no lunch allowance' : ' · live span'))
    : 'Need at least two distinct-cart paint times';
  const expectedDetail = (expected, label) => day.performance_scored && expected !== null && expected !== undefined
    ? decimal(expected) + ' ' + label + ' expected for net time'
    : 'Rate shown · partial or unscored day';
  return chartSummaryPanel(options.label + ' selected-day hourly summary', [
    {label:'Day total', value:integer(total), detail:available.length + ' available clock-hour buckets'},
    {label:'Peak hour', value:peak ? integer(peak.value) : 'No Data', detail:peak ? hourBucketLabel(peak.row.bucket) + ' bucket' : 'No hourly data'},
    {label:day.performance_scored ? 'Net painting time' : 'Net painting time · live', value:hasWindow ? decimal(netHours) + ' h' : 'No Data', detail:windowDetail},
    {label:'Actual rate', value:rate === null || rate === undefined ? 'No Data' : decimal(rate) + '/hr', detail:hasWindow ? integer(total) + ' over ' + decimal(netHours) + ' net hours' : 'No painting window'},
    {label:'Interim target', value:targetRate === null || targetRate === undefined ? 'No Data' : decimal(targetRate) + '/hr', detail:expectedDetail(targetCount, options.label.toLowerCase())},
    {label:'Long-term goal', value:goalRate === null || goalRate === undefined ? 'No Data' : decimal(goalRate) + '/hr', detail:expectedDetail(goalCount, options.label.toLowerCase())}
  ]);
}

function stagedHourlySummary(rows, options, model) {
  const available = rows.filter(row => row.data_available);
  const values = available.map(row => Number(row[options.field])).filter(Number.isFinite);
  const start = available.length ? available[0] : null;
  const end = available.length ? available[available.length - 1] : null;
  const minimum = values.length ? Math.min(...values) : null;
  const peak = values.length ? Math.max(...values) : null;
  const goal = Number(model[options.type === 'carts' ? 'goal_carts' : 'goal_pieces']);
  const hoursAtGoal = Number.isFinite(goal)
    ? available.filter(row => Number(row[options.field]) >= goal).length : 0;
  return chartSummaryPanel(options.label + ' staged point-in-time queue summary', [
    {label:'Start', value:start ? integer(start[options.field]) : 'No Data', detail:start ? hourBucketLabel(start.bucket) + ' cutoff' : 'No available snapshot'},
    {label:'Low', value:minimum === null ? 'No Data' : integer(minimum), detail:'Minimum observed queue'},
    {label:'Peak', value:peak === null ? 'No Data' : integer(peak), detail:'Maximum observed queue'},
    {label:'End', value:end ? integer(end[options.field]) : 'No Data', detail:end ? hourBucketLabel(end.bucket) + ' cutoff' : 'No available snapshot'},
    {label:'Hours at/above goal', value:Number.isFinite(goal) ? integer(hoursAtGoal) : 'No Data', detail:Number.isFinite(goal) ? 'Goal ' + integer(goal) + ' · ' + available.length + ' observed cutoffs' : 'Goal unavailable'}
  ]);
}

function qualityHourlySummary(rows, options, model) {
  const measured = rows.filter(row => row.data_available && Number(row.quality_denominator || 0) > 0);
  const numerator = measured.reduce((sum, row) => sum + Number(row.quality_numerator || 0), 0);
  const denominator = measured.reduce((sum, row) => sum + Number(row.quality_denominator || 0), 0);
  const weighted = denominator > 0 ? numerator * 100 / denominator : null;
  const ordered = measured.map(row => ({row, value:Number(row.rate_percent)})).filter(item => Number.isFinite(item.value));
  const best = ordered.reduce((value, item) => (!value || (options.lowerIsBetter ? item.value < value.value : item.value > value.value)) ? item : value, null);
  const worst = ordered.reduce((value, item) => (!value || (options.lowerIsBetter ? item.value > value.value : item.value < value.value)) ? item : value, null);
  return chartSummaryPanel(options.label + ' selected-day hourly summary', [
    {label:'Day weighted rate', value:weighted === null ? 'No Data' : decimal(weighted) + '%', detail:integer(numerator) + ' / ' + integer(denominator)},
    {label:'Measured hours', value:integer(measured.length), detail:'Hours with a denominator'},
    {label:'Best hour', value:best ? decimal(best.value) + '%' : 'No Data', detail:best ? hourBucketLabel(best.row.bucket) + ' bucket' : 'No measured hour'},
    {label:'Worst hour', value:worst ? decimal(worst.value) + '%' : 'No Data', detail:worst ? hourBucketLabel(worst.row.bucket) + ' bucket' : 'No measured hour'},
    {label:'Interim target', value:decimal(model.target_percent) + '%', detail:options.lowerIsBetter ? 'At or below' : 'At or above'},
    {label:'Goal', value:decimal(model.goal_percent) + '%', detail:options.lowerIsBetter ? 'At or below' : 'At or above'}
  ]);
}

function qualityWeeklySummary(rows, options, model) {
  const completed = rows.filter(row => row.data_available && !row.is_partial && Number(row.quality_denominator || 0) > 0);
  const numerator = completed.reduce((sum, row) => sum + Number(row.quality_numerator || 0), 0);
  const denominator = completed.reduce((sum, row) => sum + Number(row.quality_denominator || 0), 0);
  const weighted = denominator > 0 ? numerator * 100 / denominator : null;
  const latest = completed.length ? completed[completed.length - 1] : null;
  const trend = loadedLinearTrend(rows, 'rate_percent');
  const improving = trend && (options.lowerIsBetter ? trend.slope < 0 : trend.slope > 0);
  const trendValue = !trend ? 'No Data' : Math.abs(trend.slope) < .05 ? 'Flat' : improving ? 'Improving' : 'Moving away';
  return chartSummaryPanel(options.label + ' 13-week summary', [
    {label:'Period weighted rate', value:weighted === null ? 'No Data' : decimal(weighted) + '%', detail:integer(numerator) + ' / ' + integer(denominator)},
    {label:'Latest full week', value:latest ? decimal(latest.rate_percent) + '%' : 'No Data', detail:latest ? dateLabel(latest.bucket) + ' · ' + latest.represented_days + ' days' : 'No completed week'},
    {label:'Trend', value:trendValue, detail:trend ? (trend.slope >= 0 ? '+' : '') + decimal(trend.slope) + ' points/week' : 'Need two completed weeks'},
    {label:'Frozen baseline', value:decimal(model.baseline_percent) + '%', detail:integer(model.baseline_numerator) + ' / ' + integer(model.baseline_denominator)},
    {label:'Interim target', value:decimal(model.target_percent) + '%', detail:options.lowerIsBetter ? 'At or below' : 'At or above'},
    {label:'Goal', value:decimal(model.goal_percent) + '%', detail:options.lowerIsBetter ? 'At or below' : 'At or above'}
  ]);
}

function appendCommonChartNotes(content, weeklySection, weekly) {
  if (weekly.some(row => row.is_partial)) {
    const note = document.createElement('span'); note.className = 'chart-partial-note';
    note.append(text('The selected week is partial and is displayed but excluded from the trendline.'));
    weeklySection.section.append(note);
  }
  if (weekly.some(row => !row.data_available)) {
    const unavailable = document.createElement('span'); unavailable.className = 'chart-unavailable-note';
    unavailable.append(text('Unavailable weeks before the September 8 history boundary are omitted, not zero.'));
    weeklySection.section.append(unavailable);
  }
  content.append(weeklySection.section);
}

function renderStagedCharts(snapshot) {
  const content = $('#metric-chart-content'); content.replaceChildren();
  const staged = snapshot.chart_series?.staged;
  if (!staged || !Array.isArray(staged.hourly) || !Array.isArray(staged.weekly_13)) {
    const empty = document.createElement('div'); empty.className = 'chart-placeholder';
    empty.append(text('This saved snapshot predates the Staged chart contract. Refresh this date to build it.'));
    content.append(empty); return;
  }
  const hourly = staged.hourly, weekly = staged.weekly_13, model = staged.performance_model || {};
  const reportDay = fullDateLabel(snapshot.report_date);
  const hourlySection = metricChartSection('Hourly queue snapshots · selected report day', 'Point-in-time Paint Prep queue at each available hour cutoff · ' + reportDay);
  const hourlyBase = {
    trend:false, stepLine:true, formatValue:wholeNumber, verticalLabels:true, showTick:() => true,
    bucketLabel:row => hourBucketLabel(row.bucket), bucketTitle:row => hourBucketLabel(row.bucket)
  };
  hourlySection.grid.append(
    loadedChartCard('Carts staged by hour', 'Point-in-time queue · minimum goal', hourly, {
      ...hourlyBase, field:'staged_carts', label:'Staged carts', color:palette.green,
      ariaLabel:'Hourly staged-cart point-in-time queue snapshots with minimum goal for ' + reportDay,
      references:[
        {value:model.goal_carts, label:'Minimum goal', color:palette.red}
      ],
      targetAssessment:{value:model.goal_carts, label:'minimum goal', scorePredicate:row => row.data_available},
      summaryBuilder:rows => stagedHourlySummary(rows, {label:'Carts', field:'staged_carts', type:'carts'}, model)
    }),
    loadedChartCard('Pieces staged by hour', 'Point-in-time queue · minimum goal', hourly, {
      ...hourlyBase, field:'staged_pieces', label:'Staged pieces', color:palette.teal,
      ariaLabel:'Hourly staged-piece point-in-time queue snapshots with minimum goal for ' + reportDay,
      references:[
        {value:model.goal_pieces, label:'Minimum goal', color:palette.red}
      ],
      targetAssessment:{value:model.goal_pieces, label:'minimum goal', scorePredicate:row => row.data_available},
      summaryBuilder:rows => stagedHourlySummary(rows, {label:'Pieces', field:'staged_pieces', type:'pieces'}, model)
    })
  );
  const weeklySection = metricChartSection('13-week close-of-day queue averages', 'Sunday–Saturday · represented production days · partial selected week excluded from trend');
  const weeklyBase = {
    formatValue:wholeNumber, trend:true, omitNull:true, verticalLabels:true, chartType:'bar',
    bucketLabel:row => dateLabel(row.bucket), bucketTitle:row => fullDateLabel(row.bucket) + ' through ' + fullDateLabel(row.bucket_end),
    tooltipSuffix:row => ' · ' + integer(row.represented_days) + ' represented days', showTick:() => true
  };
  weeklySection.grid.append(
    loadedChartCard('Carts staged · 13 weeks', 'Average close-of-day staged carts', weekly, {
      ...weeklyBase, field:'average_carts', label:'Daily average carts', color:palette.green,
      ariaLabel:'Thirteen-week close-of-day average staged carts with trend, interim target, and minimum goal',
      references:[
        {value:model.goal_carts, label:'Minimum goal', color:palette.red, spanFullWidth:true}
      ],
      targetAssessment:{value:model.goal_carts, label:'minimum goal', scorePredicate:row => Number(row.represented_days || 0) > 0},
      summary:{label:'Carts', averageField:'average_carts', totalField:'carts_total'}
    }),
    loadedChartCard('Pieces staged · 13 weeks', 'Average close-of-day staged pieces', weekly, {
      ...weeklyBase, field:'average_pieces', label:'Daily average pieces', color:palette.teal,
      ariaLabel:'Thirteen-week close-of-day average staged pieces with trend, interim target, and minimum goal',
      references:[
        {value:model.goal_pieces, label:'Minimum goal', color:palette.red, spanFullWidth:true}
      ],
      targetAssessment:{value:model.goal_pieces, label:'minimum goal', scorePredicate:row => Number(row.represented_days || 0) > 0},
      summary:{label:'Pieces', averageField:'average_pieces', totalField:'pieces_total'}
    })
  );
  content.append(hourlySection.section);
  appendCommonChartNotes(content, weeklySection, weekly);
}

function renderPaintedCharts(snapshot) {
  const content = $('#metric-chart-content'); content.replaceChildren();
  const painted = snapshot.chart_series?.painted;
  if (!painted || !Array.isArray(painted.hourly) || !Array.isArray(painted.weekly_13)) {
    const empty = document.createElement('div'); empty.className = 'chart-placeholder';
    empty.append(text('This saved snapshot predates the Painted chart contract. Refresh this date to build it.'));
    content.append(empty); return;
  }
  const hourly = painted.hourly, weekly = painted.weekly_13;
  const uniqueColors = Array.isArray(snapshot.aggregate_details?.painted_weekly_unique_colors)
    ? snapshot.aggregate_details.painted_weekly_unique_colors : [];
  const performance = {model:painted.performance_model || {}, day:painted.selected_day || {}};
  const weeklyReference = loadedWeeklyReferenceModel(weekly, performance.model, 'net_activity_minutes');
  const reportDay = fullDateLabel(snapshot.report_date);
  const hourlySection = metricChartSection('Hourly · selected report day', '24 clock-hour buckets · ' + reportDay);
  const hourlyBase = {
    trend:false, formatValue:wholeNumber, verticalLabels:true, showTick:() => true,
    bucketLabel:row => hourBucketLabel(row.bucket), bucketTitle:row => hourBucketLabel(row.bucket)
  };
  hourlySection.grid.append(
    loadedChartCard('Carts painted by hour', 'Distinct carts · first paint exit', hourly, {
      ...hourlyBase, field:'paint_carts', label:'Painted carts', color:palette.blue,
      ariaLabel:'Hourly painted carts with interim target and long-term goal for ' + reportDay,
      references:[
        {value:performance.model.target_carts_per_hour, label:'Interim target', color:palette.amber},
        {value:performance.model.goal_carts_per_hour, label:'Long-term goal', color:palette.red},
        {value:performance.day.carts_per_net_hour, label:'Daily average', color:palette.navy, dash:'2 3', directLabel:'Daily avg', directLabelSuffix:'/hr'}
      ],
      overlays:[{
        label:'Unique colors', color:palette.green, field:'unique_colors', formatValue:wholeNumber,
        value:row => Number(row.paint_carts || 0) > 0 ? Number(row.unique_colors || 0) : null
      }],
      targetAssessment:{value:performance.model.target_carts_per_hour, scorePredicate:(row, value) => value > 0},
      summaryBuilder:rows => throughputHourlySummary(rows, {label:'Carts', field:'paint_carts', type:'carts'}, performance)
    }),
    loadedChartCard('Pieces painted by hour', 'Total paint exits', hourly, {
      ...hourlyBase, field:'paint_pieces_processed', label:'Painted pieces', color:palette.purple,
      ariaLabel:'Hourly painted pieces with interim target and long-term goal for ' + reportDay,
      references:[
        {value:performance.model.target_pieces_per_hour, label:'Interim target', color:palette.amber},
        {value:performance.model.goal_pieces_per_hour, label:'Long-term goal', color:palette.red},
        {value:performance.day.pieces_per_net_hour, label:'Daily average', color:palette.navy, dash:'2 3', directLabel:'Daily avg', directLabelSuffix:'/hr'}
      ],
      targetAssessment:{value:performance.model.target_pieces_per_hour, scorePredicate:(row, value) => value > 0},
      summaryBuilder:rows => throughputHourlySummary(rows, {label:'Pieces', field:'paint_pieces_processed', type:'pieces'}, performance)
    })
  );
  const weeklySection = metricChartSection('13-week daily averages', 'Sunday–Saturday · represented production days · partial selected week excluded from trend and target scoring');
  const weeklyBase = {
    formatValue:wholeNumber, trend:true, omitNull:true, verticalLabels:true, chartType:'bar',
    bucketLabel:row => dateLabel(row.bucket), bucketTitle:row => fullDateLabel(row.bucket) + ' through ' + fullDateLabel(row.bucket_end),
    tooltipSuffix:row => ' · ' + integer(row.represented_days) + ' represented days', showTick:() => true
  };
  weeklySection.grid.append(
    loadedChartCard('Carts painted · 13 weeks', 'Average total carts per represented day', weekly, {
      ...weeklyBase, field:'average_carts', label:'Daily average carts', color:palette.blue,
      ariaLabel:'Thirteen-week daily average painted carts with trend, interim target, and long-term goal',
      references:[
        {value:weeklyReference.targetCarts, label:'Net-time interim target', color:palette.amber, spanFullWidth:true},
        {value:weeklyReference.goalCarts, label:'Net-time long-term goal', color:palette.red, spanFullWidth:true}
      ],
      targetAssessment:{value:weeklyReference.targetCarts, scorePredicate:row => Number(row.represented_days || 0) > 0},
      summary:{label:'Carts', averageField:'average_carts', totalField:'carts_total'}
    }),
    loadedChartCard('Pieces painted · 13 weeks', 'Average total pieces per represented day', weekly, {
      ...weeklyBase, field:'average_pieces', label:'Daily average pieces', color:palette.purple,
      ariaLabel:'Thirteen-week daily average painted pieces with trend, interim target, and long-term goal',
      references:[
        {value:weeklyReference.targetPieces, label:'Net-time interim target', color:palette.amber, spanFullWidth:true},
        {value:weeklyReference.goalPieces, label:'Net-time long-term goal', color:palette.red, spanFullWidth:true}
      ],
      targetAssessment:{value:weeklyReference.targetPieces, scorePredicate:row => Number(row.represented_days || 0) > 0},
      summary:{label:'Pieces', averageField:'average_pieces', totalField:'pieces_total'}
    })
  );
  content.append(hourlySection.section);
  if (weeklyReference.averageNetHours !== null) {
    const comparison = document.createElement('span'); comparison.className = 'chart-unavailable-note';
    comparison.append(text('Horizontal references use one ' + decimal(weeklyReference.averageNetHours) + '-hour average net-painting day from ' + integer(weeklyReference.performanceDays) + ' completed painting days.'));
    weeklySection.section.append(comparison);
  }
  const demandNote = document.createElement('span'); demandNote.className = 'chart-unavailable-note';
  demandNote.append(text('Scheduled-demand comparison is hidden until its source can be proven GP-paint-only.'));
  weeklySection.section.append(demandNote);
  appendCommonChartNotes(content, weeklySection, weekly);
  if (uniqueColors.length) {
    const colorSection = metricChartSection(
      '13-week unique colors painted',
      'Distinct normalized paint colors per week · partial selected week excluded from trend and summary extremes',
      true
    );
    colorSection.grid.append(loadedChartCard(
      'Unique colors painted · 13 weeks',
      'Weekly distinct-color count with linear trend',
      uniqueColors,
      {
        field:'value', label:'Unique colors', color:palette.green, trend:true,
        trendRequiresRepresentedDays:false, omitNull:true,
        verticalLabels:true, chartType:'bar', formatValue:wholeNumber,
        ariaLabel:'Thirteen-week unique colors painted with trend, maximum week, and minimum week',
        bucketLabel:row => dateLabel(row.bucket),
        bucketTitle:row => fullDateLabel(row.bucket) + ' through ' + fullDateLabel(row.bucket_end),
        showTick:() => true,
        summaryBuilder:rows => uniqueColorWeeklySummary(rows)
      }
    ));
    appendCommonChartNotes(content, colorSection, uniqueColors);
  }
}

function renderQualityCharts(snapshot, metric, options) {
  const content = $('#metric-chart-content'); content.replaceChildren();
  const series = snapshot.chart_series?.[metric];
  if (!series || !Array.isArray(series.hourly) || !Array.isArray(series.weekly_13)) {
    const empty = document.createElement('div'); empty.className = 'chart-placeholder';
    empty.append(text('This saved snapshot predates the ' + options.label + ' chart contract. Refresh this date to build it.'));
    content.append(empty); return;
  }
  const hourly = series.hourly, weekly = series.weekly_13, model = series.performance_model || {};
  const averageReference = metric === 'finesse'
    ? weightedQualityPercent(weekly)
    : weightedQualityPercent(hourly);
  const averageLabel = metric === 'finesse' ? '13-week weighted average' : 'Daily weighted average';
  const averageDirectLabel = metric === 'finesse' ? '13-week avg' : 'Daily avg';
  const reportDay = fullDateLabel(snapshot.report_date);
  const hourlySection = metricChartSection('Hourly · selected report day', 'Weighted within each clock hour · ' + reportDay, true);
  hourlySection.grid.append(loadedChartCard(options.label + ' by hour', options.definition, hourly, {
    field:'rate_percent', label:options.label, color:options.color, trend:false, formatValue:percentagePoint,
    ariaLabel:'Hourly ' + options.label + ' with interim target and goal for ' + reportDay,
    bucketLabel:row => hourBucketLabel(row.bucket), bucketTitle:row => hourBucketLabel(row.bucket),
    verticalLabels:true, showTick:() => true,
    tooltipSuffix:row => ' · ' + integer(row.quality_numerator) + ' / ' + integer(row.quality_denominator),
    references:[
      {value:model.target_percent, label:'Interim target', color:palette.amber},
      {value:model.goal_percent, label:'Goal', color:options.lowerIsBetter ? palette.green : palette.red},
      {value:averageReference, label:averageLabel, color:palette.navy, dash:'2 3', directLabel:averageDirectLabel}
    ],
    targetAssessment:{
      value:model.target_percent, lowerIsBetter:options.lowerIsBetter,
      scorePredicate:row => Number(row.quality_denominator || 0) > 0
    },
    summaryBuilder:rows => qualityHourlySummary(rows, options, model)
  }));
  const weeklySection = metricChartSection('13-week weighted rates', 'Sunday–Saturday · numerator divided by denominator · partial selected week excluded from trend', true);
  weeklySection.grid.append(loadedChartCard(options.label + ' · 13 weeks', options.definition, weekly, {
    field:'rate_percent', label:options.label, color:options.color, trend:true, omitNull:true,
    verticalLabels:true, chartType:'bar', formatValue:percentagePoint,
    ariaLabel:'Thirteen-week weighted ' + options.label + ' with trend, interim target, and goal',
    bucketLabel:row => dateLabel(row.bucket), bucketTitle:row => fullDateLabel(row.bucket) + ' through ' + fullDateLabel(row.bucket_end),
    tooltipSuffix:row => ' · ' + integer(row.quality_numerator) + ' / ' + integer(row.quality_denominator),
    showTick:() => true,
    references:[
      {value:model.target_percent, label:'Interim target', color:palette.amber, spanFullWidth:true},
      {value:model.goal_percent, label:'Goal', color:options.lowerIsBetter ? palette.green : palette.red, spanFullWidth:true}
    ],
    targetAssessment:{
      value:model.target_percent, lowerIsBetter:options.lowerIsBetter,
      scorePredicate:row => Number(row.quality_denominator || 0) > 0
    },
    summaryBuilder:rows => qualityWeeklySummary(rows, options, model)
  }));
  content.append(hourlySection.section);
  appendCommonChartNotes(content, weeklySection, weekly);
}

// ---------- process time (aggregate-only; the section is absent until the QPTS procedure is deployed) ----------
const PROCESS_STAGE_COLORS = [CHART_SERIES_COLORS[0], CHART_SERIES_COLORS[4], CHART_SERIES_COLORS[1], CHART_SERIES_COLORS[2], CHART_SERIES_COLORS[3]];
const PROCESS_POPULATION_LABELS = {standard: 'First-pass parts (repaints excluded)', repaint: 'Repaints only'};
const PROCESS_METRICS = [
  {key: 'average_minutes', label: 'Average'},
  {key: 'median_minutes', label: 'Median'},
  {key: 'p90_minutes', label: '90th percentile'}
];
let processMetricKey = 'average_minutes';

function processMinutes(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  const minutes = Number(value);
  return minutes >= 180 ? (minutes / 60).toFixed(1) + ' h' : Math.round(minutes) + ' min';
}

function processDayRows(section, population) {
  const byDate = new Map();
  section.daily.filter(row => row.population === population && row.date <= section.report_date).forEach(row => {
    if (!byDate.has(row.date)) byDate.set(row.date, {date: row.date, stages: {}});
    byDate.get(row.date).stages[row.stage] = row;
  });
  return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
}

function processWindowTotals(rows, stageKey) {
  let weighted = 0, intervals = 0, negative = 0, long = 0;
  rows.forEach(day => {
    const row = day.stages[stageKey];
    if (!row) return;
    negative += Number(row.excluded_negative || 0);
    long += Number(row.over_12_hours || 0);
    if (row.average_minutes === null || row.intervals <= 0) return;
    weighted += Number(row.average_minutes) * Number(row.intervals);
    intervals += Number(row.intervals);
  });
  return {average: intervals ? weighted / intervals : null, intervals, negative, long};
}

function processTypicalMedian(rows, stageKey) {
  const values = rows.map(day => day.stages[stageKey]).filter(row => row && row.median_minutes !== null && row.intervals > 0).map(row => Number(row.median_minutes)).sort((a, b) => a - b);
  if (!values.length) return null;
  const middle = Math.floor(values.length / 2);
  return values.length % 2 ? values[middle] : (values[middle - 1] + values[middle]) / 2;
}

// Multi-day waits would flatten every normal day, so the axis stops near the 92nd-percentile value
// and clipped points are labelled with their true value.
function processAxisLimit(values, standard, floor) {
  const ordered = values.filter(value => value !== null && value !== undefined && Number.isFinite(Number(value))).map(Number).sort((a, b) => a - b);
  const natural = Math.max(floor, ...ordered, standard || 0) * 1.1;
  const reference = ordered.length ? ordered[Math.min(ordered.length - 1, Math.floor(ordered.length * 0.92))] : floor;
  const cap = Math.max(floor * 2, reference * 1.5, (standard || 0) * 1.4);
  return {maximum: Math.min(natural, cap), clipped: natural > cap};
}

function processTitle(node, message) {
  const title = svgNode('title'); title.append(text(message)); node.append(title); return node;
}

function processDetail(row) {
  if (!row) return 'no data';
  return processMinutes(row.average_minutes) + ' average, ' + processMinutes(row.median_minutes) + ' median, ' + processMinutes(row.p90_minutes) + ' 90th percentile, ' + integer(row.intervals) + ' intervals';
}

function processAxis(svg, maximum, left, right, width, y, steps = 5) {
  for (let index = 0; index <= steps; index += 1) {
    const value = maximum * index / steps;
    const yy = y(value);
    svg.append(svgNode('line', {x1: left, x2: width - right, y1: yy, y2: yy, stroke: palette.grid, 'stroke-width': 1}));
    const label = svgNode('text', {x: left - 8, y: yy + 4, 'text-anchor': 'end', fill: palette.muted, 'font-size': 10});
    label.append(text(maximum >= 240 ? (value / 60).toFixed(value / 60 < 10 ? 1 : 0) + ' h' : Math.round(value) + ' min'));
    svg.append(label);
  }
}

function processDateLabels(svg, rows, x, height, bottomOffset = 14) {
  const step = Math.max(1, Math.ceil(rows.length / 14));
  rows.forEach((row, index) => {
    if (index % step !== 0 && index !== rows.length - 1) return;
    const label = svgNode('text', {x: x(index), y: height - bottomOffset, 'text-anchor': 'middle', fill: palette.muted, 'font-size': 10});
    label.append(text(dateLabel(row.date))); svg.append(label);
  });
}

function processEmpty(container, message) {
  const empty = document.createElement('div'); empty.className = 'empty-state'; empty.append(text(message));
  container.replaceChildren(empty);
}

function renderProcessStack(container, rows, population, section) {
  const stackStages = section.stages.filter(stage => stage.order <= 5);
  const totalStage = section.stages.find(stage => stage.order === 6);
  const standard = (section.standards[population] || {})[totalStage.key];
  const metric = processMetricKey;
  const metricLabel = PROCESS_METRICS.find(item => item.key === metric).label;
  const totalLabel = 'Total ' + metricLabel.toLowerCase();
  if (rows.length < 2) { processEmpty(container, 'Not enough production-day data to chart.'); return; }
  const width = 980, height = 340, left = 62, right = 18, top = 20, bottom = 56;
  const stackTotals = rows.map(row => stackStages.reduce((sum, stage) => sum + Number((row.stages[stage.key] || {})[metric] || 0), 0));
  const totalLine = rows.map(row => (row.stages[totalStage.key] || {})[metric]);
  const limit = processAxisLimit([...stackTotals, ...totalLine], standard, 60);
  const maximum = limit.maximum;
  const x = index => left + (index + 0.5) * (width - left - right) / rows.length;
  const y = value => top + (maximum - Math.min(value, maximum)) * (height - top - bottom) / maximum;
  const barWidth = Math.max(4, Math.min(24, (width - left - right) / rows.length * 0.68));
  const svg = svgNode('svg', {viewBox: '0 0 ' + width + ' ' + height, role: 'img', 'aria-label': PROCESS_POPULATION_LABELS[population] + ' daily average minutes by stage'});
  processAxis(svg, maximum, left, right, width, y);
  rows.forEach((row, index) => {
    let cumulative = 0;
    stackStages.forEach((stage, stageIndex) => {
      const info = row.stages[stage.key];
      const amount = Number((info || {})[metric] || 0);
      if (amount <= 0) return;
      if (cumulative >= maximum) { cumulative += amount; return; }
      const rect = svgNode('rect', {x: x(index) - barWidth / 2, y: y(cumulative + amount), width: barWidth, height: Math.max(0.5, y(cumulative) - y(cumulative + amount)), fill: PROCESS_STAGE_COLORS[stageIndex], stroke: '#fff', 'stroke-width': 0.6, 'data-series': stage.short});
      processTitle(rect, dateLabel(row.date) + ' · ' + stage.label + ': ' + processDetail(info));
      svg.append(rect);
      cumulative += amount;
    });
    if (stackTotals[index] > maximum) {
      const flag = svgNode('text', {x: x(index), y: top - 5, 'text-anchor': 'middle', fill: palette.red, 'font-size': 9, 'font-weight': 700});
      flag.append(text('▲ ' + processMinutes(stackTotals[index]))); svg.append(flag);
    }
  });
  if (standard) {
    svg.append(svgNode('line', {x1: left, x2: width - right, y1: y(standard), y2: y(standard), stroke: palette.red, 'stroke-width': 2.2, 'stroke-dasharray': '7 5', 'data-series': 'Standard total'}));
    const label = svgNode('text', {x: left + 6, y: y(standard) - 6, 'text-anchor': 'start', fill: palette.red, 'font-size': 11, 'font-weight': 700, 'data-series': 'Standard total'});
    label.append(text('Standard ' + processMinutes(standard))); svg.append(label);
  }
  const points = [];
  rows.forEach((row, index) => { if (totalLine[index] !== null && totalLine[index] !== undefined) points.push([x(index), y(Number(totalLine[index])), index]); });
  if (points.length > 1) svg.append(svgNode('polyline', {points: points.map(point => point[0] + ',' + point[1]).join(' '), fill: 'none', stroke: palette.navy, 'stroke-width': 2.6, 'stroke-linejoin': 'round', 'data-series': totalLabel}));
  points.forEach(point => {
    const mark = chartMarker('circle', point[0], point[1], 3.4, palette.navy);
    mark.setAttribute('data-series', totalLabel);
    processTitle(mark, dateLabel(rows[point[2]].date) + ' · ' + totalStage.label + ': ' + processDetail(rows[point[2]].stages[totalStage.key]));
    svg.append(mark);
  });
  processDateLabels(svg, rows, x, height);
  const legend = stackStages.map((stage, index) => ({label: stage.short, color: PROCESS_STAGE_COLORS[index], line: false}));
  legend.push({label: totalLabel, color: palette.navy, line: true, width: 2.6, marker: 'circle'});
  if (standard) legend.push({label: 'Standard total', color: palette.red, line: true, dash: '7 5', width: 2.2});
  container.replaceChildren(svg, chartLegend(legend));
  bindSeriesHighlight(container);
}

function renderProcessStageTrend(container, rows, stage, color, marker, population, section) {
  const standard = (section.standards[population] || {})[stage.key];
  const usable = rows.filter(row => row.stages[stage.key] && row.stages[stage.key].average_minutes !== null);
  if (usable.length < 2) { processEmpty(container, 'Not enough data to chart.'); return; }
  const width = 480, height = 210, left = 54, right = 12, top = 16, bottom = 40;
  const values = usable.flatMap(row => [Number(row.stages[stage.key].average_minutes), row.stages[stage.key].median_minutes === null ? null : Number(row.stages[stage.key].median_minutes)]);
  const limit = processAxisLimit(values, standard, 10);
  const maximum = limit.maximum;
  const x = index => left + index * (width - left - right) / Math.max(usable.length - 1, 1);
  const y = value => top + (maximum - Math.min(value, maximum)) * (height - top - bottom) / maximum;
  const svg = svgNode('svg', {viewBox: '0 0 ' + width + ' ' + height, role: 'img', 'aria-label': stage.label + ' daily average minutes'});
  processAxis(svg, maximum, left, right, width, y, 4);
  if (standard) svg.append(svgNode('line', {x1: left, x2: width - right, y1: y(standard), y2: y(standard), stroke: palette.red, 'stroke-width': 2, 'stroke-dasharray': '7 5', 'data-series': 'Standard'}));
  const medianPoints = usable.map((row, index) => row.stages[stage.key].median_minutes === null ? null : x(index) + ',' + y(Number(row.stages[stage.key].median_minutes))).filter(Boolean);
  if (medianPoints.length > 1) svg.append(svgNode('polyline', {points: medianPoints.join(' '), fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-dasharray': '3 4', opacity: 0.8, 'stroke-linejoin': 'round', 'data-series': 'Median'}));
  svg.append(svgNode('polyline', {points: usable.map((row, index) => x(index) + ',' + y(Number(row.stages[stage.key].average_minutes))).join(' '), fill: 'none', stroke: color, 'stroke-width': 2.6, 'stroke-linejoin': 'round', 'data-series': 'Average'}));
  usable.forEach((row, index) => {
    const mark = chartMarker(marker, x(index), y(Number(row.stages[stage.key].average_minutes)), Number(row.stages[stage.key].average_minutes) > maximum ? 4.4 : 3.2, Number(row.stages[stage.key].average_minutes) > maximum ? palette.red : color);
    mark.setAttribute('data-series', 'Average');
    processTitle(mark, dateLabel(row.date) + ' · ' + stage.label + ': ' + processDetail(row.stages[stage.key]));
    svg.append(mark);
  });
  processDateLabels(svg, usable, x, height, 12);
  const legend = [{label: 'Average', color: color, line: true, width: 2.6, marker: marker}, {label: 'Median', color: color, line: true, dash: '3 4', width: 2}];
  if (standard) legend.push({label: 'Standard', color: palette.red, line: true, dash: '7 5', width: 2});
  container.replaceChildren(svg, chartLegend(legend));
  bindSeriesHighlight(container);
}

function processFigure(title, subtitle) {
  const figure = document.createElement('figure'); figure.className = 'loaded-chart-card';
  const caption = document.createElement('figcaption'); caption.append(text(title));
  if (subtitle) { const small = document.createElement('small'); small.append(text(subtitle)); caption.append(small); }
  const chart = document.createElement('div'); chart.className = 'chart';
  figure.append(caption, chart);
  return {figure, chart};
}

function renderProcessSummary(table, rows, population, section) {
  const standards = section.standards[population] || {};
  const sumOfStages = section.stages.filter(stage => stage.order <= 5).reduce((sum, stage) => sum + (processWindowTotals(rows, stage.key).average || 0), 0);
  const body = section.stages.map(stage => {
    const totals = processWindowTotals(rows, stage.key);
    const standard = standards[stage.key];
    const share = stage.order <= 5 && sumOfStages > 0 && totals.average !== null ? percent(totals.average / sumOfStages) : '—';
    const gap = standard && totals.average !== null ? (totals.average - standard >= 0 ? '+' : '−') + processMinutes(Math.abs(totals.average - standard)) : '—';
    return [stage.label, processMinutes(totals.average), processMinutes(processTypicalMedian(rows, stage.key)), share, integer(totals.intervals), standard ? processMinutes(standard) : 'not set', gap, integer(totals.long)];
  });
  renderTable(table, ['Stage', 'Average', 'Typical daily median', 'Share of stages', 'Intervals', 'Standard', 'Average vs standard', 'Over 12 h'].map((label, index) => ({label, value: row => row[index]})), body);
}

function renderProcessTimeCharts(snapshot) {
  const content = $('#metric-chart-content');
  const section = snapshot.process_time;
  if (!section || section.available === false) {
    const placeholder = document.createElement('div'); placeholder.className = 'chart-placeholder';
    placeholder.append(text(section ? section.reason : 'Process-time charts are not enabled yet; they need the QPTS process-time procedure.'));
    content.replaceChildren(placeholder); return;
  }
  const blocks = [];
  ['standard', 'repaint'].forEach(population => {
    const rows = processDayRows(section, population);
    const block = document.createElement('section'); block.className = 'process-block';
    const heading = document.createElement('h3'); heading.append(text(PROCESS_POPULATION_LABELS[population]));
    block.append(heading);
    const metricLabel = PROCESS_METRICS.find(item => item.key === processMetricKey).label;
    const stack = processFigure('Daily ' + metricLabel.toLowerCase() + ' minutes between scans', population === 'standard' ? 'Last 13 weeks, production days with scans' : 'Repaint loops only');
    renderProcessStack(stack.chart, rows, population, section);
    block.append(stack.figure);
    const grid = document.createElement('div'); grid.className = 'process-trend-grid';
    section.stages.filter(stage => stage.order <= 5).forEach((stage, index) => {
      const figure = processFigure(stage.label, 'Average, median' + ((section.standards[population] || {})[stage.key] ? ', standard' : '') + '; red points are above the axis');
      renderProcessStageTrend(figure.chart, rows, stage, PROCESS_STAGE_COLORS[index], CHART_SERIES_MARKERS[index], population, section);
      grid.append(figure.figure);
    });
    block.append(grid);
    const table = document.createElement('table'); table.className = 'process-summary';
    renderProcessSummary(table, rows, population, section);
    block.append(table);
    const total = processWindowTotals(rows, 'total_load_to_final_approved');
    let negative = 0, long = 0;
    section.stages.forEach(stage => { const totals = processWindowTotals(rows, stage.key); negative += totals.negative; long += totals.long; });
    const note = document.createElement('p'); note.className = 'process-note'; note.setAttribute('role', 'note');
    note.append(text('Each interval is dated by the scan that ends it. Overnight and weekend waits are included, so days after a break run high; the hover text also shows the median and 90th percentile. The axis stops near the 92nd-percentile day so a few multi-day waits do not flatten the rest; clipped days are labelled with their true value. '
      + integer(negative) + ' intervals ran backwards (scans out of order) and are left out; ' + integer(long) + ' intervals exceeded 12 hours and are counted. '
      + 'Total average over the window: ' + processMinutes(total.average) + ' across ' + integer(total.intervals) + ' parts.'));
    block.append(note);
    blocks.push(block);
  });
  const toggle = document.createElement('div'); toggle.className = 'process-toggle'; toggle.setAttribute('role', 'group'); toggle.setAttribute('aria-label', 'Statistic shown in the daily columns');
  const toggleLabel = document.createElement('span'); toggleLabel.append(text('Daily columns show'));
  toggle.append(toggleLabel);
  PROCESS_METRICS.forEach(item => {
    const button = document.createElement('button'); button.type = 'button'; button.append(text(item.label));
    button.setAttribute('aria-pressed', String(item.key === processMetricKey));
    button.addEventListener('click', () => { processMetricKey = item.key; renderProcessTimeCharts(snapshot); });
    toggle.append(button);
  });
  content.replaceChildren(toggle, ...blocks);
}

function processTimeCard(snapshot) {
  const section = snapshot.process_time;
  if (!section || section.available === false) {
    return metricCard('Process time', '—', [section ? 'Process-time data unavailable' : 'Awaiting the QPTS process-time procedure'], palette.purple);
  }
  const latest = population => {
    const rows = processDayRows(section, population).filter(row => (row.stages.total_load_to_final_approved || {}).average_minutes !== null && row.stages.total_load_to_final_approved !== undefined);
    return rows.length ? rows[rows.length - 1] : null;
  };
  const standard = latest('standard'), repaint = latest('repaint');
  return metricCard(
    'Process time',
    standard ? processMinutes(standard.stages.total_load_to_final_approved.average_minutes) : '—',
    [
      standard ? 'First-pass load to final · ' + dateLabel(standard.date) : 'No first-pass data yet',
      'Repaints: ' + (repaint ? processMinutes(repaint.stages.total_load_to_final_approved.average_minutes) + ' · ' + dateLabel(repaint.date) : '—')
    ],
    palette.purple
  );
}

function renderMetricCharts(snapshot) {
  $('#metric-chart-title').textContent = selectedChartLabel;
  const summary = $('#metric-chart-summary');
  if (selectedChartKey === 'loaded') {
    summary.textContent = 'Hourly totals show only the metric, solid goal and target references, and a fixed completed-period average; unique colors and eligible-cart pieces-per-cart history are separated in aggregate details.';
    renderLoadedCharts(snapshot); return;
  }
  if (selectedChartKey === 'carts-pieces-staged') {
    summary.textContent = 'Hourly charts are point-in-time queue snapshots, not accumulation, shown as steps with start, low, peak, end, and hours at or above the 12-cart / 36-piece minimum goals.';
    renderStagedCharts(snapshot); return;
  }
  if (selectedChartKey === 'carts-pieces-painted') {
    summary.textContent = 'Hourly painted totals include daily averages and unique colors; 13-week charts include throughput and dedicated unique-color history. Scheduled demand stays hidden until GP-only scope is proven.';
    renderPaintedCharts(snapshot); return;
  }
  if (selectedChartKey === 'repaint') {
    summary.textContent = 'Weighted hourly and 13-week repaint rates against a 4% goal; lower is better.';
    renderQualityCharts(snapshot, 'repaint', {
      label:'Repaint %',
      definition:'GP initial-pass repaint outcomes divided by GP initial passes',
      color:palette.amber,
      lowerIsBetter:true
    }); return;
  }
  if (selectedChartKey === 'finesse-effectiveness') {
    summary.textContent = 'Weighted hourly and 13-week Finesse Effectiveness against a 90% goal; higher is better.';
    renderQualityCharts(snapshot, 'finesse', {
      label:'Finesse Effectiveness',
      definition:'Completed GP-paint and Receiving/Finesse repairs divided by governed rejects',
      color:palette.green,
      lowerIsBetter:false
    }); return;
  }
  if (selectedChartKey === 'process-time') {
    summary.textContent = 'Daily average minutes between the cart-load, booth, oven-in, oven-out, EOL-approval, and final-inspection scans, with repaints reported separately and excluded from the first-pass averages.';
    renderProcessTimeCharts(snapshot); return;
  }
  summary.textContent = 'This tile is selectable; its chart contract is not enabled yet.';
  const placeholder = document.createElement('div'); placeholder.className = 'chart-placeholder';
  placeholder.append(text(`${selectedChartLabel} charts are not enabled yet.`));
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
  series.forEach((item, seriesIndex) => {
    const marker = CHART_SERIES_MARKERS[seriesIndex % CHART_SERIES_MARKERS.length];
    const usable = rows.map((row, index) => ({value: item.value(row), index})).filter(point => point.value !== null && Number.isFinite(point.value));
    const points = usable.map(point => `${x(point.index)},${y(point.value)}`).join(' ');
    svg.append(svgNode('polyline', {points, fill: 'none', stroke: item.color, 'stroke-width': 3, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-dasharray': item.dash || 'none', 'data-series': item.label}));
    usable.forEach(point => {
      const mark = chartMarker(marker, x(point.index), y(point.value), 4, item.color);
      mark.setAttribute('data-series', item.label);
      const title = svgNode('title'); title.append(text(`${dateLabel(rows[point.index].date)} · ${item.label}: ${asPercent ? (point.value * 100).toFixed(1) + '%' : Math.round(point.value).toLocaleString()}`));
      mark.append(title); svg.append(mark);
    });
  });
  const legend = document.createElement('div'); legend.className = 'chart-legend';
  series.forEach((item, seriesIndex) => legend.append(chartLegendKey({label: item.label, color: item.color, line: true, dash: item.dash, width: 3, marker: CHART_SERIES_MARKERS[seriesIndex % CHART_SERIES_MARKERS.length]})));
  container.append(svg, legend);
  bindSeriesHighlight(container);
}

function renderDaily(snapshot) {
  const active = snapshot.daily.filter(row => row.production_day);
  renderLineChart($('#throughput-chart'), active, [
    {label:'Loaded', color:CHART_SERIES_COLORS[0], value:row => Number(row.parts_loaded)},
    {label:'Painted', color:CHART_SERIES_COLORS[1], value:row => Number(row.paint_pieces_processed)},
    {label:'EOL', color:CHART_SERIES_COLORS[2], value:row => Number(row.eol_inspected)},
    {label:'Paint shipped', color:CHART_SERIES_COLORS[3], value:row => Number(row.painted_parts_shipped)}
  ]);
  renderLineChart($('#quality-chart'), active, [
    {label:'Repaint PPY', color:CHART_SERIES_COLORS[0], value:row => yieldRatio(row.ppy_approved, row.paint_decision_pieces)},
    {label:'Reject PPY', color:CHART_SERIES_COLORS[1], value:row => yieldRatio(row.reject_ppy_approved, row.reject_ppy_total)},
    {label:'Repaint FTY', color:CHART_SERIES_COLORS[2], value:row => yieldRatio(row.paint_fty_approved, row.paint_fty_total)},
    {label:'Reject FTY', color:CHART_SERIES_COLORS[3], value:row => yieldRatio(row.reject_fty_approved, row.reject_fty_total)}
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
