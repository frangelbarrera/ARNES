"""@data-scientist — proactive data analysis, statistics, and ML model evaluation."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from arnes.specialists.base import Specialist, SpecialistConfig

_DATA_SCIENTIST_SYSTEM_PROMPT = """You are @data-scientist, a senior data scientist who trusts the data more than \
the narrative and treats model evaluation as a forensic exercise.

Your job:
1. Analyze datasets (CSV, JSON, Parquet, SQL dumps) and produce statistical insights — distributions, \
correlations, outliers, missingness, drift.
2. Evaluate ML models rigorously: accuracy, precision, recall, F1, ROC-AUC, calibration, \
confusion matrix, per-slice performance, fairness across subgroups.
3. Create data visualizations (matplotlib, seaborn, plotly) — save them as files with clear captions.
4. PROACTIVELY identify data quality issues (leakage, label imbalance, snooping, dataset shift, \
duplicated rows, schema drift) before they poison a model.

Operating principles:
- Be proactive, not reactive. If you spot leakage or drift the user did not ask about, surface it.
- Never report a metric without its confidence interval or significance context.
- Sanity-check every number against a heuristic (e.g. accuracy ~= base rate is a red flag).
- Distinguish between descriptive, inferential, and predictive claims — and label them as such.
- Call out sample-size limitations explicitly. "Trend" on n=12 is not a trend.
- Default to skepticism about model performance until you have held out a clean test set.
- If the data is dirty, say so first; do not polish a number on top of garbage.

Return JSON matching this schema:
{
  "summary": "Executive summary of the analysis",
  "dataset_profile": {
    "n_rows": 10000,
    "n_columns": 12,
    "missing_pct": 4.2,
    "duplicate_rows": 17,
    "column_types": {"numeric": 7, "categorical": 4, "datetime": 1}
  },
  "statistics": [
    {
      "metric": "mean_order_value",
      "value": 42.17,
      "unit": "USD",
      "confidence_interval": [40.10, 44.24],
      "n": 9823
    }
  ],
  "model_evaluation": {
    "metrics": {
      "accuracy": 0.87,
      "precision": 0.83,
      "recall": 0.79,
      "f1": 0.81,
      "roc_auc": 0.91
    },
    "confusion_matrix": {"tp": 790, "fp": 162, "fn": 211, "tn": 8837},
    "per_slice_performance": [
      {"slice": "age_18_24", "recall": 0.61, "n": 1200}
    ],
    "failure_modes": ["Where and why the model underperforms"]
  },
  "visualizations": [
    {
      "path": "reports/eda_distribution.png",
      "title": "Order value distribution",
      "caption": "Right-skewed; log transform recommended"
    }
  ],
  "data_quality_issues": [
    {
      "severity": "critical|major|minor",
      "issue": "Target leakage: `is_returned` is present in features",
      "affected_columns": ["is_returned"],
      "recommendation": "Drop column before training"
    }
  ],
  "recommendations": ["Actionable next steps"]
}

You MUST respond with ONLY valid JSON matching the schema. No markdown, no explanation, no code fences. Just the JSON object.
"""


# ============================================================
# Pydantic output models — strong `pydantic_model` validator.
# Validates types AND enum values (severity) and enforces nested
# required fields + dict[str, ...] structures, which the weak
# JSON-schema `output_schema` check cannot do.
# ============================================================


DataSeverity = Literal["critical", "major", "minor"]


class DatasetProfile(BaseModel):
    """High-level profile of the analyzed dataset."""

    n_rows: int | None = None
    n_columns: int | None = None
    missing_pct: float | None = None
    duplicate_rows: int | None = None
    column_types: dict[str, int] = Field(default_factory=dict)


class Statistic(BaseModel):
    """A single statistical finding."""

    metric: str
    value: float | int | str
    unit: str | None = None
    confidence_interval: list[float] | None = None
    n: int | None = None


class ModelMetrics(BaseModel):
    """Standard ML evaluation metrics."""

    accuracy: float | None = None
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    roc_auc: float | None = None


class SlicePerformance(BaseModel):
    """Performance on a data slice (subgroup)."""

    slice: str
    recall: float | None = None
    precision: float | None = None
    n: int | None = None


class ModelEvaluation(BaseModel):
    """Rigorous evaluation of an ML model."""

    metrics: ModelMetrics = Field(default_factory=ModelMetrics)
    confusion_matrix: dict[str, int] = Field(default_factory=dict)
    per_slice_performance: list[SlicePerformance] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)


class Visualization(BaseModel):
    """A saved data visualization."""

    path: str
    title: str | None = None
    caption: str | None = None


class DataQualityIssue(BaseModel):
    """A data quality issue identified during analysis."""

    severity: DataSeverity
    issue: str
    affected_columns: list[str] = Field(default_factory=list)
    recommendation: str | None = None


class DataScientistOutput(BaseModel):
    """Structured output for the @data-scientist specialist."""

    summary: str
    dataset_profile: DatasetProfile = Field(default_factory=DatasetProfile)
    statistics: list[Statistic] = Field(default_factory=list)
    model_evaluation: ModelEvaluation | None = None
    visualizations: list[Visualization] = Field(default_factory=list)
    data_quality_issues: list[DataQualityIssue] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class DataScientist(Specialist):
    """@data-scientist — analyzes datasets, evaluates ML models, and surfaces data quality issues."""

    config: ClassVar[SpecialistConfig] = SpecialistConfig(
        name="@data-scientist",
        description=(
            "Data analysis, statistics, and ML model evaluation specialist. Proactively "
            "identifies data quality issues like leakage, drift, and label imbalance."
        ),
        system_prompt=_DATA_SCIENTIST_SYSTEM_PROMPT,
        tools=["fs_read", "fs_write", "shell"],
        output_schema={
            "type": "object",
            "required": ["summary"],
            "properties": {
                "summary": {"type": "string"},
                "dataset_profile": {"type": "object"},
                "statistics": {"type": "array"},
                "model_evaluation": {"type": "object"},
                "visualizations": {"type": "array"},
                "data_quality_issues": {"type": "array"},
                "recommendations": {"type": "array"},
            },
        },
        # Strong validation: pydantic validates nested DatasetProfile /
        # Statistic / ModelEvaluation / SlicePerformance / DataQualityIssue
        # models (types + required fields + enum values) — a malformed
        # `data_quality_issues: ["bad input"]` or a severity outside the
        # enum is rejected here even though it would slip past the weak
        # JSON-schema `required`-fields check.
        pydantic_model=DataScientistOutput,
        default_model="ollama/llama3.2",
        temperature=0.0,
    )
