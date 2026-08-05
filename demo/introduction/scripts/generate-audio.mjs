#!/usr/bin/env node
// Generates one WAV per script line via kokoro-tts (af_heart voice).
// Run manually before `remotion studio` / `remotion render` — this shells
// out to a slow external CLI, so it's kept out of the render hot path.

import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import os from "node:os";

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(__dirname, "..");
const audioDir = join(projectRoot, "public", "audio");

const KOKORO_HOME = join(os.homedir(), "plugin", "kokoro-tts");
const MODEL_PATH = join(KOKORO_HOME, "kokoro-v1.0.onnx");
const VOICES_PATH = join(KOKORO_HOME, "voices-v1.0.bin");
const VOICE = "af_heart";
const LANG = "en-us";

async function loadScript() {
  try {
    const tsx = await import("tsx/esm/api");
    const mod = await tsx.tsImport(
      join(projectRoot, "src", "script.ts"),
      import.meta.url,
    );
    return mod.script;
  } catch (err) {
    console.error(
      "Failed to load src/script.ts. Install 'tsx' as a devDependency (npm i -D tsx) to run this script.",
    );
    throw err;
  }
}

const lines = await loadScript();

mkdirSync(audioDir, { recursive: true });

const manifest = {};

for (const line of lines) {
  const outFile = join(audioDir, `${line.id}.wav`);
  const tmpTxt = join(tmpdir(), `dvconf-intro-${line.id}-${Date.now()}.txt`);
  writeFileSync(tmpTxt, line.voiceover, "utf8");

  console.log(`Generating audio for "${line.id}"...`);
  execFileSync(
    "kokoro-tts",
    [
      tmpTxt,
      outFile,
      "--voice",
      VOICE,
      "--lang",
      LANG,
      "--model",
      MODEL_PATH,
      "--voices",
      VOICES_PATH,
    ],
    { stdio: "inherit" },
  );

  rmSync(tmpTxt, { force: true });
  manifest[line.id] = `audio/${line.id}.wav`;
}

writeFileSync(
  join(audioDir, "manifest.json"),
  JSON.stringify(manifest, null, 2) + "\n",
);

console.log(`Done. Generated ${lines.length} audio files in ${audioDir}`);
