import { useQuery } from "@tanstack/react-query";
import { api } from "@/shared/api/endpoints";

export function useBotStatus() {
  return useQuery({
    queryKey: ["botStatus"],
    queryFn: api.botStatus,
    refetchInterval: 5000,
  });
}
