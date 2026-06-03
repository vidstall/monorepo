# `src/client`

`src/client` is the browser-facing conference application.

## Purpose

This package owns the user experience for joining and running video conferences.

- It renders the landing page and room entry flows.
- It connects to the routes service for room connection details, recording control, and server-side coordination.
- It uses LiveKit client components and browser APIs for the media experience.

## Main Responsibilities

- Present the demo and custom connection entry points.
- Create room IDs and encode end-to-end encryption passphrases.
- Join rooms using the connection details returned by `src/routes`.
- Handle in-room UI such as device selection, recording controls, keyboard shortcuts, and debug tooling.

## Package Shape

- `app/` contains the Next.js app router pages and layouts.
- `lib/` contains client utilities, hooks, and UI components.
- `styles/` contains the app styling.
- `public/` contains static assets.

## Key Flows

### Demo flow

The home page lets a user start a meeting without a custom server configuration.

- A room ID is generated on the client.
- Optional E2EE passphrase state is embedded in the route.
- The app navigates into a room page for the generated room.

### Custom connection flow

The home page also supports connecting to a custom LiveKit server.

- The user provides a LiveKit URL and access token.
- The app navigates to a custom meeting page with those parameters.
- Optional E2EE passphrase state is preserved in the URL fragment.

### Room flow

Room pages fetch connection details from the routes service.

- The client resolves the backend endpoint through `getRoutesEndpoint()`.
- The room page calls the routes API to get the LiveKit connection payload.
- Recording actions are sent back to the routes service when enabled.

## Notable Dependencies

- `livekit-client`
- `@livekit/components-react`
- `@livekit/components-styles`
- `react-hot-toast`
- `tinykeys`

## Runtime Notes

- The package is a Next.js app intended to run as a standalone frontend service.
- Local development uses the default Next.js client workflow from `src/client/package.json`.
- The package expects the routes service to be reachable separately.

## Integration Boundary

`src/client` should not own backend API logic.

- It consumes the routes service.
- It should stay focused on browser UX, media handling, and user interaction.
- Backend coordination, CORS policy, token helpers, and recording endpoints belong in `src/routes`.

