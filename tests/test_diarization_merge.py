from chessify.diarization import SpeakerTurn, assign_speakers
from chessify.schema import Word


def test_assign_by_overlap_and_nearest() -> None:
    words = [
        Word(t0=0.0, t1=0.5, w="Присядьте,"),
        Word(t0=6.1, t1=6.9, w="Примерно"),
        Word(t0=7.5, t1=7.7, w="так."),  # в паузе между отрезками — берём ближайший
    ]
    turns = [SpeakerTurn(0.0, 4.3, "SPEAKER_00"), SpeakerTurn(6.0, 7.3, "SPEAKER_01"), SpeakerTurn(8.5, 11.4, "SPEAKER_00")]
    assert [w.spk for w in assign_speakers(words, turns)] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_01"]


def test_no_turns_keeps_words() -> None:
    words = [Word(t0=0, t1=1, w="Да.")]
    assert assign_speakers(words, []) == words
