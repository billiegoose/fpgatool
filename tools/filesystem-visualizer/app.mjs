import {parseImage, makeDemoImage, START, SECTOR, PAGE, SLOTS, hex, bytesLabel} from './filesystem.mjs?v=mfs240000';

const $ = (id) => document.getElementById(id);
const grid = $('sector-grid');
const inspector = $('inspector');
let model, anchor, request = 0;
let demoSpec;
let captureBusy = false;
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) {
    if (tag === 'button') node.append(el('span', 'button-label', text));
    else node.textContent = text;
  }
  return node;
}
function reportError(error) { $('error').textContent = error.message; $('error').hidden = false; }
function download(bytes, name) {
  const url = URL.createObjectURL(new Blob([bytes], {type: 'application/octet-stream'}));
  const link = el('a'); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function acceptImage(bytes, name, demo = false) {
  const parsed = parseImage(bytes); // Keep the last good image when a load fails.
  closeInspector(false);
  model = parsed;
  $('error').hidden = true;
  $('capture-status').hidden = true;
  $('source-name').textContent = name;
  $('source-name').title = name;
  $('source-kind').textContent = demo ? 'SYNTHETIC DEMO / not a board capture' : `${bytesLabel(bytes.length)} / local dump`;
  $('file-count').textContent = model.recognized ? model.currentFiles : '--';
  $('data-count').textContent = bytesLabel(model.referencedBytes);
  $('journal-count').textContent = `${model.usedSlots} / ${SLOTS}`;
  $('journal-detail').textContent = `${SLOTS - model.nextSlot} appendable slots`;
  const notes = [];
  if (demo) notes.push('SYNTHETIC DEMO / Shared blobs, history, spanning files, and interrupted writes.');
  if (model.blank) notes.push('The index is erased; no named files can be resolved.');
  notes.push(...model.warnings);
  $('notice').textContent = notes.join(' ');
  $('notice').hidden = !notes.length;
  $('search').value = '';
  renderMap();
}
async function loadDemo() {
  if (captureBusy) return;
  const token = ++request;
  try {
    if (!demoSpec) {
      const response = await fetch('./demo.json', {cache: 'no-store'});
      if (!response.ok) throw new Error('Could not load the demo fixture. Serve this folder with a local HTTP server.');
      demoSpec = await response.json();
    }
    if (token === request) acceptImage(makeDemoImage(demoSpec), 'Amber / sample flash', true);
  } catch (error) { if (token === request) reportError(error); }
}
async function openFile(file) {
  if (!file || captureBusy) return;
  const token = ++request;
  try {
    if (![0x400000, 0x1e0000].includes(file.size)) throw new Error('Open a 4 MiB full-flash dump or a 1,966,080-byte user-partition dump.');
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (token === request) acceptImage(bytes, file.name);
  } catch (error) { if (token === request) reportError(error); }
}

async function captureRequest(path, options) {
  const response = await fetch(path, {cache: 'no-store', ...options});
  if (!response.headers.get('content-type')?.includes('application/json')) {
    throw new Error('Read flash needs the local backend. Start .venv/bin/python tools/filesystem-visualizer/server.py');
  }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Flash capture request failed');
  return result;
}
async function readFlash() {
  if (captureBusy) return;
  captureBusy = true;
  const token = ++request;
  $('error').hidden = true;
  $('demo-button').disabled = true;
  $('read-flash').disabled = true;
  $('dump-input').disabled = true;
  const picker = document.querySelector('.file-button');
  picker.setAttribute('aria-disabled', 'true');
  picker.tabIndex = -1;
  const status = $('capture-status');
  status.hidden = false;
  status.replaceChildren(el('span', '', 'Connecting to the board…'));
  const progress = el('progress');
  progress.max = 1; progress.value = 0;
  progress.setAttribute('aria-label', 'Flash capture progress');
  const message = el('span');
  try {
    let job = await captureRequest('/api/dump', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    while (job.state === 'reading') {
      message.textContent = `Reading flash / ${bytesLabel(job.bytesRead)} of ${bytesLabel(job.totalBytes)} / ${Math.floor(job.bytesRead / job.totalBytes * 100)}%`;
      progress.value = job.bytesRead / job.totalBytes;
      status.replaceChildren(message, progress);
      await new Promise(resolve => setTimeout(resolve, 500));
      job = await captureRequest(`/api/dump/${job.id}`);
    }
    if (job.state !== 'complete') throw new Error(job.error || 'Flash capture failed');
    status.replaceChildren(el('span', '', 'Loading captured flash…'));
    const response = await fetch(`/api/dump/${job.id}/image`, {cache: 'no-store'});
    if (!response.ok) throw new Error('Could not load the completed flash capture');
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (token === request) {
      acceptImage(bytes, job.fileName);
      $('source-kind').textContent = `${bytesLabel(bytes.length)} / board capture`;
      status.hidden = false;
      status.replaceChildren(el('span', '', 'Flash capture complete / saved and loaded'));
    }
  } catch (error) {
    status.hidden = true;
    reportError(error);
  } finally {
    captureBusy = false;
    $('demo-button').disabled = false;
    $('read-flash').disabled = false;
    $('dump-input').disabled = false;
    picker.removeAttribute('aria-disabled');
    picker.tabIndex = 0;
  }
}

function usageMeter(sector) {
  const meter = el('div', 'usage-meter');
  const reference = el('i'); reference.style.width = `${sector.referencedPages / 256 * 100}%`;
  const unowned = el('i', 'unowned'); unowned.style.width = `${sector.unreferencedPages / 256 * 100}%`;
  meter.append(reference, unowned);
  meter.setAttribute('aria-label', `${sector.referencedPages} referenced pages; ${sector.unreferencedPages} unreferenced programmed pages; ${sector.erasedPages} erased pages`);
  return meter;
}
function renderMap() {
  grid.replaceChildren();
  for (const sector of model.sectors) {
    const panel = el('article', `sector${sector.kind === 'index' ? ' is-index' : ''}`);
    panel.dataset.sector = sector.number;
    panel.dataset.kind = sector.kind;
    const heading = el('div', 'sector-heading');
    heading.append(el('h3', '', `SECTOR ${String(sector.number).padStart(2, '0')}`), el('small', '', hex(sector.address)));
    panel.append(heading);
    if (sector.kind === 'index') renderIndex(panel);
    else renderDataSector(panel, sector);
    grid.append(panel);
  }
  applySearch();
}
function renderIndex(panel) {
  const stack = el('div', 'file-stack index-stack');
  const title = el('div', 'index-banner', model.recognized ? 'MFS1 / INDEX' : model.blank ? 'ERASED INDEX' : 'UNKNOWN INDEX');
  title.append(el('small', '', '256 B header + 1,020 journal slots'));
  stack.append(title);
  const categories = [
    ['valid', 'Committed', false], ['uncommitted', 'Uncommitted', false], ['corrupt', 'Corrupt', true], ['unknown', 'Unknown', true],
  ];
  for (const [state, label, alert] of categories) {
    const records = model.records.filter(r => r.state === state);
    if (!records.length) continue;
    const button = el('button', `index-button${alert ? ' alert' : ''}`);
    button.append(el('span', 'button-label', label), el('span', 'button-label', records.length));
    button.addEventListener('click', () => showJournal(button, records, label));
    stack.append(button);
  }
  if (!model.usedSlots) stack.append(el('div', 'erased-space sparse', 'No records'));
  const foot = el('div', 'sector-foot');
  const meter = el('div', 'usage-meter'); const fill = el('i'); fill.style.width = `${model.nextSlot / SLOTS * 100}%`; meter.append(fill);
  foot.append(meter, el('span', '', `${model.usedSlots} slots used`));
  panel.append(stack, foot);
}
function renderDataSector(panel, sector) {
  const stack = el('div', 'file-stack');
  if (sector.kind === 'legacy') stack.append(el('div', 'legacy-label', 'Preserved legacy assets'));
  for (const span of sector.spans) {
    const {blob} = span;
    const current = blob.entries.some(e => e.current);
    const names = [...new Set(blob.entries.map(e => e.name || '(unnamed)'))];
    const button = el('button', `file-entry${current ? '' : ' is-history'}`);
    button.dataset.key = blob.key;
    button.dataset.search = blob.entries.map(e => `${e.name} ${e.digest} ${e.type}`).join(' ').toLocaleLowerCase();
    // The basis is a share of the usable stack; labels establish a floor. Items
    // shrink towards that floor, then the sector scrolls instead of clipping text.
    const minimum = 64 + (names.length - 1) * 27;
    button.style.flexBasis = `${span.length / SECTOR * 100}%`;
    button.style.minHeight = `${minimum}px`;
    button.style.maxHeight = `max(${minimum}px, ${span.length / SECTOR * 100}%)`;
    button.title = `${names.join(', ')} — ${bytesLabel(span.length)} in this sector`;
    const labels = el('div');
    for (const name of names) labels.append(el('span', 'filename', name));
    const detail = el('span', 'entry-detail');
    detail.append(el('span', '', span.parts > 1 ? `PART ${span.part}/${span.parts}` : current ? blob.entries.find(e => e.current).type.toUpperCase() : 'HISTORY'), el('span', '', `${(span.length / SECTOR * 100).toFixed(1)}%`));
    button.append(labels, detail);
    button.addEventListener('click', () => showBlob(button, span));
    stack.append(button);
  }
  if (sector.unreferencedPages) {
    const unowned = el('div', 'unreferenced', 'Unreferenced data');
    unowned.append(el('small', '', `${bytesLabel(sector.unreferencedPages * PAGE)} / programmed pages`));
    stack.append(unowned);
  }
  if (sector.erasedPages) {
    const empty = el('div', `erased-space${!sector.spans.length && !sector.unreferencedPages ? ' sparse' : ''}`);
    empty.style.flexBasis = `${sector.erasedPages / 256 * 100}%`;
    if (!sector.spans.length && !sector.unreferencedPages) empty.append(el('span', 'empty-mark', '· · ·'));
    empty.append(el('span', '', `${bytesLabel(sector.erasedPages * PAGE)} erased`));
    stack.append(empty);
  }
  const foot = el('div', 'sector-foot');
  foot.append(usageMeter(sector), el('span', '', `${Math.round((sector.referencedPages + sector.unreferencedPages) / 256 * 100)}% occupied`));
  panel.append(stack, foot);
}
function applySearch() {
  const query = $('search').value.trim().toLocaleLowerCase();
  const matched = new Set();
  for (const button of grid.querySelectorAll('.file-entry')) {
    const match = query && button.dataset.search.includes(query);
    button.classList.toggle('is-match', !!match);
    button.classList.toggle('is-muted', !!query && !match);
    if (match) matched.add(button.dataset.key);
  }
  $('match-count').textContent = query ? `${matched.size} blobs` : '';
}
function setSelected(key) {
  for (const button of grid.querySelectorAll('.file-entry')) {
    const selected = button.dataset.key === key;
    button.classList.toggle('is-selected', selected);
    button.setAttribute('aria-expanded', String(selected));
  }
}
function positionInspector() {
  if (inspector.hidden || !anchor?.isConnected) return;
  const r = anchor.getBoundingClientRect();
  const w = inspector.offsetWidth;
  const h = inspector.offsetHeight;
  const rightRoom = window.innerWidth - r.right;
  let left = rightRoom >= w + 20 ? r.right + 10 : r.left - w - 10;
  if (left < 12) left = Math.min(window.innerWidth - w - 12, Math.max(12, r.left));
  inspector.style.left = `${Math.max(12, left)}px`;
  inspector.style.top = `${Math.max(12, Math.min(r.top, window.innerHeight - h - 12))}px`;
}
function openInspector(button, kicker) {
  anchor = button;
  $('inspector-kicker').textContent = kicker;
  inspector.hidden = false;
  positionInspector();
  $('close-inspector').focus({preventScroll: true});
}
function closeInspector(restoreFocus = true) {
  inspector.hidden = true;
  setSelected(null);
  if (restoreFocus && anchor?.isConnected) anchor.focus({preventScroll: true});
  anchor = null;
}
function metadata(rows) {
  const list = el('dl', 'metadata');
  for (const [name, value, className] of rows) {
    const row = el('div'); row.append(el('dt', '', name), el('dd', className, value)); list.append(row);
  }
  return list;
}
function rawDetails(record) {
  const details = el('details'); details.append(el('summary', '', 'Raw index record'));
  const lines = [];
  for (let i = 0; i < 64; i += 16) lines.push(`${i.toString(16).padStart(2, '0')}  ${Array.from(record.raw.subarray(i, i + 16), b => b.toString(16).padStart(2, '0')).join(' ')}`);
  details.append(el('pre', 'raw-record', lines.join('\n')));
  details.addEventListener('toggle', positionInspector);
  return details;
}
function recordMetadata(record) {
  const rows = [['Journal slot', `#${record.slot} / ${hex(record.indexAddress)}`], ['Status', record.status ? `${record.visibility || record.status} / 0x${record.statusByte.toString(16)}` : record.state], ['Commit', `0x${record.raw[63].toString(16).padStart(2, '0')}`]];
  if (record.type) rows.push(['Type', `${record.type} / ${record.typeCode}`], ['Blob address', hex(record.address)], ['File length', `${record.length.toLocaleString()} B`], ['Name bytes', `${record.raw[55]} / 32 UTF-8 bytes`], ['BLAKE2s-128', record.digest.match(/.{4}/g).join(' '), 'hash'], ['CRC32', record.crc.toString(16).padStart(8, '0') + (record.crc === record.calculatedCrc ? ' / valid' : ' / INVALID')]);
  return metadata(rows);
}
function showBlob(button, span, entry) {
  const blob = span.blob;
  entry ??= blob.entries.find(e => e.current) ?? blob.entries[0];
  setSelected(blob.key);
  const content = $('inspector-content'); content.replaceChildren();
  content.append(el('h3', '', entry.name || '(unnamed object)'), el('span', 'badge', `${entry.type.toUpperCase()} / ${entry.visibility.toUpperCase()}`), recordMetadata(entry));
  content.append(metadata([['This sector', `${bytesLabel(span.length)} / ${(span.length / SECTOR * 100).toFixed(2)}%`], ['Extent', span.parts > 1 ? `Part ${span.part} of ${span.parts} sectors` : 'Within one sector']]));
  if (blob.entries.length > 1) {
    content.append(el('h4', '', 'NAMES / INDEX REFERENCES'));
    const list = el('div', 'reference-list');
    for (const reference of blob.entries) {
      const refButton = el('button', reference === entry ? 'selected' : '', reference.name || '(unnamed)');
      refButton.append(el('small', '', `Slot ${reference.slot} / ${reference.visibility}`));
      refButton.addEventListener('click', () => showBlob(button, span, reference)); list.append(refButton);
    }
    content.append(list);
  }
  if (entry.type === 'text' && blob.length) {
    content.append(el('h4', '', 'TEXT PREVIEW / FIRST 512 B'));
    const data = model.partition.subarray(blob.address - START, blob.address - START + Math.min(512, blob.length));
    content.append(el('pre', 'preview', new TextDecoder().decode(data)));
  }
  content.append(rawDetails(entry));
  const save = el('button', 'download', 'Extract file');
  save.addEventListener('click', () => download(model.partition.slice(blob.address - START, blob.address - START + blob.length), entry.name.replaceAll(/[\/\\\u0000-\u001f]/g, '_') || `${entry.digest}.bin`));
  content.append(save, el('p', 'inspector-note', 'Record CRC checked. Payload content ID has not been recomputed.'));
  openInspector(button, 'INDEX METADATA');
}
function showJournal(button, records, label, selected) {
  setSelected(null);
  const content = $('inspector-content'); content.replaceChildren();
  content.append(el('h3', '', `${label} records`));
  content.append(el('p', 'inspector-note', 'Slots are shown in append order. Uncommitted slots are consumed and cannot be reused.'));
  if (selected) {
    content.append(el('h4', '', selected.name || `Slot ${selected.slot}`), recordMetadata(selected));
    if (selected.errors?.length) content.append(el('p', 'error', selected.errors.join('; ')));
    content.append(rawDetails(selected));
  }
  const list = el('div', 'reference-list');
  for (const record of records) {
    const item = el('button', selected === record ? 'selected' : '', `#${record.slot} / ${record.name || record.state}`);
    item.addEventListener('click', () => showJournal(button, records, label, record)); list.append(item);
  }
  content.append(list);
  openInspector(button, 'JOURNAL INSPECTOR');
}

$('demo-button').addEventListener('click', loadDemo);
$('read-flash').addEventListener('click', readFlash);
$('dump-input').addEventListener('change', e => { openFile(e.target.files[0]); e.target.value = ''; });
document.querySelector('.file-button').addEventListener('keydown', e => { if (['Enter', ' '].includes(e.key)) { e.preventDefault(); $('dump-input').click(); } });
$('search').addEventListener('input', applySearch);
$('close-inspector').addEventListener('click', () => closeInspector());
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !inspector.hidden) closeInspector(); });
document.addEventListener('pointerdown', e => { if (!inspector.hidden && !inspector.contains(e.target) && !anchor?.contains(e.target) && !e.target.closest('.file-entry, .index-button')) closeInspector(false); });
window.addEventListener('resize', positionInspector);
document.addEventListener('scroll', positionInspector, true);
let dragDepth = 0;
document.addEventListener('dragenter', e => { if (e.dataTransfer.types.includes('Files')) {e.preventDefault(); dragDepth++; $('drop-overlay').hidden = false;} });
document.addEventListener('dragover', e => { if (e.dataTransfer.types.includes('Files')) e.preventDefault(); });
document.addEventListener('dragleave', () => { if (--dragDepth <= 0) {dragDepth = 0; $('drop-overlay').hidden = true;} });
document.addEventListener('drop', e => { e.preventDefault(); dragDepth = 0; $('drop-overlay').hidden = true; openFile(e.dataTransfer.files[0]); });
loadDemo();
