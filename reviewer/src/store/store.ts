export type Listener = () => void;

/**
 * Minimal hand-rolled store: one mutable state object, set-based subscribers.
 * React components subscribe through `useAppSelector` (app/services.tsx) so
 * they only re-render when their selected slice actually changes —
 * high-frequency fields like `currentTime` never re-render the cue list or
 * the editor.
 */
export class Store<S> {
  private state: S;
  private listeners = new Set<Listener>();

  constructor(initial: S) {
    this.state = initial;
  }

  getState(): S {
    return this.state;
  }

  setState(patch: Partial<S> | ((state: S) => Partial<S> | null)): void {
    const partial = typeof patch === "function" ? patch(this.state) : patch;
    if (!partial) return;
    this.state = { ...this.state, ...partial };
    for (const listener of this.listeners) listener();
  }

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
}
