"""Build a deployable source archive; never bundle runtime data or credentials."""
from pathlib import Path
import sys
import zipfile

root = Path(__file__).resolve().parent.parent
target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/workspace/artifacts/mikrofiber-vercel.zip')
target.parent.mkdir(parents=True, exist_ok=True)
files = ['README.md', 'requirements.txt', 'requirements-browser.txt', 'wsgi.py', 'vercel.json',
         'vercel.env.example', '.env.example', '.python-version', '.vercelignore', '.gitignore']
directories = ['mikrofiber', 'api', 'templates', 'static', 'seed', 'docs', 'supabase', 'scripts', 'tests']
extensions = {'.py', '.html', '.css', '.js', '.sql', '.md', '.json', '.txt', '.sh'}
for directory in directories:
    for path in sorted((root / directory).rglob('*')):
        if path.is_file() and path.suffix in extensions and '__pycache__' not in path.parts and not path.name.startswith('.env'):
            files.append(str(path.relative_to(root)))
with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for name in files:
        archive.write(root / name, 'mikrofiber-shop/' + name)
with zipfile.ZipFile(target) as archive:
    names = archive.namelist()
    assert not any(any(part in {'.venv', '.git', 'var', '.vercel', '__pycache__', '.env'} for part in Path(name).parts) for name in names)
    assert 'mikrofiber-shop/api/index.py' in names
    assert 'mikrofiber-shop/mikrofiber/schema_postgres.sql' in names
    assert 'mikrofiber-shop/vercel.json' in names
print(f'{target} ({len(files)} source files, {target.stat().st_size} bytes); runtime data and credentials excluded.')
