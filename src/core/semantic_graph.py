import ast
import os
import json
import networkx as nx
from typing import Dict, Any

SKIP_DIRS = {'.git', '.revi', '__pycache__', 'node_modules', '.venv', 'venv'}

def build_semantic_graph(directory: str) -> nx.DiGraph:
    """
    Parses the Python codebase to build a semantic dependency graph.
    Nodes: Files, Classes, Functions.
    Edges: DEFINED_IN, CALLS, IMPORTS.
    """
    G = nx.DiGraph()
    
    # Pass 1: Define all files, classes, and functions
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        for file in files:
            if not file.endswith('.py'):
                continue
            
            filepath = os.path.join(root, file)
            rel_path = os.path.relpath(filepath, directory).replace('\\', '/')
            G.add_node(rel_path, type="file", path=rel_path)
            
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                tree = ast.parse(content)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        class_id = f"{rel_path}::{node.name}"
                        G.add_node(class_id, type="class", name=node.name, file=rel_path, line=node.lineno)
                        G.add_edge(class_id, rel_path, relation="DEFINED_IN")
                        
                        # Find methods
                        for child in node.body:
                            if isinstance(child, ast.FunctionDef):
                                func_id = f"{rel_path}::{node.name}.{child.name}"
                                G.add_node(func_id, type="method", name=child.name, class_name=node.name, file=rel_path, line=child.lineno)
                                G.add_edge(func_id, class_id, relation="DEFINED_IN")
                                
                    elif isinstance(node, ast.FunctionDef) and not getattr(node, 'is_method', False):
                        # Detect standalone functions
                        func_id = f"{rel_path}::{node.name}"
                        G.add_node(func_id, type="function", name=node.name, file=rel_path, line=node.lineno)
                        G.add_edge(func_id, rel_path, relation="DEFINED_IN")
            except Exception:
                pass
                
    # Pass 2: Extract function calls and build CALLS edges
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        for file in files:
            if not file.endswith('.py'):
                continue
                
            filepath = os.path.join(root, file)
            rel_path = os.path.relpath(filepath, directory).replace('\\', '/')
            
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                tree = ast.parse(content)
                
                # We need to map calls to specific functions/methods, which is hard with pure AST.
                # We'll do a best-effort approach based on function names.
                # First, gather all function names in the graph
                all_funcs = {}
                for node, data in G.nodes(data=True):
                    if data.get('type') in ['function', 'method']:
                        all_funcs[data.get('name')] = node
                        
                current_scope = rel_path
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        current_scope = f"{rel_path}::{node.name}"
                    elif isinstance(node, ast.FunctionDef):
                        current_scope = f"{rel_path}::{node.name}" # Simplified
                        
                    if isinstance(node, ast.Call):
                        func_name = None
                        if isinstance(node.func, ast.Name):
                            func_name = node.func.id
                        elif isinstance(node.func, ast.Attribute):
                            func_name = node.func.attr
                            
                        if func_name and func_name in all_funcs:
                            target_id = all_funcs[func_name]
                            if current_scope != target_id:
                                G.add_edge(current_scope, target_id, relation="CALLS")
            except Exception:
                pass
                
    return G

def serialize_graph(G: nx.DiGraph) -> Dict[str, Any]:
    return nx.node_link_data(G)

def save_graph(G: nx.DiGraph, directory: str):
    data = serialize_graph(G)
    path = os.path.join(directory, ".revi", "semantic_graph.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)
        
def get_graph_data(directory: str) -> Dict[str, Any]:
    path = os.path.join(directory, ".revi", "semantic_graph.json")
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def query_graph_tool(query_node_name: str, directory: str = "") -> str:
    """
    Tool interface to find what depends on a specific node (function, class, file).
    """
    if not directory:
        directory = os.getenv("FOLDER_PATH", ".")
    path = os.path.join(directory, ".revi", "semantic_graph.json")
    if not os.path.exists(path):
        G = build_semantic_graph(directory)
        save_graph(G, directory)
    else:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        G = nx.node_link_graph(data)
        
    # Find matching nodes
    matches = [n for n, d in G.nodes(data=True) if query_node_name in str(n) or query_node_name == d.get('name')]
    
    if not matches:
        return f"Node '{query_node_name}' not found in the semantic graph."
        
    result = []
    for match in matches:
        data = G.nodes[match]
        result.append(f"Node: {match} ({data.get('type')})")
        
        # What depends on this? (Incoming edges)
        callers = [u for u, v, d in G.in_edges(match, data=True) if d.get('relation') == 'CALLS']
        if callers:
            result.append("  Called by:")
            for c in set(callers):
                result.append(f"    - {c}")
                
        # What does this depend on? (Outgoing edges)
        calls = [v for u, v, d in G.out_edges(match, data=True) if d.get('relation') == 'CALLS']
        if calls:
            result.append("  Calls:")
            for c in set(calls):
                result.append(f"    - {c}")
                
    return "\n".join(result)
