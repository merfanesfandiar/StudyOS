import type { Metadata } from "next";
import { AssignmentDetail } from "@/components/assignment-detail";

export const metadata: Metadata = { title: "Assignment" };

export default async function AssignmentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AssignmentDetail assignmentId={id} />;
}
