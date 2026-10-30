from odoo.tests import HttpCase, new_test_user, tagged


@tagged("post_install", "-at_install", "rasentra")
class TestDocs(HttpCase):
    def test_docs_need_login_and_block_traversal(self):
        self.assertEqual(self.url_open("/rasentra/docs", allow_redirects=False).status_code, 303)
        new_test_user(self.env, "docs_reader", groups="base.group_user", password="docs_reader")
        self.authenticate("docs_reader", "docs_reader")
        page = self.url_open("/rasentra/docs")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Arsitektur", page.text)
        self.assertEqual(self.url_open("/rasentra/docs/../__manifest__.py").status_code, 404)
        self.assertEqual(self.url_open("/rasentra/docs/%2e%2e/__manifest__.py").status_code, 404)

    def test_menu_visible_for_every_internal_user(self):
        menu = self.env.ref("rasentra_docs.menu_docs_root")
        self.assertEqual(menu.groups_id, self.env.ref("base.group_user"))
