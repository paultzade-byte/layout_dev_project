# core/counter.py

#sketch
from collections import Counter
from pathlib import Path

def text_reader(data_path):
    clean_dir = Path(data_path) / "clean_data"
    chunks = []
    for f in sorted(clean_dir.glob("*.txt")):
        chunks.append(f.read_text(encoding="utf_8"))
    return "\n".join(chunks)

def buid_char_freqs(chunks):
    char_count = Counter(chunks)
    print(char_count)
    return char_count

def build_ngram_freqs(chunks: list) -> tuple[Counter, Counter, Counter]:
    bigrams = Counter()
    trigrams = Counter()
    skipgrams = Counter()
    n = len(chunks)
    for i in range(n - 2):
        bigrams[(chunks[i], chunks[i+1])] += 1
        skipgrams[(chunks[i], chunks[i+2])] += 1
        trigrams[(chunks[i], chunks[i+1], chunks[i+2])] += 1
    if n >= 2:
        bigrams[(chunks[-2], chunks[-1])] += 1
    return bigrams, trigrams, skipgrams
