import { createHash } from 'node:crypto';
import { expect, test } from 'vitest';
import { snapshotDigest } from '../../src/lib/snapshot-digest';
import { getData } from '../../src/lib/data';

test.each([
  {}, { items: [] }, { dataset: 'live', items: [{ text: 'Grüne — \n "exact"', nested: [null, false, 2] }] },
  { 'escaped"key': '🌍', items: [undefined, null, 0], omitted: undefined, enabled: false },
  { ...getData('demo') },
])('incremental snapshot digest is byte-compatible with the existing API hash', value => {
  expect(snapshotDigest(value)).toBe(createHash('sha256').update(JSON.stringify(value)).digest('hex'));
});

test('records are serialized in order, once per collection entry', () => {
  const order: number[] = [];
  const records = Array.from({ length: 100 }, (_, id) => ({ toJSON: () => { order.push(id); return { id }; } }));
  snapshotDigest({ records });
  expect(order).toEqual(Array.from({ length: 100 }, (_, id) => id));
});
