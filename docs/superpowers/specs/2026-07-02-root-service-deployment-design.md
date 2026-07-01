# Root Service Deployment Design

## Goal

Deploy and operate Xaisen VM services entirely as `root` instead of creating a dedicated `xaisen` host user.

## Changes

- Remove the Ansible task that creates the `xaisen` user.
- Remove the `xaisen_user` inventory variable.
- Own `/opt/xaisen`, runtime directories, copied contract configuration, and service secret files as `root:root`.
- Keep Docker installation, registry login, and container lifecycle operations under Ansible privilege escalation as they are today.
- Do not change container image users; this change governs host provisioning and files managed by Ansible.

## Validation

Ansible inventory must no longer expose `xaisen_user`. Playbook syntax checks must pass, and no Ansible task may reference the removed variable.
