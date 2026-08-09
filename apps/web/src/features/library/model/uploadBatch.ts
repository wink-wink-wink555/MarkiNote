import { ApiError } from '@/shared/api';

export const UPLOAD_START_INTERVAL_MS = 125;
export const UPLOAD_RATE_LIMIT_RETRIES = 3;

interface UploadBatchOptions {
  minStartIntervalMs?: number;
  maxRateLimitRetries?: number;
  retryBaseDelayMs?: number;
  now?: () => number;
  sleep?: (milliseconds: number) => Promise<void>;
}

export interface UploadBatchResult {
  success: number;
  failed: number;
}

const defaultSleep = (milliseconds: number) => new Promise<void>((resolve) => {
  window.setTimeout(resolve, milliseconds);
});

/**
 * Upload one item at a time and globally pace every attempt below the gateway
 * request-rate budget. Only explicit 429 responses receive bounded backoff.
 */
export async function uploadBatch<T>(
  items: readonly T[],
  upload: (item: T) => Promise<unknown>,
  options: UploadBatchOptions = {},
): Promise<UploadBatchResult> {
  const minStartIntervalMs = options.minStartIntervalMs ?? UPLOAD_START_INTERVAL_MS;
  const maxRateLimitRetries = options.maxRateLimitRetries ?? UPLOAD_RATE_LIMIT_RETRIES;
  const retryBaseDelayMs = options.retryBaseDelayMs ?? 500;
  const now = options.now ?? (() => performance.now());
  const sleep = options.sleep ?? defaultSleep;
  let earliestStart = now();
  let success = 0;
  let failed = 0;

  const waitForStartSlot = async () => {
    const delay = Math.max(0, earliestStart - now());
    if (delay > 0) await sleep(delay);
    const startedAt = now();
    earliestStart = Math.max(earliestStart, startedAt) + minStartIntervalMs;
  };

  for (const item of items) {
    let rateLimitFailures = 0;
    while (true) {
      await waitForStartSlot();
      try {
        await upload(item);
        success += 1;
        break;
      } catch (error) {
        if (error instanceof ApiError && error.status === 429
          && rateLimitFailures < maxRateLimitRetries) {
          const backoff = retryBaseDelayMs * (2 ** rateLimitFailures);
          rateLimitFailures += 1;
          await sleep(backoff);
          continue;
        }
        failed += 1;
        break;
      }
    }
  }

  return { success, failed };
}
