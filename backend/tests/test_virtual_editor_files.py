import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.tool_executor import ToolExecutor
from services.agent_planner import AgentPlanner


class StubRepositoryManager:
    async def read_file(self, repo_id, file_path):
        raise FileNotFoundError(f"File not found: {file_path}")


class VirtualEditorFilesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.executor = ToolExecutor(
            StubRepositoryManager(), ast_service=None, search_service=None
        )
        self.executor.begin_session(
            "request-1",
            repo_id="local",
            selected_file="./untitled.cpp",
            selected_code="int main() {\n    return 0;\n}\n",
        )

    def tearDown(self):
        self.executor.end_session()

    async def test_read_file_returns_unsaved_editor_buffer(self):
        result = await self.executor.execute_tool(
            "read_file", "local", file_path="untitled.cpp"
        )

        self.assertEqual(result, {
            "status": "success",
            "result": "int main() {\n    return 0;\n}\n",
        })

    async def test_apply_patch_updates_unsaved_editor_buffer_for_later_tools(self):
        first = await self.executor.execute_tool(
            "apply_patch",
            "local",
            file_path="untitled.cpp",
            old_string="return 0;",
            new_string="return 1;",
        )
        second = await self.executor.execute_tool(
            "apply_patch",
            "local",
            file_path="untitled.cpp",
            old_string="return 1;",
            new_string="return 2;",
        )
        current = await self.executor.execute_tool(
            "read_file", "local", file_path="untitled.cpp"
        )

        self.assertEqual(first["status"], "success")
        self.assertTrue(first["result"]["validation"]["ok"])
        self.assertIn("return 1;", first["result"]["proposed"])
        self.assertEqual(second["status"], "success")
        self.assertIn("return 2;", second["result"]["proposed"])
        self.assertEqual(current["result"], "int main() {\n    return 2;\n}\n")

    async def test_missing_non_active_path_still_fails(self):
        result = await self.executor.execute_tool(
            "read_file", "local", file_path="missing.cpp"
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "File not found: missing.cpp")

    def test_recovered_legacy_path_argument_is_normalized(self):
        planner = AgentPlanner.__new__(AgentPlanner)
        recovered = planner._recover_failed_tool_generation(
            '{"name":"read_file","arguments":{"path":"jump_game/frontend.ts"}}'
        )

        self.assertEqual(recovered, (
            "read_file", {"file_path": "jump_game/frontend.ts"}
        ))

    def test_recovered_xml_tool_call_tag(self):
        planner = AgentPlanner.__new__(AgentPlanner)
        recovered = planner._recover_failed_tool_generation(
            '<tool_call>\n{"name": "read_file", "arguments": {"file_path": "src/App.tsx"}}\n</tool_call>'
        )
        self.assertEqual(recovered, (
            "read_file", {"file_path": "src/App.tsx"}
        ))

    def test_tool_choice_none_error_classification(self):
        from services.llm_config import is_tool_use_failed_error, sanitize_messages_for_chat
        self.assertTrue(is_tool_use_failed_error("Error: Tool choice is none, but model called a tool"))
        self.assertTrue(is_tool_use_failed_error("tool_choice is none"))

        # Test message sanitization
        messages = [
            {"role": "system", "content": "You are an assistant. For code changes (edit current file or create a new file): 1. Prefer apply_patch... Keep changes minimal"},
            {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "read_file"}}]},
            {"role": "tool", "content": "file contents"},
            {"role": "user", "content": "how does this work?"},
        ]
        clean = sanitize_messages_for_chat(messages)
        self.assertIn("direct chat mode", clean[0]["content"])
        self.assertNotIn("Prefer apply_patch", clean[0]["content"])
        self.assertEqual(clean[1]["role"], "assistant")
        self.assertEqual(clean[1]["content"], "[Called tool read_file]")
        self.assertEqual(clean[2]["role"], "user")
    def test_truncated_failed_generation_recovery(self):
        planner = AgentPlanner.__new__(AgentPlanner)
        truncated_payload = '{"name": "propose_edit", "arguments": {"file_path":"generate_interview.js","new_content":"// generate_interview.js\nconst fs = require(\'fs\');\nPacker.toBuffer(doc).'
        recovered = planner._recover_failed_tool_generation(truncated_payload)
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered[0], "propose_edit")
        self.assertEqual(recovered[1]["file_path"], "generate_interview.js")
        self.assertIn("Packer.toBuffer", recovered[1]["new_content"])
