import type { Metadata } from "next";
import { WateringView } from "@/components/views/WateringView";

export const metadata: Metadata = { title: "Watering" };

export default function Page() {
  return <WateringView />;
}
