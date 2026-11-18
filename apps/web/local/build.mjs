import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { readFile, writeFile, mkdir, copyFile } from "node:fs/promises";
const out = new URL("../dist/local/", import.meta.url);
await mkdir(out, { recursive: true });
await build({
  entryPoints: [fileURLToPath(new URL("main.tsx", import.meta.url))],
  bundle: true,
  jsx: "automatic",
  minify: true,
  outfile: fileURLToPath(new URL("ui.js", out)),
  define: { "process.env.NODE_ENV": '"production"' },
});
const css = await readFile(
  new URL("../app/globals.css", import.meta.url),
  "utf8",
);
await writeFile(
  new URL("ui.css", out),
  css.replace('@import "tailwindcss";', ""),
);
await copyFile(
  new URL("../public/favicon.svg", import.meta.url),
  new URL("favicon.svg", out),
);
