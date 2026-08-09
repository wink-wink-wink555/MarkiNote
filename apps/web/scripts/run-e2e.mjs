import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { preview } from 'vite';

const webRoot = fileURLToPath(new URL('../', import.meta.url));
const playwrightCli = fileURLToPath(new URL('../node_modules/@playwright/test/cli.js', import.meta.url));

const server = await preview({
  root: webRoot,
  logLevel: 'warn',
  preview: { host: '127.0.0.1', port: 0, strictPort: false },
});

try {
  const address = server.httpServer.address();
  if (!address || typeof address === 'string') throw new Error('Unable to resolve the managed preview port');
  const baseURL = `http://127.0.0.1:${address.port}`;
  const exitCode = await new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [playwrightCli, 'test', ...process.argv.slice(2)], {
      cwd: webRoot,
      env: { ...process.env, MARKINOTE_E2E_MANAGED_PREVIEW: '1', MARKINOTE_E2E_BASE_URL: baseURL },
      stdio: 'inherit',
    });
    child.once('error', reject);
    child.once('exit', (code) => resolve(code ?? 1));
  });
  process.exitCode = exitCode;
} finally {
  await server.close();
}
