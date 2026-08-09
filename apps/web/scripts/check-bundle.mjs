import { readFile, readdir, stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const webRoot = fileURLToPath(new URL('../', import.meta.url));
const distRoot = path.join(webRoot, 'dist');
const assetsRoot = path.join(distRoot, 'assets');
const MAX_ENTRY_BYTES = 500 * 1024;
const MAX_ASYNC_CHUNK_BYTES = 750 * 1024;
const requiredAsyncBudgets = [
  { label: 'CodeMirror editor', pattern: /^CodeEditor-.*\.js$/u, maximum: 600 * 1024 },
  { label: 'Mermaid runtime', pattern: /^mermaid\.core-.*\.js$/u, maximum: 650 * 1024 },
  { label: 'KaTeX runtime', pattern: /^katex-.*\.js$/u, maximum: 300 * 1024 },
  { label: 'KaTeX auto-render', pattern: /^auto-render-.*\.js$/u, maximum: 25 * 1024 },
];

async function listFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = await Promise.all(entries.map(async (entry) => {
    const absolutePath = path.join(directory, entry.name);
    return entry.isDirectory() ? listFiles(absolutePath) : [absolutePath];
  }));
  return files.flat();
}

const sourceMaps = (await listFiles(distRoot)).filter((file) => file.endsWith('.map'));
if (sourceMaps.length) {
  throw new Error(`Production output must not expose source maps: ${sourceMaps.map((file) => path.relative(distRoot, file)).join(', ')}`);
}

const indexHtml = await readFile(path.join(distRoot, 'index.html'), 'utf8');
const entryMatch = indexHtml.match(/<script[^>]+src="([^"]+\.js)"/u);
if (!entryMatch?.[1]) throw new Error('Unable to locate the production entry chunk');

const entryPath = path.join(distRoot, entryMatch[1].replace(/^\//u, ''));
const entryBytes = (await stat(entryPath)).size;
if (entryBytes > MAX_ENTRY_BYTES) {
  throw new Error(`Entry bundle ${path.basename(entryPath)} is ${entryBytes} bytes; budget is ${MAX_ENTRY_BYTES}`);
}

const chunks = (await readdir(assetsRoot)).filter((name) => name.endsWith('.js'));
const measurements = new Map();
for (const chunk of chunks) {
  const bytes = (await stat(path.join(assetsRoot, chunk))).size;
  measurements.set(chunk, bytes);
  if (bytes > MAX_ASYNC_CHUNK_BYTES) {
    throw new Error(`Async chunk ${chunk} is ${bytes} bytes; budget is ${MAX_ASYNC_CHUNK_BYTES}`);
  }
}

const requiredSummary = [];
for (const budget of requiredAsyncBudgets) {
  const chunk = chunks.find((name) => budget.pattern.test(name));
  if (!chunk) throw new Error(`Required lazy ${budget.label} chunk was not emitted`);
  const bytes = measurements.get(chunk);
  if (typeof bytes !== 'number' || bytes > budget.maximum) {
    throw new Error(`${budget.label} chunk ${chunk} is ${bytes ?? 'unknown'} bytes; budget is ${budget.maximum}`);
  }
  requiredSummary.push(`${budget.label}=${bytes}B`);
}

console.log(`Bundle budgets passed: sourceMaps=0; entry=${entryBytes}B; ${requiredSummary.join('; ')}; every async chunk<=${MAX_ASYNC_CHUNK_BYTES}B`);
