// Read-only MFS1 decoder. Keep the wire layout aligned with programming/mini_filesystem.py.
export const START = 0x220000;
export const END = 0x400000;
export const SECTOR = 0x10000;
// boards/basys3.toml: user_data_offset and filesystem_index_offset are distinct.
export const INDEX_START = 0x240000;
export const INDEX_OFFSET = INDEX_START - START;
export const DATA_START = INDEX_START + SECTOR;
export const PAGE = 256;
export const HEADER = 256;
export const RECORD = 64;
export const SLOTS = (SECTOR - HEADER) / RECORD;
export const TYPES = ['blob', 'text', 'font', 'scene'];
export const MAGIC = [0x4d, 0x46, 0x53, 0x31, 1, 64];
export const hex = (n) => `0x${n.toString(16).padStart(6, '0')}`;
export const bytesLabel = (n) => n < 1024 ? `${n} B` : `${(n / 1024).toFixed(n % 1024 ? 1 : 0)} KiB`;
const allErased = (bytes) => bytes.every(b => b === 255);
const u24 = (b, i) => b[i] + b[i + 1] * 256 + b[i + 2] * 65536;
const align = (n) => Math.ceil(n / PAGE) * PAGE;

export function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

export function parseImage(input) {
  const image = input instanceof Uint8Array ? input : new Uint8Array(input);
  let partition;
  if (image.length === END) partition = image.subarray(START);
  else if (image.length === END - START) partition = image;
  else throw new Error('Expected a 4 MiB full-flash dump or a 1,966,080-byte user-partition dump (0x220000–0x3fffff).');
  const index = partition.subarray(INDEX_OFFSET, INDEX_OFFSET + SECTOR);
  const blank = allErased(index);
  const recognized = MAGIC.every((b, i) => index[i] === b) && allErased(index.subarray(MAGIC.length, HEADER));
  const warnings = [];
  if (!recognized && !blank) warnings.push('Unrecognized index header. Blob ownership cannot be decoded safely.');
  const records = [];
  let usedSlots = 0;
  let nextSlot = 0;
  for (let slot = 0; slot < SLOTS; slot++) {
    const offset = HEADER + slot * RECORD;
    const raw = index.subarray(offset, offset + RECORD);
    const record = {slot, indexAddress: INDEX_START + offset, raw, state: 'erased'};
    if (!allErased(raw)) {
      usedSlots++;
      nextSlot = slot + 1;
      if (!recognized) record.state = 'unknown';
      else if (raw[63] !== 0) record.state = 'uncommitted';
      else {
        const storedCrc = new DataView(raw.buffer, raw.byteOffset, raw.byteLength).getUint32(58, true);
        record.crc = storedCrc;
        record.calculatedCrc = crc32(raw.subarray(0, 58));
        record.state = 'valid';
        record.errors = [];
        if (storedCrc !== record.calculatedCrc) record.errors.push('CRC32 mismatch');
        const nameLength = raw[55];
        if (nameLength > 32 || !allErased(raw.subarray(23 + Math.min(nameLength, 32), 55))) record.errors.push('Invalid filename length or padding');
        try { record.name = new TextDecoder('utf-8', {fatal: true}).decode(raw.subarray(23, 23 + Math.min(nameLength, 32))); }
        catch { record.name = '(invalid UTF-8)'; record.errors.push('Invalid UTF-8 filename'); }
        record.address = u24(raw, 17);
        record.length = u24(raw, 20);
        record.typeCode = raw[0];
        record.type = TYPES[raw[0]] ?? `type ${raw[0]}`;
        record.digest = Array.from(raw.subarray(1, 17), b => b.toString(16).padStart(2, '0')).join('');
        record.statusByte = raw[62];
        record.status = ({255: 'active', 253: 'superseded', 254: 'deleted'})[raw[62]] ?? 'unknown';
        const legacyRange = record.address >= START && record.address < INDEX_START && record.address + record.length <= INDEX_START;
        const dataRange = record.address >= DATA_START && record.address < END && record.address + record.length <= END;
        if (!legacyRange && !dataRange) record.errors.push('Blob outside data regions or overlapping index sector');
        if (record.errors.length) record.state = 'corrupt';
      }
    }
    records.push(record);
  }
  const entries = records.filter(r => r.state === 'valid');
  const latest = new Map();
  for (const entry of entries) if (entry.name) latest.set(entry.name, entry);
  for (const entry of entries) {
    entry.current = entry.status === 'active' && (!entry.name || latest.get(entry.name) === entry);
    entry.visibility = entry.current ? 'current' : entry.status === 'active' ? 'shadowed' : entry.status;
  }
  const blobs = new Map();
  for (const entry of entries) {
    const key = `${entry.address}:${entry.length}:${entry.digest}`;
    if (!blobs.has(key)) blobs.set(key, {key, address: entry.address, length: entry.length, entries: [], allocationEnd: Math.min(END, align(entry.address + entry.length))});
    blobs.get(key).entries.push(entry);
  }
  const sectors = Array.from({length: (END - START) / SECTOR}, (_, number) => {
    const address = START + number * SECTOR;
    return {number, address, kind: address === INDEX_START ? 'index' : address < INDEX_START ? 'legacy' : 'data', spans: [], referencedPages: 0, unreferencedPages: 0, erasedPages: 0};
  });
  for (const blob of blobs.values()) {
    // Empty files have no footprint, but remain selectable at their recorded address.
    const last = Math.floor((blob.address + Math.max(1, blob.length) - 1 - START) / SECTOR);
    const first = Math.floor((blob.address - START) / SECTOR);
    for (let s = first; s <= last; s++) {
      const sector = sectors[s];
      const from = Math.max(blob.address, sector.address);
      const to = Math.min(blob.address + blob.length, sector.address + SECTOR);
      sector.spans.push({blob, from, to, length: Math.max(0, to - from), part: s - first + 1, parts: last - first + 1});
    }
  }
  // Count physical pages once even for aliases and overlapping records. Erased
  // bytes alone cannot prove a page is available to the append-only allocator.
  const referenced = new Set();
  for (const blob of blobs.values()) {
    if (!blob.length) continue;
    for (let a = Math.floor(blob.address / PAGE) * PAGE; a < blob.allocationEnd; a += PAGE) referenced.add(a);
  }
  for (const sector of sectors.filter(s => s.kind !== 'index')) {
    sector.spans.sort((a, b) => a.from - b.from || a.blob.entries[0].slot - b.blob.entries[0].slot);
    for (let a = sector.address; a < sector.address + SECTOR; a += PAGE) {
      if (referenced.has(a)) sector.referencedPages++;
      else if (allErased(partition.subarray(a - START, a - START + PAGE))) sector.erasedPages++;
      else sector.unreferencedPages++;
    }
  }
  const corrupt = records.filter(r => r.state === 'corrupt').length;
  if (corrupt) warnings.push(`${corrupt} corrupt committed record${corrupt === 1 ? '' : 's'}; their blob locations are not trusted.`);
  const unknownStatus = entries.filter(r => r.status === 'unknown').length;
  if (unknownStatus) warnings.push(`${unknownStatus} record(s) have an unknown status byte.`);
  const overlaps = [...blobs.values()].filter(b => b.length).sort((a, b) => a.address - b.address);
  let high = START;
  for (const blob of overlaps) { if (blob.address < high) {warnings.push('Distinct blob records overlap. Inspect the journal before interpreting space usage.'); break;} high = Math.max(high, blob.address + blob.length); }
  return {partition, recognized, blank, records, entries, blobs: [...blobs.values()], sectors, usedSlots, nextSlot, warnings,
    currentFiles: entries.filter(e => e.current && e.name).length,
    referencedBytes: sectors.reduce((n, s) => n + s.referencedPages * PAGE, 0),
    unreferencedBytes: sectors.reduce((n, s) => n + s.unreferencedPages * PAGE, 0)};
}

export function makeDemoImage(spec) {
  const image = new Uint8Array(END - START).fill(255);
  image.set(MAGIC, INDEX_OFFSET);
  for (const segment of spec.segments) image.fill(segment.fill, segment.address - START, segment.address - START + segment.length);
  for (const record of spec.records) image.set(Uint8Array.from(record.hex.match(/../g), b => parseInt(b, 16)), INDEX_OFFSET + HEADER + record.slot * RECORD);
  return image;
}
