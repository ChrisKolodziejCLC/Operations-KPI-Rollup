'use strict';

const palette = {
  teal: '#13858c', blue: '#3478ad', green: '#37856e', purple: '#826aa4',
  amber: '#df922a', red: '#bd524d', navy: '#0b2239', grid: '#d9e3e8', muted: '#607487'
};

const EARLIEST_REPORT_DATE = '2026-09-08';
const WALLBOARD_POLL_MS = 30 * 1000;
let refreshInProgress = false;
let displayedReportDate = '';

const $ = (selector) => document.querySelector(selector);
const svgNode = (name, attributes = {}) => {
  const node = document.createElementNS('http://www.w3.org/2000/svg', name);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
  return node;
};
const text = (value) => document.createTextNode(String(value ?? ''));
const integer = (value) => Number(value || 0).toLocaleString();
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
  return {production: row.production_parts_loaded, bv: row.bv_parts_loaded || 0, service: row.service_parts_loaded};
}

function cartSplit(row) {
  if (row.production_carts_loaded === undefined && row.service_carts_loaded === undefined) {
    return {production: row.carts_loaded, bv: 0, service: 0};
  }
  return {production: row.production_carts_loaded, bv: row.bv_carts_loaded || 0, service: row.service_carts_loaded};
}

function paintCartSplit(row) {
  if (row.production_paint_carts === undefined && row.service_paint_carts === undefined) {
    return {production: row.paint_carts, bv: 0, service: 0};
  }
  return {production: row.production_paint_carts, bv: row.bv_paint_carts || 0, service: row.service_paint_carts};
}

function paintPieceSplit(row) {
  if (row.production_paint_pieces_processed === undefined && row.service_paint_pieces_processed === undefined) {
    return {production: row.paint_pieces_processed, bv: 0, service: 0};
  }
  return {production: row.production_paint_pieces_processed, bv: row.bv_paint_pieces_processed || 0, service: row.service_paint_pieces_processed};
}

function rateBreakdown(row, numerator, denominator) {
  const values = ['production', 'bv', 'service'].map(prefix => percent(ratio(row[`${prefix}_${numerator}`], row[`${prefix}_${denominator}`])));
  return `Prd ${values[0]} / BV ${values[1]} / Svc ${values[2]}`;
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
  const detailNode = document.createElement('small'); detailNode.append(text(detail));
  card.append(labelNode, valueNode, detailNode);
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
    value.append(text(`${integer(row.production)} Prd / ${integer(row.bv)} BV / ${integer(row.service)} Svc`));
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
    const detail = document.createElement('small'); detail.className = 'dual-yield-detail'; detail.append(text(metric.detail));
    column.append(metricLabel, value, detail); grid.append(column);
  });
  card.append(labelNode, grid);
  return card;
}

function renderCards(snapshot) {
  const current = snapshot.daily.find(row => row.date === snapshot.report_date);
  if (!current) return;
  const loaded = loadSplit(current);
  const carts = cartSplit(current);
  const paintCarts = paintCartSplit(current);
  const paintPieces = paintPieceSplit(current);
  let trailerDetail = `${integer(current.fuka_trailers_prepared)} FUKA / ${integer(current.bumper_trailers_prepared)} Bumpers / ${integer(current.fairing_trailers_prepared)} Fairings`;
  if (Number(current.other_trailers_prepared || 0) > 0) trailerDetail += ` / ${integer(current.other_trailers_prepared)} Other`;
  const cards = [
    ['Repaint %', percent(ratio(current.paint_fty_repaint_count, current.paint_fty_total)), `${integer(current.paint_fty_repaint_count)} / ${integer(current.paint_fty_total)} initial passes`, palette.amber],
    ['Receiving FTY', percent(ratio(current.receiving_approved, current.receiving_total)), `${integer(current.receiving_approved)} / ${integer(current.receiving_total)} first decisions · Qty ${integer(current.receiving_quantity)} by receive stamp`, palette.green],
    ['Final FTY', percent(ratio(current.final_approved, current.final_total)), `${integer(current.final_approved)} / ${integer(current.final_total)} first decisions · Qty ${integer(current.final_quantity)} by final stamp`, palette.purple],
    ['Paint plan composite', percent(composite(current)), 'provisional · not standard OEE', palette.purple],
    ['Pieces shipped', integer(current.parts_shipped), 'non-service total', palette.red],
    ['Complete assy sets', integer(current.complete_assy_sets), 'N33 / Chassis Fairing · dated by last assembled piece', palette.teal],
    ['Assembled bumpers', integer(current.assembled_bumper_count), 'N71-6171 · AssembledDate', palette.blue],
    ['Trailers prepared', integer(current.trailers_prepared), trailerDetail, palette.amber]
  ];
  const container = $('#cards'); container.replaceChildren();
  container.append(splitMetricCard('Pieces loaded', current.parts_loaded, current.unique_pieces_loaded, [
    {label:'Carts', production:carts.production, bv:carts.bv, service:carts.service},
    {label:'Pieces', production:loaded.production, bv:loaded.bv, service:loaded.service}
  ], palette.teal));
  container.append(splitMetricCard('Pieces painted', current.paint_pieces_processed, current.unique_pieces_processed, [
    {label:'Carts', production:paintCarts.production, bv:paintCarts.bv, service:paintCarts.service},
    {label:'Pieces', production:paintPieces.production, bv:paintPieces.bv, service:paintPieces.service}
  ], palette.blue));
  container.append(dualYieldCard('PPY (Paint Process Yield)', {
    numerator:current.ppy_approved, denominator:current.paint_decision_pieces,
    detail:`${integer(current.ppy_approved)} / ${integer(current.paint_decision_pieces)} · ${integer(current.ppy_repaint_count)} repaint · ${integer(current.reject_ppy_pending_count)} pending`
  }, {
    numerator:current.reject_ppy_approved, denominator:current.reject_ppy_total,
    detail:`${integer(current.reject_ppy_approved)} / ${integer(current.reject_ppy_total)} · ${integer(current.reject_ppy_rejected_count)} rejected · ${integer(current.reject_ppy_pending_count)} pending`
  }, palette.amber));
  container.append(dualYieldCard('FTY (First Time Yield)', {
    numerator:current.paint_fty_approved, denominator:current.paint_fty_total,
    detail:`${integer(current.paint_fty_approved)} / ${integer(current.paint_fty_total)} · ${integer(current.paint_fty_repaint_count)} repaint · ${integer(current.reject_fty_pending_count)} pending`
  }, {
    numerator:current.reject_fty_approved, denominator:current.reject_fty_total,
    detail:`${integer(current.reject_fty_approved)} / ${integer(current.reject_fty_total)} · ${integer(current.reject_fty_rejected_count)} rejected · ${integer(current.reject_fty_pending_count)} pending`
  }, palette.blue));
  cards.forEach(card => container.append(metricCard(...card)));
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
  const colors = {'Bumpers':palette.red, 'Chassis Fairings':palette.blue, 'Fenders':palette.teal};
  const container = $('#shipping-chart'); container.replaceChildren();
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
  displayedReportDate = snapshot.report_date;
  $('#report-date').textContent = `Report date ${fullDateLabel(snapshot.report_date)}`;
  $('#report-range').textContent = rangeLabel(snapshot.daily);
  $('#generated-at').textContent = `Snapshot ${new Date(snapshot.generated_at).toLocaleString()}`;
  $('#scope-label').textContent = `${snapshot.scope.label}. Method: ${snapshot.scope.method_version}.`;
  $('#date-input').value = snapshot.report_date;
  updateNavigationState();
  renderCards(snapshot); renderDaily(snapshot); renderPeriods(snapshot); renderDefects(snapshot); renderShipping(snapshot); renderPainters(snapshot); renderNotes(snapshot);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed with HTTP ${response.status}`);
  return payload;
}

async function loadLatest(quiet = false) {
  try {
    const snapshot = await api('/api/snapshot'); render(snapshot);
    if (!quiet) setStatus('Latest saved snapshot loaded.');
  } catch (error) {
    if (!quiet) setStatus(error.message, true);
  }
  try {
    const health = await api('/api/health'); $('#health-state').textContent = `${health.status} · ${health.mode} mode`;
  } catch (_) { $('#health-state').textContent = 'Health endpoint unavailable'; }
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
    await loadLatest();
  }
}

initialize();
