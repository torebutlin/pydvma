import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  base: './',            // app is served from /pydvma/app/ — relative assets
  build: { target: 'es2022' },
  worker: { format: 'es' },
});
