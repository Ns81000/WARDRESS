import os
import time
from pathlib import Path

# Config
IGNORE_DIRS = {
    '.git', 'node_modules', '__pycache__', '.pytest_cache', 
    '.claude', '.next', '.venv', 'venv', 'dist', 'build',
    'out', '.docusaurus', '.expo', '.svelte-kit', 'bower_components',
    '.ruff_cache'
}
IGNORE_FILES = {
    '.DS_Store', 'Thumbs.db', 'desktop.ini', 'project_structure.txt'
}
IGNORE_EXTS = {
    '.pyc', '.pyo', '.pyd', '.class', '.o', '.obj', '.dll', '.exe', '.so', '.dylib'
}

class Node:
    def __init__(self, name, is_dir=False, rel_path=""):
        self.name = name
        self.is_dir = is_dir
        self.rel_path = rel_path
        self.children = []
        self.size = 0
        self.lines = None
        self.mtime = None

def is_binary(file_path):
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(1024)
            return b'\x00' in chunk
    except Exception:
        return True

def get_line_count(file_path):
    if is_binary(file_path):
        return None
    
    if os.path.getsize(file_path) > 2 * 1024 * 1024: # 2MB limit
        return "Large (Skipped)"
        
    try:
        # Try reading as UTF-8 with errors ignored to handle various encodings safely
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return sum(1 for _ in f)
    except Exception:
        return None

def format_size(size_in_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.2f} {unit}" if unit != 'B' else f"{int(size_in_bytes)} B"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.2f} TB"

def build_tree(path, rel_path=""):
    name = path.name
    if name in IGNORE_DIRS or name in IGNORE_FILES:
        return None
    if path.suffix in IGNORE_EXTS:
        return None
        
    node = Node(name, is_dir=path.is_dir(), rel_path=rel_path)
    
    if path.is_dir():
        try:
            # List contents, sort them (dirs first, then files, both alphabetically)
            contents = sorted(list(path.iterdir()), key=lambda p: (not p.is_dir(), p.name.lower()))
            for child_path in contents:
                child_node = build_tree(child_path, os.path.join(rel_path, child_path.name) if rel_path else child_path.name)
                if child_node:
                    node.children.append(child_node)
            node.size = sum(c.size for c in node.children)
        except Exception:
            pass
    else:
        try:
            node.size = path.stat().st_size
            node.mtime = path.stat().st_mtime
            node.lines = get_line_count(path)
        except Exception:
            pass
            
    return node

def collect_stats(node, stats):
    if not node.is_dir:
        stats['total_files'] += 1
        stats['total_size'] += node.size
        ext = os.path.splitext(node.name)[1].lower() or 'no extension'
        
        lines = node.lines
        is_txt = (lines is not None and not isinstance(lines, str))
        if is_txt:
            stats['total_lines'] += lines
            
        if ext not in stats['by_ext']:
            stats['by_ext'][ext] = {'files': 0, 'size': 0, 'lines': 0, 'text_files': 0}
        stats['by_ext'][ext]['files'] += 1
        stats['by_ext'][ext]['size'] += node.size
        if is_txt:
            stats['by_ext'][ext]['lines'] += lines
            stats['by_ext'][ext]['text_files'] += 1
    else:
        for child in node.children:
            collect_stats(child, stats)

def render_tree(node, prefix="", is_last=True, is_root=False):
    lines = []
    if is_root:
        lines.append(".")
    else:
        marker = "└── " if is_last else "├── "
        meta_str = ""
        if not node.is_dir:
            line_str = f", {node.lines} lines" if (node.lines is not None and not isinstance(node.lines, str)) else ""
            if isinstance(node.lines, str):
                line_str = f", {node.lines}"
            mtime_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(node.mtime)) if node.mtime else "N/A"
            meta_str = f" [{format_size(node.size)}{line_str}, mod: {mtime_str}]"
        else:
            meta_str = f"/ [{format_size(node.size)}]"
            
        lines.append(f"{prefix}{marker}{node.name}{meta_str}")
        
    if node.is_dir:
        child_prefix = prefix + ("    " if is_last else "│   ") if not is_root else ""
        for i, child in enumerate(node.children):
            is_child_last = (i == len(node.children) - 1)
            lines.extend(render_tree(child, child_prefix, is_child_last))
            
    return lines

def main():
    workspace_dir = Path(__file__).resolve().parent.parent
    print(f"Scanning workspace: {workspace_dir}")
    
    root_node = build_tree(workspace_dir, "")
    if not root_node:
        print("Error: Could not scan workspace directory.")
        return
        
    stats = {
        'total_files': 0,
        'total_size': 0,
        'total_lines': 0,
        'by_ext': {}
    }
    
    collect_stats(root_node, stats)
    
    output = []
    output.append("=" * 80)
    output.append("PROJECT METADATA SUMMARY")
    output.append("=" * 80)
    output.append(f"Total Files:        {stats['total_files']:,}")
    output.append(f"Total Project Size: {format_size(stats['total_size'])}")
    output.append(f"Total Code Lines:   {stats['total_lines']:,} (excluding binary/large files)")
    avg_size = stats['total_size'] / stats['total_files'] if stats['total_files'] > 0 else 0
    output.append(f"Average File Size:  {format_size(avg_size)}")
    output.append("")
    
    output.append("Extension Breakdown:")
    output.append("-" * 90)
    output.append(f"{'Extension':<15} | {'File Count':<12} | {'Total Size':<15} | {'Total Lines':<15} | {'Text Files':<12}")
    output.append("-" * 90)
    
    sorted_exts = sorted(stats['by_ext'].items(), key=lambda x: x[1]['size'], reverse=True)
    for ext, ext_stats in sorted_exts:
        output.append(
            f"{ext:<15} | {ext_stats['files']:<12,} | {format_size(ext_stats['size']):<15} | {ext_stats['lines']:<15,} | {ext_stats['text_files']:<12,}"
        )
    output.append("-" * 90)
    output.append("")
    
    output.append("=" * 80)
    output.append("PROJECT FILE TREE & METADATA")
    output.append("=" * 80)
    output.extend(render_tree(root_node, is_root=True))
    output.append("")
    
    report_content = "\n".join(output)
    
    output_path = workspace_dir / "project_structure.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_content)
        
    print(f"Successfully generated project structure report at: {output_path}")

if __name__ == "__main__":
    main()
