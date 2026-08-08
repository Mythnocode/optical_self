
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping
import math

from optical_core.physics.hybrid.solvers.coupling_options import CouplingOptions


ScanMode = Literal["symmetric", "positive_only", "negative_only", "explicit"]
ThresholdSolverName = Literal["brent", "bisection"]
ToleranceDistributionName = Literal["normal", "uniform", "triangular", "fixed"]
SamplingMethod = Literal["random", "lhs", "sobol"]


@dataclass(frozen=True, slots=True)
class ToleranceParameter:


    path: str
    nominal: float
    unit: str = ""
    distribution: ToleranceDistributionName = "normal"
    sigma: float | None = None
    lower: float | None = None
    upper: float | None = None
    correlation_group: str | None = None

    def __post_init__(self) -> None:
        if not str(self.path).strip():
            raise ValueError("tolerance parameter path cannot be empty")
        if not math.isfinite(float(self.nominal)):
            raise ValueError(f"nominal value for {self.path!r} must be finite")
        if self.sigma is not None and (not math.isfinite(float(self.sigma)) or float(self.sigma) < 0.0):
            raise ValueError(f"sigma for {self.path!r} must be finite and non-negative")
        if self.lower is not None and self.upper is not None and float(self.lower) > float(self.upper):
            raise ValueError(f"lower bound exceeds upper bound for {self.path!r}")


@dataclass(frozen=True, slots=True)
class MonteCarloOptions:
    enabled: bool = False
    sample_count: int = 256
    sampling_method: SamplingMethod = "lhs"
    random_seed: int = 42
    threshold_efficiency: float | None = None
    confidence_level: float = 0.95
    batch_size: int = 64

    def __post_init__(self) -> None:
        if int(self.sample_count) < 1:
            raise ValueError("Monte Carlo sample_count must be positive")
        if str(self.sampling_method) not in {"random", "lhs", "sobol"}:
            raise ValueError("Monte Carlo sampling_method must be random, lhs, or sobol")
        if not 0.0 < float(self.confidence_level) < 1.0:
            raise ValueError("confidence_level must be in (0, 1)")
        if int(self.batch_size) < 1:
            raise ValueError("batch_size must be positive")
        if self.threshold_efficiency is not None and (
            not math.isfinite(float(self.threshold_efficiency))
            or not 0.0 <= float(self.threshold_efficiency) <= 1.0
        ):
            raise ValueError("Monte Carlo threshold_efficiency must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class ReceiverToleranceDistribution:
    dx_sigma_um: float = 0.0
    dy_sigma_um: float = 0.0
    dz_sigma_um: float = 0.0
    tilt_x_sigma_urad: float = 0.0
    tilt_y_sigma_urad: float = 0.0
    mfd_x_sigma_um: float = 0.0
    mfd_y_sigma_um: float = 0.0
    correlation_matrix: tuple[tuple[float, ...], ...] | None = None

    def __post_init__(self) -> None:
        sigmas = (
            self.dx_sigma_um, self.dy_sigma_um, self.dz_sigma_um,
            self.tilt_x_sigma_urad, self.tilt_y_sigma_urad,
            self.mfd_x_sigma_um, self.mfd_y_sigma_um,
        )
        if any(not math.isfinite(float(value)) or float(value) < 0.0 for value in sigmas):
            raise ValueError("receiver tolerance sigmas must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class FiberToleranceOptions:


    coupling: CouplingOptions = field(default_factory=CouplingOptions)
    sample_count: int = 11
    scan_mode: ScanMode = "symmetric"
    dx_range_um: tuple[float, float] = (-10.0, 10.0)
    dy_range_um: tuple[float, float] = (-10.0, 10.0)
    dz_range_um: tuple[float, float] = (-200.0, 200.0)
    
    
    tilt_x_range_urad: tuple[float, float] = (-20000.0, 20000.0)
    tilt_y_range_urad: tuple[float, float] = (-20000.0, 20000.0)
    dx_values_um: tuple[float, ...] | None = None
    dy_values_um: tuple[float, ...] | None = None
    dz_values_um: tuple[float, ...] | None = None
    tilt_x_values_urad: tuple[float, ...] | None = None
    tilt_y_values_urad: tuple[float, ...] | None = None
    include_offset_map: bool = False
    include_angular_scans: bool = True
    include_theory_curves: bool = True
    include_sensitivity_matrix: bool = False
    require_valid_propagation: bool = False
    scan_relative_to_base_offset: bool = True
    threshold_loss_db: float | None = 1.0
    threshold_relative_efficiency: float | None = None
    threshold_efficiency: float | None = None
    baseline_efficiency_minimum: float = 1.0e-8
    threshold_solver: ThresholdSolverName = "brent"
    threshold_position_xtol: float = 1.0e-3
    threshold_efficiency_ftol: float = 1.0e-6
    threshold_max_iterations: int = 40
    root_validation_fraction: float = 0.02
    auto_align_baseline: bool = False
    auto_align_include_dz: bool = False
    auto_align_focus_only: bool = False
    auto_align_max_iterations: int = 40
    auto_align_max_function_evaluations: int = 300
    auto_align_xtol: float = 1.0e-3
    auto_align_ftol: float = 1.0e-6
    auto_align_acceptance_tolerance: float = 1.0e-10
    auto_align_timeout_seconds: float | None = 60.0
    sensitivity_steps: tuple[float, ...] = (0.1, 0.05, 0.025)
    sensitivity_allowed_loss_db: float | None = None
    sensitivity_convergence_tolerance: float = 0.05
    sensitivity_gradient_tolerance: float = 0.1
    sensitivity_negative_eigenvalue_tolerance: float = 0.05
    include_arrays: bool = True
    max_explicit_axis_points: int = 4097
    monte_carlo: MonteCarloOptions = field(default_factory=MonteCarloOptions)
    receiver_distribution: ReceiverToleranceDistribution = field(default_factory=ReceiverToleranceDistribution)
    algorithm_version: str = "fiber-tolerance-2.1-stable"

    def __post_init__(self) -> None:
        if str(self.scan_mode) not in {"symmetric", "positive_only", "negative_only", "explicit"}:
            raise ValueError("scan_mode must be symmetric, positive_only, negative_only, or explicit")
        if int(self.sample_count) < 3:
            raise ValueError("sample_count must be at least 3")
        if int(self.sample_count) > int(self.max_explicit_axis_points):
            raise ValueError("sample_count exceeds max_explicit_axis_points")
        if int(self.max_explicit_axis_points) < 3:
            raise ValueError("max_explicit_axis_points must be at least 3")

        for name in (
            "dx_range_um", "dy_range_um", "dz_range_um",
            "tilt_x_range_urad", "tilt_y_range_urad",
        ):
            raw = tuple(getattr(self, name))
            if len(raw) != 2:
                raise ValueError(f"{name} must contain exactly two values")
            lo, hi = (float(raw[0]), float(raw[1]))
            if not (math.isfinite(lo) and math.isfinite(hi)):
                raise ValueError(f"{name} bounds must be finite")
            if lo > hi:
                raise ValueError(f"{name} lower bound cannot exceed upper bound")
            if name.startswith("tilt_") and max(abs(lo), abs(hi)) > 1.0e6:
                raise ValueError(f"{name} exceeds the stable absolute limit of 1e6 urad")
            object.__setattr__(self, name, (lo, hi))

        for name in (
            "dx_values_um", "dy_values_um", "dz_values_um",
            "tilt_x_values_urad", "tilt_y_values_urad",
        ):
            raw = getattr(self, name)
            if raw is None:
                continue
            values = tuple(sorted(set(float(value) for value in raw)))
            if not values or any(not math.isfinite(value) for value in values):
                raise ValueError(f"{name} must contain finite values")
            if len(values) > int(self.max_explicit_axis_points):
                raise ValueError(f"{name} contains too many points")
            object.__setattr__(self, name, values)

        if not math.isfinite(float(self.baseline_efficiency_minimum)) or float(self.baseline_efficiency_minimum) < 0.0:
            raise ValueError("baseline_efficiency_minimum must be finite and non-negative")
        if str(self.threshold_solver) not in {"brent", "bisection"}:
            raise ValueError("threshold_solver must be brent or bisection")
        if not math.isfinite(float(self.threshold_position_xtol)) or float(self.threshold_position_xtol) <= 0.0:
            raise ValueError("threshold_position_xtol must be positive")
        if not math.isfinite(float(self.threshold_efficiency_ftol)) or float(self.threshold_efficiency_ftol) <= 0.0:
            raise ValueError("threshold_efficiency_ftol must be positive")
        if int(self.threshold_max_iterations) < 1:
            raise ValueError("threshold_max_iterations must be positive")
        if not math.isfinite(float(self.root_validation_fraction)) or float(self.root_validation_fraction) < 0.0:
            raise ValueError("root_validation_fraction must be finite and non-negative")

        thresholds = [
            self.threshold_loss_db is not None,
            self.threshold_relative_efficiency is not None,
            self.threshold_efficiency is not None,
        ]
        if sum(thresholds) != 1:
            raise ValueError(
                "exactly one threshold definition is required: threshold_loss_db, "
                "threshold_relative_efficiency, or threshold_efficiency"
            )
        if self.threshold_loss_db is not None and (
            not math.isfinite(float(self.threshold_loss_db)) or float(self.threshold_loss_db) < 0.0
        ):
            raise ValueError("threshold_loss_db must be finite and non-negative")
        if self.threshold_relative_efficiency is not None and (
            not math.isfinite(float(self.threshold_relative_efficiency))
            or not 0.0 < float(self.threshold_relative_efficiency) <= 1.0
        ):
            raise ValueError("threshold_relative_efficiency must be in (0, 1]")
        if self.threshold_efficiency is not None and (
            not math.isfinite(float(self.threshold_efficiency))
            or not 0.0 <= float(self.threshold_efficiency) <= 1.0
        ):
            raise ValueError("threshold_efficiency must be in [0, 1]")

        if bool(self.auto_align_focus_only):
            object.__setattr__(self, "auto_align_include_dz", True)
        if int(self.auto_align_max_iterations) < 1:
            raise ValueError("auto_align_max_iterations must be positive")
        if int(self.auto_align_max_function_evaluations) < 1:
            raise ValueError("auto_align_max_function_evaluations must be positive")
        for name in ("auto_align_xtol", "auto_align_ftol"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be positive and finite")
        if not math.isfinite(float(self.auto_align_acceptance_tolerance)) or float(self.auto_align_acceptance_tolerance) < 0.0:
            raise ValueError("auto_align_acceptance_tolerance must be finite and non-negative")
        if self.auto_align_timeout_seconds is not None and (
            not math.isfinite(float(self.auto_align_timeout_seconds))
            or float(self.auto_align_timeout_seconds) <= 0.0
        ):
            raise ValueError("auto_align_timeout_seconds must be positive when provided")

        steps = tuple(float(value) for value in self.sensitivity_steps)
        if not steps or any(not math.isfinite(value) or not 0.0 < value <= 0.5 for value in steps):
            raise ValueError("sensitivity_steps must contain values in (0, 0.5]")
        object.__setattr__(self, "sensitivity_steps", steps)

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, Any] | None,
        coupling: CouplingOptions,
    ) -> "FiberToleranceOptions":
        opts = dict(values or {})

        def axis(name: str) -> tuple[float, ...] | None:
            raw = opts.get(name)
            if raw is None:
                return None
            return tuple(float(value) for value in raw)

        threshold_keys: list[str] = []
        if "threshold_loss_db" in opts and opts.get("threshold_loss_db") is not None:
            threshold_keys.append("threshold_loss_db")
        if "threshold_relative_efficiency" in opts and opts.get("threshold_relative_efficiency") is not None:
            threshold_keys.append("threshold_relative_efficiency")
        if (
            ("threshold_efficiency" in opts and opts.get("threshold_efficiency") is not None)
            or ("threshold" in opts and opts.get("threshold") is not None)
        ):
            threshold_keys.append("threshold_efficiency")
        if len(set(threshold_keys)) > 1:
            raise ValueError(
                "multiple threshold definitions were provided; choose exactly one of "
                "threshold_loss_db, threshold_relative_efficiency, or threshold_efficiency"
            )

        sensitivity_steps = opts.get("sensitivity_steps")
        if sensitivity_steps is None:
            one = float(opts.get("sensitivity_dimensionless_step", 0.05))
            sensitivity_steps = (min(one * 2.0, 0.5), one, one * 0.5)

        require_valid_propagation = bool(opts.get("require_valid_propagation", False))
        lightweight = bool(opts.get("tolerance_lightweight_mode", True))
        coupling_updates: dict[str, Any] = {
            "enforce_numerical_gates": bool(coupling.enforce_numerical_gates) or require_valid_propagation,
        }
        if lightweight:
            coupling_updates.update(
                {
                    "result_array_policy": "none",
                    "include_diagnostic_arrays": False,
                    "sampling_convergence_enabled": False,
                    
                    
                    
                    "auto_expand_output": True,
                    "auto_expand_max_steps": 1,
                    "auto_expand_max_grid_size": min(int(coupling.auto_expand_max_grid_size), 1025),
                }
            )
        resolved_coupling = replace(coupling, **coupling_updates)

        has_absolute = "threshold_efficiency" in opts or "threshold" in opts
        has_relative = "threshold_relative_efficiency" in opts
        has_db = "threshold_loss_db" in opts
        return cls(
            coupling=resolved_coupling,
            sample_count=int(opts.get("sample_count", opts.get("points", 11))),
            scan_mode=str(opts.get("scan_mode", "symmetric")),
            dx_range_um=tuple(float(v) for v in opts.get("dx_um_range", (-10.0, 10.0))),
            dy_range_um=tuple(float(v) for v in opts.get("dy_um_range", (-10.0, 10.0))),
            dz_range_um=tuple(float(v) for v in opts.get("dz_um_range", (-200.0, 200.0))),
            tilt_x_range_urad=tuple(float(v) for v in opts.get("tilt_x_urad_range", (-20000.0, 20000.0))),
            tilt_y_range_urad=tuple(float(v) for v in opts.get("tilt_y_urad_range", (-20000.0, 20000.0))),
            dx_values_um=axis("dx_um_values"),
            dy_values_um=axis("dy_um_values"),
            dz_values_um=axis("dz_um_values"),
            tilt_x_values_urad=axis("tilt_x_urad_values"),
            tilt_y_values_urad=axis("tilt_y_urad_values"),
            include_offset_map=bool(opts.get("include_offset_map", False)),
            include_angular_scans=bool(opts.get("include_angular_scans", True)),
            include_theory_curves=bool(opts.get("include_theory_curves", True)),
            include_sensitivity_matrix=bool(opts.get("include_sensitivity_matrix", False)),
            require_valid_propagation=require_valid_propagation,
            scan_relative_to_base_offset=bool(opts.get("scan_relative_to_base_offset", True)),
            threshold_loss_db=(
                float(opts["threshold_loss_db"])
                if has_db
                else (None if has_relative or has_absolute else 1.0)
            ),
            threshold_relative_efficiency=(
                float(opts["threshold_relative_efficiency"]) if has_relative else None
            ),
            threshold_efficiency=(
                float(opts.get("threshold_efficiency", opts.get("threshold"))) if has_absolute else None
            ),
            baseline_efficiency_minimum=float(opts.get("baseline_efficiency_minimum", 1.0e-8)),
            threshold_solver=str(opts.get("threshold_solver", "brent")),
            threshold_position_xtol=float(opts.get("threshold_position_xtol", opts.get("position_xtol", 1.0e-3))),
            threshold_efficiency_ftol=float(opts.get("threshold_efficiency_ftol", opts.get("efficiency_ftol", 1.0e-6))),
            threshold_max_iterations=int(opts.get("threshold_max_iterations", opts.get("max_iterations", 40))),
            root_validation_fraction=float(opts.get("root_validation_fraction", 0.02)),
            auto_align_baseline=bool(opts.get("auto_align_baseline", False)),
            auto_align_include_dz=bool(opts.get("auto_align_include_dz", False)),
            auto_align_focus_only=bool(opts.get("auto_align_focus_only", False)),
            auto_align_max_iterations=int(opts.get("auto_align_max_iterations", 40)),
            auto_align_max_function_evaluations=int(opts.get("auto_align_max_function_evaluations", opts.get("auto_align_maxfev", 300))),
            auto_align_xtol=float(opts.get("auto_align_xtol", 1.0e-3)),
            auto_align_ftol=float(opts.get("auto_align_ftol", 1.0e-6)),
            auto_align_acceptance_tolerance=float(opts.get("auto_align_acceptance_tolerance", 1.0e-10)),
            auto_align_timeout_seconds=(
                None if opts.get("auto_align_timeout_seconds", 60.0) is None
                else float(opts.get("auto_align_timeout_seconds", 60.0))
            ),
            sensitivity_steps=tuple(float(v) for v in sensitivity_steps),
            sensitivity_allowed_loss_db=(
                None if opts.get("sensitivity_allowed_loss_db") is None else float(opts["sensitivity_allowed_loss_db"])
            ),
            sensitivity_convergence_tolerance=float(opts.get("sensitivity_convergence_tolerance", 0.05)),
            sensitivity_gradient_tolerance=float(opts.get("sensitivity_gradient_tolerance", 0.1)),
            sensitivity_negative_eigenvalue_tolerance=float(opts.get("sensitivity_negative_eigenvalue_tolerance", 0.05)),
            include_arrays=bool(opts.get("include_arrays", True)),
            max_explicit_axis_points=int(opts.get("max_explicit_axis_points", 4097)),
            monte_carlo=MonteCarloOptions(
                enabled=bool(opts.get("monte_carlo_enabled", False)),
                sample_count=int(opts.get("monte_carlo_sample_count", 256)),
                sampling_method=str(opts.get("monte_carlo_sampling_method", "lhs")),
                random_seed=int(opts.get("monte_carlo_random_seed", opts.get("random_seed", 42))),
                threshold_efficiency=(None if opts.get("monte_carlo_threshold_efficiency") is None else float(opts["monte_carlo_threshold_efficiency"])),
                confidence_level=float(opts.get("monte_carlo_confidence_level", 0.95)),
                batch_size=int(opts.get("monte_carlo_batch_size", 64)),
            ),
            receiver_distribution=ReceiverToleranceDistribution(
                dx_sigma_um=float(opts.get("dx_sigma_um", 0.0)),
                dy_sigma_um=float(opts.get("dy_sigma_um", 0.0)),
                dz_sigma_um=float(opts.get("dz_sigma_um", 0.0)),
                tilt_x_sigma_urad=float(opts.get("tilt_x_sigma_urad", 0.0)),
                tilt_y_sigma_urad=float(opts.get("tilt_y_sigma_urad", 0.0)),
                mfd_x_sigma_um=float(opts.get("mfd_x_sigma_um", 0.0)),
                mfd_y_sigma_um=float(opts.get("mfd_y_sigma_um", 0.0)),
                correlation_matrix=(
                    None
                    if opts.get("receiver_correlation_matrix") is None
                    else tuple(tuple(float(v) for v in row) for row in opts["receiver_correlation_matrix"])
                ),
            ),
            algorithm_version=str(opts.get("algorithm_version", "fiber-tolerance-2.1-stable")),
        )


@dataclass(slots=True)
class ToleranceAnalysisResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "metrics": self.metrics,
            "arrays": self.arrays,
            "warnings": self.warnings,
            "metadata": self.metadata,
        }
