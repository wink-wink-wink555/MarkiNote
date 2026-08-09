from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVICE_PATH = ROOT / "apps" / "api" / "src" / "markinote_api" / "modules" / "agent" / "service.py"
PORTS_PATH = ROOT / "apps" / "api" / "src" / "markinote_api" / "modules" / "agent" / "ports.py"
PACKAGE_ROOT = ROOT / "apps" / "api" / "src" / "markinote_api"


def _imports(tree: ast.AST) -> set[str]:
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.add(node.module)
    return values


def test_agent_application_service_does_not_import_http_sql_or_concrete_journal_adapters() -> None:
    tree = ast.parse(SERVICE_PATH.read_text(encoding="utf-8"))
    imports = _imports(tree)
    forbidden = {
        "fastapi",
        "starlette",
        "sqlalchemy",
        "markinote_api.application",
        "markinote_api.modules.agent.run_journal",
        "markinote_api.modules.operations.journal",
        "markinote_api.modules.operations.backup",
    }
    assert not {
        module
        for module in imports
        if any(module == prefix or module.startswith(f"{prefix}.") for prefix in forbidden)
    }


def test_agent_dependencies_are_explicit_protocol_ports_and_run_port_rejects_secret_fields() -> None:
    tree = ast.parse(PORTS_PATH.read_text(encoding="utf-8"))
    protocol_names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(isinstance(base, ast.Name) and base.id == "Protocol" for base in node.bases)
    }
    assert {
        "AgentRunJournal",
        "AgentBackupPort",
        "CommandJournalPort",
        "ProviderStreamPort",
        "ToolExecutorPort",
    }.issubset(protocol_names)

    run_port = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AgentRunJournal"
    )
    parameter_names = {
        argument.arg
        for method in run_port.body
        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
        for argument in [*method.args.args, *method.args.kwonlyargs]
    }
    assert parameter_names.isdisjoint({"api_key", "message", "content", "tool_arguments"})


def test_api_package_has_no_retired_framework_or_root_app_imports() -> None:
    forbidden = {"app", "flask", "werkzeug", "a2wsgi"}
    violations: dict[str, list[str]] = {}
    for source in PACKAGE_ROOT.rglob("*.py"):
        imports = _imports(ast.parse(source.read_text(encoding="utf-8")))
        blocked = sorted(
            module
            for module in imports
            if any(module == prefix or module.startswith(f"{prefix}.") for prefix in forbidden)
        )
        if blocked:
            violations[source.relative_to(ROOT).as_posix()] = blocked

    assert violations == {}
