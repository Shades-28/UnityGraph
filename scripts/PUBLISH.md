# Publishing a new version to PyPI

When you're ready to ship a new version (v2.1.4, v2.2.0, etc.):

## 1. Bump the version

Edit two files to the new version number:

- `src/unitygraph/__init__.py` -- the `__version__` line
- `pyproject.toml` -- the `version =` line

Update `CHANGELOG.md` with a new entry at the top describing what changed.

## 2. Tag and push to GitHub first

```bash
git add -A
git commit -m "v2.1.4: <one-line summary>"
git tag v2.1.4
git push origin main --tags
```

## 3. Generate a fresh PyPI token

1. Go to https://pypi.org/manage/account/token/
2. Click "Add API token"
3. **Token name**: `unitygraph-publish-vX.Y.Z` (helpful for tracking)
4. **Scope**: `Project: unitygraph` (NOT "entire account" -- safer)
5. Click "Add token", copy the value (`pypi-AgEIc...`). Shown only once.

## 4. Build and upload

```bash
rm -rf dist
python -m build
python -m twine check dist/*
TWINE_USERNAME=__token__ TWINE_PASSWORD='<paste-token-here>' python -m twine upload dist/*
```

## 5. Verify the upload

```bash
pipx install --force unitygraph
unitygraph --version  # should print the new version
```

## 6. Delete the token

Go back to https://pypi.org/manage/account/token/ and remove the token
you just used. Tokens left lying around are leaked tokens waiting to
happen. Make a fresh project-scoped one for the next release.
