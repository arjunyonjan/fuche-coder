import sys
sys.path.insert(0, '.')

from main import is_code_question


def test_is_code_question():
    assert is_code_question("write a python function") == True
    assert is_code_question("what is the capital of France") == False
    assert is_code_question("explain async await") == False
    assert is_code_question("implement a binary search tree") == True
