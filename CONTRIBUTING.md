# Contributing to CivilPy

Thank you for your interest in contributing. CivilPy exists to give civil engineers cleaner access
to the Python ecosystem for engineering tasks. Contributions that extend that mission are welcome.

---

## Who Should Contribute

Ideal contributors have expertise in one or more of:

- **Civil or structural engineering** — especially bridge design, AASHTO/AREMA standards, geotechnical analysis, hydraulics, or transportation planning
- **Python development** — if you can read and run Python code (think _Automate the Boring Stuff_ level), you can contribute
- **Domain-specific tooling** — ODOT/FHWA data systems, BRR, AssetWise, Midas, Rhino, or similar platforms

All thoughtful issues, bug reports, and suggestions are welcome regardless of background.

---

## Identity Verification

CivilPy is a demonstration library only and not intend to be used in professional engineering 
contexts. Contributors submitting substantial changes are expected to verify their identity in 
person with the maintainer before those changes are merged. All bug reports are welcome by email
to dane@daneparks.com. Feature requests or expansions will likely be ignored.

---

## Attribution

CivilPy is licensed under the [MIT License](LICENSE). By submitting a contribution, you agree that your
code becomes part of the project under that license. Individual attribution cannot be maintained in
the codebase. Your contribution is acknowledged in the git history, but not in the source files or
documentation. The git history is frequently wiped at the maintainers discretion.

---

## Getting Started

### 1. Set up the project

You will need Python 3.11+ and git installed.

CivilPy lives on a self-hosted GitLab at [daneparks.com](https://daneparks.com/Dane/civilpy) and is
mirrored to [GitHub](https://github.com/drparks71/CivilPy). If you don't have a daneparks.com account,
fork the GitHub repository and work from your fork:

```bash
git clone https://github.com/<your-username>/CivilPy.git
cd CivilPy
pip install -e ".[db,geo,web,jupyter,validation]"
```

### 2. Run the tests to confirm everything works

```bash
pytest
```

All tests should pass before you make any changes. If they do not, open an issue rather than
working around it.

### 3. Make your changes

- Keep changes focused. One fix or feature per pull request.
- Do not refactor code unrelated to your change.
- Add a test for any new function you write. If you are unsure how, look at an existing test in
  the `tests/` directory — the pattern is straightforward.
- If you are adding a new engineering calculation, include a reference (e.g. AASHTO LRFD 8th Ed.
  §6.10.1) in the docstring.

### 4. Verify your changes

```bash
pytest --tb=short
```

If you added a new module, check that the import works cleanly:

```python
python -c "import civilpy"
```

### 5. Submit a pull request

Open a pull request against `master` on [GitHub](https://github.com/drparks71/CivilPy/pulls), or a
merge request on [GitLab](https://daneparks.com/Dane/civilpy) if you have an account there. Give a
clear description of what changed and why, and reference any relevant issue numbers.

GitHub is a read-only mirror, so accepted pull requests are merged on GitLab and arrive on GitHub
through the mirror. Expect the following:

- Tests run on GitLab CI, not GitHub. The maintainer runs them once your branch is pulled in.
- Your commits may be squashed or rebased when merged. When that happens the pull request is closed
  with a link to the commit that landed rather than shown as "merged".
- Keep your branch based on the current `master`. Because history may be rewritten (see
  Attribution), rebase onto a fresh `master` if your branch stops applying cleanly.

Everything below that says "merge request" applies equally to a GitHub pull request.

---

## Review Process

Minor bug fixes and documentation changes may be merged directly by the maintainer. For any
contribution that introduces new engineering calculations, new modules, or changes to existing
calculation logic, a four-role QA/QC process applies. This mirrors standard engineering
deliverable review and exists because errors in this library can propagate into real project work.

### The four roles

**Originator**
The person who wrote the contribution. Responsible for:
- Ensuring the code runs and all tests pass
- Including code references (AASHTO, AREMA, FHWA, etc.) for any calculation
- Disclosing assumptions, limitations, and known edge cases in the docstring
- Disclosing AI assistance in the merge request description if used substantially

**Reviewer**
An independent person — not the originator — who checks the work. Responsible for:
- Verifying that the calculation matches the cited reference
- Identifying missing edge cases, incorrect units, or unclear assumptions
- Reviewing the tests for completeness
- Leaving written comments on the merge request, not verbal feedback

**Revisor**
The originator (or another contributor) who addresses the reviewer's comments. Responsible for:
- Responding to each review comment — either implementing the change or explaining why not
- Not closing comments unilaterally; disputes go to the validator

**Validator**
The maintainer or a designated senior reviewer who gives final approval. Responsible for:
- Confirming that all review comments have been addressed
- Making the final merge decision
- Rejecting contributions where engineering correctness cannot be confirmed

### What this means in practice

For a typical merge request, the originator and revisor will be the same person. The reviewer
should ideally have domain expertise in the relevant engineering area. If you are unsure who
should review your contribution, ask in the merge request and the maintainer will assign someone.

Merge requests that touch engineering calculations will not be merged without at least one
named reviewer comment confirming the calculation against the reference.

The above is all placeholder text for similar projects and there should be no expectation that 
the above efforts were made for any existing code in the repository.

---

## AI Use Policy

AI-assisted development is permitted and encouraged for:

- Writing or improving code efficiency
- Rewriting comments and docstrings for clarity
- Generating boilerplate (tests, configuration, repetitive structures)

AI assistance is **not appropriate** for:

- Substituting engineering judgment. If you use AI to help write a calculation or analysis, a
  qualified engineer must verify the result independently. The engineer whose name is on the
  contribution is professionally liable for its correctness.
- Writing technical opinions or reviews "in your voice." Your submitted words should represent
  your own understanding.

Disclose AI assistance in your merge request description if it was used substantially.

---

## Code Style

- Follow existing patterns in the file you are editing.
- Docstrings should use Google style (see existing functions for examples).
- Engineering references belong in docstrings, not inline comments.
- Do not add type annotations to functions you did not write.

---

## Reporting Issues

Open an issue on [GitHub](https://github.com/drparks71/CivilPy/issues) or the
[GitLab issue tracker](https://daneparks.com/Dane/civilpy/issues). Include:

- What you were trying to do
- What happened instead
- Your Python version and OS
- A minimal code example if applicable

For security issues, see [SECURITY.md](SECURITY.md).
