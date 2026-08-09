import { describe, expect, it } from 'vitest';
import { libraryApi } from '@/features/library/api/libraryApi';

describe('generated API client', () => {
  it('uses the checked-in v1 contract against the current origin', async () => {
    const result = await libraryApi.list('');

    expect(result.items).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: 'Guide.md', path: 'Guide.md', type: 'file' }),
    ]));
  });
});
