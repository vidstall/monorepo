# Repository Guidelines

## Project Structure & Module Organization

This repository is organized by service under `services/`. `services/frontend` is the main Next.js client, with app routes in `app/`, shared helpers in `lib/`, styles in `styles/`, and assets in `public/`. `services/routes` contains the separate Next.js route service on port 3001. `services/contract` is the Sui Move package, with modules in `sources/` and tests in `tests/`. `services/coordinator` packages Redis configuration and a healthcheck. `services/media` contains the LiveKit Go media server under `cmd/`, `pkg/`, `test/`, and `deploy/`. `services/vclient` contains a small Python bot client.

## Build, Test, and Development Commands

Run commands from the relevant service directory unless noted.

- `pnpm install`: install dependencies for a Node service.
- `pnpm dev`: start `services/frontend` on the default Next.js port, or `services/routes` on port 3001.
- `pnpm build`: build a Next.js service for production.
- `pnpm test`: run frontend Vitest tests.
- `pnpm format:check` / `pnpm format:write`: check or apply Prettier formatting.
- `go test ./...`: run Go tests in `services/media`.
- `sui move build --path services/contract --build-env testnet`: build the Move package.
- `sui move test --path services/contract --build-env testnet`: run Move tests.
- `docker compose -f services/coordinator/docker-compose.yml up -d`: start the local Redis coordinator.

## Coding Style & Naming Conventions

TypeScript uses Prettier and Next.js linting; keep components in PascalCase, hooks as `useName`, and tests as `*.test.ts` or `*.test.tsx`. Go code should be `gofmt`/`go test` clean, with package tests named `*_test.go`. Move modules and tests use snake_case, matching `node_registry.move` and `node_registry_tests.move`.

## Testing Guidelines

Place tests next to the code they exercise when that pattern exists, such as `services/frontend/lib/getLiveKitURL.test.ts`. For `services/media`, prefer package-local Go tests and run `go test ./...`. For contract changes, update or add Move tests in `services/contract/tests`.

## Commit & Pull Request Guidelines

This repository currently has no commit history, so use concise Conventional Commit-style messages such as `feat(frontend): add wallet panel` or `fix(contract): validate stake withdrawal`. Pull requests should describe the change, list the commands run, link related issues, and include screenshots for visible frontend changes. Mention any required `.env` updates, but never commit secrets.

## Security & Configuration Tips

Use `.env.example` files in `services/frontend` and `services/routes` as templates for local configuration. Keep runtime secrets out of git. Do not expose the Redis coordinator directly to the public internet; use private networking, authentication, and TLS outside trusted local environments.
