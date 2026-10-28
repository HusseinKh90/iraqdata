# Publishing iraqdata

This page is for the person who publishes the repository and its data releases. Routine updates
(weekly check, applying an update, rolling back) are in section 5 of
[collecting_data_doc.md](collecting_data_doc.md).

## First publication

Everything below is done by the maintainer; none of it can be done from inside the repository.

### 1. Check the details that are shown to others

| What | Where | Check |
|---|---|---|
| Contact e-mail sent to the sites the pipeline downloads from | `CONTACT_EMAIL` in `pipeline/downloads.py` (set to `hk.hussein1990@gmail.com`) | It is an address you read. The sites use it to reach you if the pipeline misbehaves. |
| Repository the client downloads from | `DEFAULT_REPO` in `src/iraqdata/storage.py` | It is `<your GitHub account>/<repository name>`, exactly as the repository will be called. |
| Author and release date | `CITATION.cff` (`authors`, `date-released`), `pyproject.toml` (`authors`) | Names and date are right. |
| Reviewer on acknowledgements | `pipeline/metadata/acknowledged_warnings.yaml` | The `reviewer` is the person who reviewed each notice. |

If the repository will not be called `husseinkh90/iraqdata`, change `DEFAULT_REPO` and the links
that name it: `README.md`, `CITATION.cff`, `pyproject.toml` (`[project.urls]`) and `PROJECT_URL` in
`pipeline/downloads.py`. `tests/test_repository_slug.py` fails and names the one you missed. Then
re-export the release (remove `release/data-2026-10`, then run
`python pipeline/export_release.py --tag data-2026-10`), because its `datapackage.json` records the
repository.

### 2. Get the files without their history, and create the repository

**Get the files.** On GitHub, open the repository the work was done in, choose the branch
`claude/gifted-knuth-si3yk2` in the branch menu, then the green **Code** button, then **Download
ZIP** (or open
`https://github.com/HusseinKh90/python-package/archive/refs/heads/claude/gifted-knuth-si3yk2.zip`
while signed in). A ZIP holds the files only, not the commits, which is what makes the new
repository start clean. Unzip it and rename the folder to `iraqdata`.

**Create the repository** on GitHub (**+**, **New repository**) under the account and with the name
in `DEFAULT_REPO`. Leave "Add a README", ".gitignore" and "licence" off; the project has its own.
It may start private and be made public later (Settings, General, Danger Zone); the client can
download releases without signing in only when the repository is public.

**Upload the folder with git or GitHub Desktop, not with the website.** The website takes at most
100 files at a time and the project has about 280. `.gitattributes` keeps data files byte-exact, so
a clone matches `checksums.sha256` on every platform.

- With GitHub Desktop (desktop.github.com; sign in): **File**, **Add local repository**, choose the
  `iraqdata` folder, and when it says the folder is not a repository choose **create a repository
  here** (leave licence and `.gitignore` on "None"). Write the summary `iraqdata 1.0.0`, **Commit to
  main**, then **Publish repository** with the name `iraqdata` (untick "Keep this code private" to
  publish it publicly).
- With git, from inside the folder:

  ```bash
  git init -b main
  git add -A
  git commit -m "iraqdata 1.0.0"
  git remote add origin https://github.com/<account>/iraqdata.git
  git push -u origin main
  ```

### 3. Switch on what the repository needs

1. **Actions** must be enabled (Settings, Actions, General). The CI workflow runs the tests on
   Python 3.10 to 3.13 and the integrity check on Linux, macOS and Windows.
2. **Issues** must be enabled: the weekly update check opens one issue per open problem.
3. **Secrets** (Settings, Secrets and variables, Actions):
   - `HC_PING_URL`: the ping URL of a healthchecks.io check with period 7 days and grace 1 day.
     Without it the weekly run fails on purpose, so that a silent monitor cannot go unnoticed.
   - `HC_ALERT_URL` (optional): a second check, connected to whatever you read fastest.

   The steps, with what reaches you and when, are under "Update-check monitoring" in
   [collecting_data_doc.md](collecting_data_doc.md).
4. Keep e-mail on for @-mentions (GitHub, Settings, Notifications, Participating). The handle that
   is mentioned is `notify.github` in `pipeline/metadata/update_schedule.yaml`.

### 4. Create the data release

The client reads data from the repository's GitHub releases, one release per `data-YYYY-MM` tag, so
the data does not exist for users until this release does. `release/data-2026-10/` holds its
files; `release-assets.txt` there lists the 22 files to upload (every file in the folder except
`release-assets.txt` itself), under these exact names.

On the website: open the repository, **Releases** (right-hand column), **Draft a new release**.

1. **Choose a tag**: type `data-2026-10` exactly and choose **Create new tag: data-2026-10 on
   publish** (target: `main`).
2. **Release title**: `data-2026-10`.
3. **Description**: `First data release (code 1.0.0). See CHANGELOG.md.`
4. Drag the 22 files from the `release/data-2026-10` folder onto the box "Attach binaries by
   dropping them here", and wait until all 22 are listed. `checksums.sha256` and
   `datapackage.json` must be among them: the client downloads the checksums first and refuses any
   file that does not match.
5. Tick **Set as the latest release** and press **Publish release**.

With the GitHub command line the same is one command, run from the repository folder:

```bash
gh release create data-2026-10 --title "data-2026-10" --latest \
  --notes "First data release (code 1.0.0). See CHANGELOG.md." \
  $(cut -f1 release/data-2026-10/release-assets.txt | sed 's#^#release/data-2026-10/#')
```

A release that was published is never edited; a correction is a new release under a new tag.

### 5. Check it from outside

In a fresh virtual environment, with no copy of the repository on the path:

```bash
pip install git+https://github.com/<account>/<repository>
python -c "import iraqdata as id; print(id.get_data_source()); print(id.get_series('m2').tail())"
```

The first line should name release `data-2026-10` from your repository, and the table should print.

### 6. Optional: PyPI and a DOI

The README says `pip install iraqdata`, which works only once the package is on PyPI (pypi.org).
The package holds the Python code only; the data is downloaded from the repository's releases on
first use, so step 4 must be done first. The workflow `.github/workflows/publish.yml` builds the
package on GitHub and uploads it with PyPI's "trusted publishing", so you need neither Python on your
own computer nor a stored password or token.

**Once, on PyPI** (pypi.org, signed in; PyPI first asks you to switch on two-factor login with an
authenticator app, and to verify your e-mail address):

1. Open your account menu, **Your projects**, then **Publishing** (or go to
   `https://pypi.org/manage/account/publishing/`).
2. Under "Add a new pending publisher", choose **GitHub** and fill in:
   - PyPI project name: `iraqdata`
   - Owner: `HusseinKh90`
   - Repository name: `iraqdata`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
3. Click **Add**. The project does not exist yet; PyPI creates it on the first upload.

**To publish** (needs the files of this repository, including `publish.yml`, on `main`):

1. On GitHub, open the repository, **Actions**, **Publish to PyPI** (left list), **Run workflow**,
   branch `main`, **Run workflow**.
2. Wait for both jobs ("build" and "publish") to turn green.
3. Check `https://pypi.org/project/iraqdata/`, then in a fresh environment `pip install iraqdata`.

PyPI never accepts the same version twice. For a correction, raise the version in `pyproject.toml`,
`src/iraqdata/__init__.py` and `CITATION.cff`, add a `CHANGELOG.md` entry, push, and run the
workflow again.

A DOI comes from archiving a GitHub release on Zenodo (link the repository at zenodo.org, then
publish a release). The README promises one; add it to `CITATION.cff` and the README when it
exists.

### 7. Confirm the terms of reuse

The data of five publishers is republished on the basis of an open or implied permission that has
not been checked with the publisher (status `unconfirmed` in `pipeline/metadata/sources.yaml`, six
source records, listed in [source_inventory.md](source_inventory.md#terms-of-reuse-by-source)): the
BIS, COSIT, the U.S. EIA (for the bulk file and, via FRED, for Brent), JODI and OPEC. The Central
Bank of Iraq states no licence at all. Write to each publisher, ask in writing whether republishing
the values with attribution is acceptable, and record the answer (`status:
confirmed_by_maintainer`, the wording in `terms`, the date in `checked`). Until then the README and
`source_inventory.md` say that these terms are unconfirmed.

## Later releases

1. The weekly update check reports; it never changes the data. When it opens an issue about new
   data, follow section 5 of [collecting_data_doc.md](collecting_data_doc.md): archive the
   files, run `python pipeline/run_parsers.py`, run the gate (`python pipeline/validate.py
   --release`), acknowledge or fix each notice, and export under a new tag.
2. `python pipeline/export_release.py --tag data-YYYY-MM` runs the gate and the catalog check
   first and refuses to write into a folder that holds files.
3. Create the GitHub release as in step 4 above. When the new release revises or withdraws a
   published value it also carries a `history/` folder, which is what makes `as_of` work. History
   files are uploaded flat, as `history.<table>.parquet`; `release-assets.txt` gives the names.
4. Raise the version in `pyproject.toml`, `src/iraqdata/__init__.py` and `CITATION.cff` together
   when the Python code changes, and add an entry to `CHANGELOG.md`.
