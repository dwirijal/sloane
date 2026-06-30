import ast
import os
import re

# Collect all python files
py_files = []
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ('.venv-adk', '__pycache__')]
    for f in files:
        if f.endswith('.py') and f != 'dead_code_finder.py':
            py_files.append(os.path.abspath(os.path.join(root, f)))

class ReferenceCollector(ast.NodeVisitor):
    def __init__(self):
        self.names = set()
        self.imported_modules = set()
        self.attributes = set()
        self.string_literals = set()

    def visit_Name(self, node):
        self.names.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        self.attributes.add(node.attr)
        self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            self.string_literals.add(node.value)
        self.generic_visit(node)

    def visit_Import(self, node):
        for name in node.names:
            self.names.add(name.asname or name.name.split('.')[0])
            self.imported_modules.add(name.name)

    def visit_ImportFrom(self, node):
        if node.module:
            self.imported_modules.add(node.module)
        for name in node.names:
            self.names.add(name.asname or name.name)

# Parse all files and collect references
file_asts = {}
file_collectors = {}

for fp in py_files:
    with open(fp) as f:
        try:
            content = f.read()
            tree = ast.parse(content, fp)
            file_asts[fp] = (tree, content)
            collector = ReferenceCollector()
            collector.visit(tree)
            file_collectors[fp] = collector
        except SyntaxError as e:
            print(f"Syntax error in {fp}: {e}")

# Collect definitions per file
# A definition is:
# - Module level variables (Assign, AnnAssign)
# - Module level functions (FunctionDef, AsyncFunctionDef)
# - Classes (ClassDef)
# - Imports (Import, ImportFrom)
definitions = {} # fp -> list of (name, kind, lineno, node)

for fp, (tree, content) in file_asts.items():
    defs = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip test functions
            if not node.name.startswith('test_'):
                defs.append((node.name, 'function', node.lineno, node))
        elif isinstance(node, ast.ClassDef):
            defs.append((node.name, 'class', node.lineno, node))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split('.')[0]
                defs.append((name, 'import', node.lineno, node))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                name = alias.asname or alias.name
                # Skip from __future__ import annotations
                if node.module == '__future__' and name == 'annotations':
                    continue
                defs.append((name, 'import', node.lineno, node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defs.append((target.id, 'variable', node.lineno, node))
                elif isinstance(target, ast.Tuple):
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            defs.append((elt.id, 'variable', node.lineno, node))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defs.append((node.target.id, 'variable', node.lineno, node))
    definitions[fp] = defs

def is_referenced_in_file(name, fp, def_node):
    # Search references using AST
    # We must exclude references that occur inside the definition itself.
    # To do this safely, we can create a sub-visitor that visits the whole tree,
    # but skips the def_node.
    class LocalRefVisitor(ast.NodeVisitor):
        def __init__(self, skip_node):
            self.skip_node = skip_node
            self.found = False
            self.in_skip = False

        def visit(self, node):
            if node is self.skip_node:
                return
            super().visit(node)

        def visit_Name(self, node):
            if node.id == name:
                self.found = True
            self.generic_visit(node)
            
        def visit_Attribute(self, node):
            if node.attr == name:
                self.found = True
            self.generic_visit(node)

        def visit_Constant(self, node):
            if isinstance(node.value, str):
                # check if name is in string (e.g. for mocking or setattr)
                # dotted pattern: e.g. "sloane.ingest.samehadaku.patch_series"
                if name in node.value:
                    self.found = True
            self.generic_visit(node)

    visitor = LocalRefVisitor(def_node)
    visitor.visit(file_asts[fp][0])
    return visitor.found

# For each definition, check if it's referenced anywhere
results = []
for fp, defs in definitions.items():
    # If the file is a test file or main, skip checking its functions/variables/classes for global deadness
    # (they are entrypoints or test runs)
    # but still check their imports!
    is_entrypoint = fp.endswith('__main__.py') or 'tests/' in fp
    
    for name, kind, line, node in defs:
        # Check in self
        referenced_locally = is_referenced_in_file(name, fp, node)
        
        # Check in other files
        referenced_externally = False
        external_files = []
        for other_fp, collector in file_collectors.items():
            if other_fp == fp:
                continue
            
            # Check if name exists in other file's names, attributes, or string literals
            if name in collector.names or name in collector.attributes:
                referenced_externally = True
                external_files.append(other_fp)
                break
            
            # Check if name is in string literals of other file (e.g. mocking/patching)
            found_in_str = False
            for s in collector.string_literals:
                if name in s:
                    found_in_str = True
                    break
            if found_in_str:
                referenced_externally = True
                external_files.append(other_fp)
                break

        # Special handling for module-level variables/functions/classes in tests/__main__
        if is_entrypoint and kind != 'import':
            # Entry points and test files might have functions/classes that are run by frameworks,
            # so we only care about their unused imports
            continue

        if not referenced_locally and not referenced_externally:
            results.append({
                'file': fp,
                'symbol': name,
                'kind': kind,
                'line': line,
                'why_dead': 'no references found anywhere',
                'confidence': 'high'
            })
            print(f"CONFIDENT DEAD: {fp}:{line} {kind} {name}")
        elif kind == 'import' and not referenced_locally:
            # An import in module A is only useful if referenced in module A,
            # UNLESS module A is imported elsewhere and this symbol is accessed via A.symbol (re-export).
            # Let's check if any other file references this symbol via attribute access on A.
            # E.g. `import module_A; module_A.symbol`
            # For simplicity, we check if `name` is accessed as attribute in other files,
            # or if name is in other file's imports (e.g., `from A import name`).
            referenced_as_export = False
            for other_fp, collector in file_collectors.items():
                if other_fp == fp:
                    continue
                if name in collector.names or name in collector.attributes:
                    referenced_as_export = True
                    break
                for s in collector.string_literals:
                    if name in s:
                        referenced_as_export = True
                        break
            if not referenced_as_export:
                results.append({
                    'file': fp,
                    'symbol': name,
                    'kind': kind,
                    'line': line,
                    'why_dead': 'imported but never used locally or exported',
                    'confidence': 'high'
                })
                print(f"CONFIDENT DEAD IMPORT: {fp}:{line} {name}")

