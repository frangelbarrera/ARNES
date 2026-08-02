"""PlaybookLibrary — the catalogue of domain-specific task templates.

Each template encodes the "action graph" for a common task type: which
specialists to call, in what order, with which tools, what to ask the
user, and what risks to flag. This is the knowledge layer that gives
ARNES a head start on common requests instead of always falling back to
the generic single-shot planner.

Adding a new domain:

1. Add a member to :class:`TaskDomain` (in ``router.py``).
2. Add keyword weights to ``_DOMAIN_KEYWORDS`` (in ``router.py``).
3. Build a :class:`TaskTemplate` and register it in
   :func:`_build_default_library` below.

The library is intentionally pure-Python data (no LLM calls) so it is
deterministic, fast, and works offline.
"""

from __future__ import annotations

import functools

from arnes.playbooks.library.domains import TaskDomain
from arnes.playbooks.library.router import TaskRouter
from arnes.playbooks.library.templates import SpecialistStep, TaskTemplate


def _mobile_app_template() -> TaskTemplate:
    return TaskTemplate(
        name=TaskDomain.SOFTWARE_MOBILE.value,
        title="Mobile App Development",
        description=(
            "Build a mobile application for Android, iOS, or cross-platform. "
            "Covers market research, product requirements, architecture, "
            "implementation, testing, and store deployment."
        ),
        specialists=[
            SpecialistStep(
                specialist="@market-analyst",
                purpose="Assess market viability, competitor landscape, and pricing model.",
                tools=None,
                input_hint="Analyze the mobile app market for the requested concept.",
            ),
            SpecialistStep(
                specialist="@product-manager",
                purpose="Define MVP scope, user stories, and acceptance criteria.",
                tools=None,
                input_hint="Write product requirements from the market analysis.",
            ),
            SpecialistStep(
                specialist="@planner",
                purpose="Decompose into specialist steps: UI, data layer, API, auth, etc.",
                tools=None,
                input_hint="Plan the implementation steps for the mobile app.",
            ),
            SpecialistStep(
                specialist="@coder",
                purpose="Implement the app (platform-specific or cross-platform).",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Write the mobile app code following the plan.",
            ),
            SpecialistStep(
                specialist="@tester",
                purpose="Write and run unit + integration tests; report coverage.",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Test the mobile app implementation.",
            ),
            SpecialistStep(
                specialist="@security-auditor",
                purpose="Audit auth flows, data storage, network calls, and permissions.",
                tools=["fs_read"],
                input_hint="Security audit of the mobile app.",
            ),
            SpecialistStep(
                specialist="@devops-engineer",
                purpose="Set up CI/CD pipeline and store deployment (Play Store / App Store).",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Create the deployment pipeline for the mobile app.",
            ),
        ],
        clarifying_questions=[
            "Which platform(s)? Android, iOS, or both (cross-platform)?",
            "What is the core user flow? (e.g. dating, e-commerce, social)",
            "Do you have a backend/API already, or does that need building too?",
            "What is your budget for store developer accounts? ($25 Google one-time, $99 Apple/year)",
            "Offline-first or requires constant connectivity?",
        ],
        domain_context=(
            "Mobile app development. Common stacks: Flutter (Dart, cross-platform), "
            "React Native (JS/TS, cross-platform), Kotlin (Android native), "
            "Swift (iOS native). Reference repos: flutter/samples, "
            "react-native-community, android/architecture-samples. Store guidelines: "
            "Google Play Policy, Apple App Store Review Guidelines. Key concerns: "
            "app size limits, battery usage, permission justifications, data privacy "
            "(GDPR/CCPA), offline sync, push notifications."
        ),
        risks=[
            "App store rejection (guideline violations — common: thin app, wrong permissions).",
            "Cross-platform frameworks may lack access to newest platform APIs.",
            "Backend costs scale with users — estimate before launch.",
            "App signing keys must be kept secure; losing them means you cannot update.",
            "Background task restrictions differ significantly between iOS and Android.",
        ],
        estimated_duration_h=80.0,
        suggested_budget_usd=5.0,
    )


def _web_app_template() -> TaskTemplate:
    return TaskTemplate(
        name=TaskDomain.SOFTWARE_WEB.value,
        title="Web Application Development",
        description=(
            "Build a web application: frontend, backend, and deployment. "
            "Covers requirements, architecture, implementation, testing, and "
            "production deployment."
        ),
        specialists=[
            SpecialistStep(
                specialist="@product-manager",
                purpose="Define features, user journeys, and MVP scope.",
                input_hint="Write product requirements for the web app.",
            ),
            SpecialistStep(
                specialist="@planner",
                purpose="Choose stack (frontend framework, backend, DB) and plan architecture.",
                input_hint="Plan the web app architecture and implementation steps.",
            ),
            SpecialistStep(
                specialist="@coder",
                purpose="Implement frontend + backend.",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Write the web app code (frontend + backend).",
            ),
            SpecialistStep(
                specialist="@tester",
                purpose="Write unit + e2e tests (Playwright/Cypress).",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Test the web app.",
            ),
            SpecialistStep(
                specialist="@security-auditor",
                purpose="Audit auth, CORS, CSP, SQL injection, XSS, CSRF.",
                tools=["fs_read"],
                input_hint="Security audit of the web app.",
            ),
            SpecialistStep(
                specialist="@devops-engineer",
                purpose="Set up CI/CD, hosting (Vercel/Netlify/Fly/VPS), and monitoring.",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Deploy the web app to production.",
            ),
        ],
        clarifying_questions=[
            "Frontend framework preference? (React, Vue, Svelte, plain HTML?)",
            "Backend: full-framework (Django/Rails) or API-only (FastAPI/Express)?",
            "Database: relational (Postgres) or document (MongoDB)?",
            "Auth: roll-your-own, OAuth (Google/GitHub), or managed (Clerk/Auth0)?",
            "Hosting: managed (Vercel/Netlify) or self-hosted (VPS/k8s)?",
        ],
        domain_context=(
            "Web app development. Common stacks: Next.js + FastAPI, Django + React, "
            "Vue + Express. Reference repos: vercel/next.js, tiangolo/fastapi, "
            "django/django. Security must-haves: HTTPS, CSP headers, CSRF tokens, "
            "parameterised queries, input validation. Deployment: Vercel/Netlify for "
            "frontend, Fly/Railway/VPS for backend, managed Postgres (Supabase/Neon)."
        ),
        risks=[
            "XSS and CSRF are the most common web vulns — always escape + use CSRF tokens.",
            "Database migrations can fail in production — test on a staging copy.",
            "Environment variables / secrets leaked into frontend bundles.",
            "Rate limiting absent → DoS / abuse.",
            "CORS misconfigured → credentials leaked cross-origin.",
        ],
        estimated_duration_h=60.0,
        suggested_budget_usd=3.0,
    )


def _cli_tool_template() -> TaskTemplate:
    return TaskTemplate(
        name=TaskDomain.SOFTWARE_CLI.value,
        title="CLI Tool Development",
        description=(
            "Build a command-line tool: argument parsing, core logic, packaging, "
            "and distribution. Covers design, implementation, testing, and PyPI/npm release."
        ),
        specialists=[
            SpecialistStep(
                specialist="@planner",
                purpose="Define the CLI surface: commands, flags, output format.",
                input_hint="Plan the CLI commands and flags.",
            ),
            SpecialistStep(
                specialist="@coder",
                purpose="Implement the CLI (argparse/click/typer).",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Write the CLI tool code.",
            ),
            SpecialistStep(
                specialist="@tester",
                purpose="Write unit tests for each command + edge cases.",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Test the CLI tool.",
            ),
            SpecialistStep(
                specialist="@devops-engineer",
                purpose="Package for distribution (PyPI / npm / Homebrew / release binary).",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Package and publish the CLI tool.",
            ),
        ],
        clarifying_questions=[
            "Language: Python (click/typer), Go (cobra), Rust (clap), or Node (commander)?",
            "Distribution: PyPI, npm, Homebrew, standalone binary, or all?",
            "Does it need network access (API calls) or is it purely local?",
            "Interactive (prompts) or fully flag-driven?",
        ],
        domain_context=(
            "CLI tool development. Python: use click or typer (typer for type-hinted "
            "ergonomics). Go: cobra. Rust: clap. Node: commander. Always: --help text, "
            "exit codes (0 success, 1 error), --version flag, --verbose/--quiet, "
            "JSON output mode for piping. Package: pyproject.toml + build for Python, "
            "goreleaser for Go, cargo for Rust."
        ),
        risks=[
            "No --help or poor help text → unusable.",
            "Non-zero exit codes on success → breaks shell pipelines.",
            "Hardcoded paths that break on Windows.",
            "Missing dependency pinning → future breakage.",
        ],
        estimated_duration_h=12.0,
        suggested_budget_usd=0.5,
    )


def _rest_api_template() -> TaskTemplate:
    return TaskTemplate(
        name=TaskDomain.SOFTWARE_API.value,
        title="REST API Development",
        description=(
            "Design and build a REST API: schema, endpoints, auth, persistence, "
            "and OpenAPI documentation."
        ),
        specialists=[
            SpecialistStep(
                specialist="@planner",
                purpose="Define resource model, endpoints, and status codes.",
                input_hint="Plan the REST API endpoints and resources.",
            ),
            SpecialistStep(
                specialist="@coder",
                purpose="Implement the API (FastAPI/Express/Django REST).",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Write the REST API code.",
            ),
            SpecialistStep(
                specialist="@tester",
                purpose="Write API contract tests + integration tests.",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Test the REST API endpoints.",
            ),
            SpecialistStep(
                specialist="@security-auditor",
                purpose="Audit auth (JWT/OAuth), rate limiting, input validation, SQL injection.",
                tools=["fs_read"],
                input_hint="Security audit of the REST API.",
            ),
            SpecialistStep(
                specialist="@devops-engineer",
                purpose="Deploy + add health checks, metrics, and OpenAPI docs.",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Deploy the API to production.",
            ),
        ],
        clarifying_questions=[
            "Framework: FastAPI (Python), Express (Node), Django REST, or Go?",
            "Auth: API keys, JWT, or OAuth2?",
            "Database: Postgres, MySQL, SQLite, or MongoDB?",
            "Synchronous or async?",
            "OpenAPI/Swagger docs needed?",
        ],
        domain_context=(
            "REST API development. Standards: HTTP methods (GET/POST/PUT/PATCH/DELETE), "
            "status codes (200/201/204/400/401/403/404/422/429/500), idempotency keys, "
            "pagination (cursor or offset), versioning (/v1/). Frameworks: FastAPI "
            "(auto OpenAPI), Express, Django REST Framework. Always: input validation, "
            "rate limiting, CORS, HTTPS, structured logging."
        ),
        risks=[
            "No rate limiting → DoS / abuse.",
            "N+1 queries → performance cliff at scale.",
            "No idempotency → duplicate writes on retry.",
            "Auth bypass via missing checks on specific endpoints.",
        ],
        estimated_duration_h=30.0,
        suggested_budget_usd=2.0,
    )


def _osint_template() -> TaskTemplate:
    return TaskTemplate(
        name=TaskDomain.OSINT.value,
        title="OSINT Investigation",
        description=(
            "Open-source intelligence investigation: gather, correlate, and "
            "verify publicly-available information about a person, organisation, "
            "or asset. Covers source discovery, data collection, analysis, and "
            "reporting."
        ),
        specialists=[
            SpecialistStep(
                specialist="@researcher",
                purpose="Identify and gather public sources (social media, registries, news, breaches).",
                tools=["http", "fs_read", "fs_write"],
                input_hint="Gather public sources for the investigation target.",
            ),
            SpecialistStep(
                specialist="@data-scientist",
                purpose="Correlate data points, build a timeline, and score confidence per finding.",
                tools=["fs_read", "fs_write"],
                input_hint="Correlate the gathered data and build a timeline.",
            ),
            SpecialistStep(
                specialist="@security-auditor",
                purpose="Verify sources, detect disinformation, and assess collection legality.",
                tools=["fs_read", "http"],
                input_hint="Verify source authenticity and assess legal/ethical boundaries.",
            ),
            SpecialistStep(
                specialist="@market-analyst",
                purpose="If the target is an organisation: assess its market position and exposure.",
                tools=["http", "fs_read"],
                input_hint="Assess the organisation's market position and exposure.",
            ),
            SpecialistStep(
                specialist="@product-manager",
                purpose="Synthesise findings into a structured investigation report.",
                tools=["fs_write"],
                input_hint="Write the final investigation report with confidence levels.",
            ),
        ],
        clarifying_questions=[
            "What is the investigation target? (person, company, domain, asset)",
            "What is the goal? (due diligence, threat assessment, background check, journalism)",
            "What jurisdictions are involved? (affects what data is legal to collect)",
            "Time scope: current snapshot, or historical pattern over N years?",
            "Output format: structured report, timeline, or raw evidence pack?",
        ],
        domain_context=(
            "OSINT investigation. Public sources: social media (LinkedIn, Twitter/X, "
            "Mastodon), corporate registries (OpenCorporates, SEC EDGAR), domain/DNS "
            "(whois, crt.sh, SecurityTrails, Shodan), breach databases (Have I Been "
            "Pwned — for verification only), news archives, court records (PACER, "
            "CourtListener), satellite imagery (Google Earth, Sentinel Hub). Tools: "
            "Maltego, SpiderFoot, Recon-ng, theHarvester. Ethics: only collect publicly "
            "available data; respect platform ToS; do not attempt unauthorised access; "
            "document chain of custody for every finding. Confidence scoring: use the "
            "Admiralty Code (A1-F6) or a simpler High/Medium/Low with source citation."
        ),
        risks=[
            "Scraping platforms may violate their ToS — check before collecting.",
            "Data brokers sell stale/inaccurate data — verify against primary sources.",
            "Disinformation campaigns plant false trails — cross-check independent sources.",
            "GDPR/CCPA may restrict how personal data is stored/shared — anonymise where possible.",
            "Operational security: your own IP/identity may be exposed during collection.",
        ],
        estimated_duration_h=8.0,
        suggested_budget_usd=1.0,
    )


def _financial_template() -> TaskTemplate:
    return TaskTemplate(
        name=TaskDomain.FINANCIAL_ANALYSIS.value,
        title="Financial / Investment Analysis",
        description=(
            "Analyse a company, asset, or portfolio for investment purposes. "
            "Covers market research, quantitative analysis, valuation, risk "
            "assessment, and recommendation."
        ),
        specialists=[
            SpecialistStep(
                specialist="@market-analyst",
                purpose="Assess market size, competitive position, and macro trends.",
                tools=["http", "fs_read"],
                input_hint="Analyse the market and competitive position.",
            ),
            SpecialistStep(
                specialist="@data-scientist",
                purpose="Run quantitative analysis: financial ratios, DCF, comparable analysis.",
                tools=["fs_read", "fs_write"],
                input_hint="Quantitative financial analysis (ratios, DCF, comparables).",
            ),
            SpecialistStep(
                specialist="@cost-estimator",
                purpose="Project costs, break-even, and sensitivity scenarios.",
                tools=["fs_read"],
                input_hint="Project costs and break-even under multiple scenarios.",
            ),
            SpecialistStep(
                specialist="@security-auditor",
                purpose="Audit the target's financial controls and disclosure history.",
                tools=["fs_read", "http"],
                input_hint="Audit financial controls and disclosure history.",
            ),
            SpecialistStep(
                specialist="@product-manager",
                purpose="Synthesise into an investment thesis with recommendation and risks.",
                tools=["fs_write"],
                input_hint="Write the investment thesis with recommendation and risk factors.",
            ),
        ],
        clarifying_questions=[
            "What is the target? (public company, private company, crypto asset, sector)",
            "What is the analysis purpose? (buy/sell recommendation, due diligence, risk assessment)",
            "Time horizon: short-term trade, or long-term investment?",
            "Risk tolerance: conservative, balanced, or aggressive?",
            "Do you have access to paid data (Bloomberg, S&P Capital IQ) or only public filings?",
        ],
        domain_context=(
            "Financial analysis. Public data sources: SEC EDGAR (10-K, 10-Q, 8-K, "
            "proxy statements), company investor relations pages, FRED (Fed economic "
            "data), Yahoo Finance, Google Finance, Stooq. Valuation methods: DCF "
            "(discounted cash flow), comparables (P/E, EV/EBITDA, P/S), precedent "
            "transactions, asset-based. Key ratios: current, quick, debt-to-equity, "
            "ROE, ROIC, FCF yield. Always disclose: this is not financial advice; "
            "past performance does not guarantee future results; conflicts of interest."
        ),
        risks=[
            "Garbage-in-garbage-out: bad financials → bad valuation. Always trace to primary filings.",
            "Survivorship bias in comparables data.",
            "Black-swan events invalidate DCF assumptions — always run sensitivity analysis.",
            "Regulatory risk: ensure you are not providing licensed investment advice.",
            "Conflicts of interest must be disclosed.",
        ],
        estimated_duration_h=10.0,
        suggested_budget_usd=1.5,
    )


def _security_audit_template() -> TaskTemplate:
    return TaskTemplate(
        name=TaskDomain.SECURITY_AUDIT.value,
        title="Security Audit",
        description=(
            "Audit a codebase, system, or deployment for security vulnerabilities. "
            "Covers threat modelling, code review, dependency scan, and remediation plan."
        ),
        specialists=[
            SpecialistStep(
                specialist="@researcher",
                purpose="Gather context: architecture, data flows, trust boundaries, threat model.",
                tools=["fs_read", "http"],
                input_hint="Gather architecture context and build a threat model.",
            ),
            SpecialistStep(
                specialist="@security-auditor",
                purpose="Audit code for OWASP Top 10, injection, auth bypass, crypto misuse.",
                tools=["fs_read", "shell"],
                input_hint="Audit the codebase for vulnerabilities (OWASP Top 10).",
            ),
            SpecialistStep(
                specialist="@coder",
                purpose="Write fixes for the vulnerabilities found.",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Fix the identified vulnerabilities.",
            ),
            SpecialistStep(
                specialist="@tester",
                purpose="Write regression tests proving the fixes work and the vuln is closed.",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Write regression tests for the security fixes.",
            ),
            SpecialistStep(
                specialist="@devops-engineer",
                purpose="Add security to CI/CD: SAST, dependency scan, secret scanning.",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Add security scanning to the CI/CD pipeline.",
            ),
        ],
        clarifying_questions=[
            "What is the scope? (codebase, deployment, cloud account, specific feature)",
            "Compliance framework required? (OWASP, SOC 2, PCI-DSS, HIPAA, GDPR)",
            "Is this a pre-production audit or a live system audit?",
            "Do you have access to the source code, or black-box only?",
            "What is the severity threshold for blocking release? (Critical, High, Medium)",
        ],
        domain_context=(
            "Security audit. Frameworks: OWASP Top 10 (2021: A01 Broken Access Control "
            "through A10 SSRF), OWASP ASVS, NIST CSF, CIS Benchmarks. Tools: SAST "
            "(Semgrep, Bandit, CodeQL), dependency scan (pip-audit, npm audit, Snyk), "
            "secret scan (gitleaks, trufflehog), DAST (ZAP, Burp). Common findings: "
            "SQL injection (use parameterised queries), XSS (escape output), CSRF "
            "(tokens), auth bypass (check every endpoint), insecure crypto (use "
            "bcrypt/argon2 for passwords, AES-GCM for data), hardcoded secrets."
        ),
        risks=[
            "False sense of security: passing an audit ≠ secure. New vulns emerge constantly.",
            "Dependency vulnerabilities may have no fix available (vendor abandonment).",
            "Black-box audits miss logic flaws only visible in source.",
            "Remediation may introduce regressions — always test fixes.",
            "Compliance ≠ security: passing PCI-DSS doesn't mean you're not vulnerable.",
        ],
        estimated_duration_h=16.0,
        suggested_budget_usd=2.0,
    )


def _data_analysis_template() -> TaskTemplate:
    return TaskTemplate(
        name=TaskDomain.DATA_ANALYSIS.value,
        title="Data Analysis / ML",
        description=(
            "Analyse a dataset or build a machine-learning model. Covers data "
            "exploration, cleaning, modelling, evaluation, and deployment."
        ),
        specialists=[
            SpecialistStep(
                specialist="@data-scientist",
                purpose="Explore the dataset: distributions, missing values, correlations, outliers.",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Exploratory data analysis on the dataset.",
            ),
            SpecialistStep(
                specialist="@data-scientist",
                purpose="Clean, transform, and engineer features.",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Clean and feature-engineer the dataset.",
            ),
            SpecialistStep(
                specialist="@data-scientist",
                purpose="Train and evaluate candidate models with cross-validation.",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Train and evaluate ML models.",
            ),
            SpecialistStep(
                specialist="@security-auditor",
                purpose="Audit for data leakage, bias, and privacy (PII in training data).",
                tools=["fs_read"],
                input_hint="Audit the ML pipeline for leakage, bias, and privacy.",
            ),
            SpecialistStep(
                specialist="@devops-engineer",
                purpose="Package the model for inference (API, batch, or edge).",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Deploy the model for inference.",
            ),
        ],
        clarifying_questions=[
            "What is the dataset? (CSV, database, API, real-time stream)",
            "What is the task? (classification, regression, clustering, NLP, time-series)",
            "What is the target metric? (accuracy, F1, RMSE, AUC)",
            "Is the data labelled, or is this unsupervised?",
            "Deployment: batch inference, real-time API, or edge device?",
        ],
        domain_context=(
            "Data analysis / ML. Python stack: pandas, numpy, scikit-learn, "
            "xgboost, lightgbm, PyTorch, TensorFlow, matplotlib, seaborn, plotly. "
            "Best practices: train/val/test split (no leakage!), cross-validation, "
            "feature importance, confusion matrix, residual analysis. Common pitfalls: "
            "data leakage (target in features), look-ahead bias (future data in training), "
            "class imbalance (use stratified sampling + appropriate metrics), "
            "overfitting (regularisation + early stopping). Ethics: check for bias "
            "across demographic groups, remove PII from training data, document the "
            "model card."
        ),
        risks=[
            "Data leakage inflates metrics — always split before any preprocessing fit.",
            "Class imbalance without stratification → misleading accuracy.",
            "Concept drift: production data diverges from training data over time.",
            "Bias in training data → discriminatory predictions.",
            "PII in training data → privacy / legal exposure.",
        ],
        estimated_duration_h=20.0,
        suggested_budget_usd=2.0,
    )


def _devops_template() -> TaskTemplate:
    return TaskTemplate(
        name=TaskDomain.DEVOPS.value,
        title="DevOps / Infrastructure",
        description=(
            "Set up CI/CD, infrastructure-as-code, containerisation, or cloud "
            "deployment. Covers design, implementation, testing, and monitoring."
        ),
        specialists=[
            SpecialistStep(
                specialist="@planner",
                purpose="Design the infrastructure: services, network, scaling, cost.",
                input_hint="Plan the infrastructure architecture.",
            ),
            SpecialistStep(
                specialist="@coder",
                purpose="Write IaC (Terraform/Pulumi), Dockerfiles, and CI/CD pipelines.",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Write the infrastructure-as-code and CI/CD pipeline.",
            ),
            SpecialistStep(
                specialist="@security-auditor",
                purpose="Audit IAM permissions, secrets management, and network exposure.",
                tools=["fs_read", "shell"],
                input_hint="Audit IAM, secrets, and network exposure.",
            ),
            SpecialistStep(
                specialist="@devops-engineer",
                purpose="Deploy, configure monitoring (Prometheus/Grafana), and set up alerts.",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Deploy and set up monitoring + alerting.",
            ),
        ],
        clarifying_questions=[
            "Cloud provider: AWS, GCP, Azure, or self-hosted?",
            "IaC tool: Terraform, Pulumi, CloudFormation, or Ansible?",
            "Containerisation: Docker, Docker Compose, or Kubernetes?",
            "CI/CD: GitHub Actions, GitLab CI, Jenkins, or CircleCI?",
            "Monitoring: Prometheus+Grafana, Datadog, or cloud-native?",
        ],
        domain_context=(
            "DevOps. IaC: Terraform (most portable), Pulumi (code-native), "
            "CloudFormation (AWS-only). Containers: Dockerfile best practices "
            "(multi-stage builds, non-root user, .dockerignore, pinned base images). "
            "K8s: use Helm charts, set resource requests/limits, liveness/readiness "
            "probes, PodSecurityPolicies. CI/CD: GitHub Actions for OSS, GitLab CI "
            "for self-hosted. Secrets: never in code — use vault (AWS Secrets Manager, "
            "HashiCorp Vault, Doppler). Monitoring: RED metrics (Rate, Errors, Duration) "
            "for services, USE (Utilisation, Saturation, Errors) for resources."
        ),
        risks=[
            "Over-provisioned resources → cost overruns.",
            "IAM roles too broad → blast radius on compromise.",
            "No drift detection → manual changes diverge from IaC.",
            "Missing backups → data loss on infrastructure failure.",
            "Alert fatigue → real incidents ignored.",
        ],
        estimated_duration_h=16.0,
        suggested_budget_usd=1.5,
    )


def _design_template() -> TaskTemplate:
    return TaskTemplate(
        name=TaskDomain.DESIGN.value,
        title="Graphic Design",
        description=(
            "Create a graphic design asset: logo, poster, UI mockup, brand "
            "identity, or illustration. Covers requirements, research, "
            "iteration, and delivery."
        ),
        specialists=[
            SpecialistStep(
                specialist="@product-manager",
                purpose="Clarify the brief: audience, message, mood, constraints, deliverables.",
                input_hint="Clarify the design brief and requirements.",
            ),
            SpecialistStep(
                specialist="@researcher",
                purpose="Gather references: competitor designs, mood board, style inspiration.",
                tools=["http", "fs_read"],
                input_hint="Gather design references and build a mood board.",
            ),
            SpecialistStep(
                specialist="@market-analyst",
                purpose="Assess how the design positions the brand vs competitors.",
                tools=["fs_read"],
                input_hint="Assess the brand positioning vs competitors.",
            ),
            SpecialistStep(
                specialist="@coder",
                purpose="Generate the design (SVG/code-based) or write a spec for a human designer.",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Generate the design asset or write a detailed design spec.",
            ),
            SpecialistStep(
                specialist="@reviewer",
                purpose="Review against the brief: clarity, brand fit, accessibility.",
                tools=["fs_read"],
                input_hint="Review the design against the brief.",
            ),
        ],
        clarifying_questions=[
            "What is the deliverable? (logo, poster, social media graphic, UI mockup, brand guide)",
            "What is the brand personality? (minimalist, bold, playful, corporate, brutalist)",
            "Who is the target audience?",
            "Colour palette: do you have brand colours, or should we propose?",
            "Format and size: print (CMYK, DPI), digital (RGB, px), or both?",
            "Any reference designs or competitors you like/dislike?",
        ],
        domain_context=(
            "Graphic design. ARNES can generate SVG-based designs (logos, icons, "
            "patterns, data viz) via code. For raster/photographic work, it writes a "
            "detailed spec for a human designer or an image-generation model. "
            "Principles: hierarchy (size/weight/colour), contrast, whitespace, "
            "alignment (grid), consistency. Colour theory: complementary, analogous, "
            "triadic; check contrast for accessibility (WCAG AA = 4.5:1 for text). "
            "Typography: max 2 fonts, scale ratio (1.25 minor third, 1.333 major "
            "third). Tools: Figma, Inkscape (SVG), Adobe Illustrator. ARNES outputs "
            "SVG which is resolution-independent and editable."
        ),
        risks=[
            "Generic AI-generated designs lack brand differentiation.",
            "Colour contrast too low → fails accessibility (WCAG).",
            "Font licensing — many commercial fonts cannot be embedded.",
            "Print vs digital colour spaces (CMYK vs RGB) — convert early.",
            "No vector source → cannot scale without quality loss.",
        ],
        estimated_duration_h=6.0,
        suggested_budget_usd=0.5,
    )


def _content_template() -> TaskTemplate:
    return TaskTemplate(
        name=TaskDomain.CONTENT.value,
        title="Content Creation",
        description=(
            "Write long-form content: blog post, article, documentation, "
            "whitepaper, or newsletter. Covers research, outline, drafting, "
            "and editing."
        ),
        specialists=[
            SpecialistStep(
                specialist="@researcher",
                purpose="Gather sources, facts, and prior art on the topic.",
                tools=["http", "fs_read"],
                input_hint="Research the topic and gather authoritative sources.",
            ),
            SpecialistStep(
                specialist="@planner",
                purpose="Build an outline with sections, key points, and citations.",
                input_hint="Plan the content outline.",
            ),
            SpecialistStep(
                specialist="@coder",
                purpose="Draft the content following the outline.",
                tools=["fs_read", "fs_write"],
                input_hint="Write the first draft of the content.",
            ),
            SpecialistStep(
                specialist="@reviewer",
                purpose="Edit for clarity, tone, accuracy, and citation completeness.",
                tools=["fs_read"],
                input_hint="Edit and fact-check the draft.",
            ),
            SpecialistStep(
                specialist="@market-analyst",
                purpose="Optimise for SEO / audience fit if publishing publicly.",
                tools=["fs_read"],
                input_hint="Optimise for SEO and audience fit.",
            ),
        ],
        clarifying_questions=[
            "What format? (blog post, article, documentation, whitepaper, newsletter, essay)",
            "What is the target length? (500, 1500, 3000+ words)",
            "Who is the audience? (technical, business, general public)",
            "What tone? (formal, conversational, academic, punchy)",
            "Is SEO important? If so, what keywords?",
            "Do you have existing research/sources, or should we research from scratch?",
        ],
        domain_context=(
            "Content creation. Best practices: hook in the first 2 sentences, one idea "
            "per paragraph, active voice, concrete examples > abstractions, cite "
            "sources (hyperlink or footnote), use headings/subheadings for scanability. "
            "SEO: target keyword in title + first 100 words + one H2, meta description "
            "150-160 chars, internal links to related content, alt text on images. "
            "Fact-checking: verify every statistic against the primary source. "
            "Plagiarism: never copy-paste; paraphrase + cite. Accessibility: plain "
            "language, descriptive headings, transcripts for embedded media."
        ),
        risks=[
            "Hallucinated facts / citations — always verify against primary sources.",
            "Plagiarism — check with a similarity tool before publishing.",
            "SEO over-optimisation → keyword stuffing harms readability and ranking.",
            "Tone mismatch with brand voice.",
            "Outdated statistics — check publication dates of sources.",
        ],
        estimated_duration_h=4.0,
        suggested_budget_usd=0.5,
    )


def _research_template() -> TaskTemplate:
    return TaskTemplate(
        name=TaskDomain.RESEARCH.value,
        title="Academic Research",
        description=(
            "Conduct academic research: literature review, hypothesis, "
            "methodology, experiment, and writeup. Covers the full research "
            "lifecycle with reproducibility and citation rigor."
        ),
        specialists=[
            SpecialistStep(
                specialist="@researcher",
                purpose="Conduct a systematic literature review; identify gaps.",
                tools=["http", "fs_read", "fs_write"],
                input_hint="Systematic literature review on the research question.",
            ),
            SpecialistStep(
                specialist="@planner",
                purpose="Formulate hypothesis and design the methodology.",
                input_hint="Design the research methodology.",
            ),
            SpecialistStep(
                specialist="@data-scientist",
                purpose="Run the experiment / analysis with reproducible code.",
                tools=["fs_read", "fs_write", "shell"],
                input_hint="Run the experiment with reproducible code.",
            ),
            SpecialistStep(
                specialist="@reviewer",
                purpose="Peer-review the methodology, results, and threats to validity.",
                tools=["fs_read"],
                input_hint="Peer-review the methodology and results.",
            ),
            SpecialistStep(
                specialist="@coder",
                purpose="Write the paper / report with proper citations (BibTeX).",
                tools=["fs_read", "fs_write"],
                input_hint="Write the research paper with citations.",
            ),
        ],
        clarifying_questions=[
            "What is the research question?",
            "What field? (CS, biology, social science, etc. — affects methodology)",
            "Is this for publication, a thesis, or internal use?",
            "Do you have data, or does the data need collecting?",
            "Citation style? (APA, MLA, Chicago, IEEE, BibTeX)",
        ],
        domain_context=(
            "Academic research. Literature sources: Google Scholar, Semantic Scholar, "
            "arXiv, PubMed, DBLP, SSRN. Methodology: quantitative (statistical "
            "hypothesis testing), qualitative (case study, ethnography), mixed. "
            "Reproducibility: pin all dependencies, set random seeds, publish code+data, "
            "use container (Docker/Singularity). Threats to validity: internal "
            "(confounders), external (generalisability), construct (measurement), "
            "conclusion (statistical power). Ethics: IRB approval for human subjects, "
            "informed consent, data anonymisation. Citation: use Zotero/JabRef for "
            "BibTeX management; never fabricate citations."
        ),
        risks=[
            "P-hacking / cherry-picking results → irreproducible findings.",
            "Confirmation bias in literature selection.",
            "Insufficient statistical power (small sample size).",
            "Data dredging without multiple-comparison correction.",
            "Citation fabrication / hallucination — verify every reference exists.",
        ],
        estimated_duration_h=40.0,
        suggested_budget_usd=3.0,
    )


def _generic_template() -> TaskTemplate:
    return TaskTemplate(
        name=TaskDomain.GENERIC.value,
        title="Generic Planning",
        description=(
            "Fallback template when the request does not match a specific "
            "domain. Uses the proactive planner to research, estimate, and "
            "propose a custom playbook."
        ),
        specialists=[
            SpecialistStep(
                specialist="@planner",
                purpose="Analyse the request and propose a specialist sequence.",
                input_hint="Plan the approach for this request.",
            ),
        ],
        clarifying_questions=[
            "Can you describe the end goal in one sentence?",
            "What does success look like?",
            "Any constraints (budget, deadline, tools, languages)?",
        ],
        domain_context="",
        risks=[
            "Vague request → vague plan. Clarify before executing.",
        ],
        estimated_duration_h=4.0,
        suggested_budget_usd=1.0,
    )


def _build_default_library() -> dict[str, TaskTemplate]:
    """Construct the default library catalogue."""
    templates = [
        _mobile_app_template(),
        _web_app_template(),
        _cli_tool_template(),
        _rest_api_template(),
        _osint_template(),
        _financial_template(),
        _security_audit_template(),
        _data_analysis_template(),
        _devops_template(),
        _design_template(),
        _content_template(),
        _research_template(),
        _generic_template(),
    ]
    return {t.name: t for t in templates}


class PlaybookLibrary:
    """The catalogue of domain-specific task templates.

    Use :meth:`get` to look up a template by domain name, or
    :meth:`match` to classify a free-text request and return the best
    template.
    """

    def __init__(self, templates: dict[str, TaskTemplate] | None = None) -> None:
        self._templates: dict[str, TaskTemplate] = templates or _build_default_library()
        self._router = TaskRouter()

    def get(self, name: str) -> TaskTemplate | None:
        """Return the template with the given name, or ``None``."""
        return self._templates.get(name)

    def match(self, request: str) -> TaskTemplate:
        """Classify ``request`` and return the best-matching template.

        Always returns a template (falls back to the generic template when
        no domain scores above the threshold).
        """
        domain = self._router.classify(request)
        template = self._templates.get(domain.value)
        if template is None:
            template = self._templates[TaskDomain.GENERIC.value]
        return template

    def match_with_confidence(self, request: str) -> tuple[TaskTemplate, float, dict[str, int]]:
        """Return ``(template, confidence, scores)``.

        ``scores`` is the raw per-domain score dict from the router.
        """
        domain, confidence, scores = self._router.classify_with_confidence(request)
        template = self._templates.get(domain.value)
        if template is None:
            template = self._templates[TaskDomain.GENERIC.value]
        return template, confidence, scores

    def list_templates(self) -> list[TaskTemplate]:
        """Return all registered templates, sorted by name."""
        return sorted(self._templates.values(), key=lambda t: t.name)

    def list_names(self) -> list[str]:
        """Return all template names, sorted."""
        return sorted(self._templates.keys())


@functools.lru_cache(maxsize=1)
def get_default_library() -> PlaybookLibrary:
    """Return the singleton default library instance."""
    return PlaybookLibrary()
