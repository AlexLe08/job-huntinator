from jobscraper.companies import Company
from jobscraper.validate import Probe, slug_variants, validate_one


def test_slug_variants_marks_first_word_unsure():
    v = dict(slug_variants(Company("Help Scout", "greenhouse", "helpscout")))
    assert v["helpscout"] is True and v["help-scout"] is True
    assert v["help"] is False


def test_single_word_first_variant_is_confident():
    assert all(sure for _, sure in slug_variants(Company("Vercel", "greenhouse", "vercel")))


def test_validate_one_corrects_to_other_ats(monkeypatch):
    boards = {("ashby", "acme"): Probe("ashby", "acme", 5)}
    monkeypatch.setattr("jobscraper.validate.probe", lambda client, ats, tok: boards.get((ats, tok)))
    r = validate_one({k: None for k in ("greenhouse","lever","ashby","workable","recruitee")}, Company("Acme", "greenhouse", "acme"))
    assert r.status == "corrected" and r.found.ats == "ashby"


def test_validate_one_loose_guess_is_unsure(monkeypatch):
    boards = {("greenhouse", "help"): Probe("greenhouse", "help", 13, "HELP")}
    monkeypatch.setattr("jobscraper.validate.probe", lambda client, ats, tok: boards.get((ats, tok)))
    r = validate_one({k: None for k in ("greenhouse","lever","ashby","workable","recruitee")}, Company("Help Scout", "greenhouse", "helpscout"))
    assert r.status == "unsure"


def test_validate_one_dead(monkeypatch):
    monkeypatch.setattr("jobscraper.validate.probe", lambda client, ats, tok: None)
    r = validate_one({k: None for k in ("greenhouse","lever","ashby","workable","recruitee")}, Company("Nope", "lever", "nope"))
    assert r.status == "dead"


def test_apply_fixes(tmp_path):
    from jobscraper.validate import Result, apply_fixes
    p = tmp_path / "companies.yaml"
    p.write_text("# header comment\ncompanies:\n"
                 "  - {company: Acme, ats: greenhouse, token: acme, tier: boston}\n"
                 "  - {company: Gone, ats: lever, token: gone, tier: boston}\n"
                 "  - {company: Help Scout, ats: greenhouse, token: helpscout, tier: remote-first}\n")
    acme, gone, hs = (Company("Acme", "greenhouse", "acme", "boston"), Company("Gone", "lever", "gone", "boston"),
                      Company("Help Scout", "greenhouse", "helpscout", "remote-first"))
    n = apply_fixes(p, [Result(acme, "corrected", Probe("ashby", "acme", 3)), Result(gone, "dead"),
                        Result(hs, "unsure", Probe("greenhouse", "help", 13))])
    assert n == 3
    from jobscraper.companies import load_companies
    rows = {c.company: c for c in load_companies(p, include_disabled=True)}
    assert (rows["Acme"].ats, rows["Acme"].token, rows["Acme"].disabled) == ("ashby", "acme", False)
    assert rows["Gone"].disabled and rows["Help Scout"].disabled and "greenhouse/help" in rows["Help Scout"].notes
    assert p.read_text().startswith("# header comment\n")


def test_rate_limited_ats_is_skipped_not_error(monkeypatch):
    from jobscraper.http import FetchError

    def fake(client, ats, tok):
        if ats == "workable":
            raise FetchError("429", 429)
        if (ats, tok) == ("recruitee", "acme"):
            return Probe("recruitee", "acme", 4, "Acme")
        return None

    monkeypatch.setattr("jobscraper.validate.probe", fake)
    r = validate_one({k: None for k in ("greenhouse", "lever", "ashby", "workable", "recruitee")},
                     Company("Acme", "greenhouse", "acme"))
    assert r.status == "corrected" and r.found.ats == "recruitee"


def test_no_autodetect_pins_entry(monkeypatch):
    monkeypatch.setattr("jobscraper.validate.probe", lambda c, ats, tok: Probe(ats, tok, 2) if tok == "remote" else None)
    r = validate_one({k: None for k in ("greenhouse", "lever", "ashby", "workable", "recruitee")},
                     Company("Remote", "greenhouse", "remotecom", extra={"no_autodetect": True}))
    assert r.status == "dead"
