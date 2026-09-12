"""Protect the accuracy gate from accepting digit/sign or table-column mistakes."""
import pytest

from scripts.benchmark_ocr import score


@pytest.mark.parametrize('actual', ['12.50%', '-1250%', '-12.50', '-12,50%'])
def test_numeric_changes_cannot_pass_accuracy_gate(actual):
    result = score([{'text': actual, 'bbox': [10, 10, 90, 30]}],
                   [{'text': '-12.50%', 'bbox': [0, 0, 100, 40], 'numeric': True}])
    assert not result[0]['exact']


def test_correct_text_in_wrong_column_cannot_pass_accuracy_gate():
    result = score([{'text': '18', 'bbox': [110, 10, 150, 30]}],
                   [{'text': '18', 'bbox': [0, 0, 100, 40], 'numeric': True}])
    assert not result[0]['exact']


def test_only_spacing_and_unicode_width_are_ignored():
    result = score([{'text': '－１２.５０ ％', 'bbox': [10, 10, 90, 30]}],
                   [{'text': '-12.50%', 'bbox': [0, 0, 100, 40], 'numeric': True}])
    assert result[0]['exact']
