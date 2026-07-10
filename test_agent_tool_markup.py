import unittest

from agent.loop import _looks_like_serialized_tool_call


class SerializedToolCallDetectionTests(unittest.TestCase):
    def test_detects_tool_call_markup(self) -> None:
        self.assertTrue(
            _looks_like_serialized_tool_call(
                "<tool_call>use_tool<arg_key>tool_name</arg_key>"
                "<arg_value>chat.search</arg_value></tool_call>"
            )
        )

    def test_plain_answer_is_not_tool_markup(self) -> None:
        self.assertFalse(
            _looks_like_serialized_tool_call("I found the value in your previous chat.")
        )


if __name__ == "__main__":
    unittest.main()
