"""Staging deployment — mirrors production shape, testnet, persistent for QA."""
from cli.scenario import Topology, ScenarioContext

NAME = "staging"
DESCRIPTION = "Staging environment on testnet. Persistent deployment for QA and integration testing."
TOPOLOGY = Topology(
    provider="alibaba-cloud",
    region="cn-hangzhou",
    instance_type="ecs.t5-lc1m2.small",
    media_nodes=3,
    routes_nodes=1,
    vclient_nodes=0,
    coordinator_nodes=1,
    contract_network="devnet",
    deploy_contract=True,
    teardown=False,
    session_duration_secs=0,
    benchmark_targets={},
)


def run(ctx: ScenarioContext) -> None:
    ctx.step("Verify staging deployment is live")
    ctx.log(f"provider:   {ctx.topology.provider} ({ctx.topology.region})")
    ctx.log(f"instance:   {ctx.topology.instance_type}")
    ctx.log(f"nodes:      {ctx.topology.media_nodes}w / {ctx.topology.routes_nodes}d / {ctx.topology.coordinator_nodes}coord")
    ctx.log(f"network:    {ctx.topology.contract_network}")
    ctx.log("Point testbed scenarios at this deployment or test manually via the client UI.")
