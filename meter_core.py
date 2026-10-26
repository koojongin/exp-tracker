"""Offline EXP parsing and accounting; no screen or game access."""
import re
from collections import deque
from datetime import datetime


def parse_exp(text):
    text = text.replace('％', '%').replace('，', ',')
    pct = re.search(r'(\d{1,3}[.,]\d{1,2}|\d{1,3})\s*%', text)
    if not pct:
        raise ValueError('EXP 숫자와 퍼센트(%)가 함께 보이도록 영역을 지정하세요.')
    percent = float(pct.group(1).replace(',', '.'))
    before = text[:pct.start()].rstrip(' [({|')
    number = re.search(r'(\d[\d,.\s]*\d|\d)\s*$', before)
    if not number or not 0 <= percent <= 100:
        raise ValueError('EXP 숫자를 읽지 못했습니다.')
    return int(re.sub(r'\D', '', number.group(1))), percent


def verify(level, exp, percent, caps):
    cap = caps.get(level)
    if not cap or exp < 0 or exp >= cap:
        raise ValueError('레벨/EXP 범위가 맞지 않습니다. 레벨 영역이나 수동 레벨을 확인하세요.')
    expected = exp / cap * 100
    if abs(expected - percent) > 0.08:
        raise ValueError(f'검증 보류: Lv.{level} / {exp:,} EXP는 {expected:.2f}%여야 합니다 (인식 {percent:.2f}%).')
    return cap


class Session:
    def __init__(self, caps):
        self.caps = caps
        self.reset()

    def reset(self):
        self.started = None
        self.start_level = self.start_exp = None
        self.level = self.exp = self.percent = None
        self.last_time = None
        self.last_wall = None
        self.active = self.gained = self.lost = 0
        self.gained_percent = 0.0
        self.gapped = False
        self.history = deque()
        self.samples = self.levelups = 0

    def gap(self):
        self.gapped = True

    def absolute(self, level, exp):
        if level is None:
            return None
        if any(x not in self.caps for x in range(1, level)):
            return None
        return sum(self.caps[x] for x in range(1, level)) + exp

    def accept(self, level, exp, percent, now, wall=None):
        verify(level, exp, percent, self.caps)
        wall = wall or datetime.now().astimezone().isoformat(timespec='seconds')
        if self.started is None:
            self.gapped = False
            self.started = wall
            self.start_level, self.start_exp = level, exp
            self.level, self.exp, self.percent = level, exp, percent
            self.last_time, self.last_wall = now, wall
            self.history.append((0.0, 0, 0))
            self.samples = 1
            return '측정 시작'
        if self.gapped or now - self.last_time > 20:
            self.level, self.exp, self.percent = level, exp, percent
            self.last_time, self.last_wall = now, wall
            self.gapped = False
            self.history.append((self.active, self.gained, self.lost))
            return '측정 재개 · 중단 구간의 EXP는 제외'
        if level < self.level or level > self.level + 1:
            raise ValueError('캐릭터 변경 또는 레벨 인식 오류 의심: 측정을 초기화하거나 레벨을 확인하세요.')
        if level == self.level:
            delta = exp - self.exp
            percent_gain = max(0, delta) / self.caps[self.level] * 100
        else:
            delta = self.caps[self.level] - self.exp + exp
            percent_gain = (self.caps[self.level]-self.exp)/self.caps[self.level]*100 + exp/self.caps[level]*100
        # A valid percentage alone does not rule out a character change.
        if abs(delta) > max(5000, self.caps[self.level] * 0.65):
            raise ValueError('EXP 변화가 너무 큽니다. 다른 캐릭터라면 초기화하세요. 이 표본은 합산하지 않았습니다.')
        self.active += max(0, now - self.last_time)
        self.gained += max(0, delta)
        self.gained_percent += percent_gain
        self.lost += max(0, -delta)
        changed = level != self.level
        if changed:
            self.levelups += 1
        self.level, self.exp, self.percent = level, exp, percent
        self.last_time, self.last_wall = now, wall
        self.samples += 1
        self.history.append((self.active, self.gained, self.lost))
        while len(self.history) > 2 and self.history[1][0] < self.active - 310:
            self.history.popleft()
        return '레벨업 반영' if changed else f'EXP 감소 {abs(delta):,} 별도 기록' if delta < 0 else '정상 측정 중'

    def recent(self, seconds):
        if not self.history or not self.active:
            return 0, 0
        cutoff = max(0, self.active - seconds)
        # Zero-order hold: EXP changes count at the accepted sample timestamp.
        baseline = self.history[0]
        for row in self.history:
            if row[0] <= cutoff:
                baseline = row
            else:
                break
        amount = self.gained - baseline[1]
        duration = min(seconds, self.active)
        return amount, amount * 60 / duration if duration else 0

    def metrics(self):
        rate = self.gained * 60 / self.active if self.active else 0
        net_rate = (self.gained - self.lost) * 60 / self.active if self.active else 0
        one, one_rate = self.recent(60)
        five, five_rate = self.recent(300)
        eta = ((self.caps[self.level] - self.exp) / (net_rate / 60)) if self.level and net_rate > 0 else None
        return dict(active=self.active, gained=self.gained, gained_percent=self.gained_percent, lost=self.lost, net=self.gained-self.lost,
                    avg_min=rate, avg_hour=rate*60, net_min=net_rate, recent60=one, rate60=one_rate,
                    recent300=five, rate300=five_rate, eta=eta)
