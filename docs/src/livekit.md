# `src/livekit`

`src/livekit` is the SFU and server runtime layer for the video conferencing system.

## Purpose

This package provides the media-plane backend for the app.

- It runs the LiveKit server.
- It handles room/session coordination for real-time media traffic.
- It supports distributed operation through Redis-backed coordination.
- It exposes the server-side behaviors needed by the rest of the platform, including egress, ingress, webhooks, and telemetry.

## Role In The System

The application is split into distinct layers:

- `src/livekit/` is the conferencing runtime and SFU layer.
- `src/routes/` is the backend API service used by the browser app.
- `src/client/` is the browser-facing conference UI.
- `src/stateful/` provides Redis-backed coordination, job dispatch, ingress, and egress support.
- `src/contract/` is the on-chain registry boundary that governs worker participation.

`src/livekit` sits closest to the media plane and is the layer that accepts and forwards real-time audio/video/data traffic.

## Main Entry Point

The main server entrypoint is:

- `src/livekit/cmd/server/main.go`

That command defines the server CLI, loads configuration, and starts the LiveKit runtime.

It supports:

- config file and inline config input
- API key and secret loading
- node region and node IP configuration
- Redis connection settings
- TURN certificate and key configuration
- development flags and profiling flags

## Configuration

The canonical local configuration reference is:

- `src/livekit/config-sample.yaml`

This file describes the core runtime settings for:

- Redis-backed distributed mode
- node region and routing behavior
- transport and networking setup
- TURN and ICE-related settings
- telemetry and observability hooks

## Operational Responsibilities

`src/livekit` owns the server-side runtime concerns for a conferencing node.

- Accept and route participant media.
- Coordinate room and node state across distributed instances.
- Integrate with service-level components for room management and agent/worker behavior.
- Expose metrics, tracing, and debugging hooks for production operation.
- Support egress and ingress workflows used by the wider app.

## Deployment And Testing

Deployment guidance lives in:

- `src/livekit/deploy/README.md`

That documentation should be treated as the source of truth for packaging and deployment hints.

The package also includes integration and behavior tests under:

- `src/livekit/test/`

Those tests validate single-node and multi-node behavior, webhook behavior, and related runtime scenarios.

## Boundary

`src/livekit` should stay focused on the conferencing runtime itself.

- It should not own the browser UI.
- It should not own the browser-facing API service.
- It should not own the on-chain registry.

Those responsibilities belong to `src/client`, `src/routes`, and `src/contract` respectively.

