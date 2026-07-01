import { getCorsHeaders } from "@/lib/cors";
import { getPublicContractConfig } from "@/lib/contract-config";
import { NextRequest, NextResponse } from "next/server";

export function OPTIONS(request: NextRequest) {
  return new NextResponse(null, {
    status: 204,
    headers: getCorsHeaders(request.headers.get("origin")),
  });
}

export function GET(request: NextRequest) {
  try {
    return NextResponse.json(getPublicContractConfig(), {
      headers: getCorsHeaders(request.headers.get("origin")),
    });
  } catch (error) {
    return new NextResponse(
      error instanceof Error ? error.message : "Contract config error",
      {
        status: 500,
        headers: getCorsHeaders(request.headers.get("origin")),
      },
    );
  }
}
