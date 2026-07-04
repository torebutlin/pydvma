/// <reference types="svelte" />
/// <reference types="vite/client" />

// .dvma containers imported as served asset URLs (registered as an asset
// type in vite.config.ts via `assetsInclude`). Used by the ?fixture=1 hook.
declare module '*.dvma?url' {
  const src: string;
  export default src;
}
