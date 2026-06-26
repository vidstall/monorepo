"""Production deployment — persistent, workers stay registered, no auto-teardown."""
from cli.scenario import Topology, ScenarioContext

NAME = "production"
DESCRIPTION = "Full production deployment on mainnet. Stays up until manually purged."
TOPOLOGY = Topology(
    provider="alibaba-cloud",
    region="cn-hangzhou",
    instance_type="ecs.g6.large",
    worker_nodes=5,
    dist_nodes=2,
    vclient_nodes=0,
    coordinator_nodes=1,
    contract_network="mainnet",
    deploy_contract=False,
    teardown=False,
    session_duration_secs=0,
    benchmark_targets={},
)


def run(ctx: ScenarioContext) -> None:
    ctx.step("Verify deployment is live")
    ctx.log(f"provider:   {ctx.topology.provider} ({ctx.topology.region})")
    ctx.log(f"instance:   {ctx.topology.instance_type}")
    ctx.log(f"nodes:      {ctx.topology.worker_nodes}w / {ctx.topology.dist_nodes}d / {ctx.topology.coordinator_nodes}coord")
    ctx.log(f"network:    {ctx.topology.contract_network}")
    ctx.log("Use 'vidctl observe workers' and 'vidctl observe rooms' to inspect live state.")
    ctx.log("Use 'vidctl infra purge --provider alibaba-cloud' to tear down when done.")
