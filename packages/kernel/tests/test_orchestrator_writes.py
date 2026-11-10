import ast
from pathlib import Path

from evidence_kernel.paths import repo_root


def test_product_code_appends_only_through_the_orchestrator() -> None:
    root = repo_root()
    allowed = {
        Path("packages/kernel/src/evidence_kernel/ledger.py"),
        Path("packages/kernel/src/evidence_kernel/orchestrator.py"),
    }
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        relative = path.relative_to(root)
        if "tests" in relative.parts or ".venv" in relative.parts:
            continue
        if relative in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        if "ledger.append" in source or ledger_append_lines(source):
            offenders.append(relative.as_posix())
    assert offenders == []


def test_an_alias_of_the_ledger_is_a_write() -> None:
    source = "def write(ledger):\n    book = ledger\n    book.append({})\n"
    assert ledger_append_lines(source) == [3]


def test_a_list_append_is_not_a_ledger_write() -> None:
    source = "def collect():\n    rows = []\n    rows.append(1)\n"
    assert ledger_append_lines(source) == []


def test_an_annotated_ledger_parameter_is_a_write() -> None:
    source = "def write(book: Ledger):\n    book.append({})\n"
    assert ledger_append_lines(source) == [2]


def test_getattr_append_is_a_write() -> None:
    source = "def write(ledger):\n    getattr(ledger, 'append')({})\n"
    assert ledger_append_lines(source) == [2]


def test_methodcaller_append_is_a_write() -> None:
    source = "def write(ledger):\n    methodcaller('append')(ledger)\n"
    assert ledger_append_lines(source) == [2]


def ledger_append_lines(source: str) -> list[int]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [1]
    module_names = _assigned_ledger_names(tree.body, set())
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        names = set(module_names)
        names.update(_param_ledger_names(node))
        names = _assigned_ledger_names(node.body, names)
        hits.extend(_append_lines(node, names))
    return hits


def _param_ledger_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()
    args = [*fn.args.args, *fn.args.kwonlyargs, *fn.args.posonlyargs]
    for arg in args:
        if arg.arg == "ledger" or _is_ledger(arg.annotation):
            names.add(arg.arg)
    return names


def _assigned_ledger_names(statements: list[ast.stmt], names: set[str]) -> set[str]:
    found = set(names)
    changed = True
    while changed:
        changed = False
        for stmt in _iter_stmts(statements):
            if (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and _is_ledger(stmt.annotation)
            ):
                if stmt.target.id not in found:
                    found.add(stmt.target.id)
                    changed = True
                continue
            target, value = _assignment(stmt)
            if target and target not in found and _expr_is_ledger(value, found):
                found.add(target)
                changed = True
    return found


def _iter_stmts(statements: list[ast.stmt]) -> list[ast.stmt]:
    ordered: list[ast.stmt] = []
    for stmt in statements:
        ordered.append(stmt)
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        for child in ast.iter_child_nodes(stmt):
            if isinstance(child, ast.stmt):
                ordered.extend(_iter_stmts([child]))
    return ordered


def _assignment(stmt: ast.stmt) -> tuple[str | None, ast.expr | None]:
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
        target = stmt.targets[0]
        if isinstance(target, ast.Name):
            return target.id, stmt.value
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        return stmt.target.id, stmt.value
    return None, None


def _expr_is_ledger(expr: ast.expr | None, names: set[str]) -> bool:
    if isinstance(expr, ast.Name):
        return expr.id in names
    if isinstance(expr, ast.Call):
        func = expr.func
        if isinstance(func, ast.Name) and func.id == "Ledger":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "Ledger":
            return True
    return False


def _is_ledger(expr: ast.expr | None) -> bool:
    if isinstance(expr, ast.Name):
        return expr.id == "Ledger"
    if isinstance(expr, ast.Attribute):
        return expr.attr == "Ledger"
    if isinstance(expr, ast.Constant):
        return expr.value == "Ledger"
    return False


def _append_lines(fn: ast.AST, names: set[str]) -> list[int]:
    hits: list[int] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        if _direct_append(node, names) or _getattr_append(node, names):
            hits.append(node.lineno)
        elif _methodcaller_append(node, names):
            hits.append(node.lineno)
    return sorted(set(hits))


def _direct_append(node: ast.Call, names: set[str]) -> bool:
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "append":
        return False
    receiver = node.func.value
    return isinstance(receiver, ast.Name) and receiver.id in names


def _getattr_append(node: ast.Call, names: set[str]) -> bool:
    target = node.func if _is_getattr_append(node, names) else None
    if target is not None:
        return True
    return _is_getattr_append(node.func, names)


def _is_getattr_append(node: ast.AST, names: set[str]) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return False
    if node.func.id != "getattr" or len(node.args) < 2:
        return False
    receiver, attr = node.args[0], node.args[1]
    return (
        isinstance(receiver, ast.Name)
        and receiver.id in names
        and isinstance(attr, ast.Constant)
        and attr.value == "append"
    )


def _methodcaller_append(node: ast.Call, names: set[str]) -> bool:
    made = node.func if isinstance(node.func, ast.Call) else None
    if made is None or not node.args:
        return False
    if not _is_methodcaller_append(made):
        return False
    target = node.args[0]
    return isinstance(target, ast.Name) and target.id in names


def _is_methodcaller_append(node: ast.Call) -> bool:
    func = node.func
    named = isinstance(func, ast.Name) and func.id == "methodcaller"
    attributed = isinstance(func, ast.Attribute) and func.attr == "methodcaller"
    if not named and not attributed:
        return False
    if not node.args or not isinstance(node.args[0], ast.Constant):
        return False
    return node.args[0].value == "append"
