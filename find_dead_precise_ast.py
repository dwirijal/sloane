import ast
import os

files = []
for root, dirs, filenames in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ('.venv-adk', '__pycache__')]
    for f in filenames:
        if f.endswith('.py') and f not in ('dead_code_finder.py', 'find_dead_precise.py', 'find_dead_ast.py', 'find_dead_precise_ast.py'):
            files.append(os.path.join(root, f))

# Mapping from file path to potential module paths
def get_module_paths(fp):
    # e.g. ./store/merger.py -> ['sloane.store.merger', 'store.merger', 'merger']
    clean = fp.replace('./', '').replace('.py', '')
    parts = clean.split('/')
    mods = []
    for i in range(len(parts)):
        mods.append('.'.join(parts[i:]))
    return mods

file_to_mods = {f: get_module_paths(f) for f in files}

# Parse all ASTs
trees = {}
for f in files:
    with open(f) as fh:
        trees[f] = ast.parse(fh.read(), f)

# Find definitions at module-level in each file
# Each definition is: (name, kind, lineno, node)
defs = {}
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

# Helper to find all Name nodes with a specific id, excluding a skip_node
class NameFinder(ast.NodeVisitor):
    def __init__(self, target_id, skip_node=None):
        self.target_id = target_id
        self.skip_node = skip_node
        self.count = 0
        
    def visit(self, node):
        if node is self.skip_node:
            return
        super().visit(node)
        
    def visit_Name(self, node):
        if node.id == self.target_id:
            self.count += 1
        self.generic_visit(node)

# Helper to find all Attribute nodes of type `obj_name.attr_name`
class AttributeFinder(ast.NodeVisitor):
    def __init__(self, obj_name, attr_name):
        self.obj_name = obj_name
        self.attr_name = attr_name
        self.count = 0
        
    def visit_Attribute(self, node):
        if node.attr == self.attr_name and isinstance(node.value, ast.Name) and node.value.id == self.obj_name:
            self.count += 1
        self.generic_visit(node)

# Helper to search for string literals containing a string
class StringLiteralFinder(ast.NodeVisitor):
    def __init__(self, target_str):
        self.target_str = target_str
        self.count = 0
        
    def visit_Constant(self, node):
        if isinstance(node.value, str) and self.target_str in node.value:
            self.count += 1
        self.generic_visit(node)

# Analyze each definition
findings = []

for f, symbols in defs.items():
    is_entry = 'tests/' in f or f.endswith('__main__.py')
    
    for name, kind, line, node in symbols:
        if name.startswith('__') and name.endswith('__'):
            continue
        if name == 'main' and f.endswith('__main__.py'):
            continue
            
        # 1. References in the same file
        nf = NameFinder(name, skip_node=node)
        nf.visit(trees[f])
        self_refs = nf.count
        
        # 2. References in other files
        other_refs = 0
        string_refs = 0
        
        for other_f, other_tree in trees.items():
            if other_f == f:
                continue
                
            # Check string literal references in other_f (e.g. for mocking)
            sf = StringLiteralFinder(name)
            sf.visit(other_tree)
            string_refs += sf.count
            
            # Let's inspect how other_f imports things
            # We look for direct imports of `name` from `f`
            # or imports of `f` as a module and attribute access `f.name`
            
            # We traverse other_tree's top-level imports
            for other_node in other_tree.body:
                # Case A: from module import name [as alias]
                if isinstance(other_node, ast.ImportFrom) and other_node.module:
                    # check if the module imported matches one of f's module paths
                    # e.g. from sloane.store.merger import merge_raw_to_canonical
                    # or from .samehadaku import _detail (relative imports can be partial, so we check suffixes)
                    # To be safe, we check if other_node.module is a suffix or match of f's module paths
                    module_match = False
                    for mod_path in file_to_mods[f]:
                        if other_node.module == mod_path or mod_path.endswith(other_node.module):
                            module_match = True
                            break
                    if module_match:
                        # find if `name` is in names
                        for alias in other_node.names:
                            if alias.name == name:
                                local_name = alias.asname or alias.name
                                # count occurrences of local_name in other_f
                                nf_other = NameFinder(local_name, skip_node=other_node)
                                nf_other.visit(other_tree)
                                other_refs += nf_other.count
                                
                # Case B: import module [as alias]
                elif isinstance(other_node, ast.Import):
                    for alias in other_node.names:
                        # check if the imported module matches f's module paths
                        module_match = False
                        for mod_path in file_to_mods[f]:
                            if alias.name == mod_path:
                                module_match = True
                                break
                        if module_match:
                            local_module_name = alias.asname or alias.name.split('.')[-1]
                            # count occurrences of local_module_name.name in other_f
                            af = AttributeFinder(local_module_name, name)
                            af.visit(other_tree)
                            other_refs += af.count
        
        # Determine if it's dead
        if kind == 'import':
            # An import in file f is dead if it is never used in f,
            # unless it is imported by another file (re-exported)
            # wait, if other_f imports it from f, we would have found other_refs > 0.
            if self_refs == 0 and other_refs == 0 and string_refs == 0:
                findings.append((f, name, kind, line, "imported but never referenced locally or exported"))
        else:
            if is_entry:
                # We do not report functions/classes/variables defined in test files or mains as dead,
                # since they are test cases or execution entrypoints.
                continue
            if self_refs == 0 and other_refs == 0 and string_refs == 0:
                findings.append((f, name, kind, line, "defined but never referenced"))

for f, name, kind, line, why in sorted(findings):
    print(f"{f}:{line} - {name} ({kind}): {why}")

