DESIGN PROPOSAL -- FE: Client Stabilization (Phase 7)
Author: FE Agent
Phase: 7
Date: 2026-03-09

PURPOSE:
  Fix six FE-only bugs so the client works correctly as a 2-peer P2P demo
  without silent failures, stale streams, or hardcoded object IDs.

OWNS:
  - config.ts: runtime configuration and env-var validation
  - App.tsx: local stream ref, join flow, error state, signaling callbacks
  - useWebRTC.ts: peer connection lifecycle, media error state, multi-peer Map
  - useSignaling.ts: WebSocket connect promise, join timing
  - useChain.ts: createRoom event extraction (remove digest fallback)
  - RoomControls.tsx: room error banner display
  - New files: .env.example, .env, .env.testnet

MODULES AFFECTED:

  1. apps/client/src/config.ts
     - Replace hardcoded object IDs with import.meta.env.VITE_* reads
     - Add validateConfig() that throws naming missing variables
     - Export typed CONFIG object

  2. apps/client/src/hooks/useWebRTC.ts
     - Replace single pcRef with Map<string, RTCPeerConnection>
     - Replace single pendingCandidates with Map<string, RTCIceCandidateInit[]>
     - Add mediaError state and clearMediaError()
     - Add cleanupPeer(peerId) for single-peer teardown
     - Wrap getUserMedia in try/catch with typed error mapping

  3. apps/client/src/hooks/useSignaling.ts
     - Change connect() to return Promise<void> (resolve on open, reject on error)

  4. apps/client/src/hooks/useChain.ts
     - Remove digest fallback in createRoom; throw when RoomCreated event missing

  5. apps/client/src/App.tsx
     - Change localStreamRef from plain object to useRef
     - await connect() before joinRoom (remove setTimeout)
     - Pass fromPeerId through onAnswer and onIceCandidate callbacks
     - Call cleanupPeer(peerId) on onPeerLeft instead of full cleanup()
     - Add roomError state; pass to RoomControls
     - Add mediaError inline banner with Retry button above VideoGrid

  6. apps/client/src/components/RoomControls.tsx
     - Accept optional roomError prop; render red inline banner when set

  7. apps/client/.env.example (NEW)
     - Template with all VITE_ variable names and comments

  8. apps/client/.env (NEW, gitignored)
     - Localnet object IDs (values from current hardcoded config.ts)

  9. apps/client/.env.testnet (NEW, gitignored)
     - Testnet object IDs (placeholder; filled from dvconf-contracts deploy)

PUBLIC API CHANGES:

  -- config.ts ----------------------------------------------------------

  BEFORE:
    export const CONFIG = {
      PACKAGE_ID: '0x7fb5...',
      NETWORK_REGISTRY_ID: '0xac62...',
      USER_REGISTRY_ID: '0x7e06...',
      ROOM_MANAGER_ID: '0x6f96...',
      SIGNALING_URL: 'ws://localhost:8080',
      SUI_NETWORK: 'localnet' as const,
    } as const;

  AFTER:
    interface AppConfig {
      PACKAGE_ID: string;
      NETWORK_REGISTRY_ID: string;
      USER_REGISTRY_ID: string;
      ROOM_MANAGER_ID: string;
      SIGNALING_URL: string;
      SUI_NETWORK: 'localnet' | 'testnet';
    }

    function validateConfig(): AppConfig {
      const required = [
        'VITE_PACKAGE_ID',
        'VITE_NETWORK_REGISTRY_ID',
        'VITE_USER_REGISTRY_ID',
        'VITE_ROOM_MANAGER_ID',
        'VITE_SIGNALING_URL',
        'VITE_SUI_NETWORK',
      ] as const;
      for (const key of required) {
        if (!import.meta.env[key]) {
          throw new Error(`Missing required environment variable: ${key}`);
        }
      }
      return {
        PACKAGE_ID: import.meta.env.VITE_PACKAGE_ID,
        NETWORK_REGISTRY_ID: import.meta.env.VITE_NETWORK_REGISTRY_ID,
        USER_REGISTRY_ID: import.meta.env.VITE_USER_REGISTRY_ID,
        ROOM_MANAGER_ID: import.meta.env.VITE_ROOM_MANAGER_ID,
        SIGNALING_URL: import.meta.env.VITE_SIGNALING_URL,
        SUI_NETWORK: import.meta.env.VITE_SUI_NETWORK as 'localnet' | 'testnet',
      };
    }

    export const CONFIG: AppConfig = validateConfig();

  -- useWebRTC.ts -------------------------------------------------------

  BEFORE:
    export function useWebRTC(): {
      localStream: MediaStream | null;
      remoteStream: MediaStream | null;
      startLocalStream: () => Promise<MediaStream>;
      createOffer: (
        stream: MediaStream,
        remotePeerId: string,
        sendOffer: (sdp: string, targetPeerId: string) => void,
        onIceCandidate: (candidate: RTCIceCandidateInit, targetPeerId: string) => void,
      ) => Promise<void>;
      handleOffer: (
        sdp: RTCSessionDescriptionInit,
        fromPeerId: string,
        stream: MediaStream,
        sendAnswer: (sdp: string, targetPeerId: string) => void,
        onIceCandidate: (candidate: RTCIceCandidateInit, targetPeerId: string) => void,
      ) => Promise<void>;
      handleAnswer: (sdp: RTCSessionDescriptionInit) => Promise<void>;
      handleIceCandidate: (candidate: RTCIceCandidateInit) => Promise<void>;
      cleanup: () => void;
    }

  AFTER:
    export function useWebRTC(): {
      localStream: MediaStream | null;
      remoteStream: MediaStream | null;
      mediaError: string | null;          // NEW (FIX-05)
      clearMediaError: () => void;         // NEW (FIX-05)
      startLocalStream: () => Promise<MediaStream | null>;  // CHANGED: returns null on error
      createOffer: (
        stream: MediaStream,
        remotePeerId: string,
        sendOffer: (sdp: string, targetPeerId: string) => void,
        onIceCandidate: (candidate: RTCIceCandidateInit, targetPeerId: string) => void,
      ) => Promise<void>;
      handleOffer: (
        sdp: RTCSessionDescriptionInit,
        fromPeerId: string,
        stream: MediaStream,
        sendAnswer: (sdp: string, targetPeerId: string) => void,
        onIceCandidate: (candidate: RTCIceCandidateInit, targetPeerId: string) => void,
      ) => Promise<void>;
      handleAnswer: (sdp: RTCSessionDescriptionInit, fromPeerId: string) => Promise<void>;  // CHANGED: added fromPeerId
      handleIceCandidate: (candidate: RTCIceCandidateInit, fromPeerId: string) => Promise<void>;  // CHANGED: added fromPeerId
      cleanup: () => void;
      cleanupPeer: (peerId: string) => void;  // NEW (FIX-04)
    }

  Internal state changes (not exported but architecturally relevant):
    - pcRef: useRef<RTCPeerConnection | null>
      --> peerConnections: useRef<Map<string, RTCPeerConnection>>(new Map())
    - pendingCandidates: useRef<RTCIceCandidateInit[]>
      --> pendingCandidates: useRef<Map<string, RTCIceCandidateInit[]>>(new Map())
    - NEW state: const [mediaError, setMediaError] = useState<string | null>(null)

  -- useSignaling.ts ----------------------------------------------------

  BEFORE:
    connect: () => void;

  AFTER:
    connect: () => Promise<void>;

  All other exports unchanged:
    joinRoom, sendOffer, sendAnswer, sendIceCandidate, disconnect, peerId, connected

  Implementation detail: store Promise resolve/reject in a ref. On ws.onopen,
  call resolve and setConnected(true). On ws.onerror before open, reject with
  Error('WebSocket connection failed'). If ws is already connected, resolve
  immediately.

  -- useChain.ts --------------------------------------------------------

  BEFORE (createRoom, line 56):
    return roomId ?? result.digest;  // fallback to digest as room ID

  AFTER:
    if (!roomId) {
      throw new Error(
        'Room created on-chain but RoomCreated event was not returned. '
        + 'Please check the transaction.'
      );
    }
    return roomId;

  Existing catch block still returns null -- callers already handle null.
  No signature change: createRoom: () => Promise<string | null>

  -- RoomControls.tsx ---------------------------------------------------

  BEFORE:
    interface Props {
      onRegister: (name: string) => Promise<boolean>;
      onCreateRoom: () => Promise<string | null>;
      onJoinRoom: (roomId: string) => void;
      registered: boolean;
      loading: boolean;
    }

  AFTER:
    interface Props {
      onRegister: (name: string) => Promise<boolean>;
      onCreateRoom: () => Promise<string | null>;
      onJoinRoom: (roomId: string) => void;
      registered: boolean;
      loading: boolean;
      roomError: string | null;  // NEW (FIX-03)
    }

  Rendering: When roomError is truthy, render a red inline banner
  (<div> with red background, white text) above the Create Room button:
    {roomError && (
      <div style={{
        background: '#dc2626', color: 'white',
        padding: '8px 12px', borderRadius: 4, fontSize: 14,
        width: '100%', textAlign: 'center',
      }}>
        {roomError}
      </div>
    )}

  -- App.tsx (integrated view of all changes) ----------------------------

  BEFORE:
    import { useState, useCallback } from 'react';
    const localStreamRef = { current: null as MediaStream | null };
    // ...
    const { ..., handleAnswer, handleIceCandidate, cleanup } = useWebRTC();
    // ...
    onAnswer: (sdp) => handleAnswer(sdp),
    onIceCandidate: (candidate) => handleIceCandidate(candidate),
    onPeerLeft: () => cleanup(),
    // ...
    connect();
    setTimeout(() => { joinRoom(roomId); setJoined(true); }, 500);

  AFTER:
    import { useState, useCallback, useRef } from 'react';  // CHANGED: add useRef
    const localStreamRef = useRef<MediaStream | null>(null);  // CHANGED: useRef
    const [roomError, setRoomError] = useState<string | null>(null);  // NEW
    // ...
    const {
      ..., mediaError, clearMediaError,
      handleAnswer, handleIceCandidate, cleanup, cleanupPeer,
    } = useWebRTC();  // CHANGED: destructure new returns
    // ...
    onAnswer: (sdp, fromPeerId) => handleAnswer(sdp, fromPeerId),  // CHANGED: pass fromPeerId
    onIceCandidate: (candidate, fromPeerId) => handleIceCandidate(candidate, fromPeerId),  // CHANGED
    onPeerLeft: (peerId) => {
      cleanupPeer(peerId);              // CHANGED: per-peer cleanup
      setRemoteStream(null);            // clear video immediately (Peer Disconnect decision)
    },
    // ...
    // handleJoin rewritten:
    const handleJoin = useCallback(async (roomId: string) => {
      const stream = await startLocalStream();
      if (!stream) return;                   // NEW: bail on camera error
      localStreamRef.current = stream;
      await connect();                       // CHANGED: await Promise, no setTimeout
      joinRoom(roomId);
      setJoined(true);
    }, [startLocalStream, connect, joinRoom]);

    // handleCreateRoom wrapper:
    const handleCreateRoom = useCallback(async () => {
      setRoomError(null);                    // clear-on-next-action
      const id = await createRoom();
      if (!id) setRoomError('Room creation failed. Check wallet and try again.');
      return id;
    }, [createRoom]);

    // JSX additions:
    // 1. Media error banner above VideoGrid:
    {mediaError && (
      <div style={{
        background: '#dc2626', color: 'white',
        padding: '8px 12px', borderRadius: 4, margin: '8px auto',
        maxWidth: 600, textAlign: 'center',
      }}>
        {mediaError}
        <button onClick={() => { clearMediaError(); startLocalStream(); }}
          style={{ marginLeft: 8, ... }}>
          Retry
        </button>
      </div>
    )}

    // 2. RoomControls receives new props:
    <RoomControls
      onRegister={handleRegister}
      onCreateRoom={handleCreateRoom}   // CHANGED: wrapper that manages roomError
      onJoinRoom={handleJoin}
      registered={registered}
      loading={loading}
      roomError={roomError}             // NEW
    />

TYPES ADDED/CHANGED:

  NEW: AppConfig (config.ts)
    interface AppConfig {
      PACKAGE_ID: string;
      NETWORK_REGISTRY_ID: string;
      USER_REGISTRY_ID: string;
      ROOM_MANAGER_ID: string;
      SIGNALING_URL: string;
      SUI_NETWORK: 'localnet' | 'testnet';
    }

  CHANGED: RoomControls Props (RoomControls.tsx)
    + roomError: string | null

  CHANGED: useWebRTC return type
    + mediaError: string | null
    + clearMediaError: () => void
    + cleanupPeer: (peerId: string) => void
    ~ startLocalStream: () => Promise<MediaStream | null>   (was Promise<MediaStream>)
    ~ handleAnswer: added fromPeerId parameter
    ~ handleIceCandidate: added fromPeerId parameter

  CHANGED: useSignaling return type
    ~ connect: () => Promise<void>   (was () => void)

  UNCHANGED: SignalingCallbacks interface (already has fromPeerId on all callbacks)
  UNCHANGED: VideoGrid Props
  UNCHANGED: useChain return type (createRoom still returns Promise<string | null>)

DEPENDS ON:

  External packages (no version changes, already in package.json):
    - @mysten/dapp-kit (wallet connect, signAndExecuteTransaction)
    - @mysten/sui/transactions (Transaction builder)
    - @tanstack/react-query (QueryClient)
    - react, react-dom (18.x)
    - vite + @vitejs/plugin-react (build tooling, env var loading)

  Build tooling:
    - Vite import.meta.env for VITE_* variable injection
    - Vite --mode flag for .env.testnet loading (vite --mode testnet)

  Runtime:
    - Browser WebRTC API (RTCPeerConnection, getUserMedia)
    - Browser WebSocket API
    - Signaling server at VITE_SIGNALING_URL (unchanged protocol)

INTEGRATION CONTRACTS:

  1. App.tsx -> useWebRTC()
     App destructures: { localStream, remoteStream, mediaError, clearMediaError,
       startLocalStream, createOffer, handleOffer, handleAnswer,
       handleIceCandidate, cleanup, cleanupPeer }
     App passes fromPeerId from signaling callbacks to handleAnswer/handleIceCandidate.
     App calls cleanupPeer(peerId) on peer-left (not full cleanup()).
     App guards handleJoin on startLocalStream returning null.

  2. App.tsx -> useSignaling(callbacks)
     callbacks shape unchanged (SignalingCallbacks interface already correct).
     App now passes fromPeerId through onAnswer and onIceCandidate lambdas
     (previously dropped the second argument).
     connect() is now awaited: `await connect()` before `joinRoom(roomId)`.

  3. App.tsx -> useChain()
     Return shape unchanged. createRoom() may now throw internally but the
     catch block returns null -- App checks null and sets roomError state.
     New wrapper handleCreateRoom clears roomError before calling createRoom.

  4. App.tsx -> RoomControls
     New prop: roomError: string | null.
     onCreateRoom now points to handleCreateRoom (wrapper), not raw createRoom.

  5. App.tsx -> VideoGrid
     Props unchanged: { localStream, remoteStream }.
     remoteStream is set to null on peer-left for immediate video removal.

  6. config.ts -> all hooks (useChain, useSignaling)
     CONFIG export shape unchanged (same property names).
     Type changes from literal to union ('localnet' | 'testnet') but all
     consumers use it as string -- no breakage.

  7. main.tsx -> config.ts
     main.tsx uses CONFIG.SUI_NETWORK for defaultNetwork. The union type
     'localnet' | 'testnet' is compatible with createNetworkConfig keys.
     NOTE: main.tsx currently hardcodes defaultNetwork: "localnet" -- should
     be updated to use CONFIG.SUI_NETWORK for consistency. (Minor change,
     included in Task 1.)

ERROR HANDLING:

  Camera/Mic errors (FIX-05, useWebRTC.startLocalStream):
    Error mapping:
      NotAllowedError     -> 'Camera/microphone permission denied'
      NotFoundError       -> 'No camera or microphone found'
      NotReadableError    -> 'Camera is already in use'
      (other DOMException) -> 'Could not access camera/microphone'
    Display: Red inline banner above VideoGrid in App.tsx.
    Retry: Button in banner calls clearMediaError() then startLocalStream().
    Clear: Banner disappears when mediaError becomes null (clear-on-next-action).

  Room creation errors (FIX-03, useChain.createRoom):
    Missing RoomCreated event -> throw Error (caught by existing catch -> returns null)
    Wallet rejection -> caught by existing catch -> returns null
    Any other TX error -> caught by existing catch -> returns null
    Display: Red inline banner above Create Room button in RoomControls.
    Clear: App.tsx sets roomError to null before each createRoom attempt.

  WebSocket connection errors (FIX-02, useSignaling.connect):
    WebSocket error before open -> Promise rejects with Error('WebSocket connection failed')
    Caller (handleJoin in App.tsx) should catch and display error.
    NOTE: handleJoin currently has no try/catch -- needs one added.
    On rejection: set a joinError state or reuse a general error display.

  Config validation errors (FIX-06, config.ts):
    Missing VITE_ variable -> throw Error('Missing required environment variable: VITE_...')
    This runs at module import time -- app will not render. Error appears in
    browser console and Vite overlay. No UI banner needed (developer-facing error).

OPEN QUESTIONS:

  1. main.tsx defaultNetwork: Currently hardcoded to "localnet". Should Task 1
     update it to read CONFIG.SUI_NETWORK? Proposal assumes yes for consistency,
     but this is a minor scope addition. Needs Architect confirmation.

  2. handleJoin error handling: If await connect() rejects (WebSocket failure),
     there is no catch block in handleJoin currently. The PLAN.md does not
     specify a joinError state. Proposal recommends wrapping handleJoin in
     try/catch and displaying the error via the mediaError banner (reuse) or
     a separate joinError state. Needs Architect decision on which pattern.

  3. onPeerLeft and remoteStream: The proposal sets remoteStream to null on
     peer-left via cleanupPeer. But setRemoteStream is internal to useWebRTC
     -- App.tsx cannot call it directly. Options:
       (a) cleanupPeer also sets remoteStream to null internally (simple, but
           assumes single remote -- fine for Phase 7 1+1 grid)
       (b) cleanupPeer returns void, App reads remoteStream from hook state
           which auto-updates (cleanupPeer triggers re-render)
     Proposal recommends option (a): cleanupPeer sets remoteStream to null
     when the Map becomes empty. This keeps the API clean for Phase 7.

  4. .env vs .env.local naming: PLAN.md flagged that .env.local conflicts with
     Vite built-in behavior (Vite auto-loads .env.local in all modes with
     highest priority). Decision: use plain .env for localnet defaults and
     .env.testnet for testnet mode override. The .env file IS committed (as
     development defaults) or gitignored per team preference. .env.testnet is
     always gitignored. This matches PLAN.md resolution. Needs final Architect
     sign-off on whether .env is committed or gitignored.
