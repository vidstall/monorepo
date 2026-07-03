import { bootstrapOperator } from "./lib/operator-registration.js";

if (process.env.COORDINATOR_DISABLE_SELF_REGISTRATION === "true") {
  console.log(
    "[coordinator] COORDINATOR_DISABLE_SELF_REGISTRATION=true; skipping on-chain self-registration",
  );
} else {
  await bootstrapOperator();
}

// bootstrapOperator() sets up its own heartbeat interval on success, which
// already keeps the process alive. Add an idle keep-alive regardless (harmless
// if redundant) so this container - whose only job is to hold the on-chain
// identity alive - doesn't exit if registration was skipped or bootstrap
// failed before the heartbeat timer was created.
setInterval(() => {}, 1 << 30);
