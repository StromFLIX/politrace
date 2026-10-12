import { createHash } from 'node:crypto';

/** Same bytes as JSON.stringify for a plain, JSON-safe data snapshot, without
 * allocating another corpus-sized UTF-16 string and UTF-8 buffer. Records in
 * top-level collections are serialized one at a time, preserving key order. */
export function snapshotDigest(snapshot: Record<string, unknown>) {
  const hash = createHash('sha256');
  hash.update('{');
  let separator = '';
  for (const [key, value] of Object.entries(snapshot)) {
    if (value === undefined) continue;
    hash.update(`${separator}${JSON.stringify(key)}:`);
    separator = ',';
    if (Array.isArray(value)) {
      hash.update('[');
      for (let index = 0; index < value.length; index++) {
        if (index) hash.update(',');
        hash.update(JSON.stringify(value[index]) ?? 'null');
      }
      hash.update(']');
    } else {
      hash.update(JSON.stringify(value));
    }
  }
  hash.update('}');
  return hash.digest('hex');
}
