
from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "PageHeader": (".headers", "PageHeader"), "SectionTitle": (".headers", "SectionTitle"),
    "PrimaryButton": (".buttons", "PrimaryButton"), "SecondaryButton": (".buttons", "SecondaryButton"),
    "Badge": (".badges", "Badge"),
    "Card": (".cards", "Card"), "FeatureCard": (".cards", "FeatureCard"), "CollapsiblePanel": (".cards", "CollapsiblePanel"),
    "MetricCard": (".metrics", "MetricCard"), "InlineMetric": (".metrics", "InlineMetric"), "SummaryStrip": (".metrics", "SummaryStrip"),
    "InfoRow": (".information", "InfoRow"), "PageScrollArea": (".information", "PageScrollArea"), "KeyValueGrid": (".information", "KeyValueGrid"),
    "FormGrid": (".forms", "FormGrid"),
}


def __getattr__(name: str):
    module_name, attr_name = _EXPORTS.get(name, (None, None))
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)
