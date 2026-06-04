import { useQuery } from "@tanstack/react-query";
import { api, type ListQuery } from "@/shared/api/endpoints";

export function useTrades(filters: ListQuery = {}) {
  return useQuery({
    queryKey: ["trades", filters],
    queryFn: () => api.trades(filters),
    refetchInterval: 15000,
  });
}

export function useFills(filters: ListQuery = {}) {
  return useQuery({ queryKey: ["fills", filters], queryFn: () => api.fills(filters) });
}

export function useTradeDetail(tradeId: string | null) {
  return useQuery({
    queryKey: ["tradeDetail", tradeId],
    queryFn: () => api.tradeDetail(tradeId as string),
    enabled: !!tradeId,
  });
}
