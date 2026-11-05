// Seeded randomness for the property tests: mulberry32, a small generator whose whole state is one 32-bit number, so a
// failing run is replayed exactly from the seed it prints. Test code only (tsconfig.json leaves frontend/test/ out of
// the browser build).

export type Random = () => number;

export function mulberry32(seed: number): Random {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function int(random: Random, low: number, high: number): number {
  return low + Math.floor(random() * (high - low + 1));
}

export function pick<T>(random: Random, items: readonly T[]): T {
  return items[Math.floor(random() * items.length)];
}

// Runs `check` `runs` times, each with its own seed drawn from a base seed (the environment's GRID_SEED, else the
// clock); a failure names the seed that replays it.
export function property(name: string, runs: number, check: (random: Random, seed: number) => void): void {
  const base = Number(process.env.GRID_SEED ?? Date.now()) >>> 0;
  for (let run = 0; run < runs; run += 1) {
    const seed = (base + run * 2654435761) >>> 0;
    try {
      check(mulberry32(seed), seed);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw new Error(`${name}: failed at seed ${seed} (run ${run}, GRID_SEED=${base}): ${message}`);
    }
  }
}

// Freezes an object and everything in it, so a function that changes its input throws (ES modules are strict).
export function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const key of Object.keys(value as object)) {
      deepFreeze((value as Record<string, unknown>)[key]);
    }
  }
  return value;
}
