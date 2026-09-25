import type { Metadata } from "next";
import { NewAssignmentForm } from "@/components/new-assignment-form";

export const metadata: Metadata = { title: "New assignment" };

export default async function NewAssignmentPage({
  searchParams,
}: {
  searchParams: Promise<{ course?: string | string[] }>;
}) {
  const { course } = await searchParams;
  const initialCourseId = typeof course === "string" ? course : undefined;
  return <NewAssignmentForm initialCourseId={initialCourseId} />;
}
