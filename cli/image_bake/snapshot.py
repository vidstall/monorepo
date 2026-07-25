from __future__ import annotations

import json
import time

def _stop_and_create_image(provider: str, address: str, region: str, resource_id: str, image_name: str) -> tuple[bool, str, str]:
    """Stop the bake VM and create a provider-native image/snapshot from it.

    Returns (success, image_id, error_message). Commands below are the
    documented/best-confidence CLI invocations per provider (see plan doc);
    upcloud and akamai flags are explicitly best-effort/unverified -- confirm
    against `upctl --help` / `linode-cli images create --help` before relying
    on them for a real bake.
    """
    # Deferred self-import: run_capture is patched by tests as a flat
    # cli.image_bake attribute -- looking it up through the package at call
    # time is what makes that patch take effect here.
    from .. import image_bake

    run_capture = image_bake.run_capture

    if provider == "aws":
        code, _, err = run_capture(["aws", "ec2", "stop-instances", "--instance-ids", resource_id, "--region", region])
        if code != 0:
            return False, "", f"aws ec2 stop-instances failed: {err}"
        run_capture(["aws", "ec2", "wait", "instance-stopped", "--instance-ids", resource_id, "--region", region], timeout=600)
        code, out, err = run_capture(
            ["aws", "ec2", "create-image", "--instance-id", resource_id, "--name", image_name, "--region", region, "--output", "text", "--query", "ImageId"]
        )
        if code != 0 or not out.strip():
            return False, "", f"aws ec2 create-image failed: {err}"
        return True, out.strip(), ""

    if provider == "gcp":
        code, _, err = run_capture(["gcloud", "compute", "instances", "stop", resource_id, "--zone", region])
        if code != 0:
            return False, "", f"gcloud compute instances stop failed: {err}"
        code, out, err = run_capture(
            ["gcloud", "compute", "images", "create", image_name, "--source-disk", resource_id, "--source-disk-zone", region, "--format", "value(name)"]
        )
        if code != 0 or not out.strip():
            return False, "", f"gcloud compute images create failed: {err}"
        return True, out.strip(), ""

    if provider == "azure":
        # resource_id here is the deterministic VM name azure.py sets
        # (f"{name}-vm"). Resource group naming MUST mirror azure.py's
        # shared_network()/_LEGACY_LOCATION exactly: "eastus2" (the region
        # azure-node-1 was originally deployed in, before multi-region
        # support existed) keeps the bare legacy "xaisen-rg" name; every
        # other region gets its own "xaisen-rg-{region}" group. Verified
        # live: hardcoding the bare name unconditionally 404'd baking in
        # westus2, since that bake VM actually landed in "xaisen-rg-westus2".
        resource_group = "xaisen-rg" if region == "eastus2" else f"xaisen-rg-{region}"
        code, _, err = run_capture(["az", "vm", "deallocate", "--resource-group", resource_group, "--name", resource_id])
        if code != 0:
            return False, "", f"az vm deallocate failed: {err}"
        code, _, err = run_capture(["az", "vm", "generalize", "--resource-group", resource_group, "--name", resource_id])
        if code != 0:
            return False, "", f"az vm generalize failed: {err}"
        # The image MUST NOT live in the same resource group as the bake VM
        # (resource_group above) -- verified live: bake()'s own post-bake
        # teardown removes the bake host's topology row and re-runs
        # `pulumi up`, which then sees NOTHING in topology still needing that
        # region's shared network (azure.py's shared_network()), so it
        # deletes the whole per-region ResourceGroup/VNet/Subnet -- cascading
        # the image's deletion too, since deleting a resource group deletes
        # every resource inside it regardless of what created it (the image
        # is plain `az` output, entirely untracked by Pulumi). All 3 images
        # baked in one run vanished this way before this fix.
        #
        # Fix: put every region's image in its own Pulumi-unmanaged
        # "xaisen-images-<region>" resource group instead -- Pulumi never
        # touches these (doesn't know they exist), so they survive every
        # reconcile regardless of topology state. One shared RG across
        # regions does NOT work, though (confirmed live): unlike a plain
        # resource, a managed image is region-bound to its resource group --
        # `az image create` rejects a source VM whose region doesn't match
        # the target RG's location with "Source Virtual Machine ... does not
        # exist in this Azure location", even though the VM is real and the
        # RG itself accepts resources from anywhere. So the RG's location
        # must equal `region` here, which also means each region needs its
        # own RG (a second `az group create` call with a different
        # `--location` against an already-existing RG name is separately
        # rejected outright -- a resource group's location can't change).
        # `--source` needs the VM's full ARM resource ID (not just its bare
        # name) since it's no longer in the same resource group as `-g`.
        images_rg = f"xaisen-images-{region}"
        code, _, err = run_capture(["az", "group", "create", "--name", images_rg, "--location", region])
        if code != 0:
            return False, "", f"az group create (images RG) failed: {err}"
        code, vm_id, err = run_capture(
            ["az", "vm", "show", "--resource-group", resource_group, "--name", resource_id, "--query", "id", "-o", "tsv"]
        )
        if code != 0 or not vm_id.strip():
            return False, "", f"az vm show (resolving full VM id) failed: {err}"
        # --hyper-v-generation is required -- verified live: `az image create`
        # defaults to V1 and rejects a Gen2 source VM with a mismatch error.
        # azure.py's create_vm() always uses the "22_04-lts-gen2" SKU, so the
        # source is unconditionally Gen2, never V1.
        code, out, err = run_capture(
            [
                "az", "image", "create",
                "--resource-group", images_rg,
                "--name", image_name,
                "--source", vm_id.strip(),
                "--hyper-v-generation", "V2",
                "--query", "id", "-o", "tsv",
            ]
        )
        if code != 0 or not out.strip():
            return False, "", f"az image create failed: {err}"
        return True, out.strip(), ""

    if provider == "alibaba":
        code, _, err = run_capture(["aliyun", "ecs", "StopInstance", "--InstanceId", resource_id, "--RegionId", region])
        if code != 0:
            return False, "", f"aliyun ecs StopInstance failed: {err}"
        code, out, err = run_capture(
            ["aliyun", "ecs", "CreateImage", "--RegionId", region, "--InstanceId", resource_id, "--ImageName", image_name]
        )
        if code != 0 or not out.strip():
            return False, "", f"aliyun ecs CreateImage failed: {err}"
        try:
            image_id = json.loads(out).get("ImageId", "")
        except ValueError:
            image_id = ""
        if not image_id:
            return False, "", f"Could not parse ImageId from aliyun output: {out}"
        return True, image_id, ""

    if provider == "digitalocean":
        code, _, err = run_capture(["doctl", "compute", "droplet-action", "shutdown", resource_id, "--wait"])
        if code != 0:
            return False, "", f"doctl droplet-action shutdown failed: {err}"
        code, out, err = run_capture(
            ["doctl", "compute", "droplet-action", "snapshot", resource_id, "--snapshot-name", image_name, "--wait", "--format", "Resource", "--no-header"]
        )
        if code != 0:
            return False, "", f"doctl droplet-action snapshot failed: {err}"
        # doctl's snapshot action doesn't directly return the new image ID --
        # look it up by name.
        code, out, err = run_capture(["doctl", "compute", "image", "list", "--format", "ID,Name", "--no-header"])
        if code != 0:
            return False, "", f"doctl compute image list failed: {err}"
        for line in out.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[1].strip() == image_name:
                return True, parts[0].strip(), ""
        return False, "", f"Could not find snapshot '{image_name}' in doctl compute image list output."

    if provider == "upcloud":
        # Verified live against the UpCloud API (2026-07-25): `resource_id` is
        # the SERVER's UUID (persisted by upcloud.py::create_vm), but
        # `upctl storage clone` needs the boot DISK's own UUID, which is a
        # different identifier -- `upctl server show <server-uuid> -o json`
        # resolves it via storage_devices[].storage. create_vm() always
        # attaches exactly one disk to a bake VM, so there's no ambiguity to
        # resolve (its `boot_disk` field is unreliably "0" even when it's the
        # server's only disk -- don't filter on it, just take the one device).
        code, _, err = run_capture(["upctl", "server", "stop", resource_id, "--wait"])
        if code != 0:
            return False, "", f"upctl server stop failed: {err}"
        code, out, err = run_capture(["upctl", "server", "show", resource_id, "-o", "json"])
        if code != 0 or not out.strip():
            return False, "", f"upctl server show failed while resolving boot disk: {err}"
        try:
            devices = json.loads(out).get("storage_devices") or []
            storage_id = devices[0]["storage"] if devices else None
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            return False, "", f"Could not parse boot disk from 'upctl server show' output: {exc}"
        if not storage_id:
            return False, "", "No storage device found on bake server to clone"
        # `-o json` is required to get a parseable UUID back -- plain/human
        # output only prints "Cloning storage ... done" progress text, no ID
        # (verified live: with -o json, that progress text goes to stderr and
        # stdout is clean single-object JSON with a `uuid` field).
        code, out, err = run_capture(
            ["upctl", "storage", "clone", storage_id, "--title", image_name, "--zone", region, "-o", "json"]
        )
        if code != 0 or not out.strip():
            return False, "", f"upctl storage clone failed: {err}"
        try:
            new_storage_id = json.loads(out)["uuid"]
        except (json.JSONDecodeError, KeyError) as exc:
            return False, "", f"Could not parse cloned storage UUID from 'upctl storage clone' output: {exc}"
        return True, new_storage_id, ""

    if provider == "akamai":
        code, _, err = run_capture(["linode-cli", "linodes", "shutdown", resource_id])
        if code != 0:
            return False, "", f"linode-cli linodes shutdown failed: {err}"
        # shutdown is async (schedules a job) -- poll until the Linode
        # actually reports offline before snapshotting its disk, mirroring
        # aws/gcp's explicit stop-then-wait pattern above.
        for _ in range(24):
            code, out, err = run_capture(
                ["linode-cli", "linodes", "view", resource_id, "--text", "--no-headers", "--format", "status"]
            )
            if code == 0 and out.strip() == "offline":
                break
            time.sleep(5)
        else:
            return False, "", f"Linode {resource_id} did not reach 'offline' status in time: {err}"
        # `images create` snapshots a specific disk, not the Linode itself --
        # resolve the boot disk id (excluding the swap disk) rather than
        # passing the Linode's own id.
        code, out, err = run_capture(
            ["linode-cli", "linodes", "disks-list", resource_id, "--text", "--no-headers", "--format", "id,filesystem"]
        )
        if code != 0 or not out.strip():
            return False, "", f"linode-cli linodes disks-list failed: {err}"
        disk_id = ""
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].strip().lower() != "swap":
                disk_id = parts[0].strip()
                break
        if not disk_id:
            return False, "", f"Could not resolve a non-swap disk id from disks-list output: {out}"
        code, out, err = run_capture(
            ["linode-cli", "images", "create", "--disk_id", disk_id, "--label", image_name, "--text", "--no-headers", "--format", "id"]
        )
        if code != 0 or not out.strip():
            return False, "", f"linode-cli images create failed: {err}"
        return True, out.strip().splitlines()[0], ""

    if provider == "oci":
        code, _, err = run_capture(["oci", "compute", "instance", "action", "--instance-id", resource_id, "--action", "STOP"])
        if code != 0:
            return False, "", f"oci compute instance action --action STOP failed: {err}"
        for _ in range(24):
            code, out, err = run_capture(
                ["oci", "compute", "instance", "get", "--instance-id", resource_id, "--query", "data.\"lifecycle-state\"", "--raw-output"]
            )
            if code == 0 and out.strip() == "STOPPED":
                break
            time.sleep(5)
        else:
            return False, "", f"OCI instance {resource_id} did not reach 'STOPPED' state in time: {err}"
        code, out, err = run_capture(
            ["oci", "compute", "image", "create", "--instance-id", resource_id, "--display-name", image_name, "--query", "data.id", "--raw-output"]
        )
        if code != 0 or not out.strip():
            return False, "", f"oci compute image create failed: {err}"
        return True, out.strip(), ""

    return False, "", f"No image-creation path implemented for provider '{provider}'."
