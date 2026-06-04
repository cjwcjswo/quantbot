import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/shared/api/endpoints";
import { ApiClientError } from "@/shared/api/client";
import { useUiStore } from "@/shared/store/uiStore";
import type { BotMode } from "@/shared/api/types";

type Command =
  | { kind: "start"; mode: BotMode; liveConfirm: boolean }
  | { kind: "stop"; closePositions: boolean; cancelOpenOrders: boolean }
  | { kind: "pause" }
  | { kind: "resume" }
  | { kind: "sync" };

export function useCommand() {
  const qc = useQueryClient();
  const pushToast = useUiStore((s) => s.pushToast);
  return useMutation({
    mutationFn: (cmd: Command) => {
      switch (cmd.kind) {
        case "start":
          return api.start(cmd.mode, cmd.liveConfirm);
        case "stop":
          return api.stop(cmd.closePositions, cmd.cancelOpenOrders);
        case "pause":
          return api.pause();
        case "resume":
          return api.resume();
        case "sync":
          return api.sync();
      }
    },
    onSuccess: (res) => {
      pushToast("success", `명령 접수됨: ${res.command_id.slice(0, 8)} (${res.status})`);
      qc.invalidateQueries({ queryKey: ["botStatus"] });
    },
    onError: (e) =>
      pushToast("error", e instanceof ApiClientError ? e.message : "명령 실패"),
  });
}
