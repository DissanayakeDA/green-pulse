import type { Metadata } from "next";
import { PlantView } from "@/components/views/PlantView";

export const metadata: Metadata = { title: "Plant & device" };

export default function Page() {
  return <PlantView />;
}
