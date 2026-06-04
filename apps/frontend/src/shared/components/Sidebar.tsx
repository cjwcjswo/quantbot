import { NavLink } from "react-router-dom";
import { cn } from "@/shared/utils/cn";

const LINKS = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/positions", label: "Positions" },
  { to: "/orders", label: "Orders" },
  { to: "/trades", label: "Trades" },
  { to: "/events", label: "Events" },
  { to: "/strategy", label: "Strategy Config" },
  { to: "/settings", label: "Settings" },
];

export function Sidebar({ open }: { open: boolean }) {
  if (!open) return null;
  return (
    <nav className="w-48 shrink-0 border-r border-panelBorder bg-panel py-3">
      <ul className="space-y-1 px-2">
        {LINKS.map((l) => (
          <li key={l.to}>
            <NavLink
              to={l.to}
              end={l.end}
              className={({ isActive }) =>
                cn(
                  "block rounded px-3 py-2 text-sm",
                  isActive
                    ? "bg-sky-600/20 text-sky-300"
                    : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200",
                )
              }
            >
              {l.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
