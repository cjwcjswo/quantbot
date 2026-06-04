import { create } from "zustand";

export type ToastKind = "info" | "success" | "warning" | "error";

export type Toast = {
  id: number;
  kind: ToastKind;
  message: string;
};

type UiState = {
  sidebarOpen: boolean;
  mobileNavOpen: boolean;
  selectedSymbol: string | null;
  toasts: Toast[];
  toggleSidebar: () => void;
  setMobileNav: (open: boolean) => void;
  setSelectedSymbol: (s: string | null) => void;
  pushToast: (kind: ToastKind, message: string) => void;
  dismissToast: (id: number) => void;
};

let toastSeq = 1;

export const useUiStore = create<UiState>((set) => ({
  sidebarOpen: true,
  mobileNavOpen: false,
  selectedSymbol: null,
  toasts: [],
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setMobileNav: (mobileNavOpen) => set({ mobileNavOpen }),
  setSelectedSymbol: (selectedSymbol) => set({ selectedSymbol }),
  pushToast: (kind, message) =>
    set((s) => ({ toasts: [...s.toasts, { id: toastSeq++, kind, message }] })),
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));
