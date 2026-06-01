function tokenize(path) {
  const text = String(path || '').trim();
  if (!text || text === '$') return [];
  return text
    .replace(/^\$\./, '')
    .replace(/^\$/, '')
    .split('.')
    .flatMap((part) => {
      const pieces = [];
      let remaining = part;
      while (remaining.includes('[')) {
        const idx = remaining.indexOf('[');
        if (idx > 0) pieces.push(remaining.slice(0, idx));
        const end = remaining.indexOf(']', idx);
        if (end < 0) break;
        pieces.push(remaining.slice(idx + 1, end));
        remaining = remaining.slice(end + 1);
      }
      if (remaining) pieces.push(remaining);
      return pieces.filter(Boolean);
    });
}

export function extractByPath(obj, path) {
  const tokens = tokenize(path);
  let current = obj;
  for (const token of tokens) {
    if (current === null || current === undefined) return null;
    if (Array.isArray(current) && /^\d+$/.test(token)) {
      current = current[Number(token)];
      continue;
    }
    current = current[token];
  }
  return current ?? null;
}

export function renderBlock(block, rawJson) {
  const value = extractByPath(rawJson, block?.path || '$');
  let normalizedValue = value;
  if (block?.type === 'table' && Array.isArray(value)) {
    normalizedValue = value.map((row) => {
      const next = { ...row };
      (block.columns || []).forEach((column) => {
        next[column.path] = extractByPath(row, column.path) ?? row?.[column.path] ?? null;
      });
      return next;
    });
  }
  return {
    ...block,
    value: normalizedValue,
  };
}

export function buildRenderBlocks(display, rawJson) {
  const safeDisplay = display || {};
  return {
    summaryBlocks: (safeDisplay.summary_blocks || []).map((block) => renderBlock(block, rawJson)),
    detailBlocks: (safeDisplay.detail_blocks || []).map((block) => renderBlock(block, rawJson)),
  };
}
