import "@testing-library/jest-dom/vitest";

// Recharts' ResponsiveContainer needs ResizeObserver, which jsdom does not provide.
class RO { observe() {} unobserve() {} disconnect() {} }
(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;
