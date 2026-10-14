import type { Metadata } from "next";
import { ReadingsView } from "@/components/views/ReadingsView";

export const metadata: Metadata = { title: "Readings" };

export default function Page() {
  return <ReadingsView />;
}
