import type { DailyPnl, MonthlyPnl } from "@/shared/api/types";
import { DataTable, type Column } from "@/shared/components/DataTable";
import { formatNumber, pnlClass } from "@/shared/utils/format";

type Props = {
  daily: DailyPnl[];
  monthly: MonthlyPnl[];
};

function formatPercent(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  return `${formatNumber(value)}%`;
}

export function PnlReportTables({ daily, monthly }: Props) {
  const dailyColumns: Column<DailyPnl>[] = [
    { key: "day", header: "일자", render: (row) => row.day },
    {
      key: "start",
      header: "시작 자산",
      align: "right",
      render: (row) => formatNumber(row.start_equity),
    },
    {
      key: "current",
      header: "현재 자산",
      align: "right",
      render: (row) => formatNumber(row.current_equity),
    },
    {
      key: "net",
      header: "순손익",
      align: "right",
      render: (row) => <span className={pnlClass(row.net)}>{formatNumber(row.net)}</span>,
    },
    {
      key: "percent",
      header: "수익률",
      align: "right",
      render: (row) => <span className={pnlClass(row.net)}>{formatPercent(row.net_pnl_percent)}</span>,
    },
    {
      key: "mdd",
      header: "MDD",
      align: "right",
      render: (row) => formatPercent(row.max_drawdown_percent),
    },
  ];

  const monthlyColumns: Column<MonthlyPnl>[] = [
    { key: "month", header: "월", render: (row) => row.month },
    { key: "days", header: "일수", align: "right", render: (row) => row.days },
    { key: "start", header: "시작 자산", align: "right", render: (row) => formatNumber(row.start_equity) },
    { key: "end", header: "종료 자산", align: "right", render: (row) => formatNumber(row.end_equity) },
    {
      key: "net",
      header: "순손익",
      align: "right",
      render: (row) => <span className={pnlClass(row.net_pnl)}>{formatNumber(row.net_pnl)}</span>,
    },
    {
      key: "percent",
      header: "수익률",
      align: "right",
      render: (row) => <span className={pnlClass(row.net_pnl)}>{formatPercent(row.net_pnl_percent)}</span>,
    },
    {
      key: "mdd",
      header: "MDD",
      align: "right",
      render: (row) => formatPercent(row.max_drawdown_percent),
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <div>
        <h3 className="mb-2 text-xs font-semibold text-slate-400">일별</h3>
        <DataTable
          columns={dailyColumns}
          rows={daily.slice(0, 14)}
          rowKey={(row) => row.day}
          empty="일별 손익 데이터 없음"
        />
      </div>
      <div>
        <h3 className="mb-2 text-xs font-semibold text-slate-400">월별</h3>
        <DataTable
          columns={monthlyColumns}
          rows={monthly.slice(0, 12)}
          rowKey={(row) => row.month}
          empty="월별 손익 데이터 없음"
        />
      </div>
    </div>
  );
}
