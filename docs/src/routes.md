# `src/routes`

`src/routes` is the backend routes service for the meeting app.

## Purpose

This package exposes the HTTP API used by the client app to join rooms, manage recordings, and interact with the Sui contract.

- It returns connection details for LiveKit sessions with capacity enforcement.
- It builds unsigned Sui transaction bytes for client-side wallet signing.
- It handles recording control requests.
- It exposes public contract configuration.

## Package Shape

- `app/` contains the Next.js route handlers and minimal pages.
- `lib/` contains shared server-side helpers.

## Key Endpoints

### `GET /api/connection-details`

Returns the LiveKit connection payload for a room.

- Query params: `roomName`, `participantName`, `metadata` (optional), `region` (optional), `rentalId` (optional)
- Generates a participant token with a 5-minute TTL.
- If `rentalId` is provided, queries the contract for room capacity and checks current participant count via LiveKit's `RoomServiceClient`. Returns 403 if the room is at capacity.

### `GET /api/contract/config`

Returns public contract configuration: network, package ID, registry object ID, deployer address, publish digest.

### `GET /api/contract/health`

Returns contract config plus a `configured` boolean and optional error.

### Contract Transaction Endpoints

All accept `POST` with a JSON body including `sender` (Sui address). Return `{ network, packageId, registryObjectId, txBytes }` for client-side signing.

| Endpoint | Body fields |
|---|---|
| `POST /api/contract/transactions/register-worker` | `metadataUri`, `metadataHash`, `pricePerRentalMist`, `stakeMist` |
| `POST /api/contract/transactions/hire-worker` | `nodeId`, `roomName`, `capacity`, `paymentMist` |
| `POST /api/contract/transactions/order-room` | `roomName`, `capacity`, `paymentMist` |
| `POST /api/contract/transactions/cast-room-vote` | `voterNodeId`, `rentalId`, `nomineeNodeId` |
| `POST /api/contract/transactions/propose-role` | `proposerNodeId`, `nomineeNodeId`, `role` |
| `POST /api/contract/transactions/cast-role-vote` | `voterNodeId`, `proposalId` |
| `POST /api/contract/transactions/cancel-expired-order` | `rentalId` |
| `POST /api/contract/transactions/complete-rental` | `rentalId` |
| `POST /api/contract/transactions/cancel-rental` | `rentalId` |
| `POST /api/contract/transactions/withdraw-stake` | `nodeId` |

### Recording

- `GET /api/record/start?roomName=<name>` — start room recording to S3.
- `GET /api/record/stop?roomName=<name>` — stop active recordings.

## Key Libraries

- `lib/contract-config.ts` — loads contract config from `secrets/contract/<network>.env`
- `lib/contract-transactions.ts` — builds Move call transactions for all contract actions
- `lib/contract-queries.ts` — reads contract state via `devInspectTransactionBlock` (e.g., rental capacity)
- `lib/contract-route.ts` — CORS-aware route handler factory for transaction endpoints
- `lib/cors.ts` — CORS header configuration
- `lib/getLiveKitURL.ts` — LiveKit URL resolution with optional region

## Runtime Notes

- Next.js standalone server on port 3001.
- Reads `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_URL` from environment.
- Reads contract config from `secrets/contract/<network>.env` or `CONTRACT_ENV_PATH`.

## Integration Boundary

`src/routes` should remain the backend API boundary.

- It should not contain the browser UI.
- It should stay focused on request handling, token generation, transaction building, and recording control.
