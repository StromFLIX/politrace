import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://politrace.stromflix.com',
  output: 'static',
  trailingSlash: 'always',
  build: { format: 'directory' },
  vite: { build: { sourcemap: false, assetsInlineLimit: 0 } },
});
