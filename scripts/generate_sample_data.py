#!/usr/bin/env python
"""Generate the realistic synthetic job-posting dataset shipped with SkillPulse.

The data is *synthetic* but built from explicit, inspectable demand curves per skill
(see ``CURVES``), tilted by job role, industry and region, with realistic noise:
HTML markup, reposted duplicates, alias spellings, typos, paraphrased technologies,
ambiguous distractor words ("Go-getter", "R&D", "Excel in a fast-paced team") and a few
malformed rows. Nothing in the application reads the curves - the dashboard only ever sees
the generated postings - so trends must be *recovered* by the real pipeline.

Usage:
    python scripts/generate_sample_data.py            # writes data/sample/*.csv
    python scripts/generate_sample_data.py --seed 7
"""
from __future__ import annotations

import argparse
import csv
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.normalization import MODE_PLAIN, load_taxonomy  # noqa: E402

GLOBAL_SCALE = 0.60  # calibrates postings to ~10 distinct skills each
START_YEAR = 2019.0
END_YEAR = 2026.75  # data runs through 2026-09-30


# ----------------------------------------------------------------------------
# Demand curves: prevalence of a skill in postings of its "home" roles at a given year
# ----------------------------------------------------------------------------
def L(a: float, b: float):  # linear
    return lambda y: a + (b - a) * (y - START_YEAR) / (END_YEAR - START_YEAR)


def S(a: float, b: float, mid: float, width: float = 1.1):  # logistic adoption curve
    return lambda y: a + (b - a) / (1 + math.exp(-(y - mid) / width))


def D(a: float, b: float):  # exponential decay a -> b
    b = max(b, 1e-4)
    return lambda y: a * (b / a) ** ((y - START_YEAR) / (END_YEAR - START_YEAR))


def E(start: float, b: float, power: float = 1.5):  # emerges at `start`, then accelerates
    def f(y: float) -> float:
        if y <= start:
            return 0.0
        return b * min(1.0, (y - start) / (END_YEAR - start)) ** power

    return f


def P(*points: tuple[float, float]):  # piecewise linear through control points
    xs, ys = zip(*points)

    def f(y: float) -> float:
        if y <= xs[0]:
            return ys[0]
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            if y <= x1:
                return y0 + (y1 - y0) * (y - x0) / (x1 - x0)
        return ys[-1]

    return f


CURVES = {
    # Programming languages
    "Python": L(0.30, 0.62), "Java": L(0.55, 0.38), "JavaScript": L(0.52, 0.47), "TypeScript": S(0.08, 0.58, 2021.6),
    "C++": L(0.30, 0.27), "C#": L(0.28, 0.26), "C": L(0.12, 0.10), "Go": E(2018.5, 0.30, 1.2), "Rust": E(2018.8, 0.15, 1.6),
    "PHP": D(0.28, 0.10), "Ruby": D(0.14, 0.05), "Kotlin": L(0.08, 0.18), "Swift": L(0.07, 0.10), "Scala": L(0.10, 0.06),
    "R": L(0.16, 0.12), "Perl": D(0.12, 0.03), "MATLAB": L(0.09, 0.07), "COBOL": D(0.06, 0.012),
    "Visual Basic": D(0.10, 0.012), "Objective-C": D(0.08, 0.008), "Shell Scripting": L(0.28, 0.32), "SQL": L(0.55, 0.58),
    "WebAssembly": E(2021.0, 0.03, 1.2), "ActionScript": D(0.07, 0.001), "Dart": L(0.01, 0.06), "Julia": L(0.005, 0.02),
    "Fortran": L(0.03, 0.015),
    # Frontend
    "React": S(0.28, 0.64, 2020.8), "Angular": P((2019, 0.30), (2022, 0.28), (2026.75, 0.20)), "AngularJS": D(0.28, 0.02),
    "Vue": L(0.10, 0.24), "Svelte": E(2019.5, 0.09, 1.3), "jQuery": D(0.60, 0.10), "Next.js": E(2019.4, 0.32, 1.3),
    "Redux": P((2019, 0.12), (2022, 0.26), (2026.75, 0.18)), "HTML/CSS": L(0.75, 0.70), "Tailwind CSS": E(2019.3, 0.32, 1.3),
    "Bootstrap": D(0.38, 0.16), "Webpack": P((2019, 0.25), (2022, 0.30), (2026.75, 0.16)), "Flash": D(0.20, 0.003),
    "Silverlight": D(0.12, 0.001), "Backbone.js": D(0.12, 0.01), "Ember.js": D(0.06, 0.015),
    # Mobile
    "React Native": L(0.10, 0.20), "Flutter": E(2018.6, 0.22, 1.1), "Android Development": L(0.40, 0.34),
    "iOS Development": L(0.40, 0.33), "Xamarin": D(0.15, 0.02),
    # Backend & APIs
    "Django": L(0.20, 0.26), "Flask": L(0.14, 0.15), "FastAPI": E(2019.7, 0.32, 1.2), "Spring": D(0.38, 0.20),
    "Spring Boot": L(0.20, 0.34), "Node.js": L(0.30, 0.42), "Express.js": L(0.16, 0.15), "NestJS": E(2019.8, 0.15, 1.2),
    "Ruby on Rails": D(0.18, 0.06), "ASP.NET": L(0.28, 0.25), "Laravel": L(0.08, 0.10), "Struts": D(0.08, 0.004),
    "REST API": L(0.55, 0.64), "GraphQL": E(2018.5, 0.26, 1.1), "gRPC": E(2018.8, 0.15, 1.2), "SOAP": D(0.20, 0.04),
    "Microservices": L(0.25, 0.52),
    # Databases
    "PostgreSQL": L(0.30, 0.58), "MySQL": L(0.40, 0.30), "MariaDB": L(0.04, 0.04), "MongoDB": P((2019, 0.30), (2022, 0.34), (2026.75, 0.26)),
    "Redis": L(0.18, 0.38), "Oracle Database": D(0.34, 0.13), "SQL Server": L(0.30, 0.22), "SQLite": L(0.06, 0.07),
    "Elasticsearch": L(0.14, 0.19), "Cassandra": L(0.10, 0.07), "DynamoDB": L(0.05, 0.18), "NoSQL": L(0.22, 0.13),
    "Vector Databases": E(2022.6, 0.32, 1.2),
    # Cloud
    "AWS": L(0.40, 0.66), "Azure": L(0.20, 0.52), "GCP": L(0.12, 0.30), "Cloud Computing": L(0.30, 0.56),
    "Serverless": L(0.04, 0.22), "AWS Lambda": L(0.06, 0.20), "OpenStack": D(0.08, 0.008), "Heroku": D(0.10, 0.02),
    # DevOps & infrastructure
    "Docker": L(0.30, 0.66), "Kubernetes": S(0.08, 0.66, 2021.0, 1.4), "Jenkins": P((2019, 0.40), (2021, 0.38), (2026.75, 0.15)),
    "Terraform": S(0.05, 0.54, 2021.5, 1.3), "GitHub Actions": E(2019.8, 0.42, 1.2), "GitLab CI": L(0.08, 0.20),
    "CI/CD": L(0.38, 0.60), "Ansible": P((2019, 0.14), (2022, 0.24), (2026.75, 0.20)), "Puppet": D(0.14, 0.012),
    "Chef": D(0.12, 0.008), "Helm": E(2018.8, 0.30, 1.3), "Argo CD": E(2019.4, 0.22, 1.3), "Prometheus": L(0.08, 0.30),
    "Grafana": L(0.07, 0.28), "Datadog": L(0.05, 0.22), "Observability": E(2018.5, 0.26, 1.2), "Splunk": L(0.12, 0.12),
    "Linux": L(0.50, 0.48), "Nginx": L(0.15, 0.12), "Git": L(0.65, 0.72), "Subversion": D(0.20, 0.012),
    "Infrastructure as Code": S(0.05, 0.42, 2021.5), "Istio": E(2018.9, 0.10, 1.3), "Vagrant": D(0.14, 0.008),
    "VMware": D(0.22, 0.09), "Windows Server": D(0.20, 0.09),
    # AI & machine learning
    "Machine Learning": L(0.35, 0.70), "Deep Learning": L(0.20, 0.45), "NLP": L(0.12, 0.34), "Computer Vision": L(0.12, 0.24),
    "Generative AI": E(2022.55, 0.70, 0.9), "LLMs": E(2022.6, 0.66, 0.9), "Prompt Engineering": E(2022.8, 0.40, 1.0),
    "RAG": E(2023.0, 0.36, 1.0), "LangChain": E(2023.0, 0.30, 1.0), "AI Agents": E(2023.6, 0.32, 1.0),
    "OpenAI API": E(2022.8, 0.36, 1.0), "Hugging Face": S(0.01, 0.32, 2022.3, 0.9),
    "TensorFlow": P((2019, 0.30), (2020.5, 0.42), (2022.5, 0.30), (2026.75, 0.20)), "PyTorch": S(0.10, 0.46, 2020.6, 1.0),
    "Keras": D(0.14, 0.07), "scikit-learn": L(0.40, 0.36), "XGBoost": L(0.12, 0.18), "MLOps": S(0.02, 0.34, 2022.3, 1.1),
    "MLflow": L(0.02, 0.16), "Reinforcement Learning": L(0.04, 0.07), "Pandas": L(0.45, 0.50), "NumPy": L(0.42, 0.42),
    # Data & analytics
    "Statistics": L(0.35, 0.30), "A/B Testing": L(0.10, 0.14), "Apache Spark": P((2019, 0.30), (2022, 0.38), (2026.75, 0.30)),
    "Hadoop": D(0.34, 0.025), "MapReduce": D(0.14, 0.008), "Apache Kafka": L(0.14, 0.30), "Apache Airflow": L(0.06, 0.30),
    "dbt": E(2019.4, 0.27, 1.2), "Snowflake": S(0.04, 0.40, 2021.2, 1.1), "Databricks": S(0.03, 0.32, 2021.5, 1.2),
    "BigQuery": L(0.06, 0.18), "Redshift": L(0.10, 0.12), "ETL": L(0.35, 0.34), "Data Warehousing": L(0.30, 0.24),
    "Data Modeling": L(0.22, 0.20), "Power BI": L(0.15, 0.42), "Tableau": P((2019, 0.35), (2021, 0.38), (2026.75, 0.26)),
    "Looker": L(0.04, 0.10), "Data Visualization": L(0.35, 0.38), "Excel": L(0.55, 0.40),
    # Cybersecurity
    "Penetration Testing": L(0.28, 0.32), "SIEM": L(0.30, 0.34), "Incident Response": L(0.30, 0.38), "IAM": L(0.28, 0.42),
    "Zero Trust": S(0.02, 0.36, 2022.0, 1.0), "OWASP": L(0.22, 0.28), "DevSecOps": L(0.04, 0.28),
    "Network Security": L(0.40, 0.28), "Vulnerability Management": L(0.30, 0.30), "Threat Intelligence": L(0.14, 0.24),
    "Cloud Security": S(0.05, 0.42, 2021.5, 1.2), "Compliance": L(0.30, 0.38), "Encryption": L(0.25, 0.24),
    # Practices & tools
    "Agile": L(0.60, 0.50), "Scrum": L(0.38, 0.26), "JIRA": L(0.40, 0.36), "Unit Testing": L(0.38, 0.40),
    "Selenium": L(0.18, 0.10), "End-to-End Testing": L(0.04, 0.20), "Test-Driven Development": L(0.14, 0.16),
    "System Design": L(0.12, 0.38), "Design Patterns": L(0.22, 0.20),
}

ROLES = ["Software Engineer", "Backend Developer", "Frontend Developer", "Data Scientist", "Data Analyst",
         "ML Engineer", "DevOps Engineer", "Cloud Engineer", "Cybersecurity Analyst"]
CATEGORIES = ["Programming Language", "Frontend", "Mobile", "Backend & APIs", "Database", "Cloud",
              "DevOps & Infrastructure", "AI & Machine Learning", "Data & Analytics", "Cybersecurity", "Practices & Tools"]
#                      PL   FE   Mob  BE   DB   Cld  Ops  AI   Data Cyb  Prac
ROLE_CAT = {
    "Software Engineer":     [0.90, 0.45, 0.25, 0.70, 0.60, 0.50, 0.40, 0.12, 0.15, 0.08, 0.90],
    "Backend Developer":     [1.00, 0.12, 0.05, 1.00, 1.00, 0.70, 0.60, 0.12, 0.25, 0.12, 0.90],
    "Frontend Developer":    [0.60, 1.00, 0.25, 0.20, 0.10, 0.20, 0.20, 0.05, 0.05, 0.05, 0.85],
    "Data Scientist":        [0.80, 0.03, 0.01, 0.10, 0.60, 0.40, 0.15, 1.00, 0.90, 0.03, 0.50],
    "Data Analyst":          [0.50, 0.02, 0.01, 0.03, 0.80, 0.25, 0.05, 0.30, 1.00, 0.02, 0.40],
    "ML Engineer":           [0.90, 0.03, 0.01, 0.30, 0.40, 0.70, 0.55, 1.10, 0.60, 0.04, 0.70],
    "DevOps Engineer":       [0.55, 0.03, 0.01, 0.20, 0.30, 1.00, 1.20, 0.08, 0.15, 0.30, 0.70],
    "Cloud Engineer":        [0.40, 0.02, 0.01, 0.15, 0.35, 1.30, 1.00, 0.08, 0.20, 0.35, 0.50],
    "Cybersecurity Analyst": [0.35, 0.02, 0.01, 0.08, 0.15, 0.50, 0.35, 0.08, 0.10, 1.30, 0.45],
}
ROLE_SKILL = {  # per-skill overrides of the category weight, in ROLES order
    #                       SE   BE   FE   DS   DA   ML   DO   CL   CY
    "Python":              [0.65, 0.80, 0.06, 1.00, 0.60, 1.00, 0.60, 0.40, 0.50],
    "Java":                [1.00, 1.00, 0.06, 0.10, 0.05, 0.12, 0.25, 0.25, 0.08],
    "JavaScript":          [0.70, 0.50, 1.00, 0.03, 0.03, 0.03, 0.12, 0.05, 0.05],
    "TypeScript":          [0.55, 0.40, 1.00, 0.02, 0.02, 0.03, 0.08, 0.05, 0.03],
    "C++":                 [0.50, 0.25, 0.02, 0.08, 0.01, 0.35, 0.05, 0.02, 0.25],
    "C#":                  [0.60, 0.60, 0.06, 0.03, 0.03, 0.04, 0.08, 0.08, 0.06],
    "SQL":                 [0.50, 0.90, 0.03, 0.85, 1.00, 0.45, 0.20, 0.20, 0.10],
    "Shell Scripting":     [0.20, 0.30, 0.02, 0.10, 0.03, 0.20, 0.80, 0.50, 0.40],
    "R":                   [0.01, 0.01, 0.01, 0.50, 0.40, 0.08, 0.01, 0.01, 0.01],
    "HTML/CSS":            [0.50, 0.10, 1.00, 0.01, 0.03, 0.01, 0.02, 0.01, 0.02],
    "Git":                 [0.90, 0.90, 0.90, 0.60, 0.30, 0.80, 0.90, 0.70, 0.40],
    "Linux":               [0.40, 0.60, 0.05, 0.25, 0.05, 0.40, 1.00, 0.90, 0.80],
    "Agile":               [0.80, 0.80, 0.80, 0.50, 0.50, 0.60, 0.70, 0.60, 0.40],
    "Excel":               [0.02, 0.01, 0.01, 0.15, 1.00, 0.02, 0.01, 0.01, 0.05],
    "Power BI":            [0.01, 0.01, 0.01, 0.10, 1.00, 0.01, 0.01, 0.01, 0.01],
    "Tableau":             [0.01, 0.01, 0.01, 0.15, 1.00, 0.01, 0.01, 0.01, 0.01],
    "Looker":              [0.01, 0.01, 0.01, 0.15, 1.00, 0.01, 0.01, 0.01, 0.01],
    "Pandas":              [0.06, 0.08, 0.01, 1.00, 0.55, 1.00, 0.04, 0.03, 0.04],
    "NumPy":               [0.06, 0.06, 0.01, 1.00, 0.35, 1.00, 0.03, 0.02, 0.03],
    "scikit-learn":        [0.03, 0.04, 0.01, 1.00, 0.20, 0.90, 0.02, 0.02, 0.03],
    "Docker":              [0.55, 0.80, 0.20, 0.30, 0.04, 0.80, 1.00, 0.90, 0.30],
    "Kubernetes":          [0.25, 0.45, 0.05, 0.10, 0.01, 0.55, 1.00, 1.00, 0.20],
    "Terraform":           [0.08, 0.10, 0.02, 0.04, 0.01, 0.15, 1.00, 1.00, 0.15],
    "AWS":                 [0.50, 0.70, 0.15, 0.40, 0.20, 0.70, 0.90, 1.00, 0.40],
    "Azure":               [0.40, 0.55, 0.10, 0.35, 0.25, 0.50, 0.80, 1.00, 0.45],
    "GCP":                 [0.25, 0.35, 0.06, 0.30, 0.15, 0.50, 0.55, 0.70, 0.20],
    "Selenium":            [0.35, 0.20, 0.25, 0.01, 0.01, 0.01, 0.05, 0.01, 0.01],
    "Unit Testing":        [0.90, 0.90, 0.80, 0.25, 0.10, 0.40, 0.30, 0.20, 0.10],
    "System Design":       [1.00, 1.00, 0.45, 0.20, 0.03, 0.70, 0.45, 0.45, 0.10],
}
NEW_AI = {"Generative AI", "LLMs", "Prompt Engineering", "RAG", "LangChain", "AI Agents", "OpenAI API", "Vector Databases"}
NEW_AI_ROLES = {"Software Engineer", "Backend Developer", "Frontend Developer", "DevOps Engineer", "Cloud Engineer",
                "Cybersecurity Analyst", "Data Analyst"}

INDUSTRIES = {  # name -> (weight, {skill_or_category: multiplier})
    "Technology": (0.26, {"AI & Machine Learning": 1.25, "Kubernetes": 1.3, "Go": 1.4, "Rust": 1.5, "Microservices": 1.2}),
    "FinTech": (0.12, {"Python": 1.25, "Java": 1.2, "Apache Kafka": 1.6, "Compliance": 1.8, "Go": 1.5, "AWS": 1.2}),
    "Healthcare": (0.12, {"Python": 1.15, "Azure": 1.4, "SQL Server": 1.4, "Compliance": 2.4, "Excel": 1.5}),
    "E-commerce": (0.12, {"React": 1.5, "Node.js": 1.5, "AWS": 1.4, "Redis": 1.6, "MongoDB": 1.4, "A/B Testing": 2.0,
                          "Elasticsearch": 1.6, "Next.js": 1.4}),
    "Banking": (0.12, {"Java": 1.5, "Oracle Database": 1.9, "COBOL": 3.5, "SQL Server": 1.5, "Compliance": 2.4,
                       "Spring": 1.5, "Spring Boot": 1.4, "SOAP": 1.5}),
    "Consulting": (0.10, {"Azure": 1.4, "Agile": 1.4, "Excel": 1.5, "Power BI": 1.5, "Tableau": 1.4, "Scrum": 1.3}),
    "Manufacturing": (0.08, {"C++": 1.8, "C": 2.0, "MATLAB": 3.0, "Oracle Database": 1.3, "Windows Server": 1.5,
                             "VMware": 1.5, "Excel": 1.4, "Visual Basic": 2.0}),
    "Telecommunications": (0.08, {"C++": 1.5, "Java": 1.4, "Linux": 1.5, "Network Security": 2.0, "Apache Kafka": 1.3, "Perl": 2.0}),
}

# country -> (weight, region, cities, cloud_tilt_at_end)
COUNTRIES = {
    "United States": (0.34, "North America", ["San Francisco, CA", "New York, NY", "Seattle, WA", "Austin, TX", "Boston, MA", "Chicago, IL", "Denver, CO", "Atlanta, GA"], 1.20),
    "India": (0.20, "Asia-Pacific", ["Bengaluru", "Hyderabad", "Pune", "Mumbai", "Chennai", "Gurgaon"], 1.65),
    "United Kingdom": (0.09, "Europe", ["London", "Manchester"], 1.05),
    "Germany": (0.07, "Europe", ["Berlin", "Munich"], 1.00),
    "Canada": (0.05, "North America", ["Toronto", "Vancouver", "Montreal"], 1.20),
    "Australia": (0.04, "Asia-Pacific", ["Sydney", "Melbourne"], 1.35),
    "Singapore": (0.03, "Asia-Pacific", ["Singapore"], 1.40),
    "Netherlands": (0.03, "Europe", ["Amsterdam"], 1.02),
    "France": (0.03, "Europe", ["Paris"], 1.00),
    "Ireland": (0.02, "Europe", ["Dublin"], 1.10),
    "Brazil": (0.03, "Latin America", ["Sao Paulo"], 1.30),
    "Mexico": (0.02, "Latin America", ["Mexico City"], 1.25),
    "United Arab Emirates": (0.02, "Middle East & Africa", ["Dubai"], 1.30),
    "Poland": (0.015, "Europe", ["Warsaw"], 1.05),
    "Israel": (0.015, "Middle East & Africa", ["Tel Aviv"], 1.20),
}
REGION_SKILL_MULT = {"India": {"Java": 1.2, "Selenium": 1.8, "Excel": 1.2, "Angular": 1.3},
                     "United States": {"Go": 1.2, "Rust": 1.2, "Kubernetes": 1.1}}

PARAPHRASES = {  # descriptive phrases that are NOT taxonomy aliases (exercise the semantic layer)
    "Kubernetes": ["container orchestration", "container orchestration platforms"],
    "Terraform": ["declarative infrastructure provisioning", "provisioning cloud infrastructure declaratively"],
    "CI/CD": ["automated build and release pipelines", "automated build, test and deployment workflows"],
    "Microservices": ["small independently deployable services", "decomposing monoliths into independent backend services"],
    "Unit Testing": ["automated test suites", "writing automated tests for code"],
    "Cloud Computing": ["cloud hosted infrastructure", "delivering computing resources over the internet"],
    "Data Warehousing": ["analytical data stores", "designing analytical warehouses"],
    "Penetration Testing": ["simulated attack exercises", "authorized simulated attacks on systems"],
    "Zero Trust": ["never trust, always verify security model", "verifying every access request"],
    "Observability": ["monitoring, logging and tracing of production systems"],
    "Incident Response": ["detecting and containing security incidents"],
    "Generative AI": ["models that generate text and images from prompts"],
    "Computer Vision": ["algorithms that analyze images and video"],
    "Prompt Engineering": ["designing prompts and instructions for language models"],
    "Reinforcement Learning": ["agents that learn by reward from interaction"],
}
TYPOS = {"Kubernetes": ["Kubernets", "Kubernetis"], "PostgreSQL": ["Postgresql", "PostgreSql"],
         "TensorFlow": ["Tensorflow", "Tensor Flow"], "JavaScript": ["Javascript", "Java Script"],
         "Elasticsearch": ["ElasticSearch"], "Terraform": ["Terrafom"], "MongoDB": ["Mongodb"]}

# Substitution pressure: once one member of a group is chosen, others are less likely.
EXCLUSIVE_GROUPS = [
    ({"React", "Angular", "Vue", "Svelte", "AngularJS", "jQuery", "Backbone.js", "Ember.js"}, 0.30),
    ({"AWS", "Azure", "GCP"}, 0.50),
    ({"TensorFlow", "PyTorch", "Keras"}, 0.40),
    ({"PostgreSQL", "MySQL", "Oracle Database", "SQL Server", "MariaDB", "SQLite"}, 0.38),
    ({"Jenkins", "GitHub Actions", "GitLab CI"}, 0.30),
    ({"Ansible", "Puppet", "Chef"}, 0.40),
    ({"Power BI", "Tableau", "Looker"}, 0.45),
    ({"Git", "Subversion"}, 0.30),
    ({"Hadoop", "Apache Spark", "Snowflake", "Databricks"}, 0.50),
    ({"Django", "Flask", "FastAPI"}, 0.40),
    ({"Flash", "Silverlight", "HTML/CSS"}, 0.50),
]
IMPLIES = [  # (child, parent, probability parent is added when child is present)
    ("Django", "Python", 0.97), ("Flask", "Python", 0.97), ("FastAPI", "Python", 0.98), ("Pandas", "Python", 0.92),
    ("NumPy", "Python", 0.93), ("scikit-learn", "Python", 0.95), ("PyTorch", "Python", 0.9), ("TensorFlow", "Python", 0.85),
    ("Spring", "Java", 0.97), ("Spring Boot", "Java", 0.97), ("Struts", "Java", 0.97), ("React", "JavaScript", 0.80),
    ("Vue", "JavaScript", 0.80), ("Angular", "TypeScript", 0.75), ("AngularJS", "JavaScript", 0.90), ("jQuery", "JavaScript", 0.92),
    ("Next.js", "React", 0.95), ("Redux", "React", 0.95), ("Express.js", "Node.js", 0.9), ("NestJS", "Node.js", 0.95),
    ("Helm", "Kubernetes", 0.95), ("Istio", "Kubernetes", 0.95), ("Argo CD", "Kubernetes", 0.9), ("Kubernetes", "Docker", 0.88),
    ("Docker", "Linux", 0.35), ("LangChain", "LLMs", 0.9), ("RAG", "LLMs", 0.9), ("Prompt Engineering", "LLMs", 0.8),
    ("OpenAI API", "LLMs", 0.8), ("LLMs", "Generative AI", 0.8), ("Generative AI", "Machine Learning", 0.5),
    ("Deep Learning", "Machine Learning", 0.85), ("NLP", "Machine Learning", 0.8), ("Computer Vision", "Deep Learning", 0.6),
    ("MLOps", "Machine Learning", 0.8), ("MLflow", "MLOps", 0.5), ("Vector Databases", "RAG", 0.5), ("Hugging Face", "NLP", 0.6),
    ("Ruby on Rails", "Ruby", 0.97), ("Laravel", "PHP", 0.97), ("ASP.NET", "C#", 0.9), ("Kotlin", "Android Development", 0.6),
    ("Swift", "iOS Development", 0.7), ("MapReduce", "Hadoop", 0.7), ("Tailwind CSS", "HTML/CSS", 0.7),
    ("Terraform", "Infrastructure as Code", 0.6), ("GitHub Actions", "CI/CD", 0.7), ("Jenkins", "CI/CD", 0.75),
    ("GitLab CI", "CI/CD", 0.75), ("DevSecOps", "CI/CD", 0.6), ("Cloud Security", "Cloud Computing", 0.5),
    ("DynamoDB", "AWS", 0.85), ("AWS Lambda", "AWS", 0.8), ("Redshift", "AWS", 0.8), ("BigQuery", "GCP", 0.9),
    ("Snowflake", "SQL", 0.7), ("dbt", "SQL", 0.9), ("Apache Airflow", "Python", 0.7), ("Flutter", "Dart", 0.9),
    ("React Native", "React", 0.8), ("Penetration Testing", "OWASP", 0.4), ("Zero Trust", "IAM", 0.5),
]

COMPANY_WORDS_A = ["Apex", "Blue", "Cobalt", "Delta", "Echo", "Fusion", "Granite", "Horizon", "Ion", "Juniper", "Keystone",
                   "Lumen", "Meridian", "Nimbus", "Orbit", "Pioneer", "Quantum", "Redwood", "Summit", "Titan", "Umbra",
                   "Vertex", "Willow", "Xenon", "Yonder", "Zenith", "Alder", "Beacon", "Crest", "Dynamo"]
COMPANY_WORDS_B = ["Systems", "Labs", "Technologies", "Digital", "Group", "Solutions", "Networks", "Analytics", "Software",
                   "Partners", "Works", "Dynamics", "Cloud", "Data", "Logic"]
SUFFIXES = ["", "", "", " Inc.", " Ltd", " LLC", " GmbH", " Corp"]
SOURCES = ["LinkedIn", "Indeed", "Glassdoor", "Company Website", "Naukri", "Monster"]
EMPLOYMENT = [("Full-time", 0.84), ("Contract", 0.10), ("Part-time", 0.02), ("Internship", 0.04)]

TITLES = {
    "Software Engineer": ["Software Engineer", "Software Developer", "Full Stack Developer", "Full-Stack Engineer", "Application Developer", "Software Development Engineer"],
    "Backend Developer": ["Backend Developer", "Backend Engineer", "Back-End Software Engineer", "Java Developer", "Python Developer", "API Engineer", "PHP Developer"],
    "Frontend Developer": ["Frontend Developer", "Front-End Engineer", "UI Engineer", "React Developer", "Angular Developer", "Frontend Software Engineer"],
    "Data Scientist": ["Data Scientist", "Applied Data Scientist", "Data Scientist - Analytics", "Data Scientist, Product"],
    "Data Analyst": ["Data Analyst", "Business Intelligence Analyst", "BI Developer", "Analytics Engineer", "Reporting Analyst"],
    "ML Engineer": ["Machine Learning Engineer", "ML Engineer", "AI Engineer", "MLOps Engineer", "Deep Learning Engineer", "Applied Scientist", "NLP Engineer"],
    "DevOps Engineer": ["DevOps Engineer", "Site Reliability Engineer", "SRE", "Platform Engineer", "Release Engineer", "Infrastructure Engineer"],
    "Cloud Engineer": ["Cloud Engineer", "Cloud Architect", "Cloud Solutions Engineer", "AWS Cloud Engineer", "Azure Cloud Engineer"],
    "Cybersecurity Analyst": ["Cybersecurity Analyst", "Security Engineer", "SOC Analyst", "Information Security Analyst", "Penetration Tester", "Application Security Engineer"],
}
SENIORITY = ["", "", "", "Senior ", "Senior ", "Junior ", "Lead ", "Staff ", "Principal "]
TEAMS = {"Software Engineer": "product engineering", "Backend Developer": "platform services", "Frontend Developer": "web experience",
         "Data Scientist": "data science", "Data Analyst": "business analytics", "ML Engineer": "applied AI",
         "DevOps Engineer": "reliability", "Cloud Engineer": "cloud infrastructure", "Cybersecurity Analyst": "security operations"}
RESPONSIBILITIES = {
    "Software Engineer": ["Translate product requirements into well designed, maintainable software.", "Participate in code reviews and mentor teammates.", "Troubleshoot production issues and improve system reliability.", "Estimate work and break features into deliverable increments."],
    "Backend Developer": ["Design scalable APIs and data models for customer-facing products.", "Optimize service performance and database queries.", "Write clear technical documentation for internal consumers.", "Improve resilience through monitoring and incident reviews."],
    "Frontend Developer": ["Build accessible, responsive interfaces in partnership with designers.", "Improve page performance and user experience metrics.", "Maintain a shared component library.", "Collaborate with backend teams on API contracts."],
    "Data Scientist": ["Develop statistical and predictive models that drive product decisions.", "Run experiments and communicate findings to stakeholders.", "Partner with engineering to move models into production.", "Define metrics and build analysis that leaders trust."],
    "Data Analyst": ["Turn business questions into reports and dashboards.", "Validate data quality and document metric definitions.", "Present insights to non-technical stakeholders.", "Automate recurring reporting."],
    "ML Engineer": ["Train, evaluate and deploy machine learning systems at scale.", "Build reliable data and feature pipelines for models.", "Monitor model quality and drift in production.", "Work with researchers to productionize prototypes."],
    "DevOps Engineer": ["Automate infrastructure provisioning and releases.", "Improve deployment speed and system observability.", "Participate in the on-call rotation and post-incident reviews.", "Harden environments and reduce operational toil."],
    "Cloud Engineer": ["Design and operate secure, cost-efficient cloud environments.", "Lead migrations from on-premise systems.", "Define landing zones, networking and access policies.", "Advise product teams on cloud architecture."],
    "Cybersecurity Analyst": ["Monitor, triage and respond to security alerts.", "Assess systems for vulnerabilities and drive remediation.", "Maintain security policies and audit evidence.", "Run tabletop exercises and security awareness sessions."],
}
INTRO = ["{company} is hiring a {title} to join our {team} team.", "We are looking for a {title} to help {company} build what comes next.",
         "{company} is growing and seeking an experienced {title} for our {team} group.", "Join {company} as a {title} and make an impact from day one."]
ABOUT = {"Technology": "We build software used by millions of people every day.", "FinTech": "We are modernizing payments and lending for customers worldwide.",
         "Healthcare": "Our products help clinicians and patients get better outcomes.", "E-commerce": "We power online marketplaces and fast, reliable delivery.",
         "Banking": "We are a established banking group investing in digital transformation.", "Consulting": "We advise enterprise clients on technology and transformation.",
         "Manufacturing": "We design and produce industrial equipment with connected, smart factories.", "Telecommunications": "We run large scale mobile and broadband networks."}
REQ = ["{n}+ years of experience with {s}.", "Strong proficiency in {s}.", "Hands-on experience building production systems using {s}.",
       "Solid understanding of {s}.", "Experience working with {s} in a team environment.", "Working knowledge of {s}.",
       "Expertise in {s} is required.", "Demonstrated experience with {s}.", "You have shipped real projects using {s}."]
NICE = ["Nice to have: {s}.", "Familiarity with {s} is a plus.", "Exposure to {s} would be an advantage.", "Bonus points for experience with {s}.", "Experience with {s} is a plus."]
RESP_SK = ["Design, build and maintain services using {s}.", "Work with {s} to deliver reliable features.", "Own the delivery of solutions on {s}.", "Collaborate with engineers to improve our {s} stack."]
BENEFITS = ["We offer competitive pay, flexible working hours, learning budget and generous time off.", "Benefits include health coverage, equity, remote-friendly work and a supportive culture.",
            "Our team values inclusion, mentorship and continuous learning."]
DISTRACTORS = ["We are looking for a go-getter who thrives in a fast-paced environment.", "Strong R&D culture with swift decision making.",
               "Please express interest by applying through our careers page.", "You will excel in a collaborative and fast-paced team.",
               "Contact Julia from our recruiting team with any questions.", "Our spring hiring cohort starts in April.",
               "Flash sales events keep our marketplace busy.", "Join a hive of curious builders.", "The sequel to our flagship launch is coming soon.",
               "We move at a swift pace and love simple solutions.", "Our customers love the C-suite dashboards we ship."]


def join_list(items: list[str], rng: random.Random) -> str:
    if len(items) == 1:
        return items[0]
    style = rng.random()
    if style < 0.40:
        return ", ".join(items[:-1]) + ", and " + items[-1]
    if style < 0.70:
        return ", ".join(items[:-1]) + " and " + items[-1]
    if style < 0.85:
        return " / ".join(items)
    return ", ".join(items)


class Generator:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.taxonomy = load_taxonomy()
        self.entries = {e.canonical: e for e in self.taxonomy.entries}
        missing = [c for c in self.entries if c not in CURVES]
        if missing:
            raise SystemExit(f"Missing demand curves for: {missing}")
        self.companies = self._make_companies()
        self.surface_forms = {
            name: [i.text for i in e.alias_infos if i.mode == MODE_PLAIN and not i.is_canonical and "/" not in i.text]
            for name, e in self.entries.items()
        }

    def _make_companies(self) -> dict[str, list[str]]:
        names = [f"{a} {b}{s}" for a in COMPANY_WORDS_A for b in COMPANY_WORDS_B for s in SUFFIXES[:1]]
        self.rng.shuffle(names)
        out: dict[str, list[str]] = {}
        per = 28
        for i, ind in enumerate(INDUSTRIES):
            chunk = names[i * per:(i + 1) * per]
            out[ind] = [c + self.rng.choice(SUFFIXES) for c in chunk]
        return out

    # --- sampling ----------------------------------------------------------
    def role_weights(self, year: float) -> list[float]:
        t = (year - START_YEAR) / (END_YEAR - START_YEAR)
        a = [0.24, 0.17, 0.15, 0.11, 0.09, 0.04, 0.08, 0.07, 0.05]
        b = [0.17, 0.14, 0.09, 0.10, 0.08, 0.14, 0.09, 0.11, 0.08]
        return [x + (y - x) * t for x, y in zip(a, b)]

    def skill_prob(self, name: str, role: str, industry: str, country: str, year: float) -> float:
        entry = self.entries[name]
        base = CURVES[name](year)
        if base <= 0:
            return 0.0
        ri = ROLES.index(role)
        if name in ROLE_SKILL:
            w = ROLE_SKILL[name][ri]
        else:
            w = ROLE_CAT[role][CATEGORIES.index(entry.category)]
        if name in NEW_AI and role in NEW_AI_ROLES:
            progress = (year - START_YEAR) / (END_YEAR - START_YEAR)
            w = max(w, 0.10 + 0.45 * progress)
        mult = INDUSTRIES[industry][1].get(name, 1.0) * INDUSTRIES[industry][1].get(entry.category, 1.0)
        mult *= REGION_SKILL_MULT.get(country, {}).get(name, 1.0)
        if entry.category == "Cloud":
            tilt = COUNTRIES[country][3]
            mult *= 1 + (tilt - 1) * (year - START_YEAR) / (END_YEAR - START_YEAR)
        return min(0.97, base * w * mult * GLOBAL_SCALE)

    def sample_skills(self, role: str, industry: str, country: str, year: float) -> list[str]:
        rng = self.rng
        names = list(CURVES)
        rng.shuffle(names)
        chosen: set[str] = set()
        for name in names:
            p = self.skill_prob(name, role, industry, country, year)
            for group, factor in EXCLUSIVE_GROUPS:
                if name in group and chosen & group:
                    p *= factor
                    break
            if rng.random() < p:
                chosen.add(name)
        for child, parent, prob in IMPLIES:
            if child in chosen and parent not in chosen and rng.random() < prob:
                chosen.add(parent)
        return sorted(chosen)

    # --- rendering ---------------------------------------------------------
    def surface(self, name: str, allow_paraphrase: bool = True) -> tuple[str, bool]:
        """Return (text used in the posting, is_paraphrase)."""
        rng = self.rng
        r = rng.random()
        if allow_paraphrase and name in PARAPHRASES and r < 0.10:
            return rng.choice(PARAPHRASES[name]), True
        if name in TYPOS and r < 0.03:
            return rng.choice(TYPOS[name]), False
        entry = self.entries[name]
        strict_canonical = any(i.is_canonical and i.mode != MODE_PLAIN for i in entry.alias_infos)
        forms = self.surface_forms[name]
        if forms and (rng.random() < 0.38 or (strict_canonical and rng.random() < 0.65)):
            return rng.choice(forms), False
        return name, False

    def render_description(self, title: str, company: str, role: str, industry: str, skills: list[str]) -> tuple[str, list[str]]:
        rng = self.rng
        skills = list(skills)
        rng.shuffle(skills)
        n_req = max(1, round(len(skills) * 0.6))
        req, nice, resp = skills[:n_req], skills[n_req:], []
        if len(req) > 4:
            resp, req = req[:2], req[2:]
        parts = [rng.choice(INTRO).format(company=company, title=title, team=TEAMS[role]), ABOUT[industry]]
        paras = []
        resp_lines = rng.sample(RESPONSIBILITIES[role], k=rng.randint(2, 4))
        if resp:
            resp_lines.append(rng.choice(RESP_SK).format(s=join_list([self.surface(s)[0] for s in resp], rng)))
        paras.append(("Responsibilities", resp_lines))
        req_lines: list[str] = []
        chunk = max(1, math.ceil(len(req) / rng.randint(2, 3))) if req else 1
        for i in range(0, len(req), chunk):
            items = [self.surface(s)[0] for s in req[i:i + chunk]]
            req_lines.append(rng.choice(REQ).format(n=rng.choice([2, 3, 3, 4, 5, 5, 7]), s=join_list(items, rng)))
        if not req_lines:
            req_lines.append("Strong communication skills and a collaborative mindset.")
        paras.append(("Requirements", req_lines))
        if nice:
            paras.append(("Nice to have", [rng.choice(NICE).format(s=join_list([self.surface(s)[0] for s in nice], rng))]))
        tail = [rng.choice(BENEFITS)]
        if rng.random() < 0.35:
            tail.append(rng.choice(DISTRACTORS))
        paras.append(("About us" if rng.random() < 0.5 else "What we offer", tail))

        html = rng.random() < 0.35
        bullets = rng.random() < 0.5
        out = [" ".join(parts)]
        for heading, lines in paras:
            if html:
                out.append(f"<h3>{heading}</h3><ul>" + "".join(f"<li>{ln.replace('&', '&amp;')}</li>" for ln in lines) + "</ul>")
            elif bullets:
                out.append(f"{heading}:\n" + "\n".join(f"• {ln}" for ln in lines))
            else:
                out.append(f"{heading}: " + " ".join(lines))
        text = "\n\n".join(out) if not html else "<p>" + out[0] + "</p>" + "".join(out[1:])
        return text, skills

    # --- postings ----------------------------------------------------------
    def make_posting(self, d: date, job_id: str) -> dict:
        rng = self.rng
        year = d.year + (d.timetuple().tm_yday - 1) / 365.0
        role = rng.choices(ROLES, weights=self.role_weights(year))[0]
        industry = rng.choices(list(INDUSTRIES), weights=[v[0] for v in INDUSTRIES.values()])[0]
        country = rng.choices(list(COUNTRIES), weights=[v[0] for v in COUNTRIES.values()])[0]
        city = rng.choice(COUNTRIES[country][2])
        if rng.random() < 0.12:
            location = f"Remote - {country}" if rng.random() < 0.5 else f"Remote, {country}"
        elif country == "United States":
            location = city
        else:
            location = f"{city}, {country}"
        title = rng.choice(SENIORITY) + rng.choice(TITLES[role])
        company = rng.choice(self.companies[industry])
        skills = self.sample_skills(role, industry, country, year)
        while len(skills) < 3:
            skills = self.sample_skills(role, industry, country, year)
        desc, order = self.render_description(title, company, role, industry, skills)
        return {
            "job_id": job_id, "title": title, "company": company, "location": location, "description": desc,
            "industry": industry, "employment_type": rng.choices([e[0] for e in EMPLOYMENT], weights=[e[1] for e in EMPLOYMENT])[0],
            "posted_date": d.isoformat(), "source": rng.choice(SOURCES), "_skills": skills, "_role": role,
        }


MONTHLY_VOLUME = {2019: 85, 2020: 80, 2021: 120, 2022: 150, 2023: 105, 2024: 110, 2025: 125, 2026: 135}
MONTH_SHAPE_2020 = {3: 0.7, 4: 0.55, 5: 0.6, 6: 0.75}  # early-pandemic hiring dip


def month_count(rng: random.Random, year: int, month: int) -> int:
    base = MONTHLY_VOLUME[year] * MONTH_SHAPE_2020.get(month, 1.0) if year == 2020 else MONTHLY_VOLUME[year]
    return max(20, int(rng.gauss(base, base * 0.08)))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


CSV_FIELDS = ["job_id", "title", "company", "location", "description", "industry", "employment_type", "posted_date", "source"]


def generate_main(seed: int, out_dir: Path) -> None:
    gen = Generator(seed)
    rng = gen.rng
    rows: list[dict] = []
    counter = 0
    for year in range(2019, 2027):
        last_month = 9 if year == 2026 else 12
        for month in range(1, last_month + 1):
            n = month_count(rng, year, month)
            days = (date(year + (month == 12), month % 12 + 1, 1) - date(year, month, 1)).days
            for _ in range(n):
                counter += 1
                d = date(year, month, 1) + timedelta(days=rng.randrange(days))
                rows.append(gen.make_posting(d, f"SP-{year}-{counter:06d}"))

    # reposts: same posting under a new id a few days later (near-duplicates) + exact id duplicates
    originals = list(rows)
    for src in rng.sample(originals, k=int(len(originals) * 0.022)):
        d = date.fromisoformat(src["posted_date"]) + timedelta(days=rng.randint(3, 21))
        if d > date(2026, 9, 30):
            continue
        counter += 1
        rep = dict(src, job_id=f"SP-{d.year}-{counter:06d}", posted_date=d.isoformat(), source=rng.choice(SOURCES))
        rep["description"] = src["description"] + " " + rng.choice(["Apply today.", "Reposted - still hiring!", "Urgently hiring."])
        rows.append(rep)
    for src in rng.sample(originals, k=int(len(originals) * 0.004)):
        rows.append(dict(src))  # exact duplicate row (same job_id)

    truth = [{"job_id": r["job_id"], "role": r["_role"], "skills": "|".join(r["_skills"])} for r in rows]

    # a handful of malformed rows so the ingestion report is non-trivial
    bad = [
        dict(rows[10], job_id="SP-BAD-0001", posted_date="not a date"),
        dict(rows[20], job_id="SP-BAD-0002", posted_date="2027-13-45"),
        dict(rows[30], job_id="SP-BAD-0003", posted_date=""),
        dict(rows[40], job_id="SP-BAD-0004", title=""),
        dict(rows[50], job_id="", title="Software Engineer"),
        dict(rows[60], job_id="SP-BAD-0006", description="", posted_date="2024-03-02"),
        dict(rows[70], job_id="SP-BAD-0007", description="", posted_date="2025-06-11"),
    ]
    rng.shuffle(rows)
    rows.extend(bad)
    write_csv(out_dir / "job_postings.csv", rows, CSV_FIELDS)
    write_csv(out_dir / "job_postings_ground_truth.csv", truth, ["job_id", "role", "skills"])
    print(f"Wrote {len(rows)} rows to {out_dir / 'job_postings.csv'}")


def generate_upload_demo(seed: int, out_dir: Path, existing_ids: list[str]) -> None:
    """Small file for exercising the upload UI: new Oct-2026 postings plus deliberate problems."""
    gen = Generator(seed + 1000)
    rng = gen.rng
    rows = []
    for i in range(320):
        d = date(2026, 10, 1) + timedelta(days=rng.randrange(6))
        rows.append(gen.make_posting(d, f"DEMO-{i + 1:05d}"))
    rows.extend(dict(rows[i], job_id=f"DEMO-{i + 1:05d}") for i in range(4))  # duplicate ids inside the file
    for jid in existing_ids[:5]:  # ids that already exist in the sample database
        rows.append(dict(rows[7], job_id=jid, posted_date="2025-02-03"))
    rows.extend([
        dict(rows[1], job_id="DEMO-BAD-1", posted_date="31/02/2026x"),
        dict(rows[2], job_id="DEMO-BAD-2", title=""),
        dict(rows[3], job_id="DEMO-BAD-3", description=""),
    ])
    write_csv(out_dir / "upload_demo.csv", rows, CSV_FIELDS)
    print(f"Wrote {len(rows)} rows to {out_dir / 'upload_demo.csv'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "sample")
    args = ap.parse_args()
    generate_main(args.seed, args.out)
    with (args.out / "job_postings.csv").open(encoding="utf-8") as fh:
        ids = [r["job_id"] for r in csv.DictReader(fh) if r["job_id"].startswith("SP-2019")][:5]
    generate_upload_demo(args.seed, args.out, ids)


if __name__ == "__main__":
    main()
