export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  if (process.env.ROUTES_DISABLE_SELF_REGISTRATION === "true") return;

  const { bootstrapOperator } = await import("@/lib/operator-registration");
  await bootstrapOperator();
}
