import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/shared/api/endpoints";
import { useUiStore } from "@/shared/store/uiStore";
import { ApiClientError } from "@/shared/api/client";

export function usePositions() {
  return useQuery({ queryKey: ["positions"], queryFn: api.positions, refetchInterval: 5000 });
}

export function useClosePosition() {
  const qc = useQueryClient();
  const pushToast = useUiStore((s) => s.pushToast);
  return useMutation({
    mutationFn: ({ symbol, percent }: { symbol: string; percent: number }) =>
      api.closePosition(symbol, percent),
    onSuccess: (res) => {
      pushToast("success", `청산 요청됨 (명령 ${res.command_id.slice(0, 8)})`);
      qc.invalidateQueries({ queryKey: ["positions"] });
    },
    onError: (e) =>
      pushToast("error", e instanceof ApiClientError ? e.message : "청산 실패"),
  });
}
