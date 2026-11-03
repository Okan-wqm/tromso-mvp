// Stub of @aquaculture/shared-contracts for the reference harness: colours only (never numeric).
export const domainScale = { categorical: Array.from({ length: 12 }, (_v, i) => `#cat${i}`) };
export const colors = { gray: { 400: '#gray400' } } as const;
export function sequentialColor(step: number): string { return `#seq${step}`; }
