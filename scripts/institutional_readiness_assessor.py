import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class CheckResult:
    key: str
    passed: bool
    weight: float
    evidence: str


def _text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _exists(path: Path) -> bool:
    return path.exists()


def _check_tokens(root: Path, path: str, tokens: List[str], all_required: bool = True) -> CheckResult:
    p = root / path
    content = _text(p)
    if all_required:
        ok = all(tok in content for tok in tokens)
    else:
        ok = any(tok in content for tok in tokens)
    return CheckResult(
        key=f"tokens:{path}",
        passed=ok,
        weight=1.0,
        evidence=f"{path} contains required tokens={ok}",
    )


def _domain_score(checks: List[CheckResult], max_score: float) -> Tuple[float, List[Dict[str, str]]]:
    total_weight = sum(c.weight for c in checks) or 1.0
    passed_weight = sum(c.weight for c in checks if c.passed)
    score = round((passed_weight / total_weight) * max_score, 2)
    findings = [
        {
            "key": c.key,
            "status": "pass" if c.passed else "fail",
            "evidence": c.evidence,
        }
        for c in checks
    ]
    return score, findings


def assess(root: Path) -> Dict[str, object]:
    # Strategy depth checks
    strategy_checks = [
        CheckResult(
            key="strategy:tuning_pipeline",
            passed=_exists(root / "scripts" / "tune_alpha_parameters.py"),
            weight=1.0,
            evidence="scripts/tune_alpha_parameters.py exists",
        ),
        CheckResult(
            key="strategy:walkforward_script",
            passed=_exists(root / "scripts" / "run_walkforward.py"),
            weight=1.0,
            evidence="scripts/run_walkforward.py exists",
        ),
        CheckResult(
            key="strategy:new_fundamental_engines",
            passed=_exists(root / "backend" / "src" / "strategy" / "fundamental"),
            weight=2.0,
            evidence="backend/src/strategy/fundamental exists",
        ),
    ]

    backend_checks = [
        _check_tokens(
            root,
            "backend/src/api/main.py",
            ["@app.websocket", "WS_ALLOW_QUERY_TOKEN"],
            all_required=False,
        ),
        _check_tokens(
            root,
            "backend/src/core/rate_limiter.py",
            ["critical_max_requests"],
        ),
        CheckResult(
            key="backend:durable_kafka_abstraction",
            passed=_exists(root / "backend" / "src" / "platform" / "events" / "kafka_bus.py"),
            weight=2.0,
            evidence="backend/src/platform/events/kafka_bus.py exists",
        ),
    ]

    frontend_checks = [
        _check_tokens(
            root,
            "frontend/src/services/api.ts",
            ["X-CSRF-Token"],
        ),
        _check_tokens(
            root,
            "frontend/src/app/api/[...path]/route.ts",
            ["NEXT_PUBLIC_API_URL", "production"],
            all_required=False,
        ),
        CheckResult(
            key="frontend:institutional_terminal",
            passed=_exists(root / "frontend" / "src" / "app" / "terminal"),
            weight=2.0,
            evidence="frontend/src/app/terminal exists",
        ),
    ]

    security_checks = [
        _check_tokens(
            root,
            "backend/src/api/main.py",
            ["csrf", "CSRF"],
            all_required=False,
        ),
        _check_tokens(
            root,
            "backend/src/auth/auth_service.py",
            ["jti", "revoked"],
            all_required=False,
        ),
        _check_tokens(
            root,
            "tests/test_security_hardening.py",
            ["csrf", "lockout", "critical"],
            all_required=False,
        ),
    ]

    deployment_checks = [
        _check_tokens(
            root,
            "deployment/render.yaml",
            ["backend.src.api.main:app"],
        ),
        CheckResult(
            key="deployment:k8s_manifest",
            passed=_exists(root / "deployment" / "kubernetes"),
            weight=1.0,
            evidence="deployment/kubernetes exists",
        ),
        CheckResult(
            key="deployment:ci_workflow",
            passed=_exists(root / ".github" / "workflows" / "ci.yml"),
            weight=1.0,
            evidence=".github/workflows/ci.yml exists",
        ),
    ]

    validation_checks = [
        CheckResult(
            key="validation:walkforward",
            passed=_exists(root / "scripts" / "run_walkforward.py"),
            weight=1.0,
            evidence="scripts/run_walkforward.py exists",
        ),
        CheckResult(
            key="validation:promotion_readiness",
            passed=_exists(root / "scripts" / "validate_promotion_readiness.py"),
            weight=1.0,
            evidence="scripts/validate_promotion_readiness.py exists",
        ),
        CheckResult(
            key="validation:institutional_safety_suite",
            passed=_exists(root / "tests" / "test_real_money_safety.py"),
            weight=2.0,
            evidence="tests/test_real_money_safety.py exists",
        ),
    ]

    strategy_score, strategy_findings = _domain_score(strategy_checks, 10.0)
    backend_score, backend_findings = _domain_score(backend_checks, 10.0)
    frontend_score, frontend_findings = _domain_score(frontend_checks, 10.0)
    security_score, security_findings = _domain_score(security_checks, 10.0)
    deployment_score, deployment_findings = _domain_score(deployment_checks, 10.0)

    validation_raw, validation_findings = _domain_score(validation_checks, 100.0)

    report = {
        "scores": {
            "strategy": strategy_score,
            "backend": backend_score,
            "frontend": frontend_score,
            "security": security_score,
            "deployment": deployment_score,
            "real_money_readiness_percent": validation_raw,
        },
        "findings": {
            "strategy": strategy_findings,
            "backend": backend_findings,
            "frontend": frontend_findings,
            "security": security_findings,
            "deployment": deployment_findings,
            "validation": validation_findings,
        },
    }

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Assess institutional readiness baseline.")
    parser.add_argument("--repo", default=".", help="Path to repository root")
    parser.add_argument("--output", default="data/institutional_readiness_report.json", help="Output JSON path")
    args = parser.parse_args()

    root = Path(args.repo).resolve()
    report = assess(root)

    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = root / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report["scores"], indent=2))
    print(f"\nReport written: {out_path}")


if __name__ == "__main__":
    main()