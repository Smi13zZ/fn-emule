#!/usr/bin/env python3
"""check_structure.py - 面板结构闸门。

抓的是"语法合法、导入正常、一请求就 AttributeError"的那类错误：
某个方法被错误地缩进进了别的函数体，类上就没有这个方法了。
py_compile 只验语法，完全放过这种问题。

用法：
    python tools/check_structure.py src/emule/app/server/emulepanel.py [...]

两项检查：
  1. 模块级函数里嵌套了形如 method(self, ...) 的 def —— 缩进跑偏的典型指纹
  2. 类内 self.xxx 有使用、但类里从未定义，且不属于基类提供的属性 —— 运行必炸
"""
import ast
import sys

# BaseHTTPRequestHandler / socketserver 提供的实例属性与方法，不算缺失
BASE_ATTRS = {
    "path", "headers", "wfile", "rfile", "client_address", "server", "requestline",
    "command", "request_version", "close_connection", "protocol_version",
    "error_message_format", "error_content_type", "responses", "timeout",
    "request", "connection", "raw_requestline", "rbufsize", "wbufsize",
    "disable_nagle_algorithm", "server_version", "sys_version",
    "default_request_version", "log_message", "log_request", "log_error",
    "send_error", "send_response", "send_response_only", "send_header",
    "end_headers", "flush_headers", "handle", "handle_one_request",
    "handle_expect_100", "finish", "setup", "address_string",
    "date_time_string", "version_string", "translate_path", "close",
}

FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def class_level_names(body):
    """类体直接定义的名字：方法名 + 类属性赋值。"""
    names = set()
    for node in body:
        if isinstance(node, FUNC_TYPES):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    names.add(tgt.id)
                    # __slots__ = ("a", "b") 声明的属性也是类属性
                    if tgt.id == "__slots__" and isinstance(node.value, (ast.Tuple, ast.List)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                names.add(elt.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.If, ast.Try)):  # 类体里的条件定义也收进来
            names |= class_level_names(node.body)
            names |= class_level_names(getattr(node, "orelse", []))
    return names


def _walk_self(body):
    """遍历类内所有方法体，返回 (用到的 self.xxx, 被赋值的 self.xxx)。

    不钻进嵌套函数/类（它们是独立作用域，但 self 赋值仍属于本类，照样要收）。
    """
    used, assigned = set(), set()
    stack = [n for n in body if isinstance(n, FUNC_TYPES)]
    while stack:
        node = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                continue
            if (isinstance(child, ast.Assign)
                    and isinstance(child.value, ast.Attribute)
                    and isinstance(child.value.value, ast.Name)
                    and child.value.value.id == "self"):
                assigned.add(child.value.attr)
            for tgt in getattr(child, "targets", []) or []:
                if (isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "self"):
                    assigned.add(tgt.attr)
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Attribute) \
                    and isinstance(child.target.value, ast.Name) and child.target.value.id == "self":
                assigned.add(child.target.attr)
            if isinstance(child, ast.AugAssign) and isinstance(child.target, ast.Attribute) \
                    and isinstance(child.target.value, ast.Name) and child.target.value.id == "self":
                assigned.add(child.target.attr)
            if (isinstance(child, ast.Attribute)
                    and isinstance(child.value, ast.Name)
                    and child.value.id == "self"):
                used.add(child.attr)
            stack.append(child)
    return used, assigned


def check_file(path):
    with open(path, "rb") as handle:
        src = handle.read()
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError as exc:
        return ["语法错误：%s" % exc]

    problems = []

    # 1) 模块级函数里嵌套了 (self, ...) 方法
    for node in tree.body:
        if not isinstance(node, FUNC_TYPES):
            continue
        for child in node.body:
            if not isinstance(child, FUNC_TYPES):
                continue
            args = [a.arg for a in child.args.args]
            if args and args[0] == "self":
                problems.append(
                    "%s() 第 %d 行：嵌套了方法 %s(%s) —— 它本该是类的方法，缩进跑偏了"
                    % (node.name, node.lineno, child.name, ", ".join(args)))

    # 2) 类内 self.xxx 用了但没定义（含本文件内基类提供的属性）
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}

    def inherited_names(cls, seen=None):
        """沿本文件内的继承链收集基类提供的名字。"""
        seen = seen or set()
        if cls.name in seen:
            return set()
        seen.add(cls.name)
        names = set()
        for base in cls.bases:
            base_name = base.id if isinstance(base, ast.Name) else (
                base.attr if isinstance(base, ast.Attribute) else None)
            if not base_name or base_name not in classes:
                continue
            parent = classes[base_name]
            names |= class_level_names(parent.body)
            names |= _walk_self(parent.body)[1]
            names |= inherited_names(parent, seen)
        return names

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        methods = [n for n in node.body if isinstance(n, FUNC_TYPES)]
        if not methods:
            continue
        used, assigned = _walk_self(node.body)
        defined = class_level_names(node.body) | assigned | inherited_names(node)
        missing = sorted(a for a in used
                         if a not in defined and a not in BASE_ATTRS
                         and not a.startswith("__"))
        if missing:
            problems.append("类 %s 缺少这些 self 属性/方法：%s"
                            % (node.name, ", ".join(missing)))

    return problems


def main(argv):
    if len(argv) < 2:
        print("usage: check_structure.py <file.py> [more.py ...]")
        return 2
    bad = 0
    for path in argv[1:]:
        problems = check_file(path)
        if problems:
            bad += 1
            print("FAIL %s" % path)
            for item in problems:
                print("     - %s" % item)
        else:
            print("OK   %s" % path)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
