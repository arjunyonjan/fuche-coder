#!/usr/bin/env python3
import re
import sys
import time

STOPWORDS = set([
    'what', 'how', 'why', 'when', 'where', 'which', 'who', 'whom',
    'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had',
    'do', 'does', 'did', 'can', 'could', 'would', 'should', 'will', 'shall',
    'may', 'might', 'must', 'the', 'a', 'an', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'as', 'and', 'or', 'but', 'not', 'no', 'yes',
    'this', 'that', 'these', 'those', 'it', 'its', 'i', 'you', 'he', 'she',
    'we', 'they', 'me', 'him', 'her', 'us', 'them', 'my', 'your', 'his',
    'her', 'its', 'our', 'their', 'me', 'myself', 'yourself', 'himself',
    'herself', 'itself', 'ourselves', 'themselves', 'about', 'above',
    'after', 'again', 'against', 'all', 'am', 'any', 'are', 'because',
    'been', 'before', 'being', 'below', 'between', 'both', 'each', 'few',
    'more', 'most', 'other', 'some', 'such', 'than', 'too', 'under', 'up',
    'very', 'into', 'over', 'then', 'once', 'here', 'there'
])

def extract_keywords(text, max_words=5):
    words = re.findall(r'[a-zA-Z]+', text.lower())
    significant = [w for w in words if w not in STOPWORDS and len(w) > 2]
    seen = set()
    unique = []
    for w in significant:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return ' '.join(unique[:max_words])

def quality_check(answer, question):
    if not answer or answer.startswith("Search failed"):
        return 0.0
    words = set(question.lower().split())
    found = sum(1 for w in words if w in answer.lower() and len(w) > 2)
    keyword_ratio = found / max(len(words), 1)
    length_score = min(len(answer) / 500, 1.0)
    return min(keyword_ratio * 0.6 + length_score * 0.4, 1.0)

def refine_keywords(original, current, quality):
    return extract_keywords(original)

def search(query):
    from crawler import search_and_extract
    try:
        return search_and_extract(query)
    except Exception as e:
        return f"Search failed: {e}"

def self_heal(question, max_loops=3):
    keywords = extract_keywords(question) or question
    best_keywords = keywords
    best_quality = 0.0
    best_result = ""
    for loop in range(1, max_loops + 1):
        print(f"Loop {loop}: Searching with '{keywords}'")
        result = search(keywords)
        quality = quality_check(result, question)
        print(f"Quality: {quality:.2f}")

        if quality > best_quality:
            best_quality = quality
            best_result = result
            best_keywords = keywords

        if quality >= 0.7:
            print("✅ Good result")
            return result

        if loop < max_loops:
            keywords = refine_keywords(question, keywords, quality)
            if quality < 0.3:
                keywords = question
            print(f"Refined keywords: {keywords}")
            time.sleep(1)

    print("⚠️ Max loops reached, returning best result")
    return best_result

if __name__ == "__main__":
    q = " ".join(sys.argv[1:]).strip().rstrip(".,!?;:")
    if not q:
        print("Usage: python loop.py 'your question'")
        sys.exit(1)
    print(self_heal(q))
