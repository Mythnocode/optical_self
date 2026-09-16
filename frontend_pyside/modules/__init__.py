"""Primary UI-entry modules for the optical workbench.

Each first-level navigation entry owns a package here. The ordinary entries
also keep their document tabs below that package; ``app`` remains responsible
for top-level routing and cross-entry orchestration.
"""

__all__ = [
    "home",
    "simulation",
    "teaching",
    "model",
    "optimization",
    "explainability",
]
