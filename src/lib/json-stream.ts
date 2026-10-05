/** Stream bulk collections one record at a time; never allocate a second corpus-sized string. */
export function jsonBody(value: unknown): BodyInit {
  if (!value || typeof value !== 'object' || !('items' in value) || !Array.isArray(value.items)) {
    return JSON.stringify(value, null, 2) + '\n';
  }
  const { items, ...metadata } = value;
  const encoder = new TextEncoder();
  let position = -1;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (position === -1) {
        const prefix = JSON.stringify(metadata);
        controller.enqueue(encoder.encode(prefix.slice(0, -1) + (prefix === '{}' ? '' : ',') + '"items":['));
        position = 0;
      } else if (position < items.length) {
        controller.enqueue(encoder.encode((position ? ',' : '') + JSON.stringify(items[position++])));
      } else {
        controller.enqueue(encoder.encode(']}\n'));
        controller.close();
      }
    },
  });
}
