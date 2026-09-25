export type AssignmentStatus = "DRAFT" | "ACTIVE" | "COMPLETED" | "ARCHIVED";
export type RequirementPriority = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type RequirementType =
  | "FUNCTIONAL"
  | "TECHNICAL"
  | "DESIGN"
  | "DOCUMENTATION"
  | "CONSTRAINT"
  | "OTHER";

export interface User {
  id: string;
  name: string;
  email: string;
  created_at: string;
  updated_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

export interface Course {
  id: string;
  workspace_id: string;
  name: string;
  code: string;
  description: string | null;
  created_at: string;
  updated_at: string;
  assignment_count: number;
}

export interface CourseInput {
  name: string;
  code: string;
  description?: string | null;
}

export interface Requirement {
  id: string;
  assignment_id: string;
  title: string;
  description: string | null;
  priority: RequirementPriority;
  type: RequirementType;
  created_at: string;
  updated_at: string;
}

export interface RequirementInput {
  title: string;
  description?: string | null;
  priority: RequirementPriority;
  type: RequirementType;
}

export interface Constraint {
  id: string;
  assignment_id: string;
  title: string;
  description: string;
  value: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConstraintInput {
  title: string;
  description: string;
  value?: string | null;
}

export interface Criterion {
  id: string;
  assignment_id: string;
  title: string;
  description: string | null;
  weight: number;
  created_at: string;
  updated_at: string;
}

export interface CriterionInput {
  title: string;
  description?: string | null;
  weight: number | string;
}

export interface Assignment {
  id: string;
  title: string;
  deadline: string | null;
  status: AssignmentStatus;
  course_id: string;
  course_name: string;
  course_code: string;
  workspace_id: string;
  description: string | null;
  created_at: string;
  updated_at: string;
  requirements: Requirement[];
  constraints: Constraint[];
  criteria: Criterion[];
  documents: Document[];
  criteria_total: number;
}

export interface AssignmentInput {
  course_id: string;
  title: string;
  description?: string | null;
  deadline?: string | null;
  status?: AssignmentStatus;
}

export interface Document {
  id: string;
  assignment_id: string;
  filename: string;
  mime_type: string;
  size: number;
  created_at: string;
}

export interface Dashboard {
  upcoming_assignments: Assignment[];
  recent_assignments: Assignment[];
  courses_count: number;
  assignments_count: number;
  active_assignments_count: number;
  completed_assignments_count: number;
  completion_percentage: number;
  unread_notifications_count: number;
}

export interface Notification {
  id: string;
  type: string;
  title: string;
  message: string;
  read_at: string | null;
  created_at: string;
}
