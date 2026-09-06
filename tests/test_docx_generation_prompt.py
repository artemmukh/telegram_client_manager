"""Contract tests for the medical-record generation system prompt."""

from bot.utils import prompt_builder


def test_prompt_maps_all_crown_aliases_to_the_universal_k_marker():
    prompt = prompt_builder.get_system_prompt()

    assert "«мк», «Мк» или «МК»" in prompt
    assert "«циркон», «фул» и «фулциркон» означают одно и то же" in prompt
    assert "«цлит» означает цельнолитую коронку" in prompt
    assert "Любая коронка, явно указанная для конкретного зуба" in prompt
    assert 'marker "K"' in prompt


def test_prompt_maps_cervical_caries_and_reserves_x_for_tooth_conditions():
    prompt = prompt_builder.get_system_prompt()

    assert "«пришейка» означает пришеечный кариес V класса по Блэку" in prompt
    assert "Не используй \"X\" для коронок" in prompt


def test_prompt_defines_fdi_lists_and_inclusive_dental_arch_ranges():
    prompt = prompt_builder.get_system_prompt()

    assert "Тире обозначает включительный диапазон зубов" in prompt
    assert "«Мк 13-25» означает зубы 13, 14, 15, 16, 17, 18, 21, 22, 23, 24 и 25" in prompt
    assert "Точка разделяет несколько зубов" in prompt
    assert "Запятая разделяет несколько зубов" in prompt
    assert "Перенос строки разделяет несколько зубов" in prompt
