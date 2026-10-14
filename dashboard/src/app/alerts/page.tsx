import type { Metadata } from "next";
import { AlertsView } from "@/components/views/AlertsView";

export const metadata: Metadata = { title: "Email alerts" };

export default function Page() {
  return <AlertsView />;
}
