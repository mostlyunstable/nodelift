import '@testing-library/jest-dom/vitest'

// jsdom has no layout engine; React Flow needs these to mount.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver
globalThis.DOMMatrixReadOnly ??= class {
  m22 = 1
  constructor(_transform?: string) {}
} as unknown as typeof DOMMatrixReadOnly
