import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

// satori needs raw font bytes (not a font-family name resolved by the OS),
// so we point straight at the TTFs shipped inside @fontsource/inter.
function loadInter(weight: 400 | 600 | 700) {
  const path = require.resolve(`@fontsource/inter/files/inter-latin-${weight}-normal.woff`);
  return readFileSync(path);
}

export async function loadFonts() {
  return [
    { name: "Inter", data: loadInter(400), weight: 400 as const, style: "normal" as const },
    { name: "Inter", data: loadInter(600), weight: 600 as const, style: "normal" as const },
    { name: "Inter", data: loadInter(700), weight: 700 as const, style: "normal" as const },
  ];
}
