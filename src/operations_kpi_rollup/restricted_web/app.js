'use strict';

const palette = {
  teal: '#13858c', blue: '#3478ad', green: '#37856e', purple: '#826aa4',
  amber: '#df922a', red: '#bd524d', navy: '#0b2239', gray: '#9aabb5',
  grid: '#d9e3e8', muted: '#607487'
};
const seriesColors = [palette.teal, palette.blue, palette.green, palette.purple, palette.amber, palette.red, '#5f7f95', '#a46f52'];
const EARLIEST_REPORT_DATE = '2026-09-08';
let activeSnapshot = null;
let busy = false;

const $ = (selector) => document.querySelector(selector);
const svgNode = (name, attributes) => {
  const node = document.createElementNS('http://www.w3.org/2000/svg', name);
  Object.entries(attributes || {}).forEach(([key, value]) => node.setAttribute(key, String(value)));
  return node;
};
const integer = (value) => Number(value || 0).toLocaleString(undefined, {maximumFractionDigits: 0});
const decimal = (value, digits) => value === null || value === undefined || !Number.isFinite(Number(value))
  ? '—' : Number(value).toLocaleString(undefined, {minimumFractionDigits: digits === undefined ? 1 : digits, maximumFractionDigits: digits === undefined ? 1 : digits});
const percent = (value) => value === null || value === undefined || !Number.isFinite(Number(value))
  ? '—' : decimal(value, 1) + '%';
const dateLabel = (value) => value ? new Date(value + 'T12:00:00').toLocaleDateString(undefined, {month: 'short', day: 'numeric'}) : '—';
const timeLabel = (value) => value ? new Date(value).toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'}) : '—';
const localDateISO = (value) => {
  const date = value || new Date();
  return date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0');
};
const shiftDate = (value, days) => {
  const shifted = new Date(value + 'T12:00:00');
  shifted.setDate(shifted.getDate() + days);
  return localDateISO(shifted);
};
const sum = (rows, field) => rows.reduce((total, row) => total + Number(row[field] || 0), 0);

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function setStatus(message, error) {
  const node = $('#status');
  node.textContent = message;
  node.classList.toggle('error', Boolean(error));
}

function setBusy(value) {
  busy = value;
  ['#previous-day', '#today', '#next-day', '#load-date', '#refresh', '#report-date'].forEach((selector) => {
    $(selector).disabled = value;
  });
}

function emptyState(node, message) {
  clear(node);
  const empty = document.createElement('div');
  empty.className = 'chart-empty';
  empty.textContent = message;
  node.appendChild(empty);
}

function summaryCard(label, value, detail, color) {
  const card = document.createElement('article');
  card.className = 'summary-card';
  card.style.borderLeftColor = color || palette.teal;
  const labelNode = document.createElement('span');
  labelNode.textContent = label;
  const valueNode = document.createElement('strong');
  valueNode.textContent = value;
  const detailNode = document.createElement('small');
  detailNode.textContent = detail;
  card.append(labelNode, valueNode, detailNode);
  return card;
}

function aggregate(rows, keyField, fields) {
  const grouped = new Map();
  rows.forEach((row) => {
    const key = String(row[keyField] === undefined || row[keyField] === null ? 'Unknown' : row[keyField]);
    if (!grouped.has(key)) {
      const initial = {key: key};
      fields.forEach((field) => { initial[field] = 0; });
      grouped.set(key, initial);
    }
    const item = grouped.get(key);
    fields.forEach((field) => { item[field] += Number(row[field] || 0); });
  });
  return Array.from(grouped.values());
}

function appendLegend(container, items) {
  const legend = document.createElement('div');
  legend.className = 'chart-legend';
  items.forEach((item) => {
    const key = document.createElement('span');
    key.className = 'legend-key';
    const swatch = document.createElement('span');
    swatch.className = 'legend-swatch';
    swatch.style.background = item.color;
    const label = document.createElement('span');
    label.textContent = item.label;
    key.append(swatch, label);
    legend.appendChild(key);
  });
  container.appendChild(legend);
}

function renderRankBars(selector, rows, valueField, labelField, color, formatter) {
  const container = $(selector);
  clear(container);
  const sorted = rows.slice().sort((a, b) => Number(b[valueField] || 0) - Number(a[valueField] || 0));
  if (!sorted.length) {
    emptyState(container, 'No data for the selected day.');
    return;
  }
  const maximum = Math.max.apply(null, sorted.map((row) => Number(row[valueField] || 0)).concat([1]));
  sorted.forEach((row) => {
    const line = document.createElement('div');
    line.className = 'rank-row';
    const label = document.createElement('span');
    label.className = 'rank-label';
    label.title = String(row[labelField] || 'Unknown');
    label.textContent = String(row[labelField] || 'Unknown');
    const track = document.createElement('span');
    track.className = 'rank-track';
    const fill = document.createElement('span');
    fill.className = 'rank-fill';
    fill.style.background = color || palette.teal;
    fill.style.width = Math.max(0.7, Number(row[valueField] || 0) * 100 / maximum) + '%';
    track.appendChild(fill);
    const value = document.createElement('span');
    value.className = 'rank-value';
    value.textContent = formatter ? formatter(row) : integer(row[valueField]);
    line.append(label, track, value);
    container.appendChild(line);
  });
}

function renderStackedHorizontal(selector, rows, segments, options) {
  const container = $(selector);
  clear(container);
  if (!rows.length) {
    emptyState(container, 'No data for the selected day.');
    return;
  }
  const width = 760;
  const left = 145;
  const right = 62;
  const top = 18;
  const rowHeight = 38;
  const height = top + rows.length * rowHeight + 20;
  const plotWidth = width - left - right;
  const maximum = Math.max.apply(null, rows.map((row) => segments.reduce((total, segment) => total + Number(row[segment.field] || 0), 0)).concat([1]));
  const svg = svgNode('svg', {viewBox: '0 0 ' + width + ' ' + height, role: 'img', 'aria-label': options.ariaLabel || 'Stacked bar chart'});
  rows.forEach((row, rowIndex) => {
    const y = top + rowIndex * rowHeight;
    const label = svgNode('text', {x: left - 10, y: y + 19, 'text-anchor': 'end', class: 'axis-label'});
    label.textContent = String(row.label || row.key || 'Unknown').slice(0, 24);
    svg.appendChild(label);
    svg.appendChild(svgNode('rect', {x: left, y: y + 4, width: plotWidth, height: 22, rx: 3, fill: '#edf1f3'}));
    let x = left;
    segments.forEach((segment) => {
      const amount = Number(row[segment.field] || 0);
      const segmentWidth = amount * plotWidth / maximum;
      if (segmentWidth > 0) {
        svg.appendChild(svgNode('rect', {x: x, y: y + 4, width: segmentWidth, height: 22, fill: segment.color}));
        x += segmentWidth;
      }
    });
    const total = segments.reduce((value, segment) => value + Number(row[segment.field] || 0), 0);
    const value = svgNode('text', {x: left + total * plotWidth / maximum + 7, y: y + 19, class: 'value-label'});
    value.textContent = options.formatTotal ? options.formatTotal(row, total) : integer(total);
    svg.appendChild(value);
  });
  container.appendChild(svg);
  appendLegend(container, segments.map((segment) => ({label: segment.label, color: segment.color})));
}

function renderPainterShare(rows) {
  const grouped = aggregate(rows, 'painter', ['pieces']).map((row) => ({label: row.key, pieces: row.pieces}));
  const total = sum(grouped, 'pieces');
  renderRankBars('#painter-share', grouped, 'pieces', 'label', palette.teal, (row) => {
    const share = total > 0 ? row.pieces * 100 / total : 0;
    return integer(row.pieces) + ' · ' + percent(share);
  });
}

function renderPainterBooth(rows) {
  const painters = Array.from(new Set(rows.map((row) => row.painter))).sort();
  const booths = Array.from(new Set(rows.map((row) => Number(row.booth || 0)))).sort((a, b) => a - b);
  const grouped = painters.map((painter) => {
    const item = {label: painter};
    booths.forEach((booth) => {
      item['booth_' + booth] = rows.filter((row) => row.painter === painter && Number(row.booth || 0) === booth)
        .reduce((total, row) => total + Number(row.pieces || 0), 0);
    });
    return item;
  }).sort((a, b) => booths.reduce((total, booth) => total + Number(b['booth_' + booth] || 0) - Number(a['booth_' + booth] || 0), 0));
  const segments = booths.map((booth, index) => ({field: 'booth_' + booth, label: booth ? 'Booth ' + booth : 'Booth unknown', color: seriesColors[index % seriesColors.length]}));
  renderStackedHorizontal('#painter-pieces', grouped, segments, {ariaLabel: 'Pieces painted by painter and booth'});
}

function renderPainterFty(rows) {
  const grouped = aggregate(rows, 'painter', ['fty_approved', 'fty_repair', 'fty_repaint', 'fty_pending'])
    .map((row) => ({label: row.key, approved: row.fty_approved, repaired: row.fty_repair, repaint: row.fty_repaint, pending: row.fty_pending}))
    .sort((a, b) => (b.approved + b.repaired + b.repaint + b.pending) - (a.approved + a.repaired + a.repaint + a.pending));
  renderStackedHorizontal('#painter-fty', grouped, [
    {field: 'approved', label: 'Approved', color: palette.green},
    {field: 'repaired', label: 'Repaired', color: palette.amber},
    {field: 'repaint', label: 'Repaint', color: palette.red},
    {field: 'pending', label: 'Pending', color: palette.gray}
  ], {ariaLabel: 'First-time yield outcomes by painter'});
}

function sundayStart(value) {
  const current = new Date(value + 'T12:00:00');
  current.setDate(current.getDate() - current.getDay());
  return localDateISO(current);
}

function regression(values) {
  const usable = values.map((value, index) => ({x: index, y: value})).filter((point) => Number.isFinite(point.y));
  if (usable.length < 2) return null;
  const n = usable.length;
  const sumX = usable.reduce((total, point) => total + point.x, 0);
  const sumY = usable.reduce((total, point) => total + point.y, 0);
  const sumXY = usable.reduce((total, point) => total + point.x * point.y, 0);
  const sumXX = usable.reduce((total, point) => total + point.x * point.x, 0);
  const denominator = n * sumXX - sumX * sumX;
  if (!denominator) return null;
  const slope = (n * sumXY - sumX * sumY) / denominator;
  const intercept = (sumY - slope * sumX) / n;
  return values.map((value, index) => value === null ? null : intercept + slope * index);
}

function renderPainterHistory(rows, reportDate) {
  const container = $('#painter-history');
  clear(container);
  const currentWeek = sundayStart(reportDate);
  const weekKeys = [];
  for (let offset = 12; offset >= 0; offset -= 1) weekKeys.push(shiftDate(currentWeek, -offset * 7));
  const painters = aggregate(rows, 'painter', ['pieces']).sort((a, b) => b.pieces - a.pieces).map((row) => row.key);
  if (!painters.length) {
    emptyState(container, 'No painter history is available.');
    return;
  }
  const visiblePainters = painters.slice(0, 7);
  const hasOther = painters.length > visiblePainters.length;
  const series = visiblePainters.concat(hasOther ? ['Other'] : []);
  const weeks = weekKeys.map((week) => {
    const item = {week: week};
    series.forEach((name) => { item[name] = 0; });
    rows.forEach((row) => {
      if (sundayStart(row.date) !== week) return;
      const name = visiblePainters.includes(row.painter) ? row.painter : 'Other';
      item[name] += Number(row.pieces || 0);
    });
    item.total = series.reduce((total, name) => total + item[name], 0);
    return item;
  });
  const width = 840;
  const height = 330;
  const left = 42;
  const right = 18;
  const top = 30;
  const bottom = 58;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const maximum = Math.max.apply(null, weeks.map((week) => week.total).concat([1])) * 1.12;
  const slot = plotWidth / weeks.length;
  const barWidth = Math.max(12, slot * 0.62);
  const svg = svgNode('svg', {viewBox: '0 0 ' + width + ' ' + height, role: 'img', 'aria-label': 'Thirteen-week stacked pieces painted history'});
  [0, 0.25, 0.5, 0.75, 1].forEach((fraction) => {
    const y = top + plotHeight * (1 - fraction);
    svg.appendChild(svgNode('line', {x1: left, y1: y, x2: width - right, y2: y, stroke: palette.grid, 'stroke-width': 1}));
    const label = svgNode('text', {x: left - 6, y: y + 4, 'text-anchor': 'end', class: 'axis-label'});
    label.textContent = integer(maximum * fraction);
    svg.appendChild(label);
  });
  weeks.forEach((week, index) => {
    const x = left + slot * index + (slot - barWidth) / 2;
    let y = top + plotHeight;
    series.forEach((name, seriesIndex) => {
      const amount = week[name];
      const segmentHeight = amount * plotHeight / maximum;
      y -= segmentHeight;
      if (segmentHeight > 0) svg.appendChild(svgNode('rect', {x: x, y: y, width: barWidth, height: segmentHeight, fill: seriesColors[seriesIndex % seriesColors.length]}));
    });
    if (week.total > 0) {
      const value = svgNode('text', {x: x + barWidth / 2, y: y - 5, 'text-anchor': 'middle', class: 'value-label'});
      value.textContent = integer(week.total);
      svg.appendChild(value);
    }
    const label = svgNode('text', {x: x + barWidth / 2, y: height - bottom + 18, 'text-anchor': 'middle', class: 'axis-label'});
    label.textContent = dateLabel(week.week);
    label.setAttribute('transform', 'rotate(-45 ' + (x + barWidth / 2) + ' ' + (height - bottom + 18) + ')');
    svg.appendChild(label);
  });
  const currentIsPartial = reportDate < shiftDate(currentWeek, 6);
  const trendInputs = weeks.map((week, index) => currentIsPartial && index === weeks.length - 1 ? null : week.total);
  const trend = regression(trendInputs);
  if (trend) {
    const points = trend.map((value, index) => {
      if (value === null) return null;
      const x = left + slot * index + slot / 2;
      const y = top + plotHeight - Math.max(0, value) * plotHeight / maximum;
      return x + ',' + y;
    }).filter(Boolean).join(' ');
    svg.appendChild(svgNode('polyline', {points: points, fill: 'none', stroke: palette.navy, 'stroke-width': 2.5, 'stroke-dasharray': '6 4'}));
  }
  container.appendChild(svg);
  const legend = series.map((name, index) => ({label: name, color: seriesColors[index % seriesColors.length]}));
  legend.push({label: 'Complete-week total trend', color: palette.navy});
  appendLegend(container, legend);
}

function renderTable(selector, columns, rows, emptyMessage) {
  const table = $(selector);
  clear(table);
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  columns.forEach((column) => {
    const cell = document.createElement('th');
    cell.textContent = column.label;
    headRow.appendChild(cell);
  });
  head.appendChild(headRow);
  table.appendChild(head);
  const body = document.createElement('tbody');
  if (!rows.length) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = columns.length;
    cell.textContent = emptyMessage || 'No detail is available.';
    row.appendChild(cell);
    body.appendChild(row);
  } else {
    rows.forEach((item) => {
      const row = document.createElement('tr');
      columns.forEach((column) => {
        const cell = document.createElement('td');
        const value = column.format ? column.format(item[column.key], item) : item[column.key];
        cell.textContent = value === null || value === undefined || value === '' ? '—' : String(value);
        row.appendChild(cell);
      });
      body.appendChild(row);
    });
  }
  table.appendChild(body);
}

function renderPainter(snapshot) {
  const allRows = snapshot.painter_daily || [];
  const rows = allRows.filter((row) => row.date === snapshot.report_date).slice().sort((a, b) => Number(b.pieces || 0) - Number(a.pieces || 0));
  const totalPieces = sum(rows, 'pieces');
  const totalCarts = sum(rows, 'carts');
  const totalMinutes = sum(rows, 'minutes');
  const ftyTotal = sum(rows, 'fty_total');
  const ftyApproved = sum(rows, 'fty_approved');
  const painters = new Set(rows.map((row) => row.painter)).size;
  const booths = new Set(rows.map((row) => row.booth).filter((value) => Number(value) > 0)).size;
  const kpis = $('#painter-kpis');
  clear(kpis);
  [
    ['Pieces painted', integer(totalPieces), integer(totalCarts) + ' carts', palette.blue],
    ['Active painters', integer(painters), integer(booths) + ' booths represented', palette.teal],
    ['Painter-hours', decimal(totalMinutes / 60, 1), 'Summed logged booth time', palette.purple],
    ['Pieces / painter-hour', totalMinutes > 0 ? decimal(totalPieces * 60 / totalMinutes, 1) : '—', 'All painters and booths', palette.green],
    ['First-time yield', ftyTotal > 0 ? percent(ftyApproved * 100 / ftyTotal) : '—', integer(ftyApproved) + ' approved / ' + integer(ftyTotal) + ' evaluated', palette.amber],
    ['Most colors / painter-booth', rows.length ? integer(Math.max.apply(null, rows.map((row) => Number(row.unique_colors || 0)))) : '0', 'Per-row distinct color count', palette.red]
  ].forEach((card) => kpis.appendChild(summaryCard(card[0], card[1], card[2], card[3])));
  renderPainterShare(rows);
  renderPainterBooth(rows);
  renderPainterFty(rows);
  renderPainterHistory(allRows.filter((row) => row.date <= snapshot.report_date), snapshot.report_date);
  renderTable('#painter-table', [
    {key: 'painter', label: 'Painter'},
    {key: 'booth', label: 'Booth', format: (value) => value ? 'Booth ' + integer(value) : 'Unknown'},
    {key: 'carts', label: 'Carts', format: integer},
    {key: 'pieces', label: 'Pieces', format: integer},
    {key: 'minutes', label: 'Booth min', format: integer},
    {key: 'pieces_per_hour', label: 'Pieces / hr', format: (value) => decimal(value, 1)},
    {key: 'unique_colors', label: 'Colors', format: integer},
    {key: 'fty_percent', label: 'FTY', format: percent},
    {key: 'fty_approved', label: 'Approved', format: integer},
    {key: 'fty_repair', label: 'Repair', format: integer},
    {key: 'fty_repaint', label: 'Repaint', format: integer},
    {key: 'fty_pending', label: 'Pending', format: integer}
  ], rows, 'No painter production rows are available for the selected day.');
}

function renderRepaint(snapshot) {
  const contributions = snapshot.repaint && snapshot.repaint.contributions ? snapshot.repaint.contributions : [];
  ['painter', 'color', 'booth'].forEach((dimension) => {
    const rows = contributions.filter((row) => row.dimension === dimension).map((row) => ({
      label: row.label,
      repaint_events: row.repaint_events,
      contribution_percent: row.contribution_percent
    }));
    renderRankBars('#repaint-' + dimension, rows, 'repaint_events', 'label', dimension === 'painter' ? palette.red : dimension === 'color' ? palette.amber : palette.purple, (row) => integer(row.repaint_events) + ' · ' + percent(row.contribution_percent));
  });
  const details = (snapshot.repaint && snapshot.repaint.details ? snapshot.repaint.details : [])
    .filter((row) => !row.event_at || row.event_at.slice(0, 10) === snapshot.report_date);
  renderTable('#repaint-table', [
    {key: 'event_at', label: 'Time', format: timeLabel},
    {key: 'part_id', label: 'Part ID', format: integer},
    {key: 'part_number', label: 'Part number'},
    {key: 'sequence', label: 'Sequence'},
    {key: 'color', label: 'Color'},
    {key: 'painter', label: 'Painter'},
    {key: 'booth', label: 'Booth', format: (value) => value ? 'Booth ' + integer(value) : 'Unknown'},
    {key: 'repaint_loop_count', label: 'Loops', format: integer},
    {key: 'defect', label: 'Defect'}
  ], details, 'No repaint-loop detail is available for the selected day.');
}

function renderFinesse(snapshot) {
  const summary = snapshot.finesse && snapshot.finesse.summary ? snapshot.finesse.summary.filter((row) => row.date === snapshot.report_date) : [];
  const workers = Array.from(new Set(summary.map((row) => row.worker))).sort();
  const outcomes = ['approved', 'repaired', 'repaint', 'pending'];
  const grouped = workers.map((worker) => {
    const item = {label: worker};
    outcomes.forEach((outcome) => {
      item[outcome] = summary.filter((row) => row.worker === worker && row.outcome === outcome).reduce((total, row) => total + Number(row.parts || 0), 0);
    });
    return item;
  }).sort((a, b) => outcomes.reduce((total, outcome) => total + Number(b[outcome] || 0) - Number(a[outcome] || 0), 0));
  renderStackedHorizontal('#finesse-outcomes', grouped, [
    {field: 'approved', label: 'Approved', color: palette.green},
    {field: 'repaired', label: 'Repaired', color: palette.amber},
    {field: 'repaint', label: 'Repaint', color: palette.red},
    {field: 'pending', label: 'Pending', color: palette.gray}
  ], {ariaLabel: 'Finesse parts by worker and outcome'});
  const timeRows = workers.map((worker) => {
    const rows = summary.filter((row) => row.worker === worker && row.average_minutes_per_part !== null);
    const parts = sum(rows, 'parts');
    const weightedMinutes = rows.reduce((total, row) => total + Number(row.average_minutes_per_part || 0) * Number(row.parts || 0), 0);
    return {label: worker, minutes: parts > 0 ? weightedMinutes / parts : 0};
  });
  renderRankBars('#finesse-time', timeRows, 'minutes', 'label', palette.blue, (row) => decimal(row.minutes, 1) + ' min');
  const details = (snapshot.finesse && snapshot.finesse.details ? snapshot.finesse.details : [])
    .filter((row) => !row.event_at || row.event_at.slice(0, 10) === snapshot.report_date);
  renderTable('#finesse-table', [
    {key: 'event_at', label: 'Time', format: timeLabel},
    {key: 'part_id', label: 'Part ID', format: integer},
    {key: 'part_number', label: 'Part number'},
    {key: 'sequence', label: 'Sequence'},
    {key: 'color', label: 'Color'},
    {key: 'worker', label: 'Worker'},
    {key: 'outcome', label: 'Outcome'},
    {key: 'minutes_per_part', label: 'Min / part', format: (value) => decimal(value, 1)},
    {key: 'repaint_count', label: 'Repaint count', format: integer}
  ], details, 'No finesse part detail is available for the selected day.');
}

function render(snapshot) {
  activeSnapshot = snapshot;
  $('#report-date').value = snapshot.report_date;
  $('#generated-at').textContent = 'Generated ' + new Date(snapshot.generated_at).toLocaleString();
  renderPainter(snapshot);
  renderRepaint(snapshot);
  renderFinesse(snapshot);
  setStatus('Restricted data loaded for ' + dateLabel(snapshot.report_date) + '.');
}

async function fetchJson(url, options) {
  const response = await fetch(url, Object.assign({cache: 'no-store'}, options || {}));
  const payload = await response.json().catch(() => ({error: 'The server returned an unreadable response.'}));
  if (!response.ok) throw new Error(payload.error || 'Request failed with status ' + response.status + '.');
  return payload;
}

async function loadDate(reportDate) {
  if (busy) return;
  setBusy(true);
  setStatus('Loading restricted snapshot…');
  try {
    const snapshot = await fetchJson('/api/snapshot?report_date=' + encodeURIComponent(reportDate));
    render(snapshot);
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    setBusy(false);
  }
}

async function refreshDate() {
  if (busy) return;
  const reportDate = $('#report-date').value;
  setBusy(true);
  setStatus('Refreshing restricted data…');
  try {
    const snapshot = await fetchJson('/api/refresh', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Operations-KPI-Restricted-Action': 'refresh'},
      body: JSON.stringify({report_date: reportDate, force: true})
    });
    render(snapshot);
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    setBusy(false);
  }
}

async function start() {
  const dateInput = $('#report-date');
  dateInput.min = EARLIEST_REPORT_DATE;
  dateInput.max = localDateISO();
  try {
    const health = await fetchJson('/api/health');
    if (health.viewer) $('#viewer').textContent = health.viewer.name || health.viewer.user || 'Authorized viewer';
    const reportDate = health.report_date || localDateISO();
    dateInput.value = reportDate;
    await loadDate(reportDate);
  } catch (error) {
    setStatus(error.message, true);
  }
}

$('#load-date').addEventListener('click', () => loadDate($('#report-date').value));
$('#refresh').addEventListener('click', refreshDate);
$('#previous-day').addEventListener('click', () => {
  const value = shiftDate($('#report-date').value, -1);
  $('#report-date').value = value < EARLIEST_REPORT_DATE ? EARLIEST_REPORT_DATE : value;
  loadDate($('#report-date').value);
});
$('#next-day').addEventListener('click', () => {
  const value = shiftDate($('#report-date').value, 1);
  $('#report-date').value = value > localDateISO() ? localDateISO() : value;
  loadDate($('#report-date').value);
});
$('#today').addEventListener('click', () => {
  $('#report-date').value = localDateISO();
  loadDate($('#report-date').value);
});

start();
