from __future__ import annotations

from v2.core.models import BacktestMetric
from v2.core.template_learning import CustomerTemplateLearningService


class BacktestAnalyticsService:
    def __init__(self, templates: CustomerTemplateLearningService) -> None:
        self._templates = templates

    def summary_metrics(self) -> list[BacktestMetric]:
        profiles = self._templates.profiles()
        samples = sum(profile.sample_count for profile in profiles)
        failures = sum(profile.failure_count for profile in profiles)
        accuracy = 0 if samples == 0 else round((samples - failures) / samples * 100, 1)
        busiest_customer = self._templates.customer_format_counts().most_common(1)

        return [
            BacktestMetric("Parser 正確率", f"{accuracy}%", "等待正式回測資料"),
            BacktestMetric("最常失敗格式", "供應商 B PKG", "範例資料"),
            BacktestMetric("最有用 warning", "數量欄位語意衝突", "待 AI 評分"),
            BacktestMetric("格式最多客戶", busiest_customer[0][0] if busiest_customer else "-", "範例資料"),
        ]

