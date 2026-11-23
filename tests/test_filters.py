import copy

import pytest
import yaml

from jobscraper.filters import DEFAULT_PATH, FilterConfig, classify_location, classify_title, evaluate, red_flags
from jobscraper.models import Job

RAW = yaml.safe_load(DEFAULT_PATH.read_text())
CFG = FilterConfig.from_dict(RAW)


def cfg_with(**overrides):
    d = copy.deepcopy(RAW)
    d.update(overrides)
    return FilterConfig.from_dict(d)


@pytest.mark.parametrize(
    "title, tier, flags",
    [
        ("Frontend Engineer", 1, []),
        ("Front-End Developer", 1, []),
        ("Front End Engineer II", 1, []),
        ("Software Engineer, Front End", 1, []),
        ("UI Engineer", 1, []),
        ("Web Engineer", 1, []),
        ("Web Developer", 1, []),
        ("Design Systems Engineer", 1, []),
        ("Design Engineer", 1, []),
        ("Full Stack Engineer", 1, []),
        ("Full-Stack Software Engineer", 1, []),
        ("Fullstack Engineer", 1, []),
        ("Software Engineer", 1, []),
        ("Software Engineer II", 1, []),
        ("Product Engineer", 1, []),
        ("Senior Frontend Engineer", 1, ["senior"]),
        ("Sr. Software Engineer", 1, ["senior"]),
        ("Software Engineer, Frontend Infrastructure", 1, []),
        ("Mobile & Web Engineer", 1, []),
        ("Solutions Engineer", 2, []),
        ("Customer Support Engineer", 2, []),
        ("Implementation Engineer", 2, []),
        ("QA Automation Engineer", 2, []),
        ("Quality Assurance Engineer", 2, []),
        ("SDET", 2, []),
        ("Developer Advocate", 2, []),
        ("DevRel Engineer, Agentic Infrastructure", 2, []),
        ("Forward-Deployed Engineer", 2, []),
    ],
)
def test_title_keep(title, tier, flags):
    v = classify_title(title, CFG)
    assert v.keep, f"{title} dropped: {v.reason}"
    assert v.match_tier == tier
    assert v.flags == flags


@pytest.mark.parametrize(
    "title, reason_prefix",
    [
        ("Staff Frontend Engineer", "title-exclude"),
        ("Principal Software Engineer", "title-exclude"),
        ("Lead Frontend Developer", "title-exclude"),
        ("Tech Lead, Web", "title-exclude"),
        ("Engineering Manager, Dashboard", "title-exclude"),
        ("Director of Engineering", "title-exclude"),
        ("Head of Design Engineering", "title-exclude"),
        ("Software Engineer Intern", "title-exclude"),
        ("Frontend Engineering Internship", "title-exclude"),
        ("Senior / Staff Product Engineer", "title-exclude"),
        ("Embedded Software Engineer", "title-exclude"),
        ("Firmware Engineer", "title-exclude"),
        ("Data Scientist", "title-exclude"),
        ("Software Architect", "title-exclude"),
        ("iOS Engineer", "title-mobile-only"),
        ("Android Software Engineer", "title-mobile-only"),
        ("Senior Mobile Engineer", "title-mobile-only"),
        ("Backend Engineer - Music", "title-no-match"),
        ("Software Engineer, Backend", "title-swe-specialty"),
        ("Software Engineer - Machine Learning", "title-swe-specialty"),
        ("Software Engineer, Infrastructure", "title-swe-specialty"),
        ("Account Executive, Commercial", "title-no-match"),
        ("Product Manager", "title-exclude"),
        ("Product Designer", "title-no-match"),
    ],
)
def test_title_drop(title, reason_prefix):
    v = classify_title(title, CFG)
    assert not v.keep, f"{title} unexpectedly kept"
    assert v.reason.startswith(reason_prefix), v.reason


def test_solutions_architect_is_tier2_not_excluded():
    v = classify_title("Solutions Architect", CFG)
    assert v.keep and v.match_tier == 2


def test_senior_drop_mode():
    cfg = cfg_with(senior_mode="drop")
    assert classify_title("Senior Frontend Engineer", cfg).reason == "title-senior"
    assert classify_title("Frontend Engineer", cfg).keep


def test_bad_senior_mode_rejected():
    with pytest.raises(ValueError):
        cfg_with(senior_mode="maybe")


@pytest.mark.parametrize(
    "location, remote, country, expected",
    [
        ("Boston, MA", None, None, "MA"),
        ("Cambridge, Massachusetts", None, None, "MA"),
        ("Worcester, MA", None, None, "MA"),
        ("Hybrid - Waltham", None, None, "MA"),
        ("Raleigh, NC", None, None, "NC"),
        ("Durham, North Carolina", None, None, "NC"),
        ("Research Triangle Park", None, None, "NC"),
        ("Remote - US", True, None, "us_remote"),
        ("Remote (United States)", None, None, "us_remote"),
        ("US Remote", None, None, "us_remote"),
        ("United States", True, None, "us_remote"),
        ("North America", True, "United States", "us_remote"),
        ("Hybrid - San Francisco, New York City", None, None, "us_onsite"),
        ("Austin, TX", None, None, "us_onsite"),
        ("New York, NY; Toronto", None, "US", "us_onsite"),
        ("London; Boston, MA", None, None, "MA"),
        ("Remote - Germany", True, None, "non_us"),
        ("Remote - Australia", True, None, "non_us"),
        ("Toronto, Canada", None, None, "non_us"),
        ("Hybrid - London, Berlin", None, None, "non_us"),
        ("Cambridge, UK", None, None, "non_us"),
        ("Europe", True, "European Union", "non_us"),
        ("Stockholm", False, "SE", "non_us"),
        ("Remote", True, None, "remote_unspecified"),
        ("Remote", True, "US", "us_remote"),
        ("HQ", None, None, "unknown"),
        ("HQ", None, "United States", "us_onsite"),
    ],
)
def test_location(location, remote, country, expected):
    assert classify_location(location, remote, country) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Requires 8+ years of professional experience.", ["8+yrs"]),
        ("You have 10 years of experience building web apps.", ["8+yrs"]),
        ("Minimum of 12 years software experience", ["8+yrs"]),
        ("3-5 years of experience with React", []),
        ("5-8 years of experience", []),
        ("Founded 10 years ago, we serve millions.", []),
        ("Must hold an active Secret clearance", ["clearance"]),
        ("TS/SCI with polygraph required", ["clearance"]),
        ("Must be a US citizen and able to obtain a security clearance", ["clearance", "citizen+clearance"]),
        ("US citizens and green card holders welcome", []),
    ],
)
def test_red_flags(text, expected):
    assert red_flags(text, CFG) == expected


def _job(**kw):
    base = dict(
        id="x:y:1",
        source="greenhouse",
        company="Acme",
        title="Frontend Engineer",
        location="Boston, MA",
        url="https://example.com/1",
        description="React and TypeScript.",
    )
    base.update(kw)
    return Job(**base)


def test_evaluate_keeps_and_sets_tier():
    j = _job()
    v = evaluate(j, CFG)
    assert v.keep and v.location_class == "MA" and j.match_tier == 1


def test_evaluate_drops_non_us():
    assert evaluate(_job(location="London, UK"), CFG).reason == "location:non_us"


def test_evaluate_flags_ambiguous_location():
    v = evaluate(_job(location="Remote"), CFG)
    assert v.keep and "loc?" in v.flags


def test_evaluate_red_flag_drop_vs_flag():
    j = _job(description="We need 9+ years of experience in JavaScript.")
    assert evaluate(j, CFG).reason == "red-flag:8+yrs"
    d = copy.deepcopy(RAW)
    d["red_flags"]["mode"] = "flag"
    v = evaluate(_job(description="We need 9+ years of experience in JavaScript."), FilterConfig.from_dict(d))
    assert v.keep and "8+yrs" in v.flags


@pytest.mark.parametrize(
    "title",
    [
        "Software Engineer, Vulnerability Management",
        "Software Engineer, Runtimes",
        "Software Engineer, Fraud Detection",
    ],
)
def test_more_swe_specialties_dropped(title):
    assert classify_title(title, CFG).reason == "title-swe-specialty"


@pytest.mark.parametrize(
    "location, expected",
    [
        ("Remote - Asia Only", "non_us"),
        ("Remote - Anywhere in the World", "remote_unspecified"),
        ("Remote - Worldwide", "remote_unspecified"),
        ("Remote - India, United States", "us_remote"),
        ("Remote - USA Only", "us_remote"),
        ("Remote - US Only", "us_remote"),
    ],
)
def test_remote_board_locations(location, expected):
    assert classify_location(location, True, None) == expected


def test_quantum_applications_engineer_not_generic_swe():
    assert not classify_title("Senior Quantum Applications Engineer", CFG).keep


@pytest.mark.parametrize(
    "title, keep",
    [
        ("Test Automation Engineer", True),
        ("QA Automation Engineer", True),
        ("Automation Test Engineer", True),
        ("Senior Process Automation Engineer (Power Apps, Power Automate)", False),
        ("Marketing Automation Engineer", False),
    ],
)
def test_automation_means_test_automation(title, keep):
    assert classify_title(title, CFG).keep is keep
