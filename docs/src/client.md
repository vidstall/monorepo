# `src/client`

`src/client` is the browser-facing conference application.

## Purpose

This package owns the user experience for joining and running video conferences, and provides the wallet-based interface for contract interactions.

- It renders the landing page and room entry flows.
- It connects to the routes service for room connection details, recording control, and contract transactions.
- It uses LiveKit client components and browser APIs for the media experience.
- It integrates Sui wallet connectivity for on-chain operations.

## Main Responsibilities

- Present the demo and custom connection entry points.
- Create room IDs and encode end-to-end encryption passphrases.
- Join rooms using the connection details returned by `src/routes`.
- Handle in-room UI such as device selection, recording controls, keyboard shortcuts, and debug tooling.
- Provide contract interaction forms for worker registration, room ordering, voting, and rental management.

## Package Shape

- `app/` contains the Next.js app router pages and layouts.
- `lib/` contains client utilities, hooks, and UI components.
- `styles/` contains the app styling.
- `public/` contains static assets.

## Key Flows

### Owner flow

The owner uses a Sui wallet to order a room on-chain:

1. Owner connects wallet via `@mysten/dapp-kit-react`.
2. Owner fills the "Order Room" form with room name, capacity, and payment.
3. Frontend calls the routes API to build unsigned transaction bytes.
4. Owner signs the transaction with their wallet.
5. Workers vote on room assignment (via their own wallets).
6. Once assigned, the owner shares the room link with guests.

### Guest flow

Guests join without a wallet:

1. Guest opens the room link (`/rooms/<roomName>?rentalId=<id>`).
2. Guest enters their name in the PreJoin screen.
3. Frontend fetches connection details from the routes API.
4. The routes service enforces room capacity via the `rentalId` — returns 403 if full.
5. Guest connects to the LiveKit room.

### Demo flow

Quick start without contract interaction:

- A room ID is generated on the client.
- Optional E2EE passphrase state is embedded in the route.
- The app navigates into a room page for the generated room.

### Custom connection flow

For connecting to an external LiveKit server:

- The user provides a LiveKit URL and access token.
- The app connects directly without going through the routes service.

## Contract Panel

The `ContractPanel` component (rendered on the home page) provides forms for all contract operations:

| Form | Action |
|---|---|
| Register Worker | `register-worker` |
| Hire Worker | `hire-worker` (with capacity) |
| Order Room | `order-room` |
| Cast Room Vote | `cast-room-vote` |
| Propose Role | `propose-role` (SFU, Coordinator, Router) |
| Cast Role Vote | `cast-role-vote` |
| Cancel Expired Order | `cancel-expired-order` |
| Complete Rental | `complete-rental` |
| Cancel Rental | `cancel-rental` |
| Withdraw Stake | `withdraw-stake` |

Each form builds transaction bytes via the routes API and submits through the Sui wallet for signing.

## Notable Dependencies

- `livekit-client`, `@livekit/components-react`, `@livekit/components-styles`
- `@mysten/dapp-kit-react`, `@mysten/sui`
- `@livekit/krisp-noise-filter`
- `react-hot-toast`, `tinykeys`

## Runtime Notes

- Next.js app on port 3000.
- Expects the routes service to be reachable at `NEXT_PUBLIC_ROUTES_URL` (defaults to `/api`).
- Wallet state persisted in localStorage under `xaisen-sui-wallet`.

## Integration Boundary

`src/client` should not own backend API logic.

- It consumes the routes service.
- It should stay focused on browser UX, media handling, wallet integration, and user interaction.
- Backend coordination, CORS policy, token helpers, and recording endpoints belong in `src/routes`.
