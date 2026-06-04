import { useWatchlist } from "@/features/watchlist/hooks";
import { WatchlistTable } from "@/features/watchlist/components/WatchlistTable";
import { Panel } from "@/shared/components/Panel";
import { ErrorState, LoadingState } from "@/shared/components/States";
import { ApiClientError } from "@/shared/api/client";

export function WatchlistPage() {
  const { data, isLoading, error, refetch } = useWatchlist();
  const entries = data?.watchlist ?? [];

  return (
    <Panel
      title="감시 종목"
      actions={
        data ? (
          <span className="text-xs text-slate-400">
            {data.count}개 감시 중 · 봇 {data.bot_state}
            {data.degraded ? " · 연결 저하" : ""}
          </span>
        ) : null
      }
    >
      <p className="mb-3 text-sm text-slate-400">
        봇이 탐색 중인 종목과 LONG/SHORT 방향, 그리고 각 종목이 실제 진입 트리거에
        얼마나 가까운지를 보여줍니다 — 어디에 진입할지 미리 예측할 수 있습니다. 읽기 전용
        미리보기이며, 실제 주문 판단·실행은 봇이 합니다.
      </p>
      {isLoading && <LoadingState />}
      {error && (
        <ErrorState
          message={error instanceof ApiClientError ? error.message : "감시 종목을 불러오지 못했습니다"}
          onRetry={() => refetch()}
        />
      )}
      {data && <WatchlistTable entries={entries} />}
    </Panel>
  );
}
