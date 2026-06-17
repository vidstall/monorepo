import { options, postTransaction } from "@/lib/contract-route";

export const OPTIONS = options;
export const POST = postTransaction("cancel-expired-order");
