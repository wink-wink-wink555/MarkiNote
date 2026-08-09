import type { DocumentMutation } from '@/shared/api';

function isSameOrChild(path: string, parent: string): boolean {
  return path === parent || path.startsWith(`${parent}/`);
}

/**
 * Keep the open document aligned with successful AI filesystem mutations.
 * Mutations are applied in order because one tool run may move a path and
 * subsequently operate on its new location.
 */
export function selectedPathAfterMutations(
  selectedPath: string,
  mutations: DocumentMutation[] = [],
): string {
  let nextPath = selectedPath;
  for (const mutation of mutations) {
    if (!nextPath) break;
    if (mutation.type === 'delete_item' && isSameOrChild(nextPath, mutation.path)) {
      nextPath = '';
    } else if (
      mutation.type === 'move_item'
      && mutation.target
      && isSameOrChild(nextPath, mutation.path)
    ) {
      nextPath = `${mutation.target}${nextPath.slice(mutation.path.length)}`;
    }
  }
  return nextPath;
}
