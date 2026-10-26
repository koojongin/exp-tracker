"""Catalog checks and a Windows GUI smoke test with no screen capture/OCR."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from i18n import EN, translate


class TranslationTests(unittest.TestCase):
    def test_static_and_unknown_errors(self):
        for source, english in EN.items():
            self.assertEqual(translate(source, 'ko'), source)
            self.assertEqual(translate(source, 'en'), english)
            self.assertTrue(english)
        self.assertEqual(translate('WinError 5: Access denied', 'en'), 'WinError 5: Access denied')

    def test_formatted_messages(self):
        self.assertEqual(translate('인식 시험 OK · Lv.30 / EXP 43,734 [45.70%]', 'en'),
                         'OCR test OK · Lv.30 / EXP 43,734 [45.70%]')
        self.assertEqual(translate('EXP 감소 1,234 별도 기록', 'en'),
                         'EXP loss 1,234 recorded separately')
        message='검증 보류: Lv.30 / 43,734 EXP는 45.70%여야 합니다 (인식 12.00%).'
        self.assertIn('should be 45.70% (read 12.00%)', translate(message, 'en'))


@unittest.skipUnless(sys.platform == 'win32', 'Windows desktop GUI required')
class LanguageSwitchTests(unittest.TestCase):
    def test_live_switch_preserves_session_and_persists_choice(self):
        import tkinter as tk
        import maple_exp_meter as app
        with tempfile.TemporaryDirectory() as temp:
            config=Path(temp)/'config.json'
            with patch.object(app,'CONFIG',config), patch.object(app,'load_config',return_value={**app.DEFAULT,'language':'ko'}), patch.object(app.App,'worker',lambda self:None):
                root=tk.Tk()
                meter=app.App(root)
                try:
                    root.update()
                    meter.session.accept(30,43734,45.70,1,'2026-10-27T12:00:00+09:00')
                    meter.session.accept(30,43834,45.80,4,'2026-10-27T12:00:03+09:00')
                    meter.running=True
                    before=(meter.generation,meter.session.metrics(),meter.session.started,meter.session.gapped)
                    meter.set_status('정상 측정 중')
                    meter.language_var.set('English');meter.change_language();root.update()
                    self.assertEqual(meter.status.get(),'Measuring')
                    self.assertEqual(meter.start_button.cget('text'),'❚❚ Pause')
                    self.assertIn('Now Lv.30',meter.detail.get('1.0','end'))
                    self.assertEqual(meter.session_exp.get(),'+100 EXP')
                    self.assertEqual(json.loads(config.read_text(encoding='utf-8'))['language'],'en')
                    self.assertEqual(before,(meter.generation,meter.session.metrics(),meter.session.started,meter.session.gapped))
                    for widget,source in meter.localized_widgets:
                        self.assertEqual(str(widget.cget('text')),translate(source,'en'))
                    meter.apply_display(96,(0,0,1920,1080));root.update()
                    self.assertLessEqual(meter.content.winfo_reqheight(),meter.canvas.winfo_height())
                    meter.open_settings();root.update()
                    self.assertTrue(meter.language_combo.winfo_ismapped())
                    self.assertTrue(meter.windows_combo.winfo_ismapped())
                    meter.settings_window.withdraw()
                    meter.language_var.set('한국어');meter.change_language()
                    self.assertEqual(meter.status.get(),'정상 측정 중')
                    self.assertEqual(meter.start_button.cget('text'),'❚❚ 일시정지')
                    meter.toggle()
                    self.assertIn('측정 재개',meter.start_button.cget('text'))
                    meter.reset()
                    self.assertEqual(meter.session_exp.get(),'+0 EXP')
                finally:
                    meter.shutdown=True
                    root.destroy()


if __name__=='__main__':
    unittest.main()
