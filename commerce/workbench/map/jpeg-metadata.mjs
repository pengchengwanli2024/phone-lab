// Strip descriptive JPEG metadata without decoding or recompressing pixels.
// JFIF and ICC color information remain intact.
export function stripJpegHeaderMetadata(input) {
  const bytes = Buffer.from(input);
  const invalid = () => { throw new Error('Invalid JPEG texture'); };
  if (bytes.length < 4 || bytes[0] !== 255 || bytes[1] !== 216) invalid();
  const kept = [bytes.subarray(0, 2)];
  for (let offset = 2; offset < bytes.length;) {
    if (bytes[offset] !== 255 || offset + 1 >= bytes.length) invalid();
    const marker = bytes[offset + 1];
    if (marker === 218 || marker === 217) {
      kept.push(bytes.subarray(offset)); return Buffer.concat(kept);
    }
    if (offset + 4 > bytes.length) invalid();
    const size = bytes.readUInt16BE(offset + 2), end = offset + 2 + size;
    if (size < 2 || end > bytes.length) invalid();
    if (![225, 237, 254].includes(marker)) kept.push(bytes.subarray(offset, end));
    offset = end;
  }
  invalid();
}
