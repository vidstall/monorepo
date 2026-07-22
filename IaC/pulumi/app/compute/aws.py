from typing import Any

from ..common.regions import provider_region
from ..models import TopologyInstance


def create_vm(instance: TopologyInstance, public_key: str) -> dict[str, Any]:
    import pulumi_aws as aws

    name = instance["name"]
    port = int(instance.get("port") or 0)
    region = provider_region("aws", instance)
    instance["region"] = region
    baked_image = instance.get("image")
    if baked_image:
        ami_id = baked_image
    else:
        ami_id = aws.ec2.get_ami(
            most_recent=True,
            owners=["099720109477"],
            filters=[
                aws.ec2.GetAmiFilterArgs(
                    name="name",
                    values=["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"],
                ),
            ],
            region=region,
        ).id
    key = aws.ec2.KeyPair(
        f"{name}-vm-key",
        key_name=f"xaisen-{name}",
        public_key=public_key,
        region=region,
    )
    ingress = [
        aws.ec2.SecurityGroupIngressArgs(
            protocol="tcp", from_port=22, to_port=22, cidr_blocks=["0.0.0.0/0"]
        ),
    ]
    if port:
        ingress.append(
            aws.ec2.SecurityGroupIngressArgs(
                protocol="tcp",
                from_port=port,
                to_port=port,
                cidr_blocks=["0.0.0.0/0"],
            )
        )
    if instance.get("service") == "media":
        ingress.append(
            aws.ec2.SecurityGroupIngressArgs(
                protocol="tcp", from_port=7890, to_port=7890, cidr_blocks=["0.0.0.0/0"]
            )
        )
    security_group = aws.ec2.SecurityGroup(
        f"{name}-vm-sg",
        region=region,
        ingress=ingress,
        egress=[
            aws.ec2.SecurityGroupEgressArgs(
                protocol="-1", from_port=0, to_port=0, cidr_blocks=["0.0.0.0/0"]
            )
        ],
    )
    vm = aws.ec2.Instance(
        f"{name}-vm",
        ami=ami_id,
        instance_type=instance.get("size") or "t3.micro",
        key_name=key.key_name,
        vpc_security_group_ids=[security_group.id],
        associate_public_ip_address=True,
        region=region,
        tags={"Name": f"xaisen-{name}"},
    )
    # EC2 instance ID, as `aws ec2 ...` commands expect -- persisted via
    # persist_vm_resolution() for image_bake.bake().
    instance["resource_id"] = vm.id
    return {"address": vm.public_ip, "user": "ubuntu"}
