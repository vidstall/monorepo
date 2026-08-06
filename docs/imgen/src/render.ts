import { mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import React from "react";
import satori from "satori";
import { Resvg } from "@resvg/resvg-js";
import { loadFonts } from "./font.ts";

const __dirname = dirname(fileURLToPath(import.meta.url));
const diagramsDir = join(__dirname, "diagrams");
const outputDir = join(__dirname, "..", "output");

async function main() {
  mkdirSync(outputDir, { recursive: true });
  const fonts = await loadFonts();

  const files = readdirSync(diagramsDir).filter((f) => f.endsWith(".tsx"));
  for (const file of files) {
    const name = file.replace(/\.tsx$/, "");
    const mod = await import(pathToFileURL(join(diagramsDir, file)).href);
    const Component = mod.default;
    const width = mod.width ?? 1200;
    const height = mod.height ?? 900;

    const svg = await satori(React.createElement(Component), {
      width,
      height,
      fonts,
    });

    const png = new Resvg(svg, { fitTo: { mode: "width", value: 2400 } }).render().asPng();
    const outPath = join(outputDir, `${name}.png`);
    writeFileSync(outPath, png);
    console.log(`built ${outPath}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
