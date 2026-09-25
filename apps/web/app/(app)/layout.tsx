import type { Metadata } from "next";
import { ProtectedShell } from "@/components/app-shell";

export const metadata: Metadata = { title: "StudyOS" };

export default function ApplicationLayout({ children }: { children: React.ReactNode }) {
  return <ProtectedShell>{children}</ProtectedShell>;
}
