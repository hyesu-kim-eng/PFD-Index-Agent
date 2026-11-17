param([string]$RepositoryName = 'ack-project-instrument-index-agent')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Install Git for Windows first.' }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw 'Install GitHub CLI first.' }
gh auth status
if ($LASTEXITCODE -ne 0) { throw 'Run gh auth login first.' }
python tools/package_source.py --check-only
if ($LASTEXITCODE -ne 0) { throw 'Source validation failed.' }
if (Test-Path -LiteralPath '.git') { throw 'A repository already exists. Inspect its remote and staged files before publishing.' }
git init -b main
if ($LASTEXITCODE -ne 0) { throw 'git init failed.' }
git add -- .gitignore .env.example requirements.txt README.md run.py start.cmd install.cmd start_venv.cmd pfd_index tools tests .github
if ($LASTEXITCODE -ne 0) { throw 'git add failed.' }
git diff --cached --name-only
git commit -m 'Add ACK PFD instrument index review and export tool'
if ($LASTEXITCODE -ne 0) { throw 'Commit failed. Configure your Git user identity first.' }
gh repo create $RepositoryName --private --source . --remote origin --push
if ($LASTEXITCODE -ne 0) { throw 'GitHub create/push failed. Inspect gh output.' }
gh repo view --json url --jq .url
