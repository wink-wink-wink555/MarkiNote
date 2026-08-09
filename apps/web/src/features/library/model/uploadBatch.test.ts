import { describe, expect, it } from 'vitest';
import { ApiError } from '@/shared/api';
import { uploadBatch, UPLOAD_START_INTERVAL_MS } from './uploadBatch';

function virtualTime() {
  let current = 0;
  return {
    now: () => current,
    sleep: (milliseconds: number) => {
      current += milliseconds;
      return Promise.resolve();
    },
  };
}

describe('uploadBatch', () => {
  it('paces more than one gateway burst of files and keeps concurrency bounded', async () => {
    const clock = virtualTime();
    const starts: number[] = [];
    let active = 0;
    let maxActive = 0;
    const files = Array.from({ length: 45 }, (_, index) => `file-${index}.md`);

    const result = await uploadBatch(files, async () => {
      starts.push(clock.now());
      active += 1;
      maxActive = Math.max(maxActive, active);
      await Promise.resolve();
      active -= 1;
    }, clock);

    expect(result).toEqual({ success: 45, failed: 0 });
    expect(starts).toHaveLength(45);
    expect(maxActive).toBe(1);
    expect(starts.slice(1).every((start, index) => (
      start - starts[index]! >= UPLOAD_START_INTERVAL_MS
    ))).toBe(true);
  });

  it('retries only 429 responses with bounded backoff and reports permanent failures', async () => {
    const clock = virtualTime();
    const attempts = new Map<string, number>();
    const result = await uploadBatch(['ok.md', 'limited.md', 'broken.md'], (name) => {
      const attempt = (attempts.get(name) ?? 0) + 1;
      attempts.set(name, attempt);
      if (name === 'limited.md' && attempt < 3) {
        return Promise.reject(new ApiError('rate limited', 429, 'rate_limited'));
      }
      if (name === 'broken.md') return Promise.reject(new ApiError('invalid', 400, 'invalid_document'));
      return Promise.resolve();
    }, clock);

    expect(result).toEqual({ success: 2, failed: 1 });
    expect(attempts).toEqual(new Map([
      ['ok.md', 1],
      ['limited.md', 3],
      ['broken.md', 1],
    ]));
  });

  it('stops retrying after the configured 429 budget', async () => {
    const clock = virtualTime();
    let attempts = 0;
    const result = await uploadBatch(['limited.md'], () => {
      attempts += 1;
      return Promise.reject(new ApiError('rate limited', 429, 'rate_limited'));
    }, { ...clock, maxRateLimitRetries: 2 });

    expect(result).toEqual({ success: 0, failed: 1 });
    expect(attempts).toBe(3);
  });
});
