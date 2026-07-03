import { randomString } from "@/lib/client-utils";
import {
  queryRentalCapacity,
  queryRentalClient,
  queryRentalPayment,
  queryRoutedAssignment,
} from "@/lib/contract-queries";
import { getCorsHeaders } from "@/lib/cors";
import { NextRequest, NextResponse } from "next/server";
import { discoverMediaCandidates } from "@/lib/media-discovery";
import { requestParticipantToken, selectBestMedia } from "@/lib/media-protocol";
import { getPersistedNodeId } from "@/lib/operator-keypair";
import {
  assignRoutedOrder,
  orderRoomAsOperator,
} from "@/lib/operator-registration";
import { verifyWalletChallenge } from "@/lib/wallet-challenge";

// Capacity used for a free "Join a Room" order placed by routes' own
// operator wallet (the free-join UI collects no capacity from the
// participant, unlike "Order a Room").
const FREE_JOIN_CAPACITY = 50;

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

    // No rentalId: free "Join a Room". The media node's broker requires an
    // on-chain-verified paid assignment for every token it issues (see
    // verifyAssignment in xaisen_broker.go), so there is no way to skip
    // payment entirely - routes' own operator wallet places a minimal real
    // rental covering the discovered cluster's exact price, so no
    // wallet/signature is needed from the participant.
    const routerNodeId = getPersistedNodeId();
    if (!routerNodeId) throw new Error("Router is not registered on-chain");
    const candidates = await discoverMediaCandidates();
    const selected = await selectBestMedia(candidates);
    const freeRentalId = await orderRoomAsOperator(
      roomName,
      FREE_JOIN_CAPACITY,
      selected.priceMist,
    );
    const assignment = await assignRoutedOrder(
      routerNodeId,
      selected.nodeId,
      selected.clusterId,
      freeRentalId,
    );
    const identity = `${participantName}__${randomParticipantPostfix ?? randomString(4)}`;
    const brokerResult = await requestParticipantToken(selected, routerNodeId, {
      assignmentDigest: assignment.digest,
      assignmentRevision: assignment.revision,
      capacity: FREE_JOIN_CAPACITY,
      identity,
      metadata,
      rentalId: freeRentalId,
      roomName,
    });
    return NextResponse.json(
      {
        serverUrl: brokerResult.serverUrl,
        roomName,
        participantToken: brokerResult.participantToken,
        participantName,
      },
      { headers: getCorsHeaders(request.headers.get("origin")) },
    );
  } catch (error) {
    if (error instanceof Error) {
      return new NextResponse(error.message, {
        status: 500,
        headers: getCorsHeaders(request.headers.get("origin")),
      });
    }
  }
}
