import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {parseImage, makeDemoImage, crc32, START, END, SECTOR, PAGE, HEADER, RECORD, SLOTS, INDEX_START, INDEX_OFFSET, DATA_START} from './filesystem.mjs';

const spec = JSON.parse(readFileSync(new URL('./demo.json', import.meta.url)));
const demo = () => makeDemoImage(spec);
function changeRecord(image, slot, change) {
  const raw = image.subarray(INDEX_OFFSET + HEADER + slot * RECORD, INDEX_OFFSET + HEADER + (slot + 1) * RECORD);
  change(raw);
  new DataView(raw.buffer, raw.byteOffset, raw.byteLength).setUint32(58, crc32(raw.subarray(0, 58)), true);
}

test('browser fixture matches the actual Python host writer', () => {
  const result = spawnSync('python3', [fileURLToPath(new URL('./generate_demo.py', import.meta.url)), '--stdout'], {encoding: 'utf8'});
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), spec);
  const fs = parseImage(demo());
  assert.equal(fs.sectors.length, 30);
  assert.equal(fs.recognized, true);
  assert.equal(fs.currentFiles, 26);
  assert.equal(fs.entries.length, 28);
  assert.equal(fs.usedSlots, 30);
  assert.equal(fs.nextSlot, 30);
});
test('index location matches the board profile and preserves the two legacy sectors', () => {
  const board = readFileSync(new URL('../../boards/basys3.toml', import.meta.url), 'utf8');
  const indexAddress = Number(board.match(/^filesystem_index_offset\s*=\s*(0x[\da-f]+)/mi)[1]);
  assert.equal(INDEX_START, indexAddress);
  const fs = parseImage(demo());
  assert.deepEqual(fs.sectors.slice(0, 4).map(s => s.kind), ['legacy', 'legacy', 'index', 'data']);
  assert.equal(fs.records[0].indexAddress, 0x240100);
  assert.equal(fs.entries.find(e => e.name === 'boot-scene.bin').address, DATA_START);
  assert.equal(fs.sectors[0].spans[0].blob.entries[0].name, 'legacy-font.bin');
  assert.equal(fs.sectors[1].spans[0].blob.entries[0].name, 'legacy-scene.bin');
  assert.equal(fs.sectors[2].spans.length, 0);
  assert.equal(fs.warnings.some(w => /overlap/i.test(w)), false);
});
test('full flash and partition dumps yield identical locations', () => {
  const full = new Uint8Array(END).fill(255); full.set(demo(), START);
  const a = parseImage(full), b = parseImage(demo());
  assert.deepEqual(a.entries, b.entries);
  assert.equal(a.sectors[29].address, 0x3f0000);
  assert.throws(() => parseImage(new Uint8Array(1024)), /Expected/);
});
test('aliases share one footprint and history remains allocated', () => {
  const fs = parseImage(demo());
  const blob = fs.blobs.find(b => b.entries.some(e => e.name === 'red2-regular.bin'));
  assert.deepEqual(blob.entries.map(e => e.name), ['red2-regular.bin', 'red2-ui.bin']);
  assert.equal(blob.length, 4300);
  assert.equal(fs.entries.filter(e => e.name === 'boot-scene.bin' && e.current).length, 1);
  assert.equal(fs.blobs.filter(b => b.entries.some(e => e.name === 'boot-scene.bin')).length, 2);
  const expected = fs.blobs.reduce((n, b) => n + Math.ceil(b.length / PAGE) * PAGE, 0);
  assert.equal(fs.referencedBytes, expected);
});
test('spanning files are clipped per sector and sum to the blob length', () => {
  const fs = parseImage(demo());
  const spans = fs.sectors.flatMap(s => s.spans).filter(s => s.blob.entries.some(e => e.name === 'amber-components.bin'));
  assert.equal(spans.length, 3);
  assert.deepEqual(spans.map(s => s.part), [1, 2, 3]);
  assert.equal(spans[1].length, SECTOR);
  assert.equal(spans.reduce((n, s) => n + s.length, 0), 103180);
});
test('empty files are inspectable without allocating a page', () => {
  const fs = parseImage(demo());
  const empty = fs.sectors.flatMap(s => s.spans).filter(s => s.blob.entries.some(e => e.name === 'empty.txt'));
  assert.equal(empty.length, 1);
  assert.equal(empty[0].length, 0);
});
test('torn and corrupt records do not become files or stop the scan', () => {
  const fs = parseImage(demo());
  assert.equal(fs.records.filter(r => r.state === 'uncommitted').length, 1);
  const corrupt = fs.records.find(r => r.state === 'corrupt');
  assert.ok(corrupt.errors.includes('CRC32 mismatch'));
  assert.equal(fs.entries.some(e => e.name === 'damaged.txt'), false);
  assert.equal(fs.entries.some(e => e.name === 'recovery.txt'), true);
  assert.equal(fs.unreferencedBytes, 768);
});
test('latest named record wins even if superseding the old status was interrupted', () => {
  const image = demo();
  const first = parseImage(image).entries.find(e => e.name === 'boot-scene.bin');
  changeRecord(image, first.slot, raw => { raw[62] = 255; });
  const fs = parseImage(image);
  assert.equal(fs.entries.find(e => e.slot === first.slot).visibility, 'shadowed');
  assert.equal(fs.entries.filter(e => e.name === first.name && e.current).length, 1);
  const latest = fs.entries.filter(e => e.name === first.name).at(-1);
  changeRecord(image, latest.slot, raw => { raw[62] = 254; });
  assert.equal(parseImage(image).entries.filter(e => e.name === first.name && e.current).length, 0);
});
test('out-of-range blobs and invalid names are reported without trusting their addresses', () => {
  const image = demo();
  changeRecord(image, 0, raw => { raw.set([0, 0, 0], 17); });
  changeRecord(image, 1, raw => { raw[55] = 33; });
  changeRecord(image, 2, raw => { raw[23] = 0xc0; });
  const fs = parseImage(image);
  assert.ok(fs.records[0].errors.includes('Blob outside data regions or overlapping index sector'));
  assert.ok(fs.records[1].errors.includes('Invalid filename length or padding'));
  assert.ok(fs.records[2].errors.includes('Invalid UTF-8 filename'));
  assert.ok(fs.blobs.every(b => b.address >= START && (b.address < INDEX_START || b.address >= DATA_START)));
});
test('blob references cannot overlap, cross, or point inside the relocated index', () => {
  for (const [address, length] of [[INDEX_START, 1], [INDEX_START - 1, 2], [INDEX_START + 256, 0], [DATA_START - 1, 1], [START - 1, 1], [END - 1, 2]]) {
    const image = demo();
    changeRecord(image, 0, raw => {
      raw.set([address & 255, (address >>> 8) & 255, (address >>> 16) & 255], 17);
      raw.set([length & 255, (length >>> 8) & 255, (length >>> 16) & 255], 20);
    });
    assert.equal(parseImage(image).records[0].state, 'corrupt', `address ${address.toString(16)}, length ${length}`);
  }
});
test('unknown headers are not interpreted as MFS1 records', () => {
  const image = demo(); image[INDEX_OFFSET + 4] = 2;
  const fs = parseImage(image);
  assert.equal(fs.entries.length, 0);
  assert.equal(fs.records.filter(r => r.state === 'unknown').length, 30);
  assert.ok(fs.warnings.some(w => /Unrecognized/.test(w)));
  const blank = parseImage(new Uint8Array(END - START).fill(255));
  assert.equal(blank.blank, true);
  assert.equal(blank.nextSlot, 0);
  assert.equal(blank.sectors[1].erasedPages, 256);
});
test('journal holes below the append cursor are not reported as appendable', () => {
  const image = demo();
  image.fill(255, INDEX_OFFSET + HEADER + RECORD, INDEX_OFFSET + HEADER + 2 * RECORD);
  const fs = parseImage(image);
  assert.equal(fs.usedSlots, 29);
  assert.equal(fs.nextSlot, 30);
  // A fully consumed last slot makes the journal full even with earlier holes.
  image[INDEX_OFFSET + HEADER + (SLOTS - 1) * RECORD] = 1;
  assert.equal(parseImage(image).nextSlot, SLOTS);
});
