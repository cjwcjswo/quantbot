import { useMemo, useState } from "react";
import type { BotMode } from "@/shared/api/types";
import { useDailyCalendar } from "./hooks";
import { Button } from "@/shared/components/Button";
import { pnlClass } from "@/shared/utils/format";

function daysInMonth(year: number, month: number): number {
  return new Date(year, month, 0).getDate();
}

export function Calendar({
  mode,
  onSelectDate,
}: {
  mode?: BotMode;
  onSelectDate: (date: string) => void;
}) {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);
  const { data } = useDailyCalendar(year, month, mode);

  const byDate = useMemo(() => {
    const m = new Map<string, (typeof items)[number]>();
    const items = data?.items ?? [];
    for (const it of items) m.set(it.date, it);
    return m;
  }, [data]);

  const total = daysInMonth(year, month);
  const cells = Array.from({ length: total }, (_, i) => i + 1);

  const prev = () => {
    if (month === 1) {
      setYear((y) => y - 1);
      setMonth(12);
    } else setMonth((mo) => mo - 1);
  };
  const next = () => {
    if (month === 12) {
      setYear((y) => y + 1);
      setMonth(1);
    } else setMonth((mo) => mo + 1);
  };

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <Button variant="secondary" onClick={prev}>
          ‹
        </Button>
        <span className="text-sm font-medium">
          {year}-{String(month).padStart(2, "0")}
        </span>
        <Button variant="secondary" onClick={next}>
          ›
        </Button>
      </div>
      <div className="grid grid-cols-7 gap-1">
        {cells.map((d) => {
          const date = `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
          const it = byDate.get(date);
          return (
            <button
              key={d}
              onClick={() => onSelectDate(date)}
              className="flex h-14 flex-col rounded border border-panelBorder bg-bg p-1 text-left text-xs hover:border-sky-500"
            >
              <span className="text-slate-500">{d}</span>
              {it && (
                <>
                  <span className={pnlClass(it.net_pnl)}>{it.net_pnl}</span>
                  <span className="mt-auto flex gap-0.5">
                    {it.has_warning && <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />}
                    {it.has_error && <span className="h-1.5 w-1.5 rounded-full bg-red-500" />}
                    {it.manual_intervention_count > 0 && (
                      <span className="h-1.5 w-1.5 rounded-full bg-purple-400" />
                    )}
                  </span>
                </>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
