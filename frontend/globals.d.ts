/** The rail's open/collapsed state, set up by nav-boot.ts before the first paint. */
interface NavState {
  /** The saved choice ('open' | 'collapsed'), or null when the person never chose. */
  saved(): string | null;
  save(choice: 'open' | 'collapsed'): void;
  /** Applies the saved choice, or with none collapses the rail below 1100 px. */
  apply(): void;
}

interface Window {
  suderraNav: NavState;
}
