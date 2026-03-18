# Releasing healthcarecli

## One-time setup

### PyPI — Trusted Publisher (recommended, no token needed)

1. Create an account at https://pypi.org
2. Go to **Publishing** → **Add a new pending publisher**
3. Fill in:
   - PyPI project name: `healthcarecli`
   - GitHub owner: `eduardofarina`
   - Repository: `healthcarecli`
   - Workflow: `release.yml`
   - Environment: `release` (or leave blank)

### npm

1. Create an account at https://www.npmjs.com
2. Generate an **Automation** token at https://www.npmjs.com/settings/~/tokens
3. Add it as a GitHub secret: **Settings → Secrets → Actions → New secret**
   - Name: `NPM_TOKEN`
   - Value: your npm automation token

---

## Cutting a release

```bash
# 1. Bump version in both files
#    pyproject.toml  →  version = "X.Y.Z"
#    npm/package.json → "version": "X.Y.Z"   (the workflow also syncs this automatically)

# 2. Commit the version bump
git add pyproject.toml npm/package.json
git commit -m "chore: bump version to X.Y.Z"
git push

# 3. Tag and push — this triggers the release workflow
git tag vX.Y.Z
git push origin vX.Y.Z
```

The `release.yml` workflow will:
1. Run tests
2. Build sdist + wheel and publish to **PyPI**
3. Sync the npm version and publish to **npm**
4. Create a **GitHub Release** with auto-generated changelog

---

## Manual publish (fallback)

### PyPI

```bash
pip install build twine
python -m build
twine upload dist/*
```

### npm

```bash
cd npm
npm version X.Y.Z --no-git-tag-version
npm publish --access public
```
