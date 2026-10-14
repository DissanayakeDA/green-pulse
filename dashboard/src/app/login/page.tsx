import type { Metadata } from "next";
import { SignInView } from "@/components/views/AuthView";

export const metadata: Metadata = { title: "Sign in" };

export default function Page() {
  return <SignInView />;
}
