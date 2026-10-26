import json
from pathlib import Path
import unittest
from meter_core import Session,parse_exp,verify

CAPS={int(k):v for k,v in json.loads((Path(__file__).parent/'exp_caps.json').read_text()).items()}

class MeterTests(unittest.TestCase):
    def sample(self,s,level,exp,now):
        return s.accept(level,exp,round(exp/CAPS[level]*100,2),now,'2026-10-26T12:00:00+09:00')

    def test_reference_and_thousands(self):
        for text in ['EXP 43,734 [45.70%]','43.734 45.70%','43734 [45,70％]']:
            self.assertEqual(parse_exp(text),(43734,45.7))
        verify(30,43734,45.7,CAPS)
        with self.assertRaises(ValueError):verify(31,43734,45.7,CAPS)
        with self.assertRaises(ValueError):parse_exp('EXP 43734')

    def test_rates_and_rolling_window(self):
        s=Session(CAPS)
        for i in range(19):self.sample(s,30,1000+i*100,100+i*10)
        m=s.metrics()
        self.assertEqual(m['gained'],1800)
        self.assertEqual(m['active'],180)
        self.assertEqual(m['avg_min'],600)
        self.assertEqual(m['avg_hour'],36000)
        self.assertEqual(m['recent60'],600)
        self.assertEqual(m['recent300'],1800)

    def test_level_up_and_loss(self):
        s=Session(CAPS);self.sample(s,30,95000,100);self.sample(s,31,200,110)
        self.assertEqual(s.gained,900)
        self.assertEqual(s.levelups,1)
        self.sample(s,31,100,120)
        self.assertEqual(s.lost,100)
        self.assertEqual(s.metrics()['net'],800)

    def test_pause_and_long_capture_outage(self):
        s=Session(CAPS);s.gap();self.sample(s,30,1000,0);self.sample(s,30,1100,10)
        self.assertEqual(s.gained,100)
        s.gap();self.sample(s,30,2000,100);self.sample(s,30,2100,110)
        self.assertEqual(s.gained,200)
        self.assertEqual(s.active,20)
        self.sample(s,30,4000,200)
        self.assertEqual(s.gained,200)

    def test_character_switch_and_spike_not_counted(self):
        s=Session(CAPS);self.sample(s,30,1000,0)
        with self.assertRaises(ValueError):self.sample(s,29,1000,2)
        with self.assertRaises(ValueError):self.sample(s,30,90000,2)
        self.assertEqual(s.exp,1000)

    def test_lifetime_absolute(self):
        self.assertEqual(Session(CAPS).absolute(30,43734),592371)

    def test_session_percent_across_levels(self):
        s=Session(CAPS)
        self.sample(s,30,43734,0)
        self.sample(s,30,80000,10)
        self.sample(s,31,10848,20)
        expected=(95700-43734)/95700*100+10
        self.assertAlmostEqual(s.metrics()['gained_percent'],expected)
        # Decreases do not count as negative acquired EXP, matching the acquired-EXP card.
        before=s.gained_percent
        self.sample(s,31,10000,30)
        self.assertEqual(s.gained_percent,before)
        s.gap();self.sample(s,31,20000,100)
        self.assertEqual(s.gained_percent,before)
        s.reset();self.assertEqual(s.gained_percent,0)

if __name__=='__main__':unittest.main()
