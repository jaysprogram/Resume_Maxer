import pytest

from resume_maxer.numbers import check_numbers, extract_numbers
from resume_maxer.schema import Master

TECH = ["ROS 2", "Claude Sonnet 4.6", "Sonnet 4.6"]
METRICS = [
    "~1,000-person support organization",
    "~20K tokens avoided per run",
    "500+ daily users",
    "3-stage pipeline",
]


def keys(text, tech=()):
    return [n.key for n in extract_numbers(text, tech)]


# --- extract_numbers: what counts as a number -------------------------------


def test_tech_names_from_data_are_not_numbers():
    assert keys("Built ROS 2 navigation on Claude Sonnet 4.6", TECH) == []


def test_without_the_data_names_ros_2_looks_like_a_number():
    # The other polarity: the data half of the rule is what skips "ROS 2".
    assert keys("Built ROS 2 navigation") == ["2"]


@pytest.mark.parametrize("text", ["Mapped YOLOv8 detections", "Tuned Nav2 goals", "Built 3D maps"])
def test_digits_glued_to_letters_are_names(text):
    assert keys(text) == []


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("a ~1,000-person team", "~1000"),
        ("a 1000-person team", "1000"),
        ("approximately 40 testers", "~40"),
        ("About 40 testers", "~40"),
        ("saved $20K", "$20K"),
        ("saved 20k tokens", "20K"),
        ("500+ daily users", "500+"),
        ("cut latency 50%", "50%"),
        ("a three-stage pipeline", "3"),
        ("ran Python 3.12", "3.12"),
        ("ended at 12.", "12"),
    ],
)
def test_number_forms(text, key):
    assert keys(text) == [key]


def test_the_word_one_is_not_counted():
    assert keys("a one-time fix that built one page") == []


def test_unit_word_is_captured():
    [n] = extract_numbers("a ~1,000-person team")
    assert (n.raw, n.unit) == ("~1,000", "person")


# --- check_numbers: what must match -----------------------------------------


@pytest.mark.parametrize(
    "bullet",
    [
        "Shipped to a ~1,000-person support org",
        "Shipped to an approximately 1,000-person support org",
        "Reached 500+ daily users",
        "Built a three-stage pipeline",
        "Owned ROS 2 navigation on Sonnet 4.6",
        "Wrote a one-time migration",
        "Refactored the build",
    ],
)
def test_backed_numbers_pass(bullet):
    result = check_numbers(bullet, METRICS, TECH)
    assert result.ok, result.failures
    assert result.flags == []


@pytest.mark.parametrize(
    ("bullet", "message"),
    [
        # Dropping ~ turns an estimate into an exact claim.
        (
            "Shipped to a 1,000-person support org",
            "'1,000' is not in its metrics (closest: '~1,000')",
        ),
        # Tokens are not dollars: the symbol changed and the marker was dropped.
        ("Saved $20K per run", "'$20K' is not in its metrics (closest: '~20K')"),
        # Dropping + turns a floor into an exact count.
        ("Reached 500 daily users", "'500' is not in its metrics (closest: '500+')"),
        ("Reached 900+ daily users", "'900+' is not in its metrics"),
        # A digit-bearing name missing from the data is treated as a number: safe side.
        ("Ported the service to Python 3.12", "'3.12' is not in its metrics"),
    ],
)
def test_unbacked_numbers_fail_with_a_precise_message(bullet, message):
    result = check_numbers(bullet, METRICS, TECH)
    assert not result.ok
    assert result.failures == [message]


def test_name_from_data_rescues_the_same_bullet():
    assert check_numbers("Ported the service to Python 3.12", METRICS, ["Python 3.12"]).ok


def test_changed_unit_word_is_flagged_not_failed():
    result = check_numbers("Avoided ~20K dollars per run", METRICS, TECH)
    assert result.ok
    assert result.flags == ["'~20K' is followed by 'dollars', which its metrics never use"]


def test_every_failure_is_reported():
    result = check_numbers("Saved $20K for 1,000 people", METRICS, TECH)
    assert len(result.failures) == 2


def test_numbers_need_the_bullets_own_metrics():
    # The ~1,000 metric belongs to another bullet; this one cites none.
    assert not check_numbers("Supported a ~1,000-person org", [], TECH).ok


# --- tech names come from the data ------------------------------------------


def test_master_tech_names_are_the_digit_bearing_names(sample_data):
    # From a stack ("Go 1.22") and a skill alias ("k8s"); digit-free names are left out.
    assert Master.model_validate(sample_data).tech_names() == ["Go 1.22", "k8s"]
