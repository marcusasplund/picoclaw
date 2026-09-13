import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"
import solidPlugin from "vite-plugin-solid"

export default defineConfig({
  plugins: [tailwindcss(), solidPlugin()],
  resolve: { alias: { "~": path.resolve(import.meta.dirname, "src") } },
  server: { port: 3000 },
})
