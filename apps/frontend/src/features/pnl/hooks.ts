import { useQuery } from "@tanstack/react-query";
import { api } from "@/shared/api/endpoints";

export function usePnlSummary() {
  return useQuery({ queryKey: ["pnl"], queryFn: api.pnlSummary, refetchInterval: 5000 });
}

export function usePnlDaily() {
  return useQuery({ queryKey: ["pnlDaily"], queryFn: api.pnlDaily, refetchInterval: 30000 });
}
