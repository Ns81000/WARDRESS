import os
import time
from pathlib import Path

# Generic runtime limits (behavioral knobs, not project-specific filters)
BINARY_SNIFF_BYTES = 8192
LARGE_FILE_LINE_LIMIT = 2 * 1024 * 1024  # stop counting lines beyond this

# Repo internals -- never project content
VCS_INTERNAL_DIR = ".git"

# Well-known dependency / cache / build-output directory conventions across tools.
# These are generated artifacts (the "temp folders" of any stack), not project files.
TEMP_DIR_NAMES = {
    # Python
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".tox",
    ".nox", ".eggs", ".venv", "venv", ".ipynb_checkpoints",
    # Node / JS
    "node_modules", "bower_components", ".pnpm-store", ".yarn",
    ".next", ".nuxt", ".output", ".svelte-kit", ".parcel-cache", ".turbo",
    # Build outputs & caches (all stacks)
    "dist", "build", "out", ".cache", "coverage", "htmlcov",
    ".gradle", "target", "DerivedData", ".terraform", ".serverless",
}

# Generic temp / OS-junk detection by naming shape (no project-specific names)
TEMP_NAME_SUFFIXES = (
    ".tmp", ".temp", ".swp", ".swo", ".swn",
    ".part", ".crdownload", ".partial", ".pyc", ".pyo", ".pyd",
)
TEMP_NAME_PREFIXES = ("~$", "~", ".~")
SYSTEM_JUNK_FILES = {
    "thumbs.db", "desktop.ini", ".ds_store", ".localized", "ehthumbs.db",
}

OUTPUT_FILENAME = "project_structure.txt"


def is_temp_entry(name, is_dir):
    """Generic temp/junk detection based on naming shape, valid for any project."""
    lowered = name.lower()
    if lowered.startswith(TEMP_NAME_PREFIXES):
        return True
    if is_dir:
        return (
            lowered == VCS_INTERNAL_DIR
            or lowered in TEMP_DIR_NAMES
            or lowered.endswith(TEMP_NAME_SUFFIXES)
        )
    if lowered in SYSTEM_JUNK_FILES:
        return True
    return lowered.endswith(TEMP_NAME_SUFFIXES)


class Node:
    def __init__(self, name, is_dir=False, rel_path=""):
        self.name = name
        self.is_dir = is_dir
        self.rel_path = rel_path
        self.children = []
        self.size = 0
        self.lines = None
        self.mtime = None

def get_line_count(file_path):
    try:
        size = file_path.stat().st_size
    except OSError:
        return None
    if size > LARGE_FILE_LINE_LIMIT:
        return "Large (Skipped)"  # bail out before opening anything huge
    try:
        # Sniff the head for NUL bytes (binary marker) before counting lines
        with open(file_path, "rb") as f:
            if b"\x00" in f.read(BINARY_SNIFF_BYTES):
                return None
        # Read as UTF-8 with errors ignored to handle various encodings safely
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return None

def format_size(size_in_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.2f} {unit}" if unit != 'B' else f"{int(size_in_bytes)} B"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.2f} TB"

def build_tree(path, rel_path="", visited=None):
    """Walk the tree and capture every file on disk except temp/junk entries.
    Nothing project-specific is hardcoded; .gitignore content is irrelevant."""
    if visited is None:
        visited = set()

    name = path.name
    try:
        is_dir = path.is_dir()
    except OSError:
        return None

    if rel_path and is_temp_entry(name, is_dir):  # never filter the workspace root itself
        return None

    node = Node(name, is_dir=is_dir, rel_path=rel_path)

    if is_dir:
        try:
            real = str(path.resolve())
            if real in visited:
                return None  # symlink/junction loop protection
            visited.add(real)

            contents = []
            for child in path.iterdir():
                child_name = child.name
                try:
                    child_is_dir = child.is_dir()
                except OSError:
                    continue
                if child_is_dir and child.is_symlink():
                    child_is_dir = False  # never descend into linked directories
                if is_temp_entry(child_name, child_is_dir):
                    continue
                if rel_path == "" and child_name.lower() == OUTPUT_FILENAME:
                    continue  # never include the generated report itself
                contents.append((child, f"{rel_path}/{child_name}" if rel_path else child_name))

            contents.sort(key=lambda item: item[0].name.lower())
            for child_path, child_rel in contents:
                child_node = build_tree(child_path, child_rel, visited)
                if child_node:
                    node.children.append(child_node)
            node.size = sum(c.size for c in node.children)
            visited.discard(real)
        except Exception:
            pass
    else:
        try:
            stat = path.stat()
            node.size = stat.st_size
            node.mtime = stat.st_mtime
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
    output_path = workspace_dir / OUTPUT_FILENAME
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

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_content)
        
    print(f"Successfully generated project structure report at: {output_path}")

if __name__ == "__main__":
    main()
