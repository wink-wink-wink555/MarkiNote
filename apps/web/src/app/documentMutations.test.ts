import { describe, expect, it } from 'vitest';
import { selectedPathAfterMutations } from './documentMutations';

describe('selectedPathAfterMutations', () => {
  it('clears a selected file deleted directly or through its parent folder', () => {
    expect(selectedPathAfterMutations('notes/today.md', [
      { type: 'delete_item', path: 'notes/today.md' },
    ])).toBe('');
    expect(selectedPathAfterMutations('notes/today.md', [
      { type: 'delete_item', path: 'notes' },
    ])).toBe('');
  });

  it('follows files and folders moved by the AI', () => {
    expect(selectedPathAfterMutations('draft.md', [
      { type: 'move_item', path: 'draft.md', target: 'archive/draft.md' },
    ])).toBe('archive/draft.md');
    expect(selectedPathAfterMutations('notes/today.md', [
      { type: 'move_item', path: 'notes', target: 'archive/notes' },
    ])).toBe('archive/notes/today.md');
  });

  it('applies a sequence of mutations without touching similarly prefixed paths', () => {
    expect(selectedPathAfterMutations('notes/today.md', [
      { type: 'move_item', path: 'notes', target: 'archive/notes' },
      { type: 'delete_item', path: 'archive/notes' },
    ])).toBe('');
    expect(selectedPathAfterMutations('notebook/today.md', [
      { type: 'delete_item', path: 'notes' },
    ])).toBe('notebook/today.md');
  });
});
