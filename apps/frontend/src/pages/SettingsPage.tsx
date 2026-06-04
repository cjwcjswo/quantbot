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
    { key: "name", header: "Table", render: (t) => t.name },
    { key: "rows", header: "Rows", align: "right", render: (t) => t.rows.toLocaleString() },
    {
      key: "size",
      header: "Size (MB)",
      align: "right",
      render: (t) => (t.size_mb == null ? "—" : t.size_mb),
    },
    { key: "oldest", header: "Oldest", render: (t) => formatDateTime(t.oldest_created_at) },
  ];

  return (
    <div className="space-y-4">
      <Panel title="Display">
        <Button variant="secondary" onClick={toggleSidebar}>
          {sidebarOpen ? "Hide sidebar" : "Show sidebar"}
        </Button>
        <p className="mt-2 text-xs text-slate-500">
          API base: {import.meta.env.VITE_API_BASE ?? "/api"}
        </p>
      </Panel>

      <Panel title="Storage (system)">
        {storage.data && (
          <>
            <p className="mb-2 text-sm text-slate-400">
              Database size:{" "}
              {storage.data.database_size_mb == null
                ? "n/a"
                : `${storage.data.database_size_mb} MB`}
              {" · "}last cleanup: {formatDateTime(storage.data.retention_status.last_cleanup_at)}
            </p>
            <DataTable
              columns={columns}
              rows={storage.data.tables}
              rowKey={(t) => t.name}
              empty="No tables."
            />
          </>
        )}
      </Panel>
    </div>
  );
}
