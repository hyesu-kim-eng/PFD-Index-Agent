"""Allowlist-only GitHub source archive. Never packages drawings or workbooks."""
import argparse
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parent.parent
FILES={'.gitignore','.env.example','requirements.txt','README.md','run.py','start.cmd','install.cmd','start_venv.cmd'}
TREES={'pfd_index','tools','tests','.github'}
EXTENSIONS={'.py','.md','.yml','.yaml','.ps1','.txt','.cmd'}


def source_files():
    paths=[ROOT/name for name in FILES]
    for tree in TREES:
        paths.extend(f for f in (ROOT/tree).rglob('*') if f.is_file() and '__pycache__' not in f.parts and f.suffix in EXTENSIONS)
    result=sorted(set(paths))
    for path in result:
        if not path.is_file():raise ValueError(f'Missing source file: {path.name}')
        text=path.read_text(encoding='utf-8-sig')
        if re.search(r'sk-[A-Za-z0-9_-]{20,}',text):raise ValueError(f'Possible API key: {path.name}')
        if re.search(r'C:[\\/]Users[\\/]\d+',text):raise ValueError(f'Personal filesystem path: {path.name}')
        if path.suffix.lower() in {'.pdf','.xlsx','.png','.jpg'}:raise ValueError('Private asset in source manifest')
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--check-only',action='store_true');p.add_argument('--output')
    args=p.parse_args();paths=source_files()
    if args.check_only:print(f'Source manifest validated: {len(paths)} files');return
    output=Path(args.output) if args.output else ROOT/'outputs'/'ack-project-instrument-index-agent-source.zip'
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in paths:archive.write(path,Path('ack-project-instrument-index-agent')/path.relative_to(ROOT))
    print(output.resolve());print(f'{len(paths)} source files. No PDF/XLSX/local_data/outputs assets included.')


if __name__=='__main__':main()
