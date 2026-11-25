"""``init_db`` brings databases created by older versions up to the current models."""

from sqlalchemy import inspect

from app.db import init_db, make_engine


def test_init_db_moves_education_off_the_candidate_details(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE candidate_details (id INTEGER PRIMARY KEY, first_name VARCHAR(128) NOT NULL DEFAULT '',"
            " education JSON, certifications JSON)"
        )
        conn.exec_driver_sql("INSERT INTO candidate_details (first_name, education) VALUES ('Jane', '[]')")
        conn.exec_driver_sql(
            "CREATE TABLE work_history (id INTEGER PRIMARY KEY, date_start DATE NOT NULL, date_end DATE,"
            " employer VARCHAR(256) NOT NULL, role VARCHAR(256) NOT NULL, location VARCHAR(256), tech JSON,"
            " context TEXT, created_at DATETIME, updated_at DATETIME)"
        )
        conn.exec_driver_sql(
            "INSERT INTO work_history (date_start, employer, role, tech) VALUES ('2020-01-01', 'Acme', 'Dev', '[]')"
        )

    init_db(engine)
    init_db(engine)  # idempotent

    columns = {c["name"] for c in inspect(engine).get_columns("candidate_details")}
    assert "education" not in columns and "certifications" not in columns
    assert {"first_name", "photo"} <= columns
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT first_name FROM candidate_details").scalar() == "Jane"
        assert conn.exec_driver_sql("SELECT kind FROM work_history").scalar() == "job"  # existing rows are jobs
        assert conn.exec_driver_sql("SELECT transition FROM work_history").scalar() is None
