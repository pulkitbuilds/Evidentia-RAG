"""
Scores the running RAGnarok backend against a hand-labeled set of
(sentence -> expected verdict) pairs.

Usage:
    1. Start the backend (uvicorn app.main:app), log into the app once, and
       copy your access token from your browser's dev tools -> Application ->
       Local Storage -> `ragnarok:accessToken`.
    2. Note the case you want to evaluate against (or create one) -- its ID
       is visible via `GET /cases` (with the same token) or the Cases page.
    3. Ingest a corpus into that case.
    4. python eval.py labeled_set.json --base-url http://localhost:8000 --token <token> --case-id <id>

labeled_set.json format:
[
  {"sentence": "The Eiffel Tower was completed in 1889.", "expected": "supported"},
  {"sentence": "The Eiffel Tower is located in London.", "expected": "contradicted"},
  {"sentence": "I think Paris is a lovely city.", "expected": "unverified"}
]
"""
import argparse
import json
import sys

import requests


def load_labeled_set(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_case_id(base_url: str, headers: dict, case_id: str | None) -> str:
    """If no case_id was given, use the only case if there's exactly one,
    otherwise ask the user to pick."""
    resp = requests.get(f"{base_url}/cases", headers=headers, timeout=30)
    if resp.status_code == 401:
        print("Auth failed -- your --token is missing, wrong, or expired. Log in again and copy a fresh one.")
        sys.exit(1)
    resp.raise_for_status()
    cases = resp.json()["cases"]

    if case_id:
        if not any(c["id"] == case_id for c in cases):
            print(f"No case with id {case_id} found (for this account). Available cases:")
            for c in cases:
                print(f"  {c['id']}  {c['name']}")
            sys.exit(1)
        return case_id

    if len(cases) == 1:
        return cases[0]["id"]

    print("Multiple cases exist -- pass --case-id explicitly. Available cases:")
    for c in cases:
        print(f"  {c['id']}  {c['name']}")
    sys.exit(1)


def run_eval(labeled_set: list[dict], base_url: str, headers: dict, case_id: str) -> dict:
    total = len(labeled_set)
    correct = 0
    confusion: dict[str, dict[str, int]] = {}
    results = []

    for item in labeled_set:
        sentence = item["sentence"]
        expected = item["expected"]

        resp = requests.post(
            f"{base_url}/cases/{case_id}/claims/check", json={"sentence": sentence}, headers=headers, timeout=120
        )
        resp.raise_for_status()
        predicted = resp.json()["verdict"]

        confusion.setdefault(expected, {}).setdefault(predicted, 0)
        confusion[expected][predicted] += 1

        is_correct = predicted == expected
        correct += int(is_correct)
        results.append(
            {"sentence": sentence, "expected": expected, "predicted": predicted, "correct": is_correct}
        )

    accuracy = correct / total if total else 0.0
    return {"accuracy": accuracy, "total": total, "correct": correct, "confusion": confusion, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the RAGnarok claim-checking pipeline.")
    parser.add_argument("labeled_set", help="Path to a hand-labeled JSON file.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL.")
    parser.add_argument("--token", required=True, help="Access token (from localStorage after logging into the app).")
    parser.add_argument("--case-id", default=None, help="Case to evaluate against. Required if you have more than one case.")
    parser.add_argument("--verbose", action="store_true", help="Print every misprediction.")
    args = parser.parse_args()

    headers = {"Authorization": f"Bearer {args.token}"}

    case_id = resolve_case_id(args.base_url, headers, args.case_id)
    labeled_set = load_labeled_set(args.labeled_set)
    report = run_eval(labeled_set, args.base_url, headers, case_id)

    print(f"Accuracy: {report['accuracy']:.2%} ({report['correct']}/{report['total']})")
    print("\nConfusion (rows=expected, cols=predicted):")
    for expected, predictions in report["confusion"].items():
        print(f"  {expected}: {predictions}")

    if args.verbose:
        print("\nMispredictions:")
        for r in report["results"]:
            if not r["correct"]:
                print(f"  [{r['expected']} -> {r['predicted']}] {r['sentence']}")

    sys.exit(0 if report["accuracy"] == 1.0 else 1)


if __name__ == "__main__":
    main()
