import { defineConfig } from "astro/config";
import tailwind from "@astrojs/tailwind";
import sitemap from "@astrojs/sitemap";

export default defineConfig({
  site: "https://agripulse.cloud",
  integrations: [tailwind({ applyBaseStyles: false }), sitemap()],
  build: { format: "directory" },
});
