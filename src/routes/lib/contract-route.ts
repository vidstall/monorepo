import { getCorsHeaders } from "@/lib/cors";
import { buildContractTransaction } from "@/lib/contract-transactions";
import { NextRequest, NextResponse } from "next/server";

type ContractTransactionAction =
  | "register-worker"
  | "hire-worker"
  | "complete-rental"
  | "cancel-rental"
  | "withdraw-stake";

export function options(request: NextRequest) {
  return new NextResponse(null, {
    status: 204,
    headers: getCorsHeaders(request.headers.get("origin")),
  });
}

export function postTransaction(action: ContractTransactionAction) {
  return async function POST(request: NextRequest) {
    try {
      const body = (await request.json()) as Record<string, unknown>;
      const transaction = await buildContractTransaction(action, body);
      return NextResponse.json(transaction, {
        headers: getCorsHeaders(request.headers.get("origin")),
      });
    } catch (error) {
      return new NextResponse(
        error instanceof Error ? error.message : "Contract transaction error",
        {
          status: 400,
          headers: getCorsHeaders(request.headers.get("origin")),
        },
      );
    }
  };
}
