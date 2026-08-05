#!/usr/bin/env node
// Probes each generated WAV's real duration via ffprobe and writes
// src/durations.json, which the Remotion composition uses to lay out
// Sequences and captions in exact sync with the audio.

import { execFileSync } from "node:child_process";
import { writeFileSync, existsSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(__dirname, "..");
const audioDir = join(projectRoot, "public", "audio");

async function loadScript() {
  const tsx = await import("tsx/esm/api");
  const mod = await tsx.tsImport(
    join(projectRoot, "src", "script.ts"),
    import.meta.url,
  );
  return mod.script;
}

const lines = await loadScript();
const durations = {};

for (const line of lines) {
  const wavPath = join(audioDir, `${line.id}.wav`);
  if (!existsSync(wavPath)) {
    throw new Error(
      `Missing audio file for "${line.id}" at ${wavPath}. Run \`npm run tts\` first.`,
    );
  }
  const out = execFileSync("ffprobe", [
    "-v",
    "error",
    "-show_entries",
    "format=duration",
    "-of",
    "default=noprint_wrappers=1:nokey=1",
    wavPath,
  ]).toString().trim();
  durations[line.id] = parseFloat(out);
  console.log(`${line.id}: ${durations[line.id].toFixed(2)}s`);
}

writeFileSync(
  join(projectRoot, "src", "durations.json"),
  JSON.stringify(durations, null, 2) + "\n",
);

console.log(`Wrote src/durations.json (${lines.length} entries)`);
