import { useQuery } from "@tanstack/react-query";
import { api } from "@/shared/api/endpoints";
import type { BotMode } from "@/shared/api/types";

export function useDailyLog(date: string | null, mode?: BotMode) {
  return useQuery({
    queryKey: ["dailyLog", date, mode],
    queryFn: () => api.dailyLog(date as string, mode),
    enabled: !!date,
  });
}

export function useDailyCalendar(year: number, month: number, mode?: BotMode) {
  return useQuery({
    queryKey: ["dailyCalendar", year, month, mode],
    queryFn: () => api.dailyCalendar(year, month, mode),
  });
}
