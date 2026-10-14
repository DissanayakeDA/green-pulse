import type { Metadata } from "next";
import { RegisterView } from "@/components/views/AuthView";

export const metadata: Metadata = { title: "Create an account" };

export default function Page() {
  return <RegisterView />;
}
