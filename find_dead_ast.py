import ast
import os

files = []
for root, dirs, filenames in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ('.venv-adk', '__pycache__')]
    for f in filenames:
        if f.endswith('.py') and f not in ('dead_code_finder.py', 'find_dead_precise.py', 'find_dead_ast.py'):
            files.append(os.path.join(root, f))

# We need to map file path to module name(s)
# e.g. ./store/merger.py -> sloane.store.merger (or store.merger)
def get_module_names(fp):
    clean = fp.replace('./', '').replace('.py', '')
    parts = clean.split('/')
    mods = []
    # Could be imported as:
    # sloane.store.merger
    # store.merger
    # merger (if in same dir)
    for i in range(len(parts)):
        mods.append('.'.join(parts[i:]))
    return mods

file_modules = {f: get_module_names(f) for f in files}

# Parse ASTs
trees = {}
for f in files:
    with open(f) as fh:
        try:
            trees[f] = ast.parse(fh.read(), f)
        except Exception as e:
            print(f"Error parsing {f}: {e}")

# Find definitions at module-level
# Each definition is: (name, kind, lineno, node)
defs = {} # file -> list
for f, tree in trees.items():
    defs[f] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith('test_'):
                defs[f].append((node.name, 'function', node.lineno, node))
        elif isinstance(node, ast.ClassDef):
            defs[f].append((node.name, 'class', node.lineno, node))
        elif isinstance(node, ast.Import):
            for name in node.names:
                n = name.asname or name.name.split('.')[0]
                defs[f].append((n, 'import', node.lineno, node))
        elif isinstance(node, ast.ImportFrom):
            if node.module == '__future__':
                continue
            for name in node.names:
                n = name.asname or name.name
                defs[f].append((n, 'import', node.lineno, node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defs[f].append((target.id, 'variable', node.lineno, node))
                elif isinstance(target, ast.Tuple):
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            defs[f].append((elt.id, 'variable', node.lineno, node))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defs[f].append((node.target.id, 'variable', node.lineno, node))

# Helper to find all AST references to a name in a given tree
# excluding a specific definition node
class ASTRefFinder(ast.NodeVisitor):
    def __init__(self, target_name, skip_node=None):
        self.target_name = target_name
        self.skip_node = skip_node
        self.ref_count = 0
        self.string_refs = 0
        
    def visit(self, node):
        if node is self.skip_node:
            return
        super().visit(node)
        
    def visit_Name(self, node):
        if node.id == self.target_name:
            self.ref_count += 1
        self.generic_visit(node)
        
    def visit_Attribute(self, node):
        # Attribute could be module.name or object.name, but name is in attr.
        # However, to be referenced in other files, it would be module_name.name.
        # In the same file, it's just referenced as name.
        if node.attr == self.target_name:
            # Check if value is a Name (like module name)
            if isinstance(node.value, ast.Name):
                self.ref_count += 1
        self.generic_visit(node)

    def visit_Constant(self, node):
        # check string literals for mocking/setattr
        if isinstance(node.value, str):
            if self.target_name in node.value:
                self.string_refs += 1
        self.generic_visit(node)
        
    def visit_ImportFrom(self, node):
        # from module import name
        for alias in node.names:
            if (alias.asname or alias.name) == self.target_name:
                self.ref_count += 1
        self.generic_visit(node)

# For each defined symbol, let's find all references
for f, symbols in defs.items():
    # If it is a test file, or __main__.py, skip checking non-import definitions for deadness
    is_entry = 'tests/' in f or f.endswith('__main__.py')
    
    for name, kind, line, node in symbols:
        if name.startswith('__') and name.endswith('__'):
            continue
        if name == 'main' and f.endswith('__main__.py'):
            continue
            
        # Count references in self
        finder_self = ASTRefFinder(name, skip_node=node)
        finder_self.visit(trees[f])
        self_refs = finder_self.ref_count
        self_strings = finder_self.string_refs
        
        # Count references in other files
        other_refs = 0
        other_strings = 0
        other_files = []
        for other_f, tree in trees.items():
            if other_f == f:
                continue
            finder_other = ASTRefFinder(name)
            finder_other.visit(tree)
            if finder_other.ref_count > 0:
                other_refs += finder_other.ref_count
                other_files.append(other_f)
            if finder_other.string_refs > 0:
                other_strings += finder_other.string_refs
                
        total_refs = self_refs + other_refs
        total_strings = self_strings + other_strings
        
        if is_entry and kind != 'import':
            # Skip checking test functions or main runner entry points
            continue
            
        if kind == 'import':
            # An import is dead if it is never referenced locally in the same file
            # UNLESS it is exported/imported by another file (e.g. from x import y)
            # or accessed as an attribute of the module.
            # To check if it's imported by another file, we look for other_refs > 0.
            # But wait: if other_f imports `name` from `f`, `finder_other.ref_count` will count the ImportFrom alias.
            # Let's verify if there are any references at all:
            if self_refs == 0 and other_refs == 0 and total_strings == 0:
                print(f"DEAD IMPORT: {f}:{line} - '{name}' (imported in {f} but never referenced)")
        else:
            if total_refs == 0 and total_strings == 0:
                print(f"DEAD {kind.upper()}: {f}:{line} - '{name}' (defined in {f} but never referenced)")
