import test from 'node:test';
import assert from 'node:assert/strict';
import { stripJpegHeaderMetadata } from '../map/jpeg-metadata.mjs';

const segment = (marker, text) => {
  const data = Buffer.from(text), header = Buffer.from([255, marker, 0, 0]);
  header.writeUInt16BE(data.length + 2, 2); return Buffer.concat([header, data]);
};
test('map textures omit descriptive metadata and preserve coded image bytes', () => {
  const image = Buffer.from([255, 218, 0, 2, 3, 4, 255, 0, 5, 255, 217]);
  const kept = [Buffer.from([255, 216]), segment(224, 'JFIF'), segment(226, 'ICC'), segment(219, 'coding')];
  const input = Buffer.concat([...kept.slice(0, 2), segment(225, 'Exif synthetic fixture'), segment(237, 'IPTC fixture'), segment(254, 'comment'), ...kept.slice(2), image]);
  assert.deepEqual(stripJpegHeaderMetadata(input), Buffer.concat([...kept, image]));
  assert.deepEqual(stripJpegHeaderMetadata(stripJpegHeaderMetadata(input)), Buffer.concat([...kept, image]));
});
test('invalid texture headers fail rather than exporting a corrupt image', () => {
  for (const bytes of [Buffer.from('invalid'), Buffer.from([255,216,255,225,0,1]), Buffer.from([255,216,255,225,0,20,1])]) {
    assert.throws(() => stripJpegHeaderMetadata(bytes), /Invalid JPEG texture/);
  }
});
