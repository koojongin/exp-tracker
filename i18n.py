"""Small, dependency-free Korean/English UI catalog."""
import re


EN = {
    '세션 경과': 'Session time',
    '게임 창': 'Game window',
    '새로고침': 'Refresh',
    'EXP 영역 지정': 'Select EXP area',
    '레벨 영역 지정': 'Select level area',
    '기본 위치 복원': 'Restore default areas',
    '인식 시험': 'Test OCR',
    '레벨 자동': 'Auto level',
    '수동 레벨': 'Manual level',
    '인식 간격(초)': 'Interval (sec)',
    '항상 위': 'Always on top',
    '게임에 포커스가 있을 때만 측정': 'Measure only while the game is focused',
    '▶ 측정 시작': '▶ Start',
    '▶ 측정 재개': '▶ Resume',
    '❚❚ 일시정지': '❚❚ Pause',
    '측정 초기화': 'Reset',
    '상세설정': 'Settings',
    'CSV 내보내기': 'Export CSV',
    '기록 폴더': 'Open log folder',
    'OCR 엔진을 준비하고 있습니다…': 'Loading OCR engine…',
    'EXP 인식 영역 미리보기': 'EXP capture preview',
    '세션 획득률': 'Session gain',
    '평균 분당 EXP': 'Average EXP/min',
    '최근 60초 획득': 'EXP in last 60s',
    '시간당 환산 EXP': 'Estimated EXP/hr',
    '누적 획득 EXP': 'Total EXP gained',
    '60초 미만 속도는 환산값입니다. 중단 구간은 제외합니다.\n게임의 EXP 영역을 가리지 마세요.':
        'Rates under 60 seconds are estimates. Paused gaps are excluded.\nKeep the game EXP area visible.',
    'MapleStory 창을 찾지 못했습니다': 'No MapleStory window found',
    'MapleStory 창이 닫혔거나 최소화되어 있습니다.': 'The MapleStory window is closed or minimized.',
    '게임 창 위치를 확인하지 못했습니다.': 'Could not locate the game window.',
    '게임 창 크기를 확인하세요.': 'Check the game window size.',
    '화면 캡처 장치를 열지 못했습니다.': 'Could not initialize screen capture.',
    '인식 영역 크기를 확인하세요.': 'Check the capture area size.',
    '캡처 버퍼를 생성하지 못했습니다.': 'Could not create the capture buffer.',
    '게임의 화면 영역을 복사하지 못했습니다.': 'Could not capture the game screen area.',
    'OCR이 숫자를 찾지 못했습니다.': 'OCR could not find any numbers.',
    'EXP 숫자가 선명하게 읽히지 않습니다. 인식 영역을 확인하세요.': 'EXP is unclear. Check the capture area.',
    '자동 레벨 영역이 필요합니다.': 'Select a level area for automatic level detection.',
    '레벨 숫자가 읽히지 않습니다. 레벨 영역을 다시 지정하세요.': 'Could not read the level. Select the level area again.',
    '모니터 정보를 확인하지 못했습니다.': 'Could not read monitor information.',
    '준비 완료 · 저부하 캡처 / 게임 창 선택 후 인식 시험 또는 측정 시작을 누르세요.':
        'Ready · Select a game window in Settings, then test OCR or start.',
    'MapleStory 창을 찾지 못했습니다. 게임을 켠 뒤 창 새로고침을 누르세요.':
        'No MapleStory window found. Start the game, then Refresh in Settings.',
    '대기 · MapleStory 창을 클릭하면 자동으로 측정합니다.': 'Waiting · Click the MapleStory window to measure.',
    '측정 시작 대기 · MapleStory 창을 클릭하세요.': 'Waiting · Click the MapleStory window.',
    '일시정지 · 중단 중 EXP는 합산하지 않습니다.': 'Paused · EXP gained during the pause is excluded.',
    '초기화 완료 · 다음 정상 인식값부터 새 측정을 시작합니다.': 'Reset · A new session starts with the next valid reading.',
    'EXP/레벨 인식 시험 중…': 'Testing EXP and level OCR…',
    '첨부 스크린샷 기준 기본 위치로 복원했습니다.': 'Default capture areas restored.',
    '영역 지정': 'Select capture area',
    '먼저 MapleStory 창을 선택하세요.': 'Select a MapleStory window first.',
    '왼쪽 EXP 글자부터 [퍼센트%] 끝까지 여유 있게 드래그하세요. 게이지 제외. ESC 취소.':
        'Drag from EXP through [percent%], with a little margin. Exclude the bar. Esc cancels.',
    '현재 레벨 숫자만 드래그하세요. LV 글자는 제외. ESC 취소.':
        'Drag around the level number only. Exclude LV. Esc cancels.',
    '영역 지정 완료 · 인식 시험으로 확인하세요.': 'Area selection finished · Use Test OCR to check.',
    '내보내기': 'Export',
    '먼저 측정을 시작하세요.': 'Start a measurement first.',
    'CSV 기록': 'CSV logs',
    '저장 실패': 'Save failed',
    'Maple EXP Meter 오류': 'Maple EXP Meter error',
    'EXP 숫자와 퍼센트(%)가 함께 보이도록 영역을 지정하세요.': 'Include both the EXP number and percentage (%) in the capture area.',
    'EXP 숫자를 읽지 못했습니다.': 'Could not read the EXP number.',
    '레벨/EXP 범위가 맞지 않습니다. 레벨 영역이나 수동 레벨을 확인하세요.': 'Level/EXP is out of range. Check the level area or manual level.',
    '측정 시작': 'Session started',
    '측정 재개 · 중단 구간의 EXP는 제외': 'Resumed · EXP from the gap is excluded',
    '캐릭터 변경 또는 레벨 인식 오류 의심: 측정을 초기화하거나 레벨을 확인하세요.': 'Possible character change or incorrect level. Reset the session or check the level.',
    'EXP 변화가 너무 큽니다. 다른 캐릭터라면 초기화하세요. 이 표본은 합산하지 않았습니다.': 'EXP changed too much. Reset if you switched characters. This sample was excluded.',
    '레벨업 반영': 'Level-up recorded',
    '정상 측정 중': 'Measuring',
}

PREFIXES = {
    'OCR 엔진 오류: ': 'OCR engine error: ',
    '기록 저장 실패: ': 'Could not save log: ',
    '인식 시험 OK · ': 'OCR test OK · ',
    '\n오류 기록: ': '\nError log: ',
}


def translate(text, language):
    """Translate original Korean messages; keep unknown system errors intact."""
    if language != 'en':
        return text
    if text in EN:
        return EN[text]
    for source, target in PREFIXES.items():
        if text.startswith(source):
            return target + translate(text[len(source):], language)
    mismatch = re.fullmatch(r'검증 보류: Lv\.(\d+) / ([\d,]+) EXP는 ([\d.]+)%여야 합니다 \(인식 ([\d.]+)%\)\.', text)
    if mismatch:
        level, exp, expected, actual = mismatch.groups()
        return f'Reading rejected: Lv.{level} / {exp} EXP should be {expected}% (read {actual}%).'
    decrease = re.fullmatch(r'EXP 감소 ([\d,]+) 별도 기록', text)
    if decrease:
        return f'EXP loss {decrease[1]} recorded separately'
    return text
