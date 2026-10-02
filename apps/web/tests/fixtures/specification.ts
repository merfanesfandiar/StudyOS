import type {
  AssignmentAnalysis,
  AssignmentSpecification,
  DependencyGraph,
} from "../../lib/types";
import type { WorkPlan } from "../../lib/planning-types";

/**
 * A populated assignment specification, shaped by the API's own response schema.
 *
 * The field names and enum values are copied from
 * `AssignmentSpecificationResponse` rather than invented, because a plausible
 * but wrong fixture is worse than no fixture: the page throws, Next replaces the
 * route with its own English error page, and the Persian scan reports a
 * translation failure that is really a bad mock. That already happened once,
 * with a hand-written dashboard stub.
 *
 * The user-supplied text is Persian on purpose. A Persian session means a
 * Persian user, who typed Persian requirements -- so the fixture is Persian
 * throughout, and any English left on the page is chrome that failed to
 * translate rather than content that was never ours to translate. Filling this
 * with English sample text instead would make the scan flag the fixture.
 *
 * Exactly one item per collection is enough. The scan looks for leftover
 * chrome, and a list of five of the same thing does not surface a new string.
 */

const ID = {
  assignment: "3b1f5a2c-7d84-4e19-9c0a-1f2e3d4b5a60",
  course: "9a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
  requirement: "aa11bb22-cc33-4d44-9e55-ff6677889900",
  child: "bb22cc33-dd44-4e55-8f66-001122334455",
  constraint: "cc33dd44-ee55-4f66-9a77-112233445566",
  criterion: "dd44ee55-ff66-4a77-8b88-223344556677",
  deliverable: "ee55ff66-0077-4a88-9b99-334455667788",
  technology: "ff660011-1222-4b33-8c44-445566778899",
  tag: "00991122-3344-4c55-8d66-556677889900",
  document: "11992233-4455-4d66-9e77-667788990011",
  node: "22aa3344-5566-4e77-8f88-778899001122",
};

const NOW = "2026-01-01T00:00:00Z";

export const SPECIFICATION: AssignmentSpecification = {
  assignment: {
    id: ID.assignment,
    title: "طراحی ماشین حالت",
    deadline: "2026-02-01T00:00:00Z",
    status: "ACTIVE",
    course_id: ID.course,
    course_name: "مهندسی نرم‌افزار",
    course_code: "SE401",
  },
  description: "یک ماشین حالت کوچک با حالت‌های صریح و آزمون واحد طراحی کنید.",
  criteria_total: "100",
  requirements: [
    {
      id: ID.requirement,
      assignment_id: ID.assignment,
      code: "REQ-1",
      sequence: 1,
      title: "حالت‌های صریح تعریف شوند",
      description: "هر انتقال باید به‌صراحت در کد نوشته شده باشد.",
      priority: "HIGH",
      type: "FUNCTIONAL",
      status: "TODO",
      is_required: true,
      position: 1,
      parent_id: null,
      created_at: NOW,
      updated_at: NOW,
    },
    {
      id: ID.child,
      assignment_id: ID.assignment,
      code: "REQ-1.1",
      sequence: 2,
      title: "نام‌گذاری یکنواخت",
      description: "نام حالت‌ها با یک پیشوند مشترک آغاز شود.",
      priority: "LOW",
      type: "DOCUMENTATION",
      status: "TODO",
      is_required: false,
      position: 2,
      parent_id: ID.requirement,
      created_at: NOW,
      updated_at: NOW,
    },
  ],
  constraints: [
    {
      id: ID.constraint,
      assignment_id: ID.assignment,
      title: "مهلت تحویل",
      description: "کد باید پیش از پایان ترم تحویل شود.",
      value: "۱۴۰۴/۱۱/۳۰",
      type: "TIME",
      severity: "CRITICAL",
      position: 1,
      created_at: NOW,
      updated_at: NOW,
    },
  ],
  evaluation_criteria: [
    {
      id: ID.criterion,
      assignment_id: ID.assignment,
      title: "کیفیت آزمون‌ها",
      description: "آزمون‌ها هر انتقال ممکن را پوشش دهند.",
      weight: "40",
      position: 1,
      created_at: NOW,
      updated_at: NOW,
    },
  ],
  deliverables: [
    {
      id: ID.deliverable,
      assignment_id: ID.assignment,
      title: "کد منبع",
      description: "مخزن کد با تاریخچه کامل commit.",
      type: "SOURCE_CODE",
      status: "PENDING",
      is_required: true,
      position: 1,
      created_at: NOW,
      updated_at: NOW,
    },
  ],
  technologies: [
    {
      id: ID.technology,
      workspace_id: ID.course,
      name: "Java",
      version: "21",
      category: "LANGUAGE",
      created_at: NOW,
    },
  ],
  tags: [
    { id: ID.tag, workspace_id: ID.course, name: "معماری", created_at: NOW },
    { id: "1199aabb-ccdd-4ee0-9f11-2233445566aa", workspace_id: ID.course, name: "آزمون", created_at: NOW },
  ],
  resources: [
    {
      id: ID.document,
      assignment_id: ID.assignment,
      filename: "راهنمای حالت.pdf",
      mime_type: "application/pdf",
      size: 204_800,
      created_at: NOW,
    },
  ],
  readiness: {
    score: 50,
    is_complete: false,
    is_ready_for_analysis: false,
    completeness_bar: 50,
    failing_checks: ["criteria"],
    warning_checks: ["deadline"],
    checks: [
      {
        field: "title",
        label: "عنوان",
        status: "PASS",
        message: "عنوان تعیین شده است.",
        weight: 10,
        blocking: false,
      },
      {
        field: "criteria",
        label: "معیارهای ارزیابی",
        status: "FAIL",
        message: "معیارهای ارزیابی اضافه نشده‌اند.",
        weight: 30,
        blocking: true,
      },
    ],
  },
  summary: {
    assignment: {
      id: ID.assignment,
      title: "طراحی ماشین حالت",
      deadline: "2026-02-01T00:00:00Z",
      status: "ACTIVE",
      course_id: ID.course,
      course_name: "مهندسی نرم‌افزار",
      course_code: "SE401",
    },
    requirements_total: 2,
    requirements_required: 1,
    requirements_completed: 0,
    requirements_verified: 0,
    requirements_by_status: { TODO: 2 },
    critical_requirements: 1,
    constraints_total: 1,
    constraints_by_severity: { CRITICAL: 1 },
    criteria_total: "100",
    criteria_count: 1,
    criteria_balanced: false,
    deliverables_total: 1,
    deliverables_completed: 0,
    technologies: ["Java"],
    tags: ["معماری", "آزمون"],
    resources_total: 1,
    readiness: "INCOMPLETE",
    readiness_score: 50,
    specification_version: 3,
  },
  specification_version: 3,
  updated_at: NOW,
};

export const DEPENDENCY_GRAPH: DependencyGraph = {
  nodes: [
    {
      id: ID.node,
      code: "REQ-1",
      title: "حالت‌های صریح تعریف شوند",
      status: "TODO",
      priority: "HIGH",
      depth: 0,
    },
  ],
  edges: [],
  // The server sends requirement codes here, not ids: it maps the graph order back
  // through the same code sequence the requirements list uses.
  execution_order: ["REQ-1"],
  has_cycles: false,
};

export const ASSIGNMENT_ID = ID.assignment;

/**
 * An assignment that has been analyzed, so the analysis panel renders its
 * full body rather than the empty state.
 *
 * This is the largest string-dense surface in the app -- around forty labelled
 * sections -- and the Persian scan could not reach any of it while the
 * fixture described an unanalyzed assignment. Field names and enum values come
 * from `AssignmentAnalysisResponse`; the prose is Persian because a Persian
 * student's analysis is in Persian, which leaves the scan judging only chrome.
 *
 * The two Latin fields left Latin on purpose: `provider` and `model` are vendor
 * names, and keeping them real means the scan still sees a Latin token where
 * one is genuinely expected.
 */
export const ANALYSIS: AssignmentAnalysis = {
  "id": "44444444-4444-4444-8444-444444444444",
  "assignment_id": "3b1f5a2c-7d84-4e19-9c0a-1f2e3d4b5a60",
  "analysis_version": 1,
  "specification_version": 1,
  "specification_hash": "abc123def456",
  "prompt_version": "p1",
  "provider": "openai",
  "model": "gpt-4o",
  "status": "PENDING",
  "is_stale": false,
  "stale_at": null,
  "summary": "تحلیل",
  "confidence": 1.0,
  "assignment_types": [
    {
      "type": "PROGRAMMING",
      "confidence": 1.0,
      "source": "AI",
      "rationale": "تحلیل"
    }
  ],
  "academic_domains": [
    {
      "domain": "MATHEMATICS",
      "confidence": 1.0,
      "source": "AI",
      "rationale": "الزام"
    }
  ],
  "objectives": [
    {
      "statement": "الزام",
      "source": "EXPLICIT",
      "confidence": 1.0
    }
  ],
  "normalized_requirements": [
    {
      "key": "سنجه",
      "title": "خروجی",
      "description": "منبع",
      "category": "CONTENT",
      "priority": "LOW",
      "required": false,
      "source": "EXPLICIT",
      "source_reference": "ریسک",
      "confidence": 1.0,
      "evidence": [
        {
          "source_type": "TITLE",
          "source_id": "وابستگی",
          "location": "قید",
          "excerpt_reference": "ابهام",
          "supports": "تناقض",
          "confidence": 1.0
        }
      ]
    }
  ],
  "constraints": [
    {
      "id": "فرض",
      "title": "پرسش",
      "description": "هدف",
      "value": "روش",
      "type": "TECHNOLOGY",
      "severity": "INFO"
    }
  ],
  "ambiguities": [
    {
      "key": "دامنه",
      "description": "تأیید",
      "severity": "INFO",
      "affected_requirements": [
        "تحلیل"
      ],
      "evidence": [
        {
          "source_type": "TITLE",
          "source_id": "الزام",
          "location": "سنجه",
          "excerpt_reference": "خروجی",
          "supports": "منبع",
          "confidence": 1.0
        }
      ],
      "suggested_clarification": "ریسک",
      "confidence": 1.0
    }
  ],
  "contradictions": [
    {
      "key": "وابستگی",
      "description": "قید",
      "conflicting_items": [
        "ابهام"
      ],
      "severity": "INFO",
      "evidence": [
        {
          "source_type": "TITLE",
          "source_id": "تناقض",
          "location": "فرض",
          "excerpt_reference": "پرسش",
          "supports": "هدف",
          "confidence": 1.0
        }
      ],
      "clarification_needed": false,
      "confidence": 1.0
    }
  ],
  "missing_information": [
    {
      "key": "روش",
      "description": "دامنه",
      "area": "تأیید",
      "severity": "INFO",
      "evidence": [
        {
          "source_type": "TITLE",
          "source_id": "تحلیل",
          "location": "الزام",
          "excerpt_reference": "سنجه",
          "supports": "خروجی",
          "confidence": 1.0
        }
      ],
      "confidence": 1.0
    }
  ],
  "assumptions": [
    {
      "key": "منبع",
      "statement": "ریسک",
      "confidence": 1.0,
      "evidence": [
        {
          "source_type": "TITLE",
          "source_id": "وابستگی",
          "location": "قید",
          "excerpt_reference": "ابهام",
          "supports": "تناقض",
          "confidence": 1.0
        }
      ]
    }
  ],
  "clarification_questions": [
    {
      "id": "فرض",
      "code": "پرسش",
      "priority": "CRITICAL",
      "status": "OPEN",
      "question": "هدف",
      "rationale": "روش",
      "related_requirements": [
        "دامنه"
      ],
      "answer": "تأیید",
      "answered_at": "تحلیل",
      "position": 1
    }
  ],
  "deliverables": [
    {
      "key": "الزام",
      "title": "سنجه",
      "description": "خروجی",
      "required": false,
      "expected_content": [
        "منبع"
      ],
      "format": "ریسک",
      "related_requirements": [
        "وابستگی"
      ],
      "verification_needs": [
        "قید"
      ],
      "depends_on": [
        "ابهام"
      ],
      "uncertainty": "EXPLICIT",
      "evidence": [
        {
          "source_type": "TITLE",
          "source_id": "تناقض",
          "location": "فرض",
          "excerpt_reference": "پرسش",
          "supports": "هدف",
          "confidence": 1.0
        }
      ],
      "confidence": 1.0
    }
  ],
  "evaluation": {
    "rubric_available": false,
    "criteria": [
      {
        "title": "روش",
        "description": "دامنه",
        "weight": "1.0",
        "related_requirements": [
          "تأیید"
        ],
        "implied": false,
        "confidence": 1.0
      }
    ],
    "implied_quality_expectations": [
      "تحلیل"
    ],
    "missing_rubric_information": [
      "الزام"
    ],
    "confidence": 1.0
  },
  "scope": {
    "breadth": {
      "level": "NOT_APPLICABLE",
      "rationale": "سنجه"
    },
    "depth": {
      "level": "NOT_APPLICABLE",
      "rationale": "خروجی"
    },
    "research_intensity": {
      "level": "NOT_APPLICABLE",
      "rationale": "منبع"
    },
    "reasoning_intensity": {
      "level": "NOT_APPLICABLE",
      "rationale": "ریسک"
    },
    "technical_complexity": {
      "level": "NOT_APPLICABLE",
      "rationale": "وابستگی"
    },
    "writing_intensity": {
      "level": "NOT_APPLICABLE",
      "rationale": "قید"
    },
    "experimental_complexity": {
      "level": "NOT_APPLICABLE",
      "rationale": "ابهام"
    },
    "presentation_complexity": {
      "level": "NOT_APPLICABLE",
      "rationale": "تناقض"
    },
    "dependency_complexity": {
      "level": "NOT_APPLICABLE",
      "rationale": "فرض"
    },
    "deliverable_count": 1,
    "requirement_count": 1,
    "overall": "NOT_APPLICABLE",
    "confidence": 1.0
  },
  "work_areas": [
    {
      "key": "پرسش",
      "title": "هدف",
      "description": "روش",
      "category": "CONTENT",
      "related_requirements": [
        "دامنه"
      ],
      "depends_on": [
        "تأیید"
      ],
      "origin": "EXPLICIT",
      "confidence": 1.0
    }
  ],
  "resources": {
    "resources": [
      {
        "document_id": "تحلیل",
        "filename": "الزام",
        "resource_type": "سنجه",
        "role": "خروجی",
        "relevant_sections": [
          "منبع"
        ],
        "referenced_concepts": [
          "ریسک"
        ],
        "instructions": [
          "وابستگی"
        ],
        "constraints": [
          "قید"
        ],
        "terminology": [
          "ابهام"
        ],
        "evidence": [
          {
            "source_type": "TITLE",
            "source_id": "تناقض",
            "location": "فرض",
            "excerpt_reference": "پرسش",
            "supports": "هدف",
            "confidence": 1.0
          }
        ],
        "confidence": 1.0
      }
    ],
    "notes": [
      "روش"
    ],
    "confidence": 1.0
  },
  "dependencies": [
    {
      "predecessor": "دامنه",
      "successor": "تأیید",
      "kind": "تحلیل",
      "reason": "الزام",
      "confidence": 1.0
    }
  ],
  "verification": {
    "items": [
      {
        "title": "سنجه",
        "description": "خروجی",
        "method": "منبع",
        "applies_to": [
          "ریسک"
        ],
        "confidence": 1.0
      }
    ],
    "notes": [
      "وابستگی"
    ],
    "confidence": 1.0
  },
  "risks": [
    {
      "key": "قید",
      "description": "ابهام",
      "severity": "INFO",
      "affected_area": "تناقض",
      "evidence": [
        {
          "source_type": "TITLE",
          "source_id": "فرض",
          "location": "پرسش",
          "excerpt_reference": "هدف",
          "supports": "روش",
          "confidence": 1.0
        }
      ],
      "mitigation_hint": "دامنه",
      "confidence": 1.0
    }
  ],
  "specialized_analysis": [
    {
      "analyzer": "تأیید",
      "assignment_types": [
        "PROGRAMMING"
      ],
      "data": {},
      "summary": "تحلیل",
      "confidence": 1.0
    }
  ],
  "evidence": [
    {
      "source_type": "TITLE",
      "source_id": "الزام",
      "location": "سنجه",
      "excerpt_reference": "خروجی",
      "supports": "منبع",
      "confidence": 1.0
    }
  ],
  "edited": false,
  "reviewed_at": null,
  "review_note": null,
  "created_at": "سنجه",
  "updated_at": "2026-01-01T00:00:00+00:00"
};

/**
 * A plan with every part of it populated.
 *
 * The planning panel only appears once a plan exists, so until this existed the
 * Persian scan rendered it as an empty state -- which is exactly the state with
 * the least text in it. That is the same trap the specification fixture was
 * written to avoid: an empty fixture passes a page that is mostly
 * untranslated.
 *
 * Every branch that renders chrome is filled deliberately: a task in each
 * status, a milestone that is partly complete, a verification point, a risk, a
 * schedule warning, validation warnings and a fallback notice. A plan with one
 * completed task and nothing else would leave most of the panel's strings
 * unrendered and therefore unchecked.
 *
 * `analysis_id` is populated even though the version predates nothing, because
 * a plan with no analysis id takes a different branch in the panel.
 */
export const PLAN: WorkPlan = {
  id: "b7c8d9e0-1f2a-4b3c-8d4e-5f6a7b8c9d0e",
  assignment_id: ASSIGNMENT_ID,
  analysis_id: "c8d9e0f1-2a3b-4c5d-9e6f-7a8b9c0d1e2f",
  version: 2,
  trigger: "REGENERATED",
  reason: "پس از بازبینی تحلیل، بخش وظایف بازسازی شد.",
  changed_sections: ["tasks", "milestones"],
  title: "برنامهٔ مطالعه برای تحلیل داده‌های آزمایشگاهی",
  summary: "این برنامه کار را به پنج مرحله تقسیم می‌کند و پیش از ارائه، هر گام را با یک سنجه بررسی می‌کند.",
  status: "READY_FOR_REVIEW",
  objectives: [
    "داده‌های خام آزمایشگاه را پاک‌سازی و خلاصه کن",
    "روش تحلیل را با شواهد پشتیبانی کن",
  ],
  estimated_effort: "HIGH",
  min_minutes: 900,
  max_minutes: 1500,
  is_stale: true,
  approved_at: null,
  created_at: "2026-02-03T09:00:00Z",
  updated_at: "2026-02-05T14:30:00Z",
  progress_percentage: 40,
  used_fallback: true,
  validation_warnings: ["دو وظیفه زمان‌بندی هم‌پوشانی دارند", "یک وابستگی چرخه‌ای وجود دارد"],
  rejection_reasons: [],
  schedule_risk: {
    level: "HIGH",
    estimated_minutes: 1500,
    available_minutes: 1200,
    is_overcommitted: true,
    summary: "بیشترین تخمین از زمان باقی‌مانده بیشتر است.",
    factors: ["مهلت نزدیک است", "دو وابستگی پشت سر هم"],
  },
  tasks: [
    {
      id: "11111111-2222-4333-8444-555555555555",
      key: "T1",
      title: "خواندن برگهٔ آزمایش",
      description: "پروتکل را بخوان و متغیرهای مستقل و وابسته را مشخص کن.",
      type: "READ",
      status: "COMPLETED",
      priority: "HIGH",
      position: 1,
      estimated_effort: "LOW",
      min_minutes: 30,
      max_minutes: 45,
      verification_method: "فهرست متغیرها را با برگه تطبیق بده",
      acceptance_criteria: ["همهٔ متغیرها نام‌گذاری شده باشند", "واحدها مشخص باشند"],
      resources: ["برگهٔ آزمایش", "راهنمای درس"],
      notes: "قبل از شروع، یک بار کامل بخوان.",
      is_user_authored: true,
      depends_on: [],
      related_requirements: ["REQ-1"],
      related_deliverables: ["D1"],
      blocked_by: [],
    },
    {
      id: "22222222-3333-4444-8555-666666666666",
      key: "T2",
      title: "پاک‌سازی داده‌های خام",
      description: "مقادیر گمشده و پرت را حذف کن.",
      type: "ANALYZE_DATA",
      status: "IN_PROGRESS",
      priority: "HIGH",
      position: 2,
      estimated_effort: "MEDIUM",
      min_minutes: 120,
      max_minutes: 180,
      verification_method: "گزارش تعداد ردیف حذف‌شده",
      acceptance_criteria: ["هیچ مقدار گمشده‌ای باقی نماند"],
      resources: ["راهنمای درس"],
      notes: null,
      is_user_authored: false,
      depends_on: ["T1"],
      related_requirements: ["REQ-1"],
      related_deliverables: ["D1"],
      blocked_by: [],
    },
    {
      id: "33333333-4444-4555-8666-777777777777",
      key: "T3",
      title: "انتخاب آزمون آماری",
      description: "یک آزمون متناسب با نوع داده انتخاب کن.",
      type: "ANALYZE",
      status: "BLOCKED",
      priority: "MEDIUM",
      position: 3,
      estimated_effort: "MEDIUM",
      min_minutes: 60,
      max_minutes: 90,
      verification_method: "دلیل انتخاب را در یک پاراگراف بنویس",
      acceptance_criteria: ["آزمون با نوع داده سازگار باشد"],
      resources: [],
      notes: null,
      is_user_authored: false,
      depends_on: ["T2"],
      related_requirements: ["REQ-1", "REQ-2"],
      related_deliverables: ["D2"],
      blocked_by: ["T2"],
    },
    {
      id: "44444444-5555-4666-8777-888888888888",
      key: "T4",
      title: "نوشتن بخش روش",
      description: "روش را با توجیه آماری بنویس.",
      type: "WRITE",
      status: "PENDING",
      priority: "MEDIUM",
      position: 4,
      estimated_effort: "HIGH",
      min_minutes: 180,
      max_minutes: 300,
      verification_method: null,
      acceptance_criteria: [],
      resources: ["قالب گزارش"],
      notes: null,
      is_user_authored: false,
      depends_on: ["T3"],
      related_requirements: ["REQ-2"],
      related_deliverables: ["D2"],
      blocked_by: ["T3"],
    },
    {
      id: "55555555-6666-4777-8888-999999999999",
      key: "T5",
      title: "بازبینی نهایی",
      description: "پیش از تحویل، یک بار کامل بخوان.",
      type: "REVIEW",
      status: "SKIPPED",
      priority: "LOW",
      position: 5,
      estimated_effort: "VERY_LOW",
      min_minutes: 20,
      max_minutes: 30,
      verification_method: "خواندن نهایی",
      acceptance_criteria: ["خطای تایپی نداشته باشد"],
      resources: [],
      notes: null,
      is_user_authored: false,
      depends_on: ["T4"],
      related_requirements: [],
      related_deliverables: ["D2"],
      blocked_by: [],
    },
  ],
  milestones: [
    {
      id: "66666666-7777-4888-8999-aaaaaaaaaaaa",
      key: "M1",
      title: "آماده‌سازی داده",
      description: "خواندن و پاک‌سازی",
      position: 1,
      status: "IN_PROGRESS",
      task_keys: ["T1", "T2"],
      completed_task_count: 1,
      task_count: 2,
    },
    {
      id: "77777777-8888-4999-8aaa-bbbbbbbbbbbb",
      key: "M2",
      title: "تحلیل و نگارش",
      description: null,
      position: 2,
      status: "BLOCKED",
      task_keys: ["T3", "T4"],
      completed_task_count: 0,
      task_count: 2,
    },
  ],
  verification_points: [
    {
      key: "V1",
      title: "درستی پاک‌سازی",
      description: "بررسی کن که ردیف‌های حذف‌شده منطقی باشند.",
      method: "مقایسه با نسخهٔ خام",
      task_keys: ["T2"],
      related_requirements: ["REQ-1"],
    },
  ],
  risks: [
    {
      key: "R1",
      description: "اگر داده‌ها نرمال نباشند، آزمون انتخابی باید عوض شود.",
      severity: "MEDIUM",
      mitigation: "پیش از انتخاب آزمون، نرمال بودن را بررسی کن.",
      related_task_keys: ["T2", "T3"],
    },
  ],
};
