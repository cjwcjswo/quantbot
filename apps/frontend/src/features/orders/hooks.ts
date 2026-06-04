import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ListQuery } from "@/shared/api/endpoints";
import { useUiStore } from "@/shared/store/uiStore";
import { ApiClientError } from "@/shared/api/client";

export function useOrders(filters: ListQuery = {}) {
  return useQuery({
    queryKey: ["orders", filters],
    queryFn: () => api.orders(filters),
    refetchInterval: 10000,
  });
}

export function useCancelOrder() {
  const qc = useQueryClient();
  const pushToast = useUiStore((s) => s.pushToast);
  return useMutation({
    mutationFn: (orderId: string) => api.cancelOrder(orderId),
    onSuccess: (res) => {
      pushToast("success", `취소 요청됨 (명령 ${res.command_id.slice(0, 8)})`);
      qc.invalidateQueries({ queryKey: ["orders"] });
    },
    onError: (e) =>
      pushToast("error", e instanceof ApiClientError ? e.message : "취소 실패"),
  });
}
