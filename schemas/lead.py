from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field


LeadType = Literal[
    "high_intent_sales_call",
    "needs_clarification",
    "bad_fit",
    "spam_or_vendor",
]

FitLevel = Literal["high", "medium", "low"]
UrgencyLevel = Literal["same_day", "this_week", "low"]
NextAction = Literal[
    "book_discovery_call",
    "ask_missing_info",
    "send_pricing_context",
    "nurture",
    "disqualify",
]


class LeadSubmission(BaseModel):
    lead_id: str
    received_at: str
    name: str
    email: EmailStr
    company: str | None = None
    role: str | None = None
    source: str
    service_interest: str
    message: str
    budget: str | None = None
    timeline: str | None = None
    website: str | None = None


class EvidenceItem(BaseModel):
    field: str
    value: str
    interpretation: str


class LeadQualificationReport(BaseModel):
    lead_id: str
    lead_type: LeadType
    fit: FitLevel
    urgency: UrgencyLevel
    score: int = Field(ge=0, le=100)
    recommended_next_action: NextAction
    rationale: str
    evidence: list[EvidenceItem]
    disqualifying_risks: list[str] = Field(default_factory=list)


class MissingInfoReport(BaseModel):
    lead_id: str
    missing_required_fields: list[str]
    missing_helpful_fields: list[str]
    questions_to_ask: list[str]
    can_respond_now: bool
    rationale: str


class FollowupDraft(BaseModel):
    lead_id: str
    recipient_email: EmailStr
    subject: str
    body: str
    personalization_points: list[str]
    approval_required: bool = True
    reason_approval_required: str


class CrmNoteReport(BaseModel):
    lead_id: str
    crm_status: str
    note_path: str
    summary: str
    saved_fields: list[str]


class SupervisorDecision(BaseModel):
    lead_id: str
    final_classification: LeadType
    fit: FitLevel
    urgency: UrgencyLevel
    score: int = Field(ge=0, le=100)
    recommended_next_action: NextAction
    customer_message_status: Literal["drafted_only", "approval_requested", "sent", "not_applicable"]
    artifact_run_id: str
    artifact_paths: list[str]
    human_review_required: bool
    explanation_for_owner: str
    evidence_summary: list[str]


ChannelConversationStatus = Literal[
    "continue_conversation",
    "qualified_escalate",
    "not_fit_close",
    "needs_human",
]

ChannelNextAction = Literal[
    "ask_followup_question",
    "handoff_to_owner",
    "close_not_fit",
    "needs_manual_review",
]


class ChannelConversationDecision(BaseModel):
    lead_id: str
    conversation_status: ChannelConversationStatus
    reply_text: str
    extracted_profile: dict[str, str] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    fit: FitLevel
    urgency: UrgencyLevel
    score: int = Field(ge=0, le=100)
    recommended_next_action: ChannelNextAction
    qualification_summary: str
    owner_escalation_required: bool
    owner_summary: str
