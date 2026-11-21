"""``parse_interview_steps`` and ``POST /api/scrape/interview-steps``."""

from app.tasks.parse.parse import InterviewStep, parse_interview_steps


def test_no_process_returns_empty():
    assert parse_interview_steps("We build things.\nRequirements:\n- Python\n- SQL") == []
    assert parse_interview_steps("") == []
    assert parse_interview_steps(None) == []


def test_numbered_list_under_heading():
    text = (
        "About us\n\nRecruitment process:\n"
        "1. HR call (30 min)\n2. Technical interview\n3) Meeting with the team\n\nBenefits"
    )
    steps = parse_interview_steps(text)
    assert [s.title for s in steps] == ["HR call", "Technical interview", "Meeting with the team"]
    assert steps[0] == InterviewStep(1, "HR call", 30)
    assert [s.number for s in steps] == [1, 2, 3]


def test_bullets_under_polish_heading():
    text = "Proces rekrutacji:\n• Rozmowa z HR\n• Zadanie techniczne\n• Spotkanie z CTO (1h)\n"
    steps = parse_interview_steps(text)
    assert [s.title for s in steps] == ["Rozmowa z HR", "Zadanie techniczne", "Spotkanie z CTO"]
    assert steps[2].duration_minutes == 60


def test_arrow_chain():
    steps = parse_interview_steps("Our process: HR screen → Tech interview → Offer")
    assert [s.title for s in steps] == ["HR screen", "Tech interview", "Offer"]


def test_bullets_without_heading_are_ignored():
    assert parse_interview_steps("Requirements:\n- Python\n- Docker\n- 3 years") == []


def test_endpoint(client):
    res = client.post(
        "/api/scrape/interview-steps",
        json={"text": "Interview process\nStep 1: Culture match\nStep 2: Technical (60 min)"},
    )
    assert res.status_code == 200
    assert res.json() == [
        {"number": 1, "title": "Culture match", "duration_minutes": None},
        {"number": 2, "title": "Technical", "duration_minutes": 60},
    ]
    assert client.post("/api/scrape/interview-steps", json={"text": "nothing"}).json() == []
