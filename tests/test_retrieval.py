"""不启动模型的检索回归测试：python -m unittest discover -s tests"""
import sys
import json
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from retrieval import QuestionBank, format_context, head_of_question
from prompt import SYSTEM_PROMPT


class RetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = QuestionBank(ROOT / "data" / "questions.js")

    def test_bank_exact_stem_with_different_options(self):
        matches = self.bank.search("最小权限原则的含义是？\nA. 无条件授权\nB. 只授予完成工作所必需的最小权限")
        self.assertTrue(matches[0].exact)
        self.assertEqual(matches[0].question["stem"], "最小权限原则的含义是（ ）。")
        self.assertEqual(matches[0].question["answer"], ["C"])
        self.assertIn("重新对应用户的选项字母", SYSTEM_PROMPT)

    def test_substring_is_not_exact(self):
        matches = self.bank.search("一张典型的服务器数字证书通常包含哪些内容？\nA. 公钥\nB. 颁发者")
        self.assertFalse(any(m.exact for m in matches))

    def test_related_candidate_is_returned(self):
        matches = self.bank.search("远程桌面协议 RDP 的默认端口号是？\nA. 22\nB. 3389\nC. 5900\nD. 8080")
        self.assertIn("RDP", matches[0].question["stem"])
        context, reliable = format_context(matches, 0.55)
        self.assertTrue(reliable)
        self.assertIn("3389", context)

    def test_unformatted_text_variants(self):
        stem = "最小权限原则的含义是？"
        for suffix in ("", "\nA. 其他\nB. 最小权限", " A.其他 B.最小权限", "A.其他B.最小权限", "Ａ、其他Ｂ、最小权限"):
            with self.subTest(suffix=suffix):
                text = stem + suffix
                self.assertEqual(head_of_question(text), stem)
                self.assertTrue(self.bank.search(text, 1)[0].exact)

    def test_not_split_single_marker_in_question(self):
        text = "请说明 RSA. 和签名之间的关系"
        self.assertEqual(head_of_question(text), text)

    def test_http_plain_text_to_retrieval_without_model(self):
        # 用模拟模型检查前端 JSON 传输中的 question 字符串，不启动真实模型。
        import app
        from http.server import ThreadingHTTPServer
        query = "最小权限原则的含义是？A.无条件授权B.只授予必要权限"
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        app.set_state(ready=True)
        thread.start()
        try:
            with patch.object(app.LLAMA, "chat", return_value="模拟回答") as chat:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/api/ask",
                    data=json.dumps({"question": query}, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=10) as response:
                    data = json.load(response)
                self.assertTrue(data["retrieval_reliable"])
                self.assertEqual(chat.call_args.args[0], query)
                self.assertIn("最小权限原则", chat.call_args.args[1])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
