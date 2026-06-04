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
      title="Watchlist"
      actions={
        data ? (
          <span className="text-xs text-slate-400">
            {data.count} watched · bot {data.bot_state}
            {data.degraded ? " · degraded" : ""}
          </span>
        ) : null
      }
    >
      <p className="mb-3 text-sm text-slate-400">
        Symbols the bot is scanning, their LONG/SHORT lean, and how close each is to a real
        entry trigger — so you can anticipate where it may enter. This is a read-only preview;
        the bot still decides and places every order.
      </p>
      {isLoading && <LoadingState />}
      {error && (
        <ErrorState
          message={error instanceof ApiClientError ? error.message : "Failed to load watchlist"}
          onRetry={() => refetch()}
        />
      )}
      {data && <WatchlistTable entries={entries} />}
    </Panel>
  );
}
