import pytest

from app.services.normalization import TaxonomyError, get_taxonomy, load_taxonomy
from app.services.skill_extraction import SkillExtractor


@pytest.fixture(scope="module")
def ex():
    return SkillExtractor(use_semantic=True)


def skills(ex, text):
    return set(ex.extract(text).skills)


def test_exact_skill(ex):
    assert skills(ex, "We need strong Python skills.") == {"python"}


@pytest.mark.parametrize("variant", ["Postgres", "PostgreSQL", "PostgreSQL DB", "postgres db", "POSTGRESQL"])
def test_postgres_aliases_normalize_to_one_skill(ex, variant):
    assert skills(ex, f"Experience with {variant}.") == {"postgresql"}


@pytest.mark.parametrize("variant", ["ReactJS", "React.js", "React JS", "react.js", "React 18"])
def test_react_aliases(ex, variant):
    assert skills(ex, f"Build UIs with {variant}.") == {"react"}


@pytest.mark.parametrize("variant", ["ML", "Machine Learning", "Machine-Learning", "machine learning"])
def test_ml_aliases(ex, variant):
    assert "machine-learning" in skills(ex, f"Hands-on {variant} experience.")


def test_case_variations(ex):
    assert skills(ex, "PYTHON, python, Python") == {"python"}
    assert skills(ex, "kubernetes and DOCKER") == {"kubernetes", "docker"}


def test_no_false_substring_matches(ex):
    assert skills(ex, "The sequel to our launch was a hit.") == set()
    assert skills(ex, "She loves javascripting? no. Pythonic idioms; scalable; reactive; angularly.") == set()
    assert "sql" not in skills(ex, "Experience with PostgreSQL and MySQL.")


def test_postgresql_is_not_also_sql_but_sql_alone_is(ex):
    assert skills(ex, "Write SQL queries.") == {"sql"}


@pytest.mark.parametrize("text", ["Our customers love the C-suite.", "Strong R&D culture.", "We want a go-getter.",
                                  "Contact Julia from recruiting.", "A hive of curious builders.", "Express interest by email."])
def test_ambiguous_words_are_not_skills(ex, text):
    assert skills(ex, text) == set()


def test_ambiguous_words_with_tech_context_are_skills(ex):
    assert "go" in skills(ex, "Experience with Python, Go and Rust.")
    assert "r" in skills(ex, "Statistical analysis in R and Python.")
    assert "apache-spark" in skills(ex, "Big data on Hadoop and Spark clusters.")


def test_symbols_in_names(ex):
    assert {"c-plus-plus", "c-sharp"} <= skills(ex, "C++ and C# development; also Node.js, ASP.NET and CI/CD.")
    assert {"node.js", "ci-cd"} <= skills(ex, "C++ and C# development; also Node.js, ASP.NET and CI/CD.")


def test_multiword_alias_never_spans_punctuation(ex):
    assert skills(ex, "Exposure to Jenkins, CI/CD pipelines") == {"jenkins", "ci-cd"}


def test_unknown_skill_returns_nothing_but_may_become_candidate(ex):
    res = ex.extract("Experience with Zorbify, FlibberStack and Quuxlang.")
    assert res.skills == {}
    assert {"Zorbify", "FlibberStack"} <= set(res.candidates)


def test_typos_and_spacing_variants(ex):
    r = ex.extract("Experience with Kubernets, Terrafom and Tensor Flow.")
    assert set(r.skills) == {"kubernetes", "terraform", "tensorflow"}
    assert r.skills["kubernetes"][1] == "fuzzy" and r.skills["kubernetes"][0] < 0.95


def test_semantic_similarity_maps_descriptive_phrases(ex):
    r = ex.extract("Experience with container orchestration platforms.")
    assert "kubernetes" in r.skills and r.skills["kubernetes"][1] == "embedding"
    assert 0.55 <= r.skills["kubernetes"][0] <= 0.9


def test_semantic_layer_ignores_generic_phrases(ex):
    assert ex.extract("Experience with team collaboration and clear communication.").skills == {}


def test_confidence_and_method_are_recorded(ex):
    r = ex.extract("Python and Postgres and Machine Learning.")
    assert r.skills["python"] == (0.98, "keyword")
    assert r.skills["postgresql"][1] == "taxonomy" and 0.9 <= r.skills["postgresql"][0] < 0.98


def test_taxonomy_is_consistent():
    tax = get_taxonomy()
    assert len(tax) >= 150
    assert tax.lookup("k8s").canonical == "Kubernetes" and tax.lookup("Golang").canonical == "Go"
    assert tax.resolve("Kubernets").canonical == "Kubernetes"


def test_conflicting_aliases_are_rejected(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text("canonical,category,aliases,description\nA,X,shared,d\nB,X,shared,d\n")
    with pytest.raises(TaxonomyError, match="Conflicting aliases"):
        load_taxonomy(f)
