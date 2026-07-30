# data/models.py
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class UserProfile:
    id: Optional[int] = None
    school: str = ""
    grade: str = ""
    major: str = ""
    preferences: list[str] = field(default_factory=list)
    onboarding_done: bool = False
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Course:
    id: Optional[int] = None
    name: str = ""
    day_of_week: int = 0  # 0=Mon, 6=Sun
    start_time: str = ""  # "08:00"
    end_time: str = ""    # "10:00"
    location: str = ""
    week_range: str = ""  # "1-16"
    semester: str = ""    # "2026-2027-1"


@dataclass
class Exam:
    id: Optional[int] = None
    course_name: str = ""
    exam_date: str = ""   # "2026-08-15"
    exam_time: str = ""
    location: str = ""
    notes: str = ""


@dataclass
class Event:
    id: Optional[int] = None
    title: str = ""
    event_date: str = ""
    start_time: str = ""
    end_time: str = ""
    location: str = ""
    reminder: bool = False
    reminder_time: str = ""
    created_by_agent: bool = False
    created_at: str = ""


@dataclass
class ClubActivity:
    id: Optional[int] = None
    club_name: str = ""
    title: str = ""
    activity_date: str = ""
    start_time: str = ""
    location: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class KnowledgeItem:
    id: Optional[int] = None
    category: str = ""
    title: str = ""
    content: str = ""
    keywords: str = ""
