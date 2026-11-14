from pathlib import Path

import pytest

from rag_app.config.domain_profile import load_domain_profile
from rag_app.core.errors import AppError, ErrorCode

pytestmark = pytest.mark.unit


def test_project_domain_profile_is_valid() -> None:
    profile = load_domain_profile(Path("config/domain_profile.toml"))

    assert profile.platform_name == "ضفيرة"
    assert profile.example_questions


def test_incomplete_profile_raises_config_invalid(tmp_path: Path) -> None:
    file = tmp_path / "p.toml"
    file.write_text('assistant_name = "x"\n', encoding="utf-8")

    with pytest.raises(AppError) as info:
        load_domain_profile(file)

    assert info.value.code is ErrorCode.CONFIG_INVALID
