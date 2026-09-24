export async function sectionImage(endpoint, result, signal) {
  const response = await fetch(`${endpoint}/api/revisions/${result.revision}/sections/${result.section_id}/section.png`, {
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000),
  });
  if (!response.ok || !response.headers.get('content-type')?.startsWith('image/png')) {
    await response.body?.cancel();
    throw Error(`Section image unavailable (HTTP ${response.status})`);
  }
  const reader = response.body.getReader(), chunks = [];
  let size = 0;
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    size += value.length;
    if (size > 4 * 1024 * 1024) {
      await reader.cancel();
      throw Error('Section PNG exceeds 4 MiB');
    }
    chunks.push(value);
  }
  const image = Buffer.concat(chunks);
  if (image.length < 24 || !image.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10])) ||
      !image.readUInt32BE(16) || !image.readUInt32BE(20) || image.readUInt32BE(16) > 4096 || image.readUInt32BE(20) > 4096)
    throw Error('Invalid or oversized section PNG');
  return {type:'image', mimeType:'image/png', data:image.toString('base64')};
}
