#!/usr/bin/env python3
"""
Gate for the published dictionary.

Mirrors the rules in Services/DictionaryImporter.cs. Anything this rejects would either be
refused by the app at sync time (leaving users on a stale dictionary) or accepted with silently
wrong data, so it must fail the build before Pages ever serves it.

Usage: python validate_dictionary.py dictionary.json
"""
import json
import sys
import unicodedata

ENGLISH = "en"
ENGLISH_ALIASES = {"en", "eng", "english", "английский", "англ"}
MIN_WORDS = 5          # the app refuses to start a session below this
MIN_TRANSLATIONS = 1   # a word with no translation cannot be practised


def fail(errors, message):
    errors.append(message)


def validate(path):
    errors, warnings = [], []

    raw = open(path, "rb").read()

    if raw.startswith(b"\xef\xbb\xbf"):
        fail(errors, "File starts with a UTF-8 BOM; save without one.")
        raw = raw[3:]

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        fail(errors, f"File is not valid UTF-8: {e}")
        return errors, warnings

    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        fail(errors, f"Invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}")
        return errors, warnings

    # --- shape ---
    declared = {}
    if isinstance(doc, list):
        words = doc
        warnings.append("No 'languages' block: imported columns will be named from their codes.")
    elif isinstance(doc, dict):
        if not isinstance(doc.get("words"), list):
            fail(errors, "Expected an object with a 'words' array, or a bare array of words.")
            return errors, warnings
        words = doc["words"]

        block = doc.get("languages")
        if block is None:
            warnings.append("No 'languages' block: imported columns will be named from their codes.")
        elif not isinstance(block, list):
            fail(errors, "'languages' must be an array.")
        else:
            for i, lang in enumerate(block, 1):
                if not isinstance(lang, dict):
                    fail(errors, f"languages[{i}]: expected an object.")
                    continue
                code, name = lang.get("code"), lang.get("name")
                if not isinstance(code, str) or not code.strip():
                    fail(errors, f"languages[{i}]: missing 'code'.")
                    continue
                if not isinstance(name, str) or not name.strip():
                    warnings.append(f"languages[{i}] ({code}): no 'name'; the code will be shown as the column header.")
                if code in declared:
                    fail(errors, f"languages[{i}]: duplicate code '{code}'.")
                declared[code] = name
    else:
        fail(errors, "Top level must be an object or an array.")
        return errors, warnings

    if not words:
        fail(errors, "'words' is empty; the app would reject this payload and keep its cache.")
        return errors, warnings

    # --- words ---
    seen = {}
    used_codes = set()

    for i, word in enumerate(words, 1):
        if not isinstance(word, dict):
            fail(errors, f"words[{i}]: expected an object.")
            continue

        english = None
        translations = 0

        for key, value in word.items():
            if not isinstance(value, str):
                fail(errors, f"words[{i}]: value for '{key}' must be a string.")
                continue
            if not value.strip():
                warnings.append(f"words[{i}]: empty value for '{key}' will be ignored on import.")
                continue

            if value != value.strip():
                warnings.append(f"words[{i}]: '{key}' has surrounding whitespace.")
            if value != unicodedata.normalize("NFC", value):
                warnings.append(f"words[{i}]: '{key}' is not NFC-normalised; matching may behave oddly.")

            if key.lower() in ENGLISH_ALIASES:
                english = value.strip()
            else:
                translations += 1
                used_codes.add(key)

        if not english:
            fail(errors, f"words[{i}]: no English key; the app would skip this entry.")
            continue

        if translations < MIN_TRANSLATIONS:
            fail(errors, f"words[{i}] ('{english}'): no translations, so it can never be practised.")

        fold = english.casefold()
        if fold in seen:
            fail(errors, f"words[{i}] ('{english}'): duplicate of words[{seen[fold]}]; "
                         "the app collapses these onto one entry.")
        else:
            seen[fold] = i

    if len(seen) < MIN_WORDS:
        fail(errors, f"Only {len(seen)} unique words; the app needs at least {MIN_WORDS} to start a session.")

    if declared:
        for code in sorted(used_codes - set(declared) - {ENGLISH}):
            warnings.append(f"Language '{code}' is used but not declared in 'languages'.")
        for code in sorted(set(declared) - used_codes - {ENGLISH}):
            warnings.append(f"Language '{code}' is declared but never used.")

    # --- coverage, purely informational ---
    if used_codes:
        print("Coverage:")
        for code in sorted(used_codes):
            have = sum(1 for w in words if isinstance(w, dict) and str(w.get(code, "")).strip())
            label = declared.get(code) or code
            print(f"  {label} ({code}): {have}/{len(words)}")

    return errors, warnings


def main():
    if len(sys.argv) != 2:
        print("usage: validate_dictionary.py <dictionary.json>", file=sys.stderr)
        return 2

    path = sys.argv[1]
    errors, warnings = validate(path)

    for w in warnings:
        print(f"::warning::{w}")
    for e in errors:
        print(f"::error::{e}")

    if errors:
        print(f"\nFAILED: {len(errors)} error(s), {len(warnings)} warning(s).")
        return 1

    print(f"\nOK: {path} is valid ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
