import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  base: './',            // app is served from /pydvma/app/ — relative assets
  // .dvma containers are opaque binary assets (the ?fixture=1 hook fetches one
  // as a URL); register the extension so Vite hashes+serves it, not parses it.
  assetsInclude: ['**/*.dvma'],
  build: { target: 'es2022' },
  worker: { format: 'es' },
});
