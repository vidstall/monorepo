# `src/routes`

`src/routes` is the backend routes service for the meeting app.

## Purpose

This package exposes the HTTP API used by the client app to join and manage rooms.

- It returns connection details for LiveKit sessions.
- It handles recording control requests.
- It keeps browser-facing API logic separate from the frontend app.

## Main Responsibilities

- Provide the connection-details endpoint used by the client.
- Provide start/stop recording endpoints.
- Apply response headers and CORS behavior for browser requests.
- Translate route requests into LiveKit server-side SDK operations.

## Package Shape

- `app/` contains the Next.js route handlers and minimal pages.
- `lib/` contains shared server-side helpers.

## Key Endpoints

### `GET /api/connection-details`

Returns the LiveKit connection payload for a room.

- Generates or reuses the LiveKit server URL for the target region.
- Produces the token and room metadata needed by the client.
- Serves as the main backend handoff from the frontend into LiveKit.

### `POST /api/record/start`

Starts room recording through LiveKit egress.

- Uses the room name from the request.
- Checks for existing recordings before creating a new one.
- Returns a conflict-style failure when recording already exists.

### `POST /api/record/stop`

Stops active room recordings through LiveKit egress.

- Lists active recordings for the room.
- Stops each active egress session.
- Returns a not-found-style failure when no recording exists.

## Runtime Notes

- The package is a standalone Next.js server and runs on its own port.
- The package name in `src/routes/package.json` identifies it as the routes service.
- The default dev server runs on port `3001`.

## Integration Boundary

`src/routes` should remain the backend API boundary for the meeting app.

- It should not contain the main browser UI.
- It should not own the full conferencing experience.
- It should stay focused on request handling, LiveKit token/URL generation, and recording control.

## Dependencies

- `livekit-server-sdk`
- `next`
- `react`
- `react-dom`

