import pytest
from sqlalchemy import func, select

from app import models
from app.services import companies
from app.services.companies import normalize_company_name, resolve_company, similarity


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Techland Sp. z o.o. ", "techland sp z o o"),
        ("TECHLAND", "techland"),
        ("CD PROJEKT RED S.A.", "cd projekt red s a"),
        ("Flying Wild Hog, Ltd.", "flying wild hog ltd"),
        ("Spółka Przykładowa", "spolka przykladowa"),
        ("Game-Dev & Co", "game dev co"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalize_company_name(raw, expected):
    assert normalize_company_name(raw) == expected


def test_similarity_is_bounded():
    assert similarity("techland", "techland") == 1.0
    assert 0.85 <= similarity("techland", "techlnad") < 1.0
    assert similarity("techland", "") == 0.0
    assert similarity("techland", "people can fly") < 0.5


def _names(session):
    return session.scalars(select(models.Company.name).order_by(models.Company.id)).all()


def test_first_spelling_creates_canonical_row_and_alias(db_session):
    match = resolve_company(db_session, " Techland ", source="skillshot")
    db_session.commit()

    assert match.created is True
    assert match.match_kind == "new"
    assert match.similarity is None
    assert match.company.name == "Techland"
    assert match.company.normalized_name == "techland"
    alias = db_session.scalar(select(models.CompanyAlias))
    assert alias.company_id == match.company.id
    assert alias.alias == "Techland"
    assert alias.normalized_alias == "techland"
    assert alias.match_kind == "new"
    assert alias.source == "skillshot"


def test_same_normalised_name_is_an_exact_match(db_session):
    first = resolve_company(db_session, "Techland")
    db_session.commit()

    second = resolve_company(db_session, "TECHLAND")
    db_session.commit()

    assert second.company.id == first.company.id
    assert second.match_kind == "alias"
    assert second.created is False
    assert _names(db_session) == ["Techland"]


def test_canonical_name_without_alias_is_an_exact_match(db_session):
    company = models.Company(name="Techland", normalized_name="techland")
    db_session.add(company)
    db_session.commit()

    match = resolve_company(db_session, " TECHLAND. ")
    db_session.commit()

    assert match.company.id == company.id
    assert match.match_kind == "exact"
    alias = db_session.scalar(select(models.CompanyAlias))
    assert alias.alias == "TECHLAND."
    assert alias.match_kind == "exact"


def test_known_alias_short_circuits(db_session, monkeypatch):
    first = resolve_company(db_session, "Techland")
    resolve_company(db_session, "Techlnad")
    db_session.commit()

    def boom(*_args, **_kwargs):
        raise AssertionError("fuzzy matching must not run for a known alias")

    monkeypatch.setattr(companies, "_find_fuzzy", boom)
    again = resolve_company(db_session, "Techlnad")

    assert again.company.id == first.company.id
    assert again.match_kind == "alias"
    assert again.similarity is not None
    assert db_session.scalar(select(func.count(models.CompanyAlias.id))) == 2


def test_typo_is_fuzzy_matched_to_existing_company(db_session):
    first = resolve_company(db_session, "Techland")
    db_session.commit()

    typo = resolve_company(db_session, "Techlnad")
    db_session.commit()

    assert typo.company.id == first.company.id
    assert typo.match_kind == "fuzzy"
    assert typo.similarity >= companies.FUZZY_THRESHOLD
    assert typo.created is False
    alias = db_session.scalar(
        select(models.CompanyAlias).where(models.CompanyAlias.alias == "Techlnad")
    )
    assert alias.company_id == first.company.id
    assert alias.match_kind == "fuzzy"
    assert alias.similarity == typo.similarity
    assert _names(db_session) == ["Techland"]


def test_fuzzy_match_picks_the_closest_company(db_session):
    resolve_company(db_session, "People Can Fly")
    close = resolve_company(db_session, "CD Projekt Red")
    resolve_company(db_session, "CD Projekt Blue")
    db_session.commit()

    match = resolve_company(db_session, "CD Projket Red")

    assert match.company.id == close.company.id
    assert match.match_kind == "fuzzy"


def test_fuzzy_match_also_considers_aliases(db_session):
    first = resolve_company(db_session, "CD Projekt Red")
    db_session.commit()
    # A manual alias (previous name) that is nothing like the canonical name.
    db_session.add(
        models.CompanyAlias(
            company_id=first.company.id,
            alias="CDP Red Studio",
            normalized_alias="cdp red",
            match_kind="manual",
        )
    )
    db_session.commit()

    match = resolve_company(db_session, "CDP Rde")

    assert match.company.id == first.company.id
    assert match.match_kind == "fuzzy"


def test_unrelated_names_create_separate_companies(db_session):
    resolve_company(db_session, "Techland")
    other = resolve_company(db_session, "Tech Mahindra")
    db_session.commit()

    assert other.match_kind == "new"
    assert _names(db_session) == ["Techland", "Tech Mahindra"]


def test_short_names_are_never_fuzzy_matched(db_session):
    resolve_company(db_session, "ACME")
    other = resolve_company(db_session, "ACMI")
    db_session.commit()

    assert other.match_kind == "new"
    assert _names(db_session) == ["ACME", "ACMI"]


def test_empty_name_resolves_to_nothing(db_session):
    assert resolve_company(db_session, "") is None
    assert resolve_company(db_session, "   ") is None
    assert db_session.scalar(select(models.Company)) is None


def test_threshold_can_be_tightened(db_session):
    resolve_company(db_session, "Techland")
    db_session.commit()

    strict = resolve_company(db_session, "Techlnad", threshold=0.99)

    assert strict.match_kind == "new"
