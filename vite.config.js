import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { minify } from "html-minifier-terser";

const proxy = { "/api": "http://127.0.0.1:8001" };

export default defineConfig({
  base: "./",
  plugins: [
    vue(),
    {
      name: "minify-html",
      apply: "build",
      transformIndexHtml: {
        order: "post",
        handler: (html) =>
          minify(html, {
            collapseWhitespace: true,
            removeComments: true,
            minifyCSS: true,
            minifyJS: true,
          }),
      },
    },
  ],
  build: {
    cssCodeSplit: false,
    outDir: "dist",
    emptyOutDir: true,
    minify: "esbuild",
    cssMinify: true,
    sourcemap: false,
    // WebVPN wraps JS in a normal function; ship no module imports/exports.
    rollupOptions: { output: { format: "iife", inlineDynamicImports: true } },
  },
  server: { proxy },
  preview: { proxy },
});
