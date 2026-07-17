# Architecture Diagrams

PlantUML sequence diagrams organized by domain. Each diagram shows ONE flow clearly.

## On-Chain (`onchain/`)

| Diagram | Description |
|---|---|
| `registration-flow.puml` | Miner registration: stake, role determination, cap creation |
| `room-lifecycle.puml` | Room create (PENDING) and close (CLOSED) lifecycle |

## Off-Chain (`offchain/`)

| Diagram | Description |
|---|---|
| `cp-daemon-startup.puml` | CP daemon startup: config, registration check, heartbeat + pollers |
| `cp-daemon-runtime.puml` | CP daemon runtime: heartbeat loop, event handling, relay scoring |
| `validator-daemon-startup.puml` | Validator daemon startup: config, registration check, session wallet |
| `validator-daemon-runtime.puml` | Validator daemon runtime: measurement cycle, dual-key signing |

## Integration (`integration/`)

| Diagram | Description |
|---|---|
| `auto-registration.puml` | Full 2-step auto-registration: daemon calls chain (miner + role registry) |
| `event-polling.puml` | Daemon polls chain events via EventPoller + queryEvents |

## Rendering

Use any PlantUML renderer. For VS Code, install the PlantUML extension.

```bash
# CLI rendering (requires Java + plantuml.jar)
java -jar plantuml.jar docs/architecture/diagrams/**/*.puml
```
