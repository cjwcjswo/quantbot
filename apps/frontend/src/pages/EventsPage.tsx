import { useState } from "react";
import { useEvents } from "@/features/events/hooks";
import { EventsTable } from "@/features/events/components/EventsTable";
import { Panel } from "@/shared/components/Panel";
import { SelectInput, TextInput } from "@/shared/components/Field";
import { ErrorState, LoadingState } from "@/shared/components/States";
import { ApiClientError } from "@/shared/api/client";

const SEVERITIES = ["INFO", "WARNING", "ERROR", "CRITICAL"];

export function EventsPage() {
  const [symbol, setSymbol] = useState("");
  const [eventType, setEventType] = useState("");
  const [severity, setSeverity] = useState("");

  const { data, isLoading, error, refetch } = useEvents({
    symbol: symbol || undefined,
    event_type: eventType || undefined,
    severity: severity || undefined,
    limit: 200,
  });

  return (
    <Panel title="이벤트">
      <div className="mb-3 flex flex-wrap gap-3">
        <TextInput label="종목" value={symbol} onChange={setSymbol} placeholder="BTCUSDT" />
        <TextInput
          label="이벤트 유형"
          value={eventType}
          onChange={setEventType}
          placeholder="TPSL_SET"
        />
        <SelectInput
          label="심각도"
          value={severity}
          onChange={setSeverity}
          options={SEVERITIES}
        />
      </div>

      {isLoading && <LoadingState />}
      {error && (
        <ErrorState
          message={error instanceof ApiClientError ? error.message : "이벤트를 불러오지 못했습니다"}
          onRetry={() => refetch()}
        />
      )}
      {data && <EventsTable events={data.events} />}
    </Panel>
  );
}
