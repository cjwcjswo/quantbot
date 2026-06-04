import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { DailyPnl } from "@/shared/api/types";
import { EmptyState } from "@/shared/components/States";

export function PnlChart({ daily }: { daily: DailyPnl[] }) {
  if (daily.length === 0) return <EmptyState label="아직 일일 손익 데이터가 없습니다." />;
  const data = [...daily]
    .sort((a, b) => a.day.localeCompare(b.day))
    .map((d) => ({ day: d.day, net: Number(d.net) }));

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
        <CartesianGrid stroke="#1e293b" vertical={false} />
        <XAxis dataKey="day" tick={{ fill: "#64748b", fontSize: 11 }} stroke="#334155" />
        <YAxis tick={{ fill: "#64748b", fontSize: 11 }} stroke="#334155" />
        <Tooltip
          contentStyle={{
            background: "#0f172a",
            border: "1px solid #1e293b",
            borderRadius: 6,
            color: "#e2e8f0",
          }}
        />
        <Line type="monotone" dataKey="net" stroke="#38bdf8" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
