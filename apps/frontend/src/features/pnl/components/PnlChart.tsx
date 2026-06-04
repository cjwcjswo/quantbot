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
        <defs>
          <linearGradient id="pnlLine" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#22d3ee" />
            <stop offset="100%" stopColor="#818cf8" />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#1A2333" vertical={false} />
        <XAxis dataKey="day" tick={{ fill: "#64748b", fontSize: 11 }} stroke="#1A2333" />
        <YAxis tick={{ fill: "#64748b", fontSize: 11 }} stroke="#1A2333" />
        <Tooltip
          cursor={{ stroke: "#22d3ee", strokeOpacity: 0.25 }}
          contentStyle={{
            background: "#0C1220",
            border: "1px solid #1A2333",
            borderRadius: 10,
            color: "#e2e8f0",
            fontSize: 12,
          }}
        />
        <Line type="monotone" dataKey="net" stroke="url(#pnlLine)" strokeWidth={2.5} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
