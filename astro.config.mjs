import { defineConfig } from "astro/config";
import mdx from "@astrojs/mdx";

const isUSB = process.env.BUILD_TARGET === "usb";

export default defineConfig({
  site: "https://vojtamaur.cz",
  integrations: [mdx()],
  trailingSlash: isUSB ? "never" : "always",
  build: {
    format: isUSB ? "file" : "directory",
  },
});