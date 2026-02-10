import argparse
import ast
import os


def count_functions_in_file(file_path, min_lines):
    """Counts the number of functions in a given Python file that have at least `min_lines` lines."""
    with open(file_path, 'r') as f:
        tree = ast.parse(f.read())
    function_count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start_line = node.lineno
            end_line = node.end_lineno
            if (end_line - start_line + 1) >= min_lines:
                function_count += 1
    return function_count

def scan_directory(directory, min_lines):
    """Recursively scans a directory for .py files and counts the number of functions in each, filtering by minimum lines."""
    results = {}
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                full_path = os.path.join(root, file)
                func_count = count_functions_in_file(full_path, min_lines)
                if func_count > 0:
                    results[full_path] = func_count
    return results

def main():
    parser = argparse.ArgumentParser(description='Scan Python files for the number of functions.')
    parser.add_argument('directory', help='The directory to scan for .py files.')
    parser.add_argument('--min-lines', type=int, default=0, help='The minimum number of lines a function must have to be counted.')
    args = parser.parse_args()

    # Scan the directory and print the results sorted by the number of functions in descending order
    function_counts = scan_directory(args.directory, args.min_lines)
    for file, count in sorted(function_counts.items(), key=lambda item: item[1], reverse=True):
        print(f'{file}: {count} functions')

if __name__ == '__main__':
    main()
