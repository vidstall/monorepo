#!/usr/bin/env npx tsx
/**
 * DVConf Phase 2 Testnet Deployment Script
 *
 * Upgrades the on-chain package with Phase 2 modules and creates the 5
 * Phase 2 registry shared objects.
 *
 * Prerequisites:
 *   1. `sui` CLI installed and active-env set to `testnet`
 *   2. Active address must own the AdminCap and UpgradeCap from Phase 1
 *   3. `.env.testnet` populated with Phase 1 object IDs
 *   4. `@mysten/sui` and `dotenv` installed:
 *        npm install @mysten/sui dotenv
 *      Or run directly with npx tsx (tsx resolves TS on the fly):
 *        npx tsx scripts/deploy-phase2.ts
 *
 * Usage:
 *   npx tsx scripts/deploy-phase2.ts
 *
 * The script will:
 *   1. Read Phase 1 IDs from .env.testnet
 *   2. Run `sui client upgrade` via child process to publish the upgrade
 *   3. Call `create(&AdminCap)` on each Phase 2 registry
 *   4. Extract the new shared object IDs from TX effects
 *   5. Append new IDs to .env.testnet
 */

import { execSync } from 'node:child_process';
import { readFileSync, appendFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { SuiClient, getFullnodeUrl } from '@mysten/sui/client';
import { Transaction } from '@mysten/sui/transactions';
import { Ed25519Keypair } from '@mysten/sui/keypairs/ed25519';
import { config } from 'dotenv';

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const PROJECT_ROOT = resolve(__dirname, '..');
const ENV_PATH = resolve(PROJECT_ROOT, '.env.testnet');

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function log(msg: string): void {
  const ts = new Date().toISOString();
  console.log(`[${ts}] ${msg}`);
}

function fatal(msg: string): never {
  console.error(`\n  FATAL: ${msg}\n`);
  process.exit(1);
}

function requireEnv(key: string): string {
  const val = process.env[key];
  if (!val) fatal(`Missing required env var: ${key}. Check ${ENV_PATH}`);
  return val;
}

/**
 * Extract shared object IDs created in a transaction.
 * Returns an array of object ID strings.
 */
function extractCreatedSharedObjects(
  effects: Record<string, unknown>,
): string[] {
  const created = effects['created'] as
    | Array<{
        reference?: { objectId?: string };
        owner?: { Shared?: unknown } | string;
      }>
    | undefined;

  if (!Array.isArray(created)) return [];

  return created
    .filter((obj) => {
      const owner = obj.owner;
      return (
        typeof owner === 'object' &&
        owner !== null &&
        'Shared' in (owner as Record<string, unknown>)
      );
    })
    .map((obj) => obj.reference?.objectId ?? '')
    .filter(Boolean);
}

// ---------------------------------------------------------------------------
// Step 1: Load environment
// ---------------------------------------------------------------------------

log('Loading .env.testnet ...');
config({ path: ENV_PATH });

const PACKAGE_ID = requireEnv('PACKAGE_ID');
const ADMIN_CAP_ID = requireEnv('ADMIN_CAP_ID');
const UPGRADE_CAP_ID = requireEnv('UPGRADE_CAP_ID');

log(`  PACKAGE_ID     = ${PACKAGE_ID}`);
log(`  ADMIN_CAP_ID   = ${ADMIN_CAP_ID}`);
log(`  UPGRADE_CAP_ID = ${UPGRADE_CAP_ID}`);

// ---------------------------------------------------------------------------
// Step 2: Upgrade the package
// ---------------------------------------------------------------------------

log('');
log('=== Step 2: Upgrade package ===');
log('Running `sui client upgrade` ...');

let upgradeOutput: string;
try {
  upgradeOutput = execSync(
    `sui client upgrade --gas-budget 500000000 --upgrade-capability ${UPGRADE_CAP_ID} --skip-dependency-verification`,
    { cwd: PROJECT_ROOT, encoding: 'utf-8', stdio: ['inherit', 'pipe', 'pipe'] },
  );
} catch (err: unknown) {
  const msg = err instanceof Error ? err.message : String(err);
  fatal(`Package upgrade failed:\n${msg}`);
}

log('Upgrade output (last 30 lines):');
const outputLines = upgradeOutput.split('\n');
console.log(outputLines.slice(-30).join('\n'));

// Try to extract the new package ID from upgrade output.
// The `sui client upgrade` command prints something like:
//   "Published Objects ... PackageID: 0x..."
const newPkgMatch = upgradeOutput.match(
  /Package(?:ID)?[:\s]+\b(0x[0-9a-fA-F]{64})\b/i,
);
const newPackageId = newPkgMatch ? newPkgMatch[1] : null;

if (newPackageId) {
  log(`New PACKAGE_ID: ${newPackageId}`);
} else {
  log(
    'WARNING: Could not auto-extract new package ID from upgrade output.',
  );
  log(
    'You may need to update PACKAGE_ID in .env.testnet manually.',
  );
}

// ---------------------------------------------------------------------------
// Step 3: Create Phase 2 registries
// ---------------------------------------------------------------------------

log('');
log('=== Step 3: Create Phase 2 registry shared objects ===');

// Resolve the active keypair from sui keystore.
// The `sui client active-address` command prints the current address.
const activeAddress = execSync('sui client active-address', {
  encoding: 'utf-8',
}).trim();
log(`Active address: ${activeAddress}`);

// We need the keypair to sign TXs via the SDK.
// Read from sui keystore (default location).
const homeDir =
  process.env['HOME'] ??
  process.env['USERPROFILE'] ??
  fatal('Cannot determine home directory');
const keystorePath = resolve(homeDir, '.sui', 'sui_config', 'sui.keystore');

let keypair: Ed25519Keypair;
try {
  const keystoreContent = readFileSync(keystorePath, 'utf-8');
  const keys: string[] = JSON.parse(keystoreContent);

  // Try each key until we find the one matching the active address.
  let found = false;
  for (const b64Key of keys) {
    try {
      const kp = Ed25519Keypair.fromSecretKey(
        Uint8Array.from(Buffer.from(b64Key, 'base64')).slice(1), // strip scheme flag byte
      );
      if (
        kp.getPublicKey().toSuiAddress().toLowerCase() ===
        activeAddress.toLowerCase()
      ) {
        keypair = kp;
        found = true;
        break;
      }
    } catch {
      // Not an Ed25519 key or doesn't match — skip
    }
  }

  if (!found) {
    fatal(
      `Could not find Ed25519 keypair for active address ${activeAddress} in ${keystorePath}`,
    );
  }
} catch (err: unknown) {
  const msg = err instanceof Error ? err.message : String(err);
  fatal(`Failed to read keystore at ${keystorePath}: ${msg}`);
}

// Use the new package ID if we extracted it, otherwise fall back to the
// original PACKAGE_ID (works when the upgrade doesn't change the package address,
// which is not common — but the user will be warned).
const effectivePkgId = newPackageId ?? PACKAGE_ID;

const client = new SuiClient({ url: getFullnodeUrl('testnet') });

// The 5 Phase 2 registries to create, in order.
const REGISTRIES = [
  { module: 'user_registry', fn: 'create', envKey: 'USER_REGISTRY_ID' },
  { module: 'validator_registry', fn: 'create', envKey: 'VALIDATOR_REGISTRY_ID' },
  { module: 'relay_registry', fn: 'create', envKey: 'RELAY_REGISTRY_ID' },
  { module: 'control_plane_registry', fn: 'create', envKey: 'CP_REGISTRY_ID' },
  { module: 'room_manager', fn: 'create', envKey: 'ROOM_MANAGER_ID' },
] as const;

const createdIds: Record<string, string> = {};

for (const reg of REGISTRIES) {
  log(`Creating ${reg.module} ...`);

  const tx = new Transaction();

  tx.moveCall({
    target: `${effectivePkgId}::${reg.module}::${reg.fn}`,
    arguments: [tx.object(ADMIN_CAP_ID)],
  });

  try {
    const result = await client.signAndExecuteTransaction({
      signer: keypair!,
      transaction: tx,
      options: { showEffects: true, showObjectChanges: true },
    });

    await client.waitForTransaction({ digest: result.digest });

    log(`  TX digest: ${result.digest}`);

    // Extract the shared object created by this call.
    // Use objectChanges which is more reliable than raw effects.
    const changes = result.objectChanges ?? [];
    const sharedObj = (
      changes as Array<{
        type: string;
        objectId?: string;
        owner?: { Shared?: unknown } | string;
      }>
    ).find((c) => {
      if (c.type !== 'created') return false;
      const owner = c.owner;
      return (
        typeof owner === 'object' &&
        owner !== null &&
        'Shared' in (owner as Record<string, unknown>)
      );
    });

    if (sharedObj?.objectId) {
      createdIds[reg.envKey] = sharedObj.objectId;
      log(`  ${reg.envKey} = ${sharedObj.objectId}`);
    } else {
      // Fallback: try effects.created
      const effects = (result.effects ?? {}) as Record<string, unknown>;
      const fromEffects = extractCreatedSharedObjects(effects);
      if (fromEffects.length > 0) {
        createdIds[reg.envKey] = fromEffects[0];
        log(`  ${reg.envKey} = ${fromEffects[0]} (from effects)`);
      } else {
        log(`  WARNING: Could not extract object ID for ${reg.module}`);
        log('  Raw objectChanges:');
        console.log(JSON.stringify(changes, null, 2));
      }
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    fatal(`Failed to create ${reg.module}: ${msg}`);
  }
}

// ---------------------------------------------------------------------------
// Step 4: Append new IDs to .env.testnet
// ---------------------------------------------------------------------------

log('');
log('=== Step 4: Update .env.testnet ===');

const envLines: string[] = [
  '',
  '# Phase 2 Registry Objects',
  `# Created: ${new Date().toISOString()}`,
];

if (newPackageId) {
  envLines.push(`# Upgraded PACKAGE_ID (old: ${PACKAGE_ID})`);
  envLines.push(`PACKAGE_ID=${newPackageId}`);
}

for (const reg of REGISTRIES) {
  const id = createdIds[reg.envKey];
  if (id) {
    envLines.push(`${reg.envKey}=${id}`);
  } else {
    envLines.push(`# ${reg.envKey}=<FAILED — set manually>`);
  }
}

const envBlock = envLines.join('\n') + '\n';

// Check if any of these keys already exist in .env.testnet to avoid duplicates.
const existingEnv = readFileSync(ENV_PATH, 'utf-8');
const alreadyPresent = REGISTRIES.filter((r) =>
  existingEnv.includes(`${r.envKey}=`),
);

if (alreadyPresent.length > 0) {
  log(
    `WARNING: The following keys already exist in .env.testnet and will NOT be overwritten:`,
  );
  for (const r of alreadyPresent) {
    log(`  - ${r.envKey}`);
  }
  log('New values are appended as comments. Edit manually if needed.');

  // Append as comments instead
  const commentedBlock = envBlock
    .split('\n')
    .map((line) => {
      if (
        line.startsWith('#') ||
        line.trim() === '' ||
        line.startsWith('PACKAGE_ID=')
      )
        return line;
      const key = line.split('=')[0];
      if (alreadyPresent.some((r) => r.envKey === key)) {
        return `# DUPLICATE — ${line}`;
      }
      return line;
    })
    .join('\n');

  appendFileSync(ENV_PATH, commentedBlock);
} else {
  appendFileSync(ENV_PATH, envBlock);
}

log('Appended to .env.testnet');

// ---------------------------------------------------------------------------
// Step 5: Summary
// ---------------------------------------------------------------------------

log('');
log('═══════════════════════════════════════════════');
log(' Phase 2 Deployment Summary');
log('═══════════════════════════════════════════════');

if (newPackageId) {
  log(`  PACKAGE_ID (new)           = ${newPackageId}`);
}

for (const reg of REGISTRIES) {
  const id = createdIds[reg.envKey] ?? '<NOT CREATED>';
  log(`  ${reg.envKey.padEnd(25)} = ${id}`);
}

const successCount = Object.keys(createdIds).length;
log('');
log(`  ${successCount}/${REGISTRIES.length} registries created successfully.`);

if (successCount === REGISTRIES.length) {
  log('');
  log('  Phase 2 deployment COMPLETE.');
  log('  Next: update dvconf-daemons .env to reference these IDs.');
} else {
  log('');
  log('  Some registries failed. Check logs above and retry manually.');
}

log('');
