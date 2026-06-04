import { useQuery } from "@tanstack/react-query";
import { api, type ListQuery } from "@/shared/api/endpoints";

export function useEvents(filters: ListQuery = {}) {
  return useQuery({
    queryKey: ["events", filters],
    queryFn: () => api.events(filters),
    refetchInterval: 15000,
  });
}
