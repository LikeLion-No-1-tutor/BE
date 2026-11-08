"""수업을 시작할 때 학생 AI의 첫 인사.

AI를 부르지 않고 페르소나별 고정 문장에 주제 이름만 넣는다.
"""
GREETINGS = {
    'haneul': '선생님 안녕하세요! 오늘은 {title} 배우는 거죠? 쉬운 말로 알려 주세요!',
    'minjun': '선생님 안녕하세요! 오늘 {title} 배우는 거죠? 잘 들을게요.',
    'seoyeon': '안녕하세요, 선생님. 오늘은 {title}에 대해 배우는 거죠? 잘 부탁드려요.',
}
DEFAULT_GREETING = '선생님 안녕하세요! 오늘 {title} 배우는 거죠? 잘 들을게요.'


def greeting_for(persona, title):
    return GREETINGS.get(persona.code, DEFAULT_GREETING).format(title=title)
