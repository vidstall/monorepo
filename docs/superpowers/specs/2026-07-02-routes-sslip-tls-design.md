# Routes sslip.io TLS Design

## Goal

Make `vidctl infra start --service routes` provision a browser-trusted endpoint at `https://<public-ip>.sslip.io/api` and publish that endpoint through the existing on-chain routes registration.

## Deployment

- Alibaba security groups expose SSH, HTTP, and HTTPS for routes nodes; port 3001 is private.
- Ansible creates a private Docker network, runs routes internally on port 3001, and runs `caddy:2-alpine` on ports 80/443.
- Caddy persists certificate state and reverse-proxies the sslip.io hostname to the routes container.
- Ansible derives the hostname from `ansible_host`, injects `ROUTES_PUBLIC_URL`, and waits for the trusted HTTPS contract-health endpoint before reporting success.
- Pulumi lifecycle target URNs cover the HTTP/HTTPS rules and removal of the old public port-3001 rule.

## On-chain endpoint state

- New routes registrations store the sslip.io API URL in worker metadata.
- Existing routes workers compare the configured public URL with current metadata and submit `update_worker_metadata` before marking active when it changed.
- Existing governed router discovery, heartbeat freshness, latency probing, caching, and failover remain the frontend selection mechanism.

## Validation

- Infrastructure tests verify 80/443 exposure, no public 3001, and complete lifecycle targets.
- Ansible checks cover private networking, Caddy persistence, derived hostname, injected URL, and HTTPS readiness.
- Routes tests cover initial registration and metadata refresh.
- Deployment succeeds only when the trusted sslip.io health URL responds.

## Assumptions

- Routes nodes have public IPv4 addresses and inbound ports 80/443.
- sslip.io and Caddy's ACME certificate authority are acceptable external dependencies.
- Certificate issuance failure fails the lifecycle command rather than publishing an HTTP endpoint.
