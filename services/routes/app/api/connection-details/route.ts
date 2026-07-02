import { randomString } from "@/lib/client-utils";
import {
  queryRentalCapacity,
  queryRentalClient,
  queryRentalPayment,
  queryRoutedAssignment,
} from "@/lib/contract-queries";
import { getCorsHeaders } from "@/lib/cors";
import { getLiveKitURL } from "@/lib/getLiveKitURL";
import { ConnectionDetails } from "@/lib/types";
import {
  AccessToken,
  AccessTokenOptions,
  VideoGrant,
} from "livekit-server-sdk";
import { NextRequest, NextResponse } from "next/server";
import { discoverMediaCandidates } from "@/lib/media-discovery";
import { requestParticipantToken, selectBestMedia } from "@/lib/media-protocol";
import { getPersistedNodeId } from "@/lib/operator-keypair";
import { assignRoutedOrder } from "@/lib/operator-registration";
import { verifyWalletChallenge } from "@/lib/wallet-challenge";

const API_KEY = process.env.LIVEKIT_API_KEY;
const API_SECRET = process.env.LIVEKIT_API_SECRET;
const LIVEKIT_URL = process.env.LIVEKIT_URL;

const COOKIE_KEY = "random-participant-postfix";

export function OPTIONS(request: NextRequest) {
  return new NextResponse(null, {
    status: 204,
    headers: getCorsHeaders(request.headers.get("origin")),
  });
}

export async function GET(request: NextRequest) {
  try {
    // Parse query parameters
    const roomName = request.nextUrl.searchParams.get("roomName");
    const participantName = request.nextUrl.searchParams.get("participantName");
    const metadata = request.nextUrl.searchParams.get("metadata") ?? "";
    const region = request.nextUrl.searchParams.get("region");
    let randomParticipantPostfix = request.cookies.get(COOKIE_KEY)?.value;

    if (typeof roomName !== "string") {
      return new NextResponse("Missing required query parameter: roomName", {
        status: 400,
        headers: getCorsHeaders(request.headers.get("origin")),
      });
    }
    if (participantName === null) {
      return new NextResponse(
        "Missing required query parameter: participantName",
        {
          status: 400,
          headers: getCorsHeaders(request.headers.get("origin")),
        },
      );
    }

    const rentalId = request.nextUrl.searchParams.get("rentalId");
    if (rentalId) {
      if (!/^\d+$/.test(rentalId)) throw new Error("Invalid rentalId");
      const [capacity, payment, rentalClient] = await Promise.all([
        queryRentalCapacity(Number(rentalId)),
        queryRentalPayment(BigInt(rentalId)),
        queryRentalClient(BigInt(rentalId)),
      ]);
      if (capacity === null || payment === null || rentalClient === null)
        throw new Error("Rental could not be verified");
      const walletSignature =
        request.nextUrl.searchParams.get("walletSignature");
      const walletNonce = request.nextUrl.searchParams.get("walletNonce");
      const walletExpiresAt = Number(
        request.nextUrl.searchParams.get("walletExpiresAt"),
      );
      if (
        !walletSignature ||
        !walletNonce ||
        !Number.isSafeInteger(walletExpiresAt)
      ) {
        throw new Error("Wallet proof is required for routed rentals");
      }
      await verifyWalletChallenge(
        {
          rentalId,
          participantName,
          nonce: walletNonce,
          expiresAtMs: walletExpiresAt,
        },
        walletSignature,
        rentalClient,
      );

      const routerNodeId = getPersistedNodeId();
      if (!routerNodeId) throw new Error("Router is not registered on-chain");
      const candidates = (await discoverMediaCandidates()).filter(
        (candidate) => candidate.priceMist === payment,
      );
      const current = await queryRoutedAssignment(BigInt(rentalId));
      let selected;
      let assignment: { digest?: string; revision: number };
      const assignedCandidates = current
        ? candidates.filter(
            (candidate) =>
              candidate.clusterId === current.clusterId &&
              candidate.nodeId === current.mediaNodeId,
          )
        : [];
      if (current?.routerNodeId === routerNodeId && assignedCandidates.length) {
        try {
          selected = await selectBestMedia(assignedCandidates);
          assignment = { revision: current.revision };
        } catch {
          selected = await selectBestMedia(candidates);
          assignment = await assignRoutedOrder(
            routerNodeId,
            selected.nodeId,
            selected.clusterId,
            rentalId,
          );
        }
      } else {
        selected = await selectBestMedia(candidates);
        assignment = await assignRoutedOrder(
          routerNodeId,
          selected.nodeId,
          selected.clusterId,
          rentalId,
        );
      }
      const identity = `${participantName}__${randomParticipantPostfix ?? randomString(4)}`;
      const brokerResult = await requestParticipantToken(
        selected,
        routerNodeId,
        {
          assignmentDigest: assignment.digest,
          assignmentRevision: assignment.revision,
          capacity,
          identity,
          metadata,
          rentalId,
          roomName,
        },
      );
      return NextResponse.json(
        {
          serverUrl: brokerResult.serverUrl,
          roomName,
          participantToken: brokerResult.participantToken,
          participantName,
        },
        { headers: getCorsHeaders(request.headers.get("origin")) },
      );
    }

    if (!LIVEKIT_URL) throw new Error("LIVEKIT_URL is not defined");
    const livekitServerUrl = region
      ? getLiveKitURL(LIVEKIT_URL, region)
      : LIVEKIT_URL;
    if (livekitServerUrl === undefined) throw new Error("Invalid region");

    // Generate participant token
    if (!randomParticipantPostfix) {
      randomParticipantPostfix = randomString(4);
    }
    const participantToken = await createParticipantToken(
      {
        identity: `${participantName}__${randomParticipantPostfix}`,
        name: participantName,
        metadata,
      },
      roomName,
    );

    // Return connection details
    const data: ConnectionDetails = {
      serverUrl: livekitServerUrl,
      roomName: roomName,
      participantToken: participantToken,
      participantName: participantName,
    };
    return new NextResponse(JSON.stringify(data), {
      headers: {
        "Content-Type": "application/json",
        "Set-Cookie": buildCookieHeader(request, randomParticipantPostfix),
        ...getCorsHeaders(request.headers.get("origin")),
      },
    });
  } catch (error) {
    if (error instanceof Error) {
      return new NextResponse(error.message, {
        status: 500,
        headers: getCorsHeaders(request.headers.get("origin")),
      });
    }
  }
}

function createParticipantToken(
  userInfo: AccessTokenOptions,
  roomName: string,
) {
  const at = new AccessToken(API_KEY, API_SECRET, userInfo);
  at.ttl = "5m";
  const grant: VideoGrant = {
    room: roomName,
    roomJoin: true,
    canPublish: true,
    canPublishData: true,
    canSubscribe: true,
  };
  at.addGrant(grant);
  return at.toJwt();
}

function getCookieExpirationTime(): string {
  var now = new Date();
  var time = now.getTime();
  var expireTime = time + 60 * 120 * 1000;
  now.setTime(expireTime);
  return now.toUTCString();
}

function buildCookieHeader(request: NextRequest, value: string): string {
  const secureFlag = request.nextUrl.protocol === "https:" ? "; Secure" : "";
  return `${COOKIE_KEY}=${value}; Path=/; HttpOnly; SameSite=Strict${secureFlag}; Expires=${getCookieExpirationTime()}`;
}
