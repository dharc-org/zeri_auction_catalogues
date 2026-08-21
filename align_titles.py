"""
align_titles.py

Sostituisce find_best_match_in_window + cursore con un allineamento
GLOBALE monotono (stile Needleman-Wunsch) tra la sequenza di titoli
(i chunk, in ordine) e la sequenza di righe candidate (in ordine).

Perché: nel matching greedy con cursore, un match sbagliato-ma-sopra-soglia
sposta il cursore troppo avanti e "brucia" il testo corretto per tutti i
chunk successivi -> fallimento a cascata senza possibilità di recupero
(è esattamente il pattern osservato: tutto ok fino a un certo lotto, poi
un salto anomalo di riga, poi tutti i lotti seguenti falliscono).

Il DP invece ottimizza l'assegnazione dell'INTERA sequenza in un colpo
solo: un match locale debole/sbagliato non compromette il resto, perché
l'algoritmo può "saltare" quel titolo (nessun match, penalità fissa) e
recuperare l'allineamento corretto sui titoli successivi.

Vincolo di monotonia: se il titolo i è assegnato alla riga j, il titolo
i+1 può solo essere assegnato a una riga >= j (l'ordine è preservato in
entrambe le sequenze).
"""
from __future__ import annotations
import re
from rapidfuzz import fuzz

SKIP_PENALTY = 30  # costo di non assegnare nessuna riga a un titolo
BAND = 400  # ampiezza banda attorno alla diagonale attesa (limita costo O(N*M))
NEG = float("-inf")


def normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def align_titles_to_lines(
    titles: list[str],
    candidates: list[tuple[int, str]],
) -> list[tuple[int | None, float]]:
    """
    titles: un title per chunk, in ordine.
    candidates: [(line_number, testo_riga), ...] in ordine (1-based line_number).

    Ritorna una lista parallela a `titles`: (line_number assegnata o None, score).
    """
    n, m = len(titles), len(candidates)
    if n == 0 or m == 0:
        return [(None, 0.0)] * n

    norm_titles = [normalize(t) for t in titles]
    norm_lines = [normalize(c[1]) for c in candidates]
    ratio = m / n

    # dp[i][j]: miglior punteggio cumulativo usando i primi i titoli e le
    # prime j righe (0-based logico, array (n+1) x (m+1))
    dp = [[NEG] * (m + 1) for _ in range(n + 1)]
    choice = [[None] * (m + 1) for _ in range(n + 1)]  # 'carry' | 'skip' | 'match'
    for j in range(m + 1):
        dp[0][j] = 0.0

    for i in range(1, n + 1):
        expected_j = int(i * ratio)
        lo = max(1, expected_j - BAND)
        hi = min(m, expected_j + BAND)
        for j in range(lo, hi + 1):
            best, src = NEG, None

            # non consuma la riga j per il titolo i (si sposta solo il
            # limite superiore di righe disponibili)
            if j > lo and dp[i][j - 1] != NEG:
                best, src = dp[i][j - 1], 'carry'

            # titolo i senza match (nessuna riga assegnata), penalità fissa
            if dp[i - 1][j] != NEG:
                cand = dp[i - 1][j] - SKIP_PENALTY
                if cand > best:
                    best, src = cand, 'skip'

            # titolo i assegnato alla riga j
            if dp[i - 1][j - 1] != NEG:
                score = fuzz.ratio(norm_titles[i - 1], norm_lines[j - 1])
                cand = dp[i - 1][j - 1] + score
                if cand > best:
                    best, src = cand, 'match'

            dp[i][j] = best
            choice[i][j] = src

    best_j = max(range(m + 1), key=lambda j: dp[n][j])

    result_line: list[int | None] = [None] * n
    result_score: list[float] = [0.0] * n
    i, j = n, best_j
    while i > 0:
        src = choice[i][j]
        if src == 'carry':
            j -= 1
        elif src == 'skip':
            i -= 1
        elif src == 'match':
            result_line[i - 1] = candidates[j - 1][0]
            result_score[i - 1] = fuzz.ratio(norm_titles[i - 1], norm_lines[j - 1])
            i -= 1
            j -= 1
        else:
            # non dovrebbe succedere se BAND è sufficientemente ampia;
            # se succede, il titolo i-esimo resta senza match
            i -= 1

    return list(zip(result_line, result_score))
