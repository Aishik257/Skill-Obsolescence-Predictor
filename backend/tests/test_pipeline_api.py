"""End-to-end: synthetic postings with known demand curves -> pipeline -> API.

The synthetic data (tests/factories.py) is built so that Python/Docker grow, COBOL/Flash decline,
Java/Git stay flat and Generative AI appears late. The pipeline must *recover* those facts.
"""
import time

import pytest
from sqlalchemy import select

from app.models.prediction import Prediction
from app.models.skill import Skill
from app.services import pipeline
from tests.conftest import wipe
from tests.factories import build_rows, to_csv

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture(scope="module")
def analysed():
    from app.core.database import SessionLocal
    from app.services.ingestion import ingest_csv
    from app.services.normalization import sync_taxonomy
    with SessionLocal() as db:
        wipe(db)
        sync_taxonomy(db)
        rows = build_rows(seed=1)
        ingest_csv(db, to_csv(rows), "synthetic.csv")
        result = pipeline.run_sync(db, "run-all")
    yield result
    with SessionLocal() as db:
        wipe(db)


@pytest.fixture()
def preds(analysed):
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        names = {s.id: s.name for s in db.scalars(select(Skill))}
        return {names[p.skill_id]: p for p in db.scalars(select(Prediction))}


# ---- pipeline result contract ------------------------------------------------------------
def test_run_all_returns_contract(analysed):
    assert analysed["status"] == "completed"
    assert {"jobs_processed", "skills_detected", "trends_calculated", "predictions_generated"} <= set(analysed)
    assert analysed["jobs_processed"] > 1800 and analysed["skills_detected"] >= 6
    assert analysed["predictions_generated"] >= analysed["trends_calculated"] >= 6


# ---- the pipeline recovers the planted trends --------------------------------------------
@pytest.mark.parametrize("skill,status", [("Python", "growing"), ("Docker", "growing"), ("Generative AI", "emerging"),
                                          ("Java", "stable"), ("Git", "stable")])
def test_trend_status_recovered(preds, skill, status):
    assert preds[skill].trend_status == status


@pytest.mark.parametrize("skill", ["COBOL", "Flash"])
def test_declining_skills_found(preds, skill):
    assert preds[skill].trend_status in {"declining", "at_risk"}


def test_scores_order_follows_the_truth(preds):
    assert preds["Flash"].obsolescence_score > 65 and preds["COBOL"].obsolescence_score > 60
    assert preds["Python"].obsolescence_score < 20 and preds["Generative AI"].obsolescence_score < 20
    assert preds["Java"].risk_level in {"LOW", "MEDIUM"} and preds["Git"].risk_level in {"LOW", "MEDIUM"}
    assert preds["Flash"].obsolescence_score > preds["Java"].obsolescence_score > preds["Python"].obsolescence_score


def test_metrics_are_close_to_planted_values(preds):
    assert 0.50 < preds["Python"].current_demand < 0.62          # planted 0.60 at the end, trailing year ~0.56
    assert abs(preds["Java"].current_demand - 0.35) < 0.05
    assert preds["Python"].growth_rate > 1.0 and preds["COBOL"].growth_rate < -0.6


def test_predictions_are_explainable(preds):
    e = preds["Flash"].explanation
    assert e["headline"].startswith("Flash") and e["summary"] and len(e["bullets"]) >= 4
    assert any(r["rule"] == "declining" or r["rule"] == "at_risk" for r in e["rules"])
    assert e["limitations"] and "risk" in e["risk_text"].lower()
    assert {c["component"] for c in e["score_breakdown"]} >= {"historical_decline", "forecasted_decline"}
    assert preds["Python"].confidence_label in {"High", "Medium", "Low"}


def test_forecast_status_and_future_demand(preds):
    for s in ("Python", "Docker", "COBOL"):
        assert preds[s].forecast_status == "ok" and preds[s].future_demand is not None
    assert preds["Python"].future_demand > preds["Python"].current_demand * 0.95
    assert preds["COBOL"].future_demand < preds["COBOL"].current_demand * 1.15


# ---- API ----------------------------------------------------------------------------------
@pytest.fixture()
def api(analysed, client):
    return client


def skill_id(api, name):
    return api.get("/api/skills/search", params={"q": name}).json()["results"][0]["skill_id"]


def test_health_and_docs(api):
    assert api.get("/api/health").json()["status"] == "ok"
    assert api.get("/api/docs").status_code == 200 and api.get("/api/openapi.json").status_code == 200


def test_overview_kpis_come_from_data(api):
    o = api.get("/api/analytics/overview").json()
    k = o["kpis"]
    assert k["total_jobs"] > 1800 and k["growing"] >= 2 and (k["declining"] + k["at_risk"]) >= 2 and k["emerging"] >= 1
    assert o["has_data"] and o["limitations"] and o["market_outlook"]["bullets"]
    names = [r["name"] for r in o["highest_risk"]]
    assert "Flash" in names[:3]


def test_overview_respects_filters(api):
    g = api.get("/api/analytics/overview").json()["kpis"]["total_jobs"]
    f = api.get("/api/analytics/overview", params={"role": "Data Scientist"}).json()
    assert f["scope"] == "filtered" and 0 < f["kpis"]["total_jobs"] < g
    y = api.get("/api/analytics/overview", params={"year": 2022}).json()
    assert y["kpis"]["total_jobs"] < g / 3


def test_skill_list_search_sort_and_pagination(api):
    r = api.get("/api/skills", params={"page_size": 3, "sort": "obsolescence_score"}).json()
    assert len(r["items"]) == 3 and r["total"] >= 6
    scores = [x["obsolescence_score"] for x in r["items"]]
    assert scores == sorted(scores, reverse=True)
    assert api.get("/api/skills", params={"status": "growing"}).json()["total"] >= 2
    assert {x["name"] for x in api.get("/api/skills", params={"q": "pyth"}).json()["items"]} == {"Python"}
    assert api.get("/api/skills", params={"q": "zzzz"}).json()["items"] == []


def test_search_finds_aliases_and_role_views(api):
    r = api.get("/api/skills/search", params={"q": "k8s"}).json()
    s = api.get("/api/skills/search", params={"q": "python"}).json()
    assert s["results"][0]["name"] == "Python" and s["role_views"] and "Python for" in s["role_views"][0]["name"]
    assert api.get("/api/skills/search", params={"q": "qqqqqq"}).json()["results"] == []
    assert isinstance(r["results"], list)


def test_skill_detail_history_forecast(api):
    sid = skill_id(api, "Python")
    d = api.get(f"/api/skills/{sid}").json()
    assert d["trend_status"] == "growing" and d["explanation"]["recommendation"] and d["top_roles"]
    h = api.get(f"/api/skills/{sid}/history", params={"granularity": "year"}).json()
    assert len(h["points"]) == 7 and h["points"][0]["frequency"] < h["points"][-1]["frequency"]
    assert all(p["ci_low"] <= p["frequency"] <= p["ci_high"] for p in h["points"] if p["frequency"] is not None)
    f = api.get(f"/api/skills/{sid}/forecast").json()
    assert f["status"] == "ok" and len(f["forecast"]) == 12 and set(f["horizons"]) == {"1y", "2y", "3y"}
    assert len(f["models"]) == 4 and sum(m["selected"] for m in f["models"]) == 1
    assert f["horizons"]["3y"]["lower"] <= f["horizons"]["3y"]["predicted"] <= f["horizons"]["3y"]["upper"]


def test_filtered_history_and_forecast(api):
    sid = skill_id(api, "Python")
    h = api.get(f"/api/skills/{sid}/history", params={"role": "Data Scientist", "granularity": "year"}).json()
    assert h["filters"] == {"role": "Data Scientist"} and h["total_jobs"] > 0
    f = api.get(f"/api/skills/{sid}/forecast", params={"role": "Data Scientist"}).json()
    assert f["scope"] == "filtered" and f["status"] in {"ok", "insufficient_data"}
    empty = api.get(f"/api/skills/{sid}/forecast", params={"role": "Cloud Engineer", "year": 2018}).json()
    assert empty["status"] == "insufficient_data" and empty["message"] == "Insufficient historical data" and empty["forecast"] == []


def test_trend_rankings(api):
    g = api.get("/api/trends/growing").json()["items"]
    d = api.get("/api/trends/declining").json()["items"]
    e = api.get("/api/trends/emerging").json()["items"]
    assert [x["name"] for x in e] == ["Generative AI"]
    assert g[0]["growth_rate"] >= g[-1]["growth_rate"] and {x["name"] for x in d} >= {"Flash", "COBOL"}
    assert d[0]["growth_rate"] <= d[-1]["growth_rate"]


def test_trend_series_for_multiple_skills(api):
    ids = [skill_id(api, n) for n in ("Python", "Java", "COBOL")]
    s = api.get("/api/trends/series", params={"skill_ids": ",".join(map(str, ids)), "granularity": "year"}).json()
    assert len(s["series"]) == 3 and len(s["periods"]) == 7 == len(s["series"][0]["frequency"])
    assert api.get("/api/trends/series", params={"skill_ids": "1", "role": "Data Scientist", "year": 2018}).json()["empty"] is True


def test_predictions_endpoints(api):
    hr = api.get("/api/predictions/high-risk").json()["items"]
    assert hr and all(x["risk_level"] in {"HIGH", "CRITICAL"} for x in hr)
    sid = skill_id(api, "Flash")
    p = api.get(f"/api/predictions/{sid}").json()
    assert p["obsolescence_score"] > 60 and p["components"] and p["explanation"]["bullets"]
    assert api.get("/api/predictions", params={"risk": "LOW", "page_size": 100}).json()["total"] >= 2


def test_forecast_list_and_detail(api):
    r = api.get("/api/forecasts", params={"page_size": 50}).json()
    assert r["total"] >= 6 and all(x["status"] in {"ok", "insufficient_data"} for x in r["items"])
    ok = next(x for x in r["items"] if x["status"] == "ok")
    assert api.get(f"/api/forecasts/{ok['skill_id']}").json()["status"] == "ok"


def test_model_performance_endpoint(api):
    m = api.get("/api/analytics/model-performance").json()
    assert m["available"] and {x["model"] for x in m["models"]} == {"naive_mean", "linear_trend", "damped_holt", "ar_ridge"}
    assert "never shuffled" in m["validation"]["method"] and m["selected_summary"]["mean_rmse"] is not None
    assert sum(x["times_selected"] for x in m["models"]) == m["selected_summary"]["skills_with_forecast"]


def test_breakdown_by_role_and_relevance(api):
    sid = skill_id(api, "Python")
    b = api.get(f"/api/skills/{sid}/breakdown", params={"dimension": "role"}).json()
    assert {g["group"] for g in b["groups"]} >= {"Data Scientist", "Backend Developer"}
    for g in b["groups"]:
        if g.get("sufficient"):
            assert g["relevance"] and g["growth_label"]


def test_categories_filters_risk_map_demand_by_candidates(api):
    assert api.get("/api/analytics/categories").json()["items"]
    f = api.get("/api/analytics/filters").json()
    assert "Data Scientist" in [r["value"] for r in f["roles"]] and f["years"][0] == 2019
    assert api.get("/api/analytics/risk-map").json()["items"]
    d = api.get("/api/analytics/demand-by", params={"dimension": "industry"}).json()
    assert d["groups"] and d["cells"] and all(0 <= c["share"] <= 1 for c in d["cells"])
    assert "items" in api.get("/api/analytics/candidates").json()


def test_related_and_replacement_endpoints(api):
    sid = skill_id(api, "Flash")
    assert "disclaimer" in api.get(f"/api/skills/{sid}/replacements").json()
    assert "related" in api.get(f"/api/skills/{skill_id(api, 'Python')}/related").json()


def test_recommendations(api):
    gap = api.post("/api/recommendations/skill-gap", json={"role": None, "skills": ["Python", "Java", "Flash", "nonsense-skill"]}).json()
    assert {s["name"] for s in gap["strong_skills"]} >= {"Python", "Java"} and gap["unrecognized"] == ["nonsense-skill"]
    assert [s["name"] for s in gap["at_risk_skills"]] == ["Flash"]
    lp = api.post("/api/recommendations/learning-path", json={"role": "Data Scientist", "skills": ["Python"]}).json()
    assert lp["recommendations"] and "Python" not in {r["name"] for r in lp["recommendations"]}
    assert all(r["reasons"] for r in lp["recommendations"])
    assert not {r["name"] for r in lp["recommendations"]} & {"Flash", "COBOL"}  # never recommend declining skills


# ---- error handling ------------------------------------------------------------------------
@pytest.mark.parametrize("url,code", [("/api/skills/999999", 404), ("/api/skills/999999/history", 404),
                                      ("/api/predictions/999999", 404), ("/api/jobs/999999", 404),
                                      ("/api/skills?sort=bogus", 422), ("/api/skills?role=Wizard", 422),
                                      ("/api/skills/1/history?granularity=week", 422), ("/api/trends/series?skill_ids=x", 422),
                                      ("/api/analytics/overview?date_from=2025-01-02&date_to=2024-01-01", 422)])
def test_error_responses_are_human_readable(api, url, code):
    r = api.get(url)
    assert r.status_code == code and isinstance(r.json()["detail"], str) and len(r.json()["detail"]) > 10


def test_bad_recommendation_requests(api):
    assert api.post("/api/recommendations/skill-gap", json={"skills": ["zzzzzz"]}).status_code == 400
    assert api.post("/api/recommendations/learning-path", json={"role": "Astronaut", "skills": ["Python"]}).status_code == 422
    assert api.post("/api/recommendations/learning-path", json={"skills": []}).status_code == 422


# ---- jobs & upload ---------------------------------------------------------------------------
def test_jobs_list_detail_and_stats(api):
    lst = api.get("/api/jobs", params={"page_size": 5, "q": "Data Scientist"}).json()
    assert lst["total"] > 0 and all("Data Scientist" in j["title"] for j in lst["items"])
    jid = lst["items"][0]["id"]
    d = api.get(f"/api/jobs/{jid}").json()
    assert d["skills"] and all(0.55 <= s["confidence"] <= 1 for s in d["skills"])
    s = api.get("/api/jobs/stats").json()
    assert s["active_postings"] > 1800 and s["pending_extraction"] == 0 and s["has_predictions"] and not s["analysis_stale"]
    assert api.get("/api/jobs", params={"q": "%"}).json()["total"] == 0  # LIKE wildcards are escaped


def test_upload_dry_run_import_and_staleness(api):
    # distinct company + title + text per row so the cleaning stage (correctly) sees five different postings
    companies = ["Northwind Labs", "Acme Analytics", "Blue Harbor Systems", "Quantum Retail", "Helios Health"]
    topics = ["recommendation engines", "payment reconciliation", "fleet telemetry", "clinical dashboards", "ad attribution"]
    rows = [dict(build_rows(seed=99, per_quarter=1)[0], job_id=f"UP-{i}", posted_date="2025-12-20",
                 title="Data Scientist", company=companies[i],
                 description=f"{companies[i]} is hiring for {topics[i]}. Experience with Python and Docker required. "
                             f"You will own {topics[i]} models end to end.") for i in range(5)]
    rows.append(dict(rows[0]))  # duplicate id in file
    rows.append(dict(rows[1], job_id="UP-BAD", posted_date="not-a-date"))
    pre = api.post("/api/jobs/upload", params={"dry_run": True}, files={"file": ("new.csv", to_csv(rows), "text/csv")}).json()
    assert pre["dry_run"] and pre["valid_records"] == 5 and pre["duplicates_in_file"] == 1 and pre["invalid_dates"] == 1
    assert pre["imported"] == 0 and api.get("/api/jobs/stats").json()["pending_cleaning"] == 0
    done = api.post("/api/jobs/upload", files={"file": ("new.csv", to_csv(rows), "text/csv")}).json()
    assert done["imported"] == 5
    st = api.get("/api/jobs/stats").json()
    assert st["pending_cleaning"] == 5 and st["analysis_stale"] is True
    # step-by-step pipeline as the UI does it
    assert api.post("/api/pipeline/clean").json()["status"] == "completed"
    assert api.post("/api/pipeline/extract-skills").json()["details"]["extraction"]["jobs_processed"] == 5
    assert api.post("/api/pipeline/analyze").json()["status"] == "completed"
    assert api.post("/api/pipeline/forecast").json()["status"] == "completed"
    assert api.post("/api/pipeline/predict").json()["status"] == "completed"
    assert api.get("/api/jobs/stats").json()["analysis_stale"] is False
    jid = api.get("/api/jobs", params={"q": "Data Scientist"}).json()["items"][0]["id"]
    assert api.delete(f"/api/jobs/{jid}").status_code == 200 and api.get(f"/api/jobs/{jid}").status_code == 404


@pytest.mark.parametrize("name,content,ctype,code", [
    ("jobs.txt", b"a,b", "text/plain", 400), ("jobs.csv", b"", "text/csv", 400), ("jobs.csv", b"x,y\n1,2\n", "text/csv", 400),
    ("jobs.csv", b"\x00\x01\x02", "text/csv", 400), ("jobs.csv", b"a,b", "image/png", 400)])
def test_upload_rejections(api, name, content, ctype, code):
    r = api.post("/api/jobs/upload", files={"file": (name, content, ctype)})
    assert r.status_code == code and "detail" in r.json()


def test_upload_size_limit(api, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(type(settings), "max_upload_bytes", property(lambda self: 100))
    r = api.post("/api/jobs/upload", files={"file": ("big.csv", b"job_id,title\n" + b"x" * 500, "text/csv")})
    assert r.status_code == 413 and "too large" in r.json()["detail"]


# ---- pipeline control -----------------------------------------------------------------------------
def test_background_run_with_progress_polling_and_lock(api):
    started = api.post("/api/pipeline/predict", params={"background": True})
    assert started.status_code == 200 and started.json()["status"] == "running"
    rid = started.json()["run_id"]
    assert api.post("/api/pipeline/analyze").status_code == 409  # one run at a time
    for _ in range(120):
        s = api.get("/api/pipeline/status", params={"run_id": rid}).json()
        if s["status"] != "running":
            break
        time.sleep(0.25)
    assert s["status"] == "completed" and s["progress"] == 100 and s["log"]
    assert api.get("/api/pipeline/runs").json()["items"][0]["run_id"] == rid
    assert api.get("/api/pipeline/status", params={"run_id": 999999}).status_code == 404


def test_pipeline_without_data_is_a_clear_400(client):
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        wipe(db)
    r = client.post("/api/pipeline/run-all")
    assert r.status_code == 400 and "No job postings available" in r.json()["detail"]
    o = client.get("/api/analytics/overview").json()
    assert o["has_data"] is False and o["kpis"]["total_jobs"] == 0
    assert client.get("/api/analytics/model-performance").json()["available"] is False
    assert client.get("/api/skills").json()["items"] == []
