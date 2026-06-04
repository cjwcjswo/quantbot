import { createBrowserRouter } from "react-router-dom";
import { Layout } from "@/shared/components/Layout";
import { DashboardPage } from "@/pages/DashboardPage";
import { PositionsPage } from "@/pages/PositionsPage";
import { OrdersPage } from "@/pages/OrdersPage";
import { TradesPage } from "@/pages/TradesPage";
import { EventsPage } from "@/pages/EventsPage";
import { StrategyConfigPage } from "@/pages/StrategyConfigPage";
import { SettingsPage } from "@/pages/SettingsPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "positions", element: <PositionsPage /> },
      { path: "orders", element: <OrdersPage /> },
      { path: "trades", element: <TradesPage /> },
      { path: "events", element: <EventsPage /> },
      { path: "strategy", element: <StrategyConfigPage /> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
]);
