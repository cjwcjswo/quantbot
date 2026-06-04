import { NavLink } from "react-router-dom";
import { useUiStore } from "@/shared/store/uiStore";
import { cn } from "@/shared/utils/cn";

const LINKS = [
  { to: "/", label: "대시보드", end: true },
  { to: "/watchlist", label: "감시 종목" },
  { to: "/positions", label: "포지션" },
  { to: "/orders", label: "주문" },
  { to: "/trades", label: "체결내역" },
  { to: "/events", label: "이벤트" },
  { to: "/strategy", label: "전략 설정" },
  { to: "/settings", label: "설정" },
];

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <ul className="space-y-1 px-2">
      {LINKS.map((l) => (
        <li key={l.to}>
          <NavLink
            to={l.to}
            end={l.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                isActive
                  ? "bg-accent/10 font-medium text-accent ring-1 ring-inset ring-accent/25"
                  : "text-slate-400 hover:bg-white/[0.04] hover:text-slate-200",
              )
            }
          >
            {({ isActive }) => (
              <>
                <span
                  className={cn(
                    "h-1.5 w-1.5 rounded-full transition-colors",
                    isActive ? "bg-accent" : "bg-slate-600",
                  )}
                />
                {l.label}
              </>
            )}
          </NavLink>
        </li>
      ))}
    </ul>
  );
}

function Brand() {
  return (
    <span className="flex items-center gap-2 text-sm font-bold tracking-tight">
      <span className="h-2 w-2 rounded-full bg-accent shadow-glow" />
      <span className="bg-gradient-to-r from-accent to-indigo-400 bg-clip-text text-transparent">
        QuantBot
      </span>
    </span>
  );
}

export function Sidebar({ open }: { open: boolean }) {
  const mobileNavOpen = useUiStore((s) => s.mobileNavOpen);
  const setMobileNav = useUiStore((s) => s.setMobileNav);

  return (
    <>
      {/* Desktop rail */}
      {open && (
        <nav className="hidden w-52 shrink-0 border-r border-panelBorder/60 bg-panel/30 py-4 lg:block">
          <NavItems />
        </nav>
      )}

      {/* Mobile slide-over */}
      <div className={cn("fixed inset-0 z-40 lg:hidden", !mobileNavOpen && "pointer-events-none")}>
        <div
          className={cn(
            "absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity duration-200",
            mobileNavOpen ? "opacity-100" : "opacity-0",
          )}
          onClick={() => setMobileNav(false)}
        />
        <nav
          className={cn(
            "absolute inset-y-0 left-0 w-64 border-r border-panelBorder bg-surface py-4 shadow-2xl transition-transform duration-200 ease-out",
            mobileNavOpen ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <div className="mb-4 flex items-center justify-between px-4">
            <Brand />
            <button
              onClick={() => setMobileNav(false)}
              aria-label="메뉴 닫기"
              className="grid h-7 w-7 place-items-center rounded-lg text-slate-400 ring-1 ring-inset ring-white/10 hover:bg-white/5 hover:text-slate-200"
            >
              ✕
            </button>
          </div>
          <NavItems onNavigate={() => setMobileNav(false)} />
        </nav>
      </div>
    </>
  );
}
