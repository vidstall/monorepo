from typing import Any

import pulumi

from ..common.environment import alibaba_scan_all_regions, require_env


def find_spot_type(
    name: str,
    provider: Any,
    region: str,
) -> tuple[str, str, Any, Any]:
    import pulumi_alicloud as alicloud

    result = alicloud.ecs.get_instance_types(
        cpu_core_count=1,
        memory_size=1,
        spot_strategy="SpotAsPriceGo",
        network_type="Vpc",
        opts=pulumi.InvokeOptions(provider=provider),
    )
    if result.instance_types:
        matched = result.instance_types[0]
        return region, str(matched.id), matched, provider
    if not alibaba_scan_all_regions():
        raise ValueError(
            f"No 1 vCPU / 1 GiB spot-capable Alibaba instance type found in region {region}."
        )
    access_key = require_env("ALIBABA_CLOUD_ACCESS_KEY_ID")
    secret_key = require_env("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
    regions = alicloud.get_regions(opts=pulumi.InvokeOptions(provider=provider))
    candidates = (candidate for candidate in regions.ids if candidate != region)
    for index, candidate_region in enumerate(candidates):
        candidate_provider = alicloud.Provider(
            f"{name}-vm-provider-{index}",
            access_key=access_key,
            secret_key=secret_key,
            region=candidate_region,
        )
        result = alicloud.ecs.get_instance_types(
            cpu_core_count=1,
            memory_size=1,
            spot_strategy="SpotAsPriceGo",
            network_type="Vpc",
            opts=pulumi.InvokeOptions(provider=candidate_provider),
        )
        if result.instance_types:
            matched = result.instance_types[0]
            return candidate_region, str(matched.id), matched, candidate_provider
    raise ValueError(
        "No 1 vCPU / 1 GiB spot-capable Alibaba instance type found in any Alibaba region."
    )
