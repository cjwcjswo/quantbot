import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/shared/api/endpoints";
import { ApiClientError } from "@/shared/api/client";
import { useUiStore } from "@/shared/store/uiStore";

export function useStrategyConfig() {
  return useQuery({ queryKey: ["strategyConfig"], queryFn: api.strategyConfig });
}

export function usePatchConfig() {
  const qc = useQueryClient();
  const pushToast = useUiStore((s) => s.pushToast);
  return useMutation({
    mutationFn: ({
      version,
      patch,
      reason,
    }: {
      version: number;
      patch: Record<string, unknown>;
      reason: string;
    }) => api.patchConfig(version, patch, reason),
    onSuccess: (res) => {
      pushToast("success", `설정 v${res.config_version} 변경 요청됨 (RELOAD_CONFIG)`);
      qc.invalidateQueries({ queryKey: ["strategyConfig"] });
    },
    onError: (e) =>
      pushToast(
        "error",
        e instanceof ApiClientError ? `${e.code}: ${e.message}` : "설정 변경 실패",
      ),
  });
}
