import { expect, test } from 'vitest';
import { jsonBody } from '../../src/lib/json-stream';

test.each([
  { items: [] }, { dataset: 'live', total: 0, items: [] },
  { items: [{ text: 'Grüne — \n "exact"', nested: [null, false, 2] }, { text: 'second' }], schema_version: '1.0' },
  { law: 'unmodified' }, null,
])('streaming API body preserves JSON values and order: %j', async value => {
  const text = await new Response(jsonBody(value)).text();
  expect(JSON.parse(text)).toEqual(value);
});

test('bulk responses serialize records lazily, not all before the first read', async () => {
  let serialized = 0;
  const item = { toJSON: () => { serialized++; return { text: 'entry' }; } };
  const body = jsonBody({ items: Array(100).fill(item) }) as ReadableStream;
  expect(serialized).toBe(0);
  const reader = body.getReader();
  await reader.read();
  expect(serialized).toBeLessThan(2);
  await reader.cancel();
});
