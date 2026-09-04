# Dynamic GUI Acceptance

- PASS homepage is reduced to platform overview; redundant goal/current-work blocks are absent
- PASS simulation panel collapse/restore, overview/detail, and wavefront routing
- PASS ML has no overview landing page; model construction stages and forward prediction remain direct

## FAILURES
- FAIL shell: top command bar should be system/run/analysis only: ['simulation', 'optimization', 'surrogate', 'explainability', 'teaching']
- FAIL optimization: optimization result too small PySide6.QtCore.QSize(278, 360)
- FAIL teaching: teaching mismatch nav count 0 != 5
- FAIL responsive: top command bar should be system/run/analysis only: ['simulation', 'optimization', 'surrogate', 'explainability', 'teaching']
