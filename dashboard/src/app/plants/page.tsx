import type { Metadata } from "next";
import { PlantsView } from "@/components/views/PlantsView";

export const metadata: Metadata = { title: "Plant profiles" };

export default function Page() {
  return <PlantsView />;
}
