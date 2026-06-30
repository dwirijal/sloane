import ast
import os
import re

# Collect files
files = []
for root, dirs, filenames in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ('.venv-adk', '__pycache__')]
    for f in filenames:
        if f.endswith('.py') and f not in ('dead_code_finder.py', 'find_dead_precise.py'):
            files.append(os.path.join(root, f))

# Read contents
contents = {}
for f in files:
    with open(f) as fh:
        contents[f] = fh.read()

# Build a map of all referenced names per file
ref_names = {f: set() for f in files}
ref_attrs = {f: set() for f in files}
ref_strings = {f: set() for f in files}

# Custom visitor to collect references
class RefVisitor(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename = filename
        
    def visit_Name(self, node):
        ref_names[self.filename].add(node.id)
        self.generic_visit(node)
        
    def visit_Attribute(self, node):
        ref_attrs[self.filename].add(node.attr)
        self.generic_visit(node)
        
    def visit_Constant(self, node):
        if isinstance(node.value, str):
            ref_strings[self.filename].add(node.value)
        self.generic_visit(node)

# Populate reference maps
for f, code in contents.items():
    try:
        tree = ast.parse(code, f)
        RefVisitor(f).visit(tree)
    except Exception as e:
        print(f"Error parsing {f}: {e}")

# Find definitions in each file
defs = {} # file -> list of (name, type, lineno)
for f, code in contents.items():
    defs[f] = []
    try:
        tree = ast.parse(code, f)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith('test_'):
                    defs[f].append((node.name, 'function', node.lineno))
            elif isinstance(node, ast.ClassDef):
                defs[f].append((node.name, 'class', node.lineno))
            elif isinstance(node, ast.Import):
                for name in node.names:
                    # imported name is the asname if present, otherwise the root name (e.g. import foo.bar -> foo)
                    n = name.asname or name.name.split('.')[0]
                    defs[f].append((n, 'import', node.lineno))
            elif isinstance(node, ast.ImportFrom):
                if node.module == '__future__':
                    continue
                for name in node.names:
                    n = name.asname or name.name
                    defs[f].append((n, 'import', node.lineno))
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        defs[f].append((target.id, 'variable', node.lineno))
                    elif isinstance(target, ast.Tuple):
                        for elt in target.elts:
                            if isinstance(elt, ast.Name):
                                defs[f].append((elt.id, 'variable', node.lineno))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                defs[f].append((node.target.id, 'variable', node.lineno))
    except Exception:
        pass

# Check each definition for global usage
dead_symbols = []
for f, symbols in defs.items():
    for name, kind, line in symbols:
        # Rules:
        # 1. Skip __*__
        if name.startswith('__') and name.endswith('__'):
            continue
        # 2. Skip 'main' in entrypoints
        if name == 'main' and f.endswith('__main__.py'):
            continue
        
        # Is it referenced in the same file?
        # A name is referenced in the same file if its count in the AST is > 1.
        # Let's count occurrences of name as ast.Name or ast.Attribute or in string literals.
        # But wait: if it's defined and never used, it only appears once as a definition.
        # Let's do a more precise count.
        # We can compile a regex pattern for the name.
        pat = re.compile(r'\b' + re.escape(name) + r'\b')
        self_count = 0
        lines = contents[f].split('\n')
        for idx, ln in enumerate(lines, 1):
            if idx == line:
                # definition line
                continue
            if pat.search(ln):
                self_count += 1
                
        # Is it referenced in other files?
        other_referenced = False
        other_files = []
        for other_f in files:
            if other_f == f:
                continue
            
            # Check AST names/attributes/strings in other file
            if name in ref_names[other_f] or name in ref_attrs[other_f]:
                other_referenced = True
                other_files.append(other_f)
                break
                
            # Check string literal matches (e.g. for mocking dotted name like "sloane.ingest.samehadaku.patch_series")
            found_in_str = False
            for s in ref_strings[other_f]:
                if name in s:
                    found_in_str = True
                    break
            if found_in_str:
                other_referenced = True
                other_files.append(other_f)
                break
        
        if self_count == 0 and not other_referenced:
            # Check if this is a test file or main file: we only care about their imports
            if ('tests/' in f or f.endswith('__main__.py')) and kind != 'import':
                continue
            dead_symbols.append((f, name, kind, line, "defined but never referenced"))
        elif kind == 'import' and self_count == 0:
            # Imported in file `f`, but not used in file `f` (self_count == 0).
            # Is it used as a re-export? (i.e. another file imports `f` and accesses `f.name` or imports `name` from `f`)
            # E.g. `from .samehadaku import _detail` in `ingest/samehadaku.py`
            # or `import module; module.name`
            # Let's check if the module `f` is imported in other files, and `name` is referenced.
            # A simple approximation: if any other file references `name` in its AST (as Name/Attribute/String),
            # it might be a re-export. But let's be more precise: is the filename `f` imported there?
            # Let's check:
            is_re_exported = False
            # Check if name is imported from this module in other files
            # E.g. from sloane.store.state import get_state
            # Let's check if any other file has an ImportFrom where module ends with f's name and names have `name`
            # or if name is used as an attribute of the imported module.
            # To be safe, if `name` is found in ref_names/ref_attrs/ref_strings of other files, we check if they import f.
            # Let's check:
            for other_f in files:
                if other_f == f:
                    continue
                if name in ref_names[other_f] or name in ref_attrs[other_f]:
                    # Check if other_f imports f
                    # Let's check imports in other_f
                    imports_f = False
                    # convert f's path to relative module name, e.g. sloane.db.writer -> db.writer or writer
                    f_module_parts = f.replace('./', '').replace('.py', '').split('/')
                    f_module_name = '.'.join(f_module_parts)
                    # read other_f AST to see if it imports f_module_name
                    other_code = contents[other_f]
                    if f_module_name in other_code or f_module_parts[-1] in other_code:
                        imports_f = True
                    if imports_f:
                        is_re_exported = True
                        break
            if not is_re_exported:
                dead_symbols.append((f, name, kind, line, "imported but never referenced locally or exported"))

for f, name, kind, line, why in sorted(dead_symbols):
    print(f"{f}:{line} - {name} ({kind}): {why}")

