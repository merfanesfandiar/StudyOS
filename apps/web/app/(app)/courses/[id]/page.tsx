import type { Metadata } from "next";
import { CourseDetail } from "@/components/course-detail";

export const metadata: Metadata = { title: "Course" };

export default async function CoursePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CourseDetail courseId={id} />;
}
