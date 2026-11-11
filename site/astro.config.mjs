import { defineConfig } from 'astro/config';

// Local only. No `site` or deploy adapter is configured on purpose:
// publishing needs the owner's explicit approval at a stage close.
export default defineConfig({
  server: { host: '127.0.0.1' },
});
