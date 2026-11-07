"""Exercise actual branding functions without starting bots or network clients."""
import ast
import io
from pathlib import Path
import types
import unittest
import openpyxl
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.pagesizes import letter

ROOT = Path(__file__).resolve().parent


def load_function(filename, name, namespace):
    tree = ast.parse((ROOT / filename).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, 'exec'), namespace)
    return namespace[name]


class CanvasSpy:
    def __init__(self):
        self.images = []

    def drawImage(self, path, *args, **kwargs):
        self.images.append(path)

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class BrandingTests(unittest.TestCase):
    def test_all_pdf_letterheads_keep_company_and_association_only(self):
        logos = {'metra': 'company.png', 'rgcq': 'association.png'}
        width, height = letter
        env = dict(LOGOS=logos, cm=cm, W=width, H=height, BLACK=colors.black, colors=colors)
        general = load_function('app.py', 'draw_header_footer', env)
        legacy = types.SimpleNamespace(**env)
        dept_env = dict(legacy=legacy, _original_draw_header_footer=general,
                        DEPARTMENTS={'CIV': {'header': 'Civil'}, 'GEO': {'header': 'Geotechnical'}})
        department = load_function('department_ods_patch.py', 'draw_header_footer', dept_env)
        doc = types.SimpleNamespace(page=1, pagesize=letter)
        for code in ('STR', 'CIV', 'GEO'):
            dept_env['_pdf_department'] = code
            canvas = CanvasSpy()
            department(canvas, doc)
            self.assertEqual(canvas.images, ['company.png', 'association.png'])
        loi_env = dict(_ODS=legacy, english=lambda d: d.get('language') == 'en', cm=cm, colors=colors)
        loi = load_function('loi16_runtime.py', 'draw_proposal_branding', loi_env)
        for lang in ('fr', 'en'):
            canvas = CanvasSpy()
            loi(canvas, doc, {'language': lang})
            self.assertEqual(canvas.images, ['company.png', 'association.png'])

    def test_excel_removes_embedded_marks_preserves_cells_and_other_images(self):
        strip = load_function('app.py', 'remove_regulator_logos', {'io': io})
        original = openpyxl.load_workbook(ROOT / 'template.xlsx')
        cells = [[list(row) for row in s.values] for s in original]
        before = sum(len(s._images) for s in original)
        strip(original)
        after = sum(len(s._images) for s in original)
        self.assertEqual(before - after, 4)
        self.assertEqual(after, 4)
        out = io.BytesIO()
        original.save(out)
        out.seek(0)
        checked = openpyxl.load_workbook(out)
        self.assertEqual([[list(row) for row in s.values] for s in checked], cells)
        self.assertEqual(sum(len(s._images) for s in checked), 4)
        strip(checked)
        self.assertEqual(sum(len(s._images) for s in checked), 4)


if __name__ == '__main__':
    unittest.main()
