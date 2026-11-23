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
  amber: '#df922a', red: '#bd524d', navy: '#0b2239', gray: '#9aabb5',
  grid: '#d9e3e8', muted: '#607487'
};
const seriesColors = CHART_SERIES_COLORS;
const EARLIEST_REPORT_DATE = '2026-09-08';
let businessDate = null;
let businessTimeZone = null;
let activeSnapshot = null;

// Names view: shown only to a signed-in, allowlisted Windows session (the server decides). IDs stay the default
// and names are looked up on demand for the IDs on screen; they are never stored in the snapshot or the browser.
let namesAllowed = false;
let namesOn = false;
let rosterNames = {};
let rosterAsked = {};
const personLabel = (kind) => namesOn ? kind : kind + ' ID';

function snapshotIds(snapshot) {
  const ids = new Set();
  (snapshot.painter_daily || []).forEach((row) => ids.add(String(row.painter_id)));
  ((snapshot.repaint || {}).details || []).forEach((row) => ids.add(String(row.painter_id)));
  ((snapshot.repaint || {}).contributions || []).forEach((row) => { if (row.dimension === 'painter') ids.add(String(row.label)); });
  ((snapshot.finesse || {}).summary || []).forEach((row) => ids.add(String(row.worker_id)));
  ((snapshot.finesse || {}).details || []).forEach((row) => ids.add(String(row.worker_id)));
  ['Unassigned', 'null', 'undefined', ''].forEach((value) => ids.delete(value));
  return Array.from(ids);
}

function namedSnapshot(snapshot) {
  const shared = {};
  Object.keys(rosterNames).forEach((id) => { shared[rosterNames[id]] = (shared[rosterNames[id]] || 0) + 1; });
  // Two IDs that share a name keep their ID in brackets so the charts never merge two people.
  const nameOf = (id) => {
    const name = rosterNames[String(id)];
    if (!name) return id;
    return shared[name] > 1 ? name + ' (' + String(id) + ')' : name;
  };
  const view = JSON.parse(JSON.stringify(snapshot));
  (view.painter_daily || []).forEach((row) => { row.painter_id = nameOf(row.painter_id); });
  if (view.repaint) {
    (view.repaint.details || []).forEach((row) => { row.painter_id = nameOf(row.painter_id); });
    (view.repaint.contributions || []).forEach((row) => { if (row.dimension === 'painter') row.label = nameOf(row.label); });
  }
  if (view.finesse) {
    (view.finesse.summary || []).forEach((row) => { row.worker_id = nameOf(row.worker_id); });
    (view.finesse.details || []).forEach((row) => { row.worker_id = nameOf(row.worker_id); });
  }
  return view;
}

async function loadNames(snapshot) {
  const missing = snapshotIds(snapshot).filter((id) => !rosterAsked[id]);
  if (!missing.length) return;
  const payload = await fetchJson('/api/roster?ids=' + encodeURIComponent(missing.join(',')));
  missing.forEach((id) => { rosterAsked[id] = true; });
  rosterNames = Object.assign({}, rosterNames, payload.people || {});
}

async function renderWithNames(snapshot) {
  if (namesOn) {
    try {
      await loadNames(snapshot);
    } catch (error) {
      namesOn = false;
      $('#names-toggle').checked = false;
      sessionStorage.removeItem('kpi-names');
      render(snapshot);
      setStatus('Names could not be loaded (' + error.message + ') so IDs are shown.', true);
      return;
    }
  }
  render(snapshot);
}

async function setNames(on) {
  if (busy || !activeSnapshot) { $('#names-toggle').checked = namesOn; return; }
  namesOn = Boolean(on) && namesAllowed;
  if (namesOn) sessionStorage.setItem('kpi-names', '1'); else sessionStorage.removeItem('kpi-names');
  setBusy(true);
  setStatus(namesOn ? 'Looking up names…' : 'Showing IDs…');
  try {
    await renderWithNames(activeSnapshot);
  } finally {
    setBusy(false);
  }
}

async function initNames() {
  try {
    const session = await fetchJson('/api/session');
    if (session && session.names_allowed) {
      namesAllowed = true;
      $('#names-toggle-label').hidden = false;
      if (sessionStorage.getItem('kpi-names') === '1') {
        namesOn = true;
        $('#names-toggle').checked = true;
      }
    }
  } catch (error) {
    // The public wallboard port has no sign-in route, so names simply stay off there.
  }
  offerNamesSignIn();
}

// Where names are not available (the open wallboard port) point the short list at the Windows sign-in page;
// the link's address lives in index.html and stays hidden on the sign-in site itself.
function offerNamesSignIn() {
  const link = $('#names-signin-link');
  if (!link || namesAllowed) return;
  const signIn = new URL(link.getAttribute('href'));
  if (signIn.origin !== location.origin) link.hidden = false;
}
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
// "Today" is the plant's day and the server owns it (/api/drilldown/health business_date, the same Central day BRAK and
// the emailed report use). A viewer's own computer clock is only a fallback for a server that does not report one.
const businessToday = () => businessDate || localDateISO();
const snapshotStamp = (value) => {
  const when = new Date(value);
  if (!Number.isFinite(when.getTime())) return 'time unavailable';
  try {
    return businessTimeZone
      ? when.toLocaleString(undefined, {timeZone: businessTimeZone, timeZoneName: 'short'})
      : when.toLocaleString();
  } catch (_) {
    return when.toLocaleString();
  }
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
  items.forEach((item) => legend.appendChild(chartLegendKey(item)));
  container.appendChild(legend);
  bindSeriesHighlight(container);
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
        const rect = svgNode('rect', {x: x, y: y + 4, width: segmentWidth, height: 22, fill: segment.color, stroke: '#fff', 'stroke-width': 1, 'data-series': segment.label});
        addTitle(rect, String(row.label || row.key || 'Unknown') + ' · ' + segment.label + ': ' + integer(amount));
        svg.appendChild(rect);
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
  const grouped = aggregate(rows, 'painter_id', ['pieces']).map((row) => ({label: row.key, pieces: row.pieces}));
  const total = sum(grouped, 'pieces');
  renderRankBars('#painter-share', grouped, 'pieces', 'label', palette.teal, (row) => {
    const share = total > 0 ? row.pieces * 100 / total : 0;
    return integer(row.pieces) + ' · ' + percent(share);
  });
}

function renderPainterBooth(rows) {
  const painters = Array.from(new Set(rows.map((row) => row.painter_id))).sort();
  const booths = Array.from(new Set(rows.map((row) => Number(row.booth || 0)))).sort((a, b) => a - b);
  const grouped = painters.map((painter) => {
    const item = {label: painter};
    booths.forEach((booth) => {
      item['booth_' + booth] = rows.filter((row) => row.painter_id === painter && Number(row.booth || 0) === booth)
        .reduce((total, row) => total + Number(row.pieces || 0), 0);
    });
    return item;
  }).sort((a, b) => booths.reduce((total, booth) => total + Number(b['booth_' + booth] || 0) - Number(a['booth_' + booth] || 0), 0));
  const segments = booths.map((booth, index) => ({field: 'booth_' + booth, label: booth ? 'Booth ' + booth : 'Booth unknown', color: seriesColors[index % seriesColors.length]}));
  renderStackedHorizontal('#painter-pieces', grouped, segments, {ariaLabel: 'Pieces painted by painter and booth'});
}

function renderPainterFty(rows) {
  const grouped = aggregate(rows, 'painter_id', ['fty_approved', 'fty_repair', 'fty_repaint', 'fty_pending'])
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

const plainId = (value) => value === null || value === undefined || value === '' ? '—' : String(value);

// ---------- unassigned handling ----------
// Rows with no painter or worker ID arrive as "Unassigned". Charts leave that category out and the
// footnote under each panel's charts states how many records were left out.
const isUnassigned = (value) => value === null || value === undefined || String(value).trim() === '' || String(value).trim().toLowerCase() === 'unassigned';

function unassignedCounts(rows, field, measures, reportDate) {
  const weekKeys = new Set(periodKeys('week', reportDate));
  const monthKeys = new Set(periodKeys('month', reportDate));
  const unassigned = rows.filter((row) => isUnassigned(row[field]) && row.date <= reportDate);
  const scopes = {
    day: unassigned.filter((row) => row.date === reportDate),
    weeks: unassigned.filter((row) => weekKeys.has(periodKey(row.date, 'week'))),
    months: unassigned.filter((row) => monthKeys.has(periodKey(row.date, 'month')))
  };
  const counts = {};
  Object.keys(scopes).forEach((scope) => {
    counts[scope] = {};
    Object.keys(measures).forEach((name) => { counts[scope][name] = sum(scopes[scope], measures[name]); });
  });
  return counts;
}

function renderUnassignedNote(selector, subject, counts, units) {
  const node = $(selector);
  if (!node) return;
  const noun = (amount, unit) => (Number(amount) === 1 && unit.singular ? unit.singular : unit.label);
  const describe = (scope) => units.map((unit) => integer(counts[scope][unit.name]) + ' ' + noun(counts[scope][unit.name], unit)).join(' on ');
  node.textContent = 'Unassigned ' + subject + ' (no ID recorded in QPTS) are left out of the charts above. Unassigned records found: '
    + describe('day') + ' on the selected day; ' + describe('weeks') + ' in the last 13 weeks; '
    + describe('months') + ' in the monthly view.';
}

// ---------- 13-week and monthly trend charts ----------
const OUTCOME_SERIES = [
  {field: 'approved', label: 'Approved', color: palette.green},
  {field: 'repaired', label: 'Repaired', color: palette.amber},
  {field: 'repaint', label: 'Repaint', color: palette.red},
  {field: 'pending', label: 'Pending', color: palette.gray}
];

function shiftMonth(monthKey, delta) {
  const parts = monthKey.split('-').map(Number);
  const index = parts[0] * 12 + (parts[1] - 1) + delta;
  return Math.floor(index / 12) + '-' + String(index % 12 + 1).padStart(2, '0');
}

function periodKeys(grain, reportDate) {
  const keys = [];
  if (grain === 'week') {
    const current = sundayStart(reportDate);
    for (let offset = 12; offset >= 0; offset -= 1) keys.push(shiftDate(current, -offset * 7));
    return keys;
  }
  const current = reportDate.slice(0, 7);
  const earliest = EARLIEST_REPORT_DATE.slice(0, 7);
  for (let offset = 12; offset >= 0; offset -= 1) {
    const key = shiftMonth(current, -offset);
    if (key >= earliest) keys.push(key);
  }
  return keys;
}

const periodKey = (dateText, grain) => grain === 'week' ? sundayStart(dateText) : dateText.slice(0, 7);

function periodLabel(key, grain) {
  if (grain === 'week') return dateLabel(key);
  return new Date(key + '-01T12:00:00').toLocaleDateString(undefined, {month: 'short', year: 'numeric'});
}

function periodIsOpen(key, grain, reportDate) {
  return grain === 'week' ? reportDate < shiftDate(key, 6) : reportDate.slice(0, 7) === key;
}

function periodMatrix(rows, grain, reportDate, entityField, fields) {
  const keys = periodKeys(grain, reportDate);
  const slots = new Map(keys.map((key, index) => [key, index]));
  const periods = keys.map((key) => {
    const totals = {};
    fields.forEach((field) => { totals[field] = 0; });
    return {key: key, totals: totals, entities: new Map()};
  });
  rows.forEach((row) => {
    const slot = slots.get(periodKey(row.date, grain));
    if (slot === undefined) return;
    const period = periods[slot];
    const entity = String(row[entityField] === undefined || row[entityField] === null ? 'Unassigned' : row[entityField]);
    if (!period.entities.has(entity)) {
      const bucket = {};
      fields.forEach((field) => { bucket[field] = 0; });
      period.entities.set(entity, bucket);
    }
    const bucket = period.entities.get(entity);
    fields.forEach((field) => {
      const amount = Number(row[field] || 0);
      bucket[field] += amount;
      period.totals[field] += amount;
    });
  });
  return periods;
}

function rankedEntities(periods, volumeField) {
  const totals = new Map();
  periods.forEach((period) => period.entities.forEach((bucket, entity) => {
    totals.set(entity, (totals.get(entity) || 0) + bucket[volumeField]);
  }));
  return Array.from(totals.entries())
    .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))
    .map((item) => item[0]);
}

function addTitle(node, text) {
  const title = svgNode('title');
  title.textContent = text;
  node.appendChild(title);
  return node;
}

function niceMax(value) {
  const exponent = Math.pow(10, Math.floor(Math.log10(Math.max(value, 1e-9) / 4)));
  const fraction = value / 4 / exponent;
  const nice = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((candidate) => candidate >= fraction - 1e-9) || 10;
  return nice * exponent * 4;
}

function drawAxes(svg, geometry, maximum, formatter, minimum) {
  const floor = minimum || 0;
  [0, 0.25, 0.5, 0.75, 1].forEach((fraction) => {
    const y = geometry.top + geometry.plotHeight * (1 - fraction);
    svg.appendChild(svgNode('line', {x1: geometry.left, y1: y, x2: geometry.width - geometry.right, y2: y, stroke: palette.grid, 'stroke-width': 1}));
    const label = svgNode('text', {x: geometry.left - 6, y: y + 4, 'text-anchor': 'end', class: 'axis-label'});
    label.textContent = formatter(floor + (maximum - floor) * fraction);
    svg.appendChild(label);
  });
}

function drawPeriodLabels(svg, geometry, periods, grain, reportDate) {
  const slot = geometry.plotWidth / periods.length;
  periods.forEach((period, index) => {
    const x = geometry.left + slot * index + slot / 2;
    const y = geometry.height - geometry.bottom + 18;
    const label = svgNode('text', {x: x, y: y, 'text-anchor': 'middle', class: 'axis-label'});
    label.textContent = periodLabel(period.key, grain) + (periodIsOpen(period.key, grain, reportDate) ? '*' : '');
    label.setAttribute('transform', 'rotate(-45 ' + x + ' ' + y + ')');
    svg.appendChild(label);
  });
}

function trendGeometry() {
  const width = 640;
  const height = 320;
  const left = 46;
  const right = 14;
  const top = 28;
  const bottom = 62;
  return {width: width, height: height, left: left, right: right, top: top, bottom: bottom, plotWidth: width - left - right, plotHeight: height - top - bottom};
}

function renderPeriodStack(container, spec) {
  clear(container);
  const periods = periodMatrix(spec.rows, spec.grain, spec.reportDate, spec.entityField, spec.fields);
  let series;
  if (spec.fixedSeries) {
    series = spec.fixedSeries.map((item) => ({name: item.field, label: item.label, color: item.color}));
  } else {
    const ranked = rankedEntities(periods, spec.volumeField);
    if (!ranked.length) {
      emptyState(container, 'No history is available yet.');
      return;
    }
    const visible = ranked.slice(0, 7);
    series = visible.map((name, index) => ({name: name, label: name, color: seriesColors[index % seriesColors.length]}));
    if (ranked.length > visible.length) series.push({name: 'Other', label: 'Other', color: palette.gray});
  }
  const visibleNames = new Set(series.map((item) => item.name));
  const data = periods.map((period) => {
    const item = {key: period.key, total: 0};
    series.forEach((entry) => { item[entry.name] = 0; });
    if (spec.fixedSeries) {
      series.forEach((entry) => {
        const amount = period.totals[entry.name] || 0;
        item[entry.name] = amount;
        item.total += amount;
      });
      return item;
    }
    period.entities.forEach((bucket, entity) => {
      const name = visibleNames.has(entity) ? entity : 'Other';
      const amount = spec.value(bucket);
      item[name] = (item[name] || 0) + amount;
      item.total += amount;
    });
    return item;
  });
  if (!data.some((item) => item.total > 0)) {
    emptyState(container, 'No history is available yet.');
    return;
  }
  const geometry = trendGeometry();
  const maximum = niceMax(Math.max.apply(null, data.map((item) => item.total).concat([1])) * 1.08);
  const slot = geometry.plotWidth / data.length;
  const barWidth = Math.max(10, slot * 0.64);
  const svg = svgNode('svg', {viewBox: '0 0 ' + geometry.width + ' ' + geometry.height, role: 'img', 'aria-label': spec.ariaLabel});
  drawAxes(svg, geometry, maximum, (value) => spec.axisFormat ? spec.axisFormat(value) : integer(value));
  data.forEach((item, index) => {
    const x = geometry.left + slot * index + (slot - barWidth) / 2;
    let y = geometry.top + geometry.plotHeight;
    series.forEach((entry) => {
      const amount = item[entry.name] || 0;
      const segmentHeight = amount * geometry.plotHeight / maximum;
      y -= segmentHeight;
      if (segmentHeight > 0) {
        const rect = svgNode('rect', {x: x, y: y, width: barWidth, height: segmentHeight, fill: entry.color, stroke: '#fff', 'stroke-width': 0.8, 'data-series': entry.label});
        addTitle(rect, entry.label + ' · ' + periodLabel(item.key, spec.grain) + ': ' + spec.format(amount));
        svg.appendChild(rect);
      }
    });
    if (item.total > 0) {
      const value = svgNode('text', {x: x + barWidth / 2, y: y - 5, 'text-anchor': 'middle', class: 'value-label'});
      value.textContent = spec.format(item.total);
      svg.appendChild(value);
    }
  });
  drawPeriodLabels(svg, geometry, periods, spec.grain, spec.reportDate);
  if (spec.trend && spec.grain === 'week') {
    const inputs = data.map((item, index) => periodIsOpen(item.key, spec.grain, spec.reportDate) && index === data.length - 1 ? null : item.total);
    const line = regression(inputs);
    if (line) {
      const points = line.map((value, index) => {
        if (value === null) return null;
        const x = geometry.left + slot * index + slot / 2;
        const y = geometry.top + geometry.plotHeight - Math.max(0, value) * geometry.plotHeight / maximum;
        return x + ',' + y;
      }).filter(Boolean).join(' ');
      svg.appendChild(svgNode('polyline', {points: points, fill: 'none', stroke: palette.navy, 'stroke-width': 2.5, 'stroke-dasharray': '6 4', 'data-series': 'Completed-period trend'}));
    }
  }
  container.appendChild(svg);
  const legend = series.map((entry) => ({label: entry.label, color: entry.color}));
  if (spec.trend && spec.grain === 'week') legend.push({label: 'Completed-period trend', color: palette.navy, line: true, dash: '6 4', width: 2.5});
  appendLegend(container, legend);
}

function renderPeriodLines(container, spec) {
  clear(container);
  const periods = periodMatrix(spec.rows, spec.grain, spec.reportDate, spec.entityField, spec.fields);
  const ranked = rankedEntities(periods, spec.volumeField).slice(0, 7);
  const overall = periods.map((period) => spec.rate(period.totals));
  const lines = ranked.map((entity, index) => ({
    label: entity,
    color: seriesColors[index % seriesColors.length],
    marker: CHART_SERIES_MARKERS[index % CHART_SERIES_MARKERS.length],
    values: periods.map((period) => period.entities.has(entity) ? spec.rate(period.entities.get(entity)) : null)
  }));
  const finite = lines.reduce((all, line) => all.concat(line.values), overall).filter((value) => value !== null && Number.isFinite(value));
  if (!finite.length) {
    emptyState(container, 'No history is available yet.');
    return;
  }
  const geometry = trendGeometry();
  const minimum = spec.axisMin ? spec.axisMin(finite) : 0;
  const maximum = Math.min(spec.maxCap || Infinity, niceMax(Math.max.apply(null, finite.concat([1])) * 1.08));
  const span = Math.max(maximum - minimum, 1e-9);
  const slot = geometry.plotWidth / periods.length;
  const svg = svgNode('svg', {viewBox: '0 0 ' + geometry.width + ' ' + geometry.height, role: 'img', 'aria-label': spec.ariaLabel});
  drawAxes(svg, geometry, maximum, (value) => spec.axisFormat ? spec.axisFormat(value) : decimal(value, 0), minimum);
  const pointAt = (index, value) => [geometry.left + slot * index + slot / 2, geometry.top + geometry.plotHeight - Math.min(span, Math.max(0, value - minimum)) * geometry.plotHeight / span];
  const drawLine = (label, color, values, dashed, width, marker) => {
    let segment = [];
    const flush = () => {
      if (segment.length > 1) {
        svg.appendChild(svgNode('polyline', {points: segment.map((point) => point.join(',')).join(' '), fill: 'none', stroke: color, 'stroke-width': width, 'stroke-dasharray': dashed ? '6 4' : 'none', 'stroke-linejoin': 'round', 'data-series': label}));
      }
      segment = [];
    };
    values.forEach((value, index) => {
      if (value === null || !Number.isFinite(value)) { flush(); return; }
      segment.push(pointAt(index, value));
    });
    flush();
    values.forEach((value, index) => {
      if (value === null || !Number.isFinite(value)) return;
      const point = pointAt(index, value);
      const mark = chartMarker(marker || 'circle', point[0], point[1], dashed ? 3.2 : 3.6, color);
      mark.setAttribute('data-series', label);
      addTitle(mark, label + ' · ' + periodLabel(periods[index].key, spec.grain) + ': ' + spec.format(value));
      svg.appendChild(mark);
    });
  };
  lines.forEach((line) => drawLine(line.label, line.color, line.values, false, 2, line.marker));
  drawLine(spec.overallLabel, palette.navy, overall, true, 2.8, 'circle');
  drawPeriodLabels(svg, geometry, periods, spec.grain, spec.reportDate);
  container.appendChild(svg);
  const legend = lines.map((line) => ({label: line.label, color: line.color, line: true, marker: line.marker}));
  legend.push({label: spec.overallLabel, color: palette.navy, line: true, dash: '6 4', width: 2.8, marker: 'circle'});
  appendLegend(container, legend);
}

function trendCard(grid, title, note) {
  const figure = document.createElement('figure');
  figure.className = 'chart-card';
  const caption = document.createElement('figcaption');
  caption.textContent = title;
  const small = document.createElement('small');
  small.textContent = note;
  caption.appendChild(small);
  const chart = document.createElement('div');
  chart.className = 'chart';
  figure.append(caption, chart);
  grid.appendChild(figure);
  return chart;
}

function renderTrendMetrics(gridSelector, rows, reportDate, metrics) {
  const grid = $(gridSelector);
  clear(grid);
  metrics.forEach((metric) => {
    [['week', 'Last 13 weeks', 'Sunday–Saturday weeks; * is in progress'], ['month', 'Monthly', 'Calendar months since 2026-09-08; * is in progress']].forEach((entry) => {
      const chart = trendCard(grid, metric.title + ' · ' + entry[1], entry[2]);
      const spec = Object.assign({rows: rows, grain: entry[0], reportDate: reportDate, ariaLabel: metric.title + ', ' + entry[1].toLowerCase()}, metric.spec);
      (metric.kind === 'stack' ? renderPeriodStack : renderPeriodLines)(chart, spec);
    });
  });
}

function renderTrends(snapshot) {
  const reportDate = snapshot.report_date;
  const painterRows = (snapshot.painter_daily || []).filter((row) => row.date <= reportDate && !isUnassigned(row.painter_id));
  const finesseRows = ((snapshot.finesse && snapshot.finesse.summary) || []).filter((row) => row.date <= reportDate && !isUnassigned(row.worker_id)).map((row) => {
    const timed = row.average_minutes_per_part !== null && row.average_minutes_per_part !== undefined;
    return Object.assign({}, row, {
      timed_parts: timed ? Number(row.parts || 0) : 0,
      weighted_minutes: timed ? Number(row.average_minutes_per_part) * Number(row.parts || 0) : 0,
      approved: row.outcome === 'approved' ? Number(row.parts || 0) : 0,
      repaired: row.outcome === 'repaired' ? Number(row.parts || 0) : 0,
      repaint: row.outcome === 'repaint' ? Number(row.parts || 0) : 0,
      pending: row.outcome === 'pending' ? Number(row.parts || 0) : 0
    });
  });
  renderTrendMetrics('#painter-trends', painterRows, reportDate, [
    {title: 'Pieces painted', kind: 'stack', spec: {entityField: 'painter_id', fields: ['pieces'], volumeField: 'pieces', value: (b) => b.pieces, format: integer, trend: true}},
    {title: 'Carts painted', kind: 'stack', spec: {entityField: 'painter_id', fields: ['carts'], volumeField: 'carts', value: (b) => b.carts, format: integer}},
    {title: 'Painter-hours', kind: 'stack', spec: {entityField: 'painter_id', fields: ['minutes'], volumeField: 'minutes', value: (b) => b.minutes / 60, format: (value) => decimal(value, 1)}},
    {title: 'Pieces per painter-hour', kind: 'lines', spec: {entityField: 'painter_id', fields: ['pieces', 'minutes'], volumeField: 'pieces', rate: (b) => b.minutes > 0 ? b.pieces * 60 / b.minutes : null, format: (value) => decimal(value, 1), overallLabel: 'All painters'}},
    {title: 'First-time yield', kind: 'lines', spec: {entityField: 'painter_id', fields: ['fty_approved', 'fty_total'], volumeField: 'fty_total', rate: (b) => b.fty_total > 0 ? b.fty_approved * 100 / b.fty_total : null, format: percent, axisFormat: (value) => decimal(value, 0) + '%', maxCap: 100, axisMin: (values) => Math.max(0, Math.floor((Math.min.apply(null, values) - 5) / 10) * 10), overallLabel: 'All painters'}}
  ]);
  renderTrendMetrics('#repaint-trends', painterRows, reportDate, [
    {title: 'Repaint events by painter', kind: 'stack', spec: {entityField: 'painter_id', fields: ['fty_repaint'], volumeField: 'fty_repaint', value: (b) => b.fty_repaint, format: integer}},
    {title: 'Repaint rate by painter', kind: 'lines', spec: {entityField: 'painter_id', fields: ['fty_repaint', 'fty_total'], volumeField: 'fty_total', rate: (b) => b.fty_total > 0 ? b.fty_repaint * 100 / b.fty_total : null, format: percent, axisFormat: (value) => decimal(value, 1) + '%', overallLabel: 'All painters'}}
  ]);
  renderTrendMetrics('#finesse-trends', finesseRows, reportDate, [
    {title: 'Parts worked by worker', kind: 'stack', spec: {entityField: 'worker_id', fields: ['parts'], volumeField: 'parts', value: (b) => b.parts, format: integer}},
    {title: 'Average minutes per part', kind: 'lines', spec: {entityField: 'worker_id', fields: ['timed_parts', 'weighted_minutes'], volumeField: 'timed_parts', rate: (b) => b.timed_parts > 0 ? b.weighted_minutes / b.timed_parts : null, format: (value) => decimal(value, 1) + ' min', axisFormat: (value) => decimal(value, 0), overallLabel: 'All workers'}},
    {title: 'Outcome mix', kind: 'stack', spec: {entityField: 'outcome', fields: ['approved', 'repaired', 'repaint', 'pending'], volumeField: 'approved', fixedSeries: OUTCOME_SERIES, value: (b) => b.approved + b.repaired + b.repaint + b.pending, format: integer}}
  ]);
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
  const chartRows = rows.filter((row) => !isUnassigned(row.painter_id));
  const totalPieces = sum(rows, 'pieces');
  const totalCarts = sum(rows, 'carts');
  const totalMinutes = sum(rows, 'minutes');
  const ftyTotal = sum(rows, 'fty_total');
  const ftyApproved = sum(rows, 'fty_approved');
  const painters = new Set(rows.map((row) => row.painter_id)).size;
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
  renderPainterShare(chartRows);
  renderPainterBooth(chartRows);
  renderPainterFty(chartRows);
  renderUnassignedNote('#painter-footnote', 'painters', unassignedCounts(allRows, 'painter_id', {pieces: 'pieces', carts: 'carts'}, snapshot.report_date), [{name: 'pieces', label: 'pieces', singular: 'piece'}, {name: 'carts', label: 'carts', singular: 'cart'}]);
  renderTable('#painter-table', [
    {key: 'painter_id', label: personLabel('Painter'), format: plainId},
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
    const rows = contributions.filter((row) => row.dimension === dimension && !(dimension === 'painter' && isUnassigned(row.label))).map((row) => ({
      label: row.label,
      repaint_events: row.repaint_events,
      contribution_percent: row.contribution_percent
    }));
    renderRankBars('#repaint-' + dimension, rows, 'repaint_events', 'label', dimension === 'painter' ? palette.red : dimension === 'color' ? palette.amber : palette.purple, (row) => integer(row.repaint_events) + ' · ' + percent(row.contribution_percent));
  });
  const painterHistory = snapshot.painter_daily || [];
  const repaintCounts = unassignedCounts(painterHistory, 'painter_id', {events: 'fty_repaint'}, snapshot.report_date);
  const dayUnassigned = contributions.filter((row) => row.dimension === 'painter' && isUnassigned(row.label)).reduce((total, row) => total + Number(row.repaint_events || 0), 0);
  repaintCounts.day.events = Math.max(repaintCounts.day.events, dayUnassigned);
  renderUnassignedNote('#repaint-footnote', 'painters', repaintCounts, [{name: 'events', label: 'repaint events', singular: 'repaint event'}]);
  const details = (snapshot.repaint && snapshot.repaint.details ? snapshot.repaint.details : [])
    .filter((row) => !row.event_at || row.event_at.slice(0, 10) === snapshot.report_date);
  renderTable('#repaint-table', [
    {key: 'event_at', label: 'Time', format: timeLabel},
    {key: 'part_id', label: 'Part ID', format: plainId},
    {key: 'part_number', label: 'Part number'},
    {key: 'sequence', label: 'Sequence'},
    {key: 'color', label: 'Color'},
    {key: 'painter_id', label: personLabel('Painter'), format: plainId},
    {key: 'booth', label: 'Booth', format: (value) => value ? 'Booth ' + integer(value) : 'Unknown'},
    {key: 'repaint_loop_count', label: 'Loops', format: integer},
    {key: 'defect', label: 'Defect'}
  ], details, 'No repaint-loop detail is available for the selected day.');
}

function renderFinesse(snapshot) {
  const allSummary = snapshot.finesse && snapshot.finesse.summary ? snapshot.finesse.summary : [];
  const summary = allSummary.filter((row) => row.date === snapshot.report_date && !isUnassigned(row.worker_id));
  const workers = Array.from(new Set(summary.map((row) => row.worker_id))).sort();
  const outcomes = ['approved', 'repaired', 'repaint', 'pending'];
  const grouped = workers.map((worker) => {
    const item = {label: worker};
    outcomes.forEach((outcome) => {
      item[outcome] = summary.filter((row) => row.worker_id === worker && row.outcome === outcome).reduce((total, row) => total + Number(row.parts || 0), 0);
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
    const rows = summary.filter((row) => row.worker_id === worker && row.average_minutes_per_part !== null);
    const parts = sum(rows, 'parts');
    const weightedMinutes = rows.reduce((total, row) => total + Number(row.average_minutes_per_part || 0) * Number(row.parts || 0), 0);
    return {label: worker, minutes: parts > 0 ? weightedMinutes / parts : 0};
  });
  renderRankBars('#finesse-time', timeRows, 'minutes', 'label', palette.blue, (row) => decimal(row.minutes, 1) + ' min');
  renderUnassignedNote('#finesse-footnote', 'Finesse workers', unassignedCounts(allSummary, 'worker_id', {parts: 'parts'}, snapshot.report_date), [{name: 'parts', label: 'parts', singular: 'part'}]);
  const details = (snapshot.finesse && snapshot.finesse.details ? snapshot.finesse.details : [])
    .filter((row) => !row.event_at || row.event_at.slice(0, 10) === snapshot.report_date);
  renderTable('#finesse-table', [
    {key: 'event_at', label: 'Time', format: timeLabel},
    {key: 'part_id', label: 'Part ID', format: plainId},
    {key: 'part_number', label: 'Part number'},
    {key: 'sequence', label: 'Sequence'},
    {key: 'color', label: 'Color'},
    {key: 'worker_id', label: personLabel('Worker'), format: plainId},
    {key: 'outcome', label: 'Outcome'},
    {key: 'minutes_per_part', label: 'Min / part', format: (value) => decimal(value, 1)},
    {key: 'repaint_count', label: 'Repaint count', format: integer}
  ], details, 'No finesse part detail is available for the selected day.');
}

// ---------- assembly production: counts by work center and operator ----------
// Counts only. QPTS records the operator who finished each piece (AssembledLogin) and the workstation it was built at
// (GPAssyLogin, the work center), but not when a build started, so no assembly time is shown here yet.
// Operator rows are served only after Windows sign-in; the open wallboard port receives an empty list and a note.
const NO_OPERATOR_LABEL = 'No operator recorded';
const NO_WORK_CENTER_LABEL = 'No work center recorded';
const ASSEMBLY_UNAVAILABLE = 'Assembly counts are not available for this snapshot.';
const ASSEMBLY_NOTE = 'Counts only: pieces assembled, and the N71-6171 bumpers among them. QPTS records the operator who finished each piece and the work center (workstation) it was built at, but not when a build started, so no assembly time is shown yet. Weeks run Sunday\u2013Saturday; * marks the week in progress. Days active counts days with at least one piece.';

function assemblyAvailable(snapshot) {
  const section = snapshot.assembly;
  return section && section.available !== false && Array.isArray(section.work_centers) ? section : null;
}

const assemblyLabel = (entity, emptyLabel) => entity.key === null || entity.key === undefined || entity.key === '' ? emptyLabel : String(entity.key);

function assemblyTrendRows(entities, weeks, emptyLabel) {
  const rows = [];
  entities.forEach((entity) => {
    entity.weeks.forEach((week, index) => {
      rows.push({date: weeks[index], entity: assemblyLabel(entity, emptyLabel), pieces: Number(week.pieces || 0)});
    });
  });
  return rows;
}

function assemblyColumns(firstLabel, section, reportDate) {
  const columns = [
    {key: 'label', label: firstLabel, format: plainId},
    {key: 'day_pieces', label: 'Selected day', format: integer},
    {key: 'day_bumpers', label: 'Bumpers (day)', format: integer}
  ];
  section.weeks.forEach((week, index) => {
    columns.push({key: 'week' + index, label: 'Wk ' + dateLabel(week) + (periodIsOpen(week, 'week', reportDate) ? '*' : ''), format: integer});
  });
  columns.push(
    {key: 'total_pieces', label: '13-wk pieces', format: integer},
    {key: 'total_bumpers', label: '13-wk bumpers', format: integer},
    {key: 'days', label: 'Days active', format: integer},
    {key: 'daily_average', label: 'Avg / active day', format: (value) => decimal(value, 1)}
  );
  return columns;
}

function assemblyTableRows(entities, emptyLabel, totals, totalLabel) {
  const rows = entities.map((entity) => {
    const row = {
      label: assemblyLabel(entity, emptyLabel),
      day_pieces: entity.day.pieces,
      day_bumpers: entity.day.bumpers,
      total_pieces: entity.total.pieces,
      total_bumpers: entity.total.bumpers,
      days: entity.total.days,
      daily_average: entity.total.daily_average
    };
    entity.weeks.forEach((week, index) => { row['week' + index] = week.pieces; });
    return row;
  });
  const all = {
    label: totalLabel,
    day_pieces: totals.day.pieces,
    day_bumpers: totals.day.bumpers,
    total_pieces: sum(totals.weeks, 'pieces'),
    total_bumpers: sum(totals.weeks, 'bumpers'),
    days: null,
    daily_average: null
  };
  totals.weeks.forEach((week, index) => { all['week' + index] = week.pieces; });
  rows.push(all);
  return rows;
}

function renderAssemblyDay(selector, entities, emptyLabel) {
  const rows = entities.filter((entity) => entity.day.pieces > 0).map((entity) => ({label: assemblyLabel(entity, emptyLabel), pieces: entity.day.pieces, bumpers: entity.day.bumpers}));
  if (!rows.length) {
    emptyState($(selector), 'No pieces were assembled on the selected day.');
    return;
  }
  renderRankBars(selector, rows, 'pieces', 'label', palette.blue, (row) => integer(row.pieces) + (row.bumpers ? ' (' + integer(row.bumpers) + (Number(row.bumpers) === 1 ? ' bumper)' : ' bumpers)') : ''));
}

function renderAssemblyTrend(selector, entities, section, emptyLabel, reportDate, ariaLabel) {
  renderPeriodStack($(selector), {
    rows: assemblyTrendRows(entities, section.weeks, emptyLabel),
    grain: 'week',
    reportDate: reportDate,
    entityField: 'entity',
    fields: ['pieces'],
    volumeField: 'pieces',
    value: (bucket) => bucket.pieces,
    format: integer,
    trend: true,
    ariaLabel: ariaLabel
  });
}

function renderAssembly(snapshot) {
  const section = assemblyAvailable(snapshot);
  const reportDate = snapshot.report_date;
  const kpis = $('#assembly-kpis');
  clear(kpis);
  const operatorWrap = $('#assembly-operator-wrap');
  const operatorNote = $('#assembly-operator-note');
  $('#assembly-footnote').textContent = ASSEMBLY_NOTE;
  if (!section) {
    ['#assembly-day-work-centers', '#assembly-day-operators', '#assembly-trend-work-centers', '#assembly-trend-operators'].forEach((selector) => emptyState($(selector), ASSEMBLY_UNAVAILABLE));
    renderTable('#assembly-work-center-table', [{key: 'label', label: 'Work center'}], [], ASSEMBLY_UNAVAILABLE);
    operatorWrap.hidden = true;
    operatorNote.hidden = true;
    return;
  }
  const totals = section.totals;
  const operators = (section.operators || []).filter((entity) => entity.key !== null);
  const operatorsSeen = operators.length;
  const activeOperators = operators.filter((entity) => entity.day.pieces > 0).length;
  const workCentersSeen = section.work_centers.filter((entity) => entity.key !== null).length;
  const activeWorkCenters = section.work_centers.filter((entity) => entity.key !== null && entity.day.pieces > 0).length;
  const thisWeek = totals.weeks[totals.weeks.length - 1] || {pieces: 0, bumpers: 0};
  [
    ['Pieces assembled', integer(totals.day.pieces), integer(totals.day.bumpers) + ' N71-6171 bumpers', palette.blue],
    ['Active work centers', integer(activeWorkCenters), 'of ' + integer(workCentersSeen) + ' used in 13 weeks', palette.teal],
    section.operators_visible
      ? ['Active operators', integer(activeOperators), 'of ' + integer(operatorsSeen) + ' recorded in 13 weeks', palette.purple]
      : ['Active operators', '\u2014', section.operators_note || 'Appear after Windows sign-in', palette.purple],
    ['This week so far', integer(thisWeek.pieces), integer(thisWeek.bumpers) + ' bumpers', palette.green],
    ['Last 13 weeks', integer(sum(totals.weeks, 'pieces')), integer(sum(totals.weeks, 'bumpers')) + ' bumpers', palette.amber]
  ].forEach((card) => kpis.appendChild(summaryCard(card[0], card[1], card[2], card[3])));
  renderAssemblyDay('#assembly-day-work-centers', section.work_centers, NO_WORK_CENTER_LABEL);
  renderAssemblyTrend('#assembly-trend-work-centers', section.work_centers, section, NO_WORK_CENTER_LABEL, reportDate, 'Pieces assembled by work center, last 13 weeks');
  renderTable('#assembly-work-center-table', assemblyColumns('Work center', section, reportDate), assemblyTableRows(section.work_centers, NO_WORK_CENTER_LABEL, totals, 'All work centers'), 'No assembly rows are available for this snapshot.');
  if (section.operators_visible) {
    renderAssemblyDay('#assembly-day-operators', section.operators, NO_OPERATOR_LABEL);
    renderAssemblyTrend('#assembly-trend-operators', section.operators, section, NO_OPERATOR_LABEL, reportDate, 'Pieces assembled by operator, last 13 weeks');
    renderTable('#assembly-operator-table', assemblyColumns('Operator', section, reportDate), assemblyTableRows(section.operators, NO_OPERATOR_LABEL, totals, 'All operators'), 'No assembly rows are available for this snapshot.');
    operatorWrap.hidden = false;
    operatorNote.hidden = true;
  } else {
    const note = section.operators_note || 'Operator rows appear after Windows sign-in.';
    emptyState($('#assembly-day-operators'), note);
    emptyState($('#assembly-trend-operators'), note);
    operatorWrap.hidden = true;
    operatorNote.hidden = false;
    operatorNote.textContent = note;
  }
}

function render(snapshot) {
  activeSnapshot = snapshot;
  const view = namesOn ? namedSnapshot(snapshot) : snapshot;
  $('#report-date').value = snapshot.report_date;
  $('#generated-at').textContent = 'Generated ' + snapshotStamp(snapshot.generated_at);
  renderPainter(view);
  renderRepaint(view);
  renderFinesse(view);
  renderAssembly(view);
  renderTrends(view);
  setStatus('Drill-down data loaded for ' + dateLabel(snapshot.report_date) + '.');
}

async function fetchJson(url, options) {
  const response = await fetch(url, Object.assign({cache: 'no-store'}, options || {}));
  const payload = await response.json().catch(() => ({error: 'The server returned an unreadable response.'}));
  if (!response.ok) {
    const failure = new Error(payload.error || 'Request failed with status ' + response.status + '.');
    failure.notFound = response.status === 404;
    throw failure;
  }
  return payload;
}

function requestRefresh(reportDate, force) {
  return fetchJson('/api/drilldown/refresh', {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Operations-KPI-Action': 'refresh'},
    body: JSON.stringify({report_date: reportDate, force: force})
  });
}

async function loadDate(reportDate) {
  if (busy) return;
  setBusy(true);
  setStatus('Loading drill-down snapshot…');
  try {
    let snapshot;
    try {
      snapshot = await fetchJson('/api/drilldown/snapshot?report_date=' + encodeURIComponent(reportDate));
    } catch (error) {
      if (!error.notFound) throw error;
      setStatus('Building drill-down data for ' + dateLabel(reportDate) + '…');
      snapshot = await requestRefresh(reportDate, false);
    }
    await renderWithNames(snapshot);
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
  setStatus('Refreshing drill-down data…');
  try {
    const snapshot = await requestRefresh(reportDate, true);
    await renderWithNames(snapshot);
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    setBusy(false);
  }
}

async function loadBusinessClock() {
  try {
    const health = await fetchJson('/api/drilldown/health');
    if (/^\d{4}-\d{2}-\d{2}$/.test(String(health.business_date || ''))) businessDate = health.business_date;
    if (typeof health.business_timezone === 'string' && health.business_timezone) businessTimeZone = health.business_timezone;
  } catch (_) {
    // Keep the last known plant day; with none, the date falls back to this computer's own.
  }
}

async function start() {
  await initNames();
  await loadBusinessClock();
  const dateInput = $('#report-date');
  dateInput.min = EARLIEST_REPORT_DATE;
  dateInput.max = businessToday();
  try {
    // Always open on today: the service's latest snapshot can be a past day another viewer browsed.
    const reportDate = businessToday();
    dateInput.value = reportDate;
    await loadDate(reportDate);
  } catch (error) {
    setStatus(error.message, true);
  }
}

$('#load-date').addEventListener('click', () => loadDate($('#report-date').value));
$('#refresh').addEventListener('click', refreshDate);
$('#names-toggle').addEventListener('change', (event) => setNames(event.target.checked));
$('#previous-day').addEventListener('click', () => {
  const value = shiftDate($('#report-date').value, -1);
  $('#report-date').value = value < EARLIEST_REPORT_DATE ? EARLIEST_REPORT_DATE : value;
  loadDate($('#report-date').value);
});
$('#next-day').addEventListener('click', async () => {
  await loadBusinessClock();
  const today = businessToday();
  const value = shiftDate($('#report-date').value, 1);
  $('#report-date').max = today;
  $('#report-date').value = value > today ? today : value;
  loadDate($('#report-date').value);
});
$('#today').addEventListener('click', async () => {
  await loadBusinessClock();
  const today = businessToday();
  $('#report-date').max = today;
  $('#report-date').value = today;
  loadDate($('#report-date').value);
});

start();
