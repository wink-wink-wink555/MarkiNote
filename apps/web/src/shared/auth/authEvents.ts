type AuthenticationRequiredListener = () => void;

const listeners = new Set<AuthenticationRequiredListener>();

export function notifyAuthenticationRequired(): void {
  for (const listener of listeners) listener();
}

export function onAuthenticationRequired(listener: AuthenticationRequiredListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
