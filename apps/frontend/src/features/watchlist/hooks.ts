import { useQuery } from "@tanstack/react-query";
import { api } from "@/shared/api/endpoints";

export function useWatchlist() {
  return useQuery({ queryKey: ["watchlist"], queryFn: api.watchlist, refetchInterval: 5000 });
}
