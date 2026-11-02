import { FullDashboard } from "./FullDashboard";
import { ShowcaseDashboard } from "./ShowcaseDashboard";

export function Dashboard() {
  return process.env.NEXT_PUBLIC_MODE === "full" ? <FullDashboard /> : <ShowcaseDashboard />;
}
