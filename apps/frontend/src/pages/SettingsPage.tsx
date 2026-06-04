import { useQuery } from "@tanstack/react-query";
import { api } from "@/shared/api/endpoints";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { DataTable, type Column } from "@/shared/components/DataTable";
import { useUiStore } from "@/shared/store/uiStore";
import type { StorageTable } from "@/shared/api/types";
import { formatDateTime } from "@/shared/utils/format";

export function SettingsPage() {
  const sidebarOpen = useUiStore((s) => s.sidebarOpen);
  const toggleSidebar = useUiStore((s) => s.toggleSidebar);
  const storage = useQuery({ queryKey: ["systemStorage"], queryFn: api.systemStorage });

  const columns: Column<StorageTable>[] = [
    { key: "name", header: "테이블", render: (t) => t.name },
    { key: "rows", header: "행 수", align: "right", render: (t) => t.rows.toLocaleString() },
    {
      key: "size",
      header: "크기(MB)",
      align: "right",
      render: (t) => (t.size_mb == null ? "—" : t.size_mb),
    },
    { key: "oldest", header: "가장 오래된 기록", render: (t) => formatDateTime(t.oldest_created_at) },
  ];

  return (
    <div className="space-y-4">
      <Panel title="화면">
        <Button variant="secondary" onClick={toggleSidebar}>
          {sidebarOpen ? "사이드바 숨기기" : "사이드바 표시"}
        </Button>
        <p className="mt-2 text-xs text-slate-500">
          API 주소: {import.meta.env.VITE_API_BASE ?? "/api"}
        </p>
      </Panel>

      <Panel title="스토리지 (시스템)">
        {storage.data && (
          <>
            <p className="mb-2 text-sm text-slate-400">
              DB 크기:{" "}
              {storage.data.database_size_mb == null
                ? "없음"
                : `${storage.data.database_size_mb} MB`}
              {" · "}마지막 정리: {formatDateTime(storage.data.retention_status.last_cleanup_at)}
            </p>
            <DataTable
              columns={columns}
              rows={storage.data.tables}
              rowKey={(t) => t.name}
              empty="테이블 없음"
            />
          </>
        )}
      </Panel>
    </div>
  );
}
