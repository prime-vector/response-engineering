#!/usr/bin/env python3
"""
Ingest the corpus into the index the precedent_archive surface serves.

Stdlib only, like the mock it feeds. See interfaces/PRECEDENT.md for the
surface this exists to satisfy, and docs/precedent-analyst.md for the real
adapter's store, which is a different problem: this one is the conformance
reference, so it has to be reproducible on any machine with no services
running.

    python3 corpus/ingest.py                       # heading-aware, the default
    python3 corpus/ingest.py --chunker fixed       # the Phase 5 baseline
    python3 corpus/ingest.py --check               # report drift, write nothing

Two chunkers are kept deliberately. Heading-aware carries the heading path
down to the passage, which is what makes a citation checkable by a human in
about five seconds. Fixed-size ignores structure and is the baseline the
heading-aware one has to beat on the evals, measured rather than asserted.

Idempotence is structural rather than promised: passage ids are derived from
(chunker, source_uri, heading_path, ordinal), so re-ingesting unchanged
sources produces byte-identical output and the file is left alone. There is
no wall-clock timestamp anywhere in the index for the same reason.
"""

import argparse
import hashlib
import json
import os
import re
import sys

DOCUMENTS = "corpus/documents"
INDEXES = {"heading": "corpus/index.json", "fixed": "corpus/index.fixed.json"}
MANIFEST = "corpus/manifest.yaml"

# A section longer than this is split at sentence boundaries. Chosen so a
# passage stays quotable in a bridge message: a citation nobody reads is a
# citation nobody checks.
MAX_PASSAGE_CHARS = 900
FIXED_PASSAGE_CHARS = 600

# Front matter keys carried down onto every passage from the document. These
# are the qualifiers interfaces/PRECEDENT.md requires: a passage has to arrive
# with what stops it being over-read.
CARRIED = ("source_uri", "source_family", "record_status", "recorded_at",
           "cause_claimed", "superseded_by", "signature")


def parse_document(path):
    """Split a corpus document into its front matter and body.

    The front matter is a flat key/value block, deliberately: a document whose
    provenance needs a nested structure to express is a document whose
    provenance nobody will check.
    """
    with open(path) as fh:
        raw = fh.read()
    if not raw.startswith("---\n"):
        raise ValueError(f"{path}: no front matter. Every corpus document "
                         "must declare its source and licence.")
    _, front_raw, body = raw.split("---\n", 2)
    front = {}
    for line in front_raw.splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        front[key.strip()] = value.strip()

    for required in ("source_uri", "source_family", "licence", "recorded_at"):
        if not front.get(required):
            raise ValueError(f"{path}: front matter is missing '{required}'. "
                             "A document that cannot say where it came from "
                             "does not get indexed.")
    return front, body.strip(), hashlib.sha256(raw.encode()).hexdigest()


def _split_long(text, limit):
    """Split at sentence boundaries, never mid-sentence. A passage cut through
    a sentence reads as evidence of something the source did not say."""
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out, current = [], ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > limit:
            out.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current.strip():
        out.append(current.strip())
    return out


def chunk_heading(body):
    """Heading-aware. Yields (heading_path_tail, text) with the section
    heading preserved, so the citation names where in the document it sits."""
    title = ""
    section = ""
    buffer = []
    out = []

    def flush():
        text = "\n".join(buffer).strip()
        if text:
            for part in _split_long(text, MAX_PASSAGE_CHARS):
                out.append((section, part))
        buffer.clear()

    for line in body.splitlines():
        if line.startswith("# "):
            flush()
            title = line[2:].strip()
            section = ""
        elif line.startswith("## "):
            flush()
            section = line[3:].strip()
        else:
            buffer.append(line)
    flush()
    return title, out


def chunk_fixed(body):
    """Fixed-size, structure-blind. The baseline: same documents, same
    citation fields, but the heading path degrades to the document title
    because nothing tracked where the text sat. That degradation is the
    thing Phase 5 measures."""
    title = ""
    text_lines = []
    for line in body.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            text_lines.append(line[3:].strip())
        else:
            text_lines.append(line)
    text = " ".join(l.strip() for l in text_lines if l.strip())

    out, current = [], ""
    for word in text.split():
        if len(current) + len(word) + 1 > FIXED_PASSAGE_CHARS:
            out.append(("", current.strip()))
            current = word
        else:
            current = f"{current} {word}".strip()
    if current.strip():
        out.append(("", current.strip()))
    return title, out


def passage_id(chunker, source_uri, heading_path, ordinal):
    """Stable across re-ingest, so a passage_id cited on a board today still
    resolves next month. Derived from position rather than from content: an
    edit to the wording must not orphan a citation someone already made."""
    key = f"{chunker}|{source_uri}|{heading_path}|{ordinal}"
    return "p-" + hashlib.sha256(key.encode()).hexdigest()[:12]


def build(chunker):
    if not os.path.isdir(DOCUMENTS):
        raise SystemExit(f"No corpus at {DOCUMENTS}. Generate the prior "
                         "incident records first:\n"
                         "  python3 fixtures/generate.py --corpus corpus/documents")

    paths = sorted(
        os.path.join(root, name)
        for root, _, names in os.walk(DOCUMENTS)
        for name in names if name.endswith(".md")
    )
    if not paths:
        raise SystemExit(f"No documents under {DOCUMENTS}.")

    documents, passages = [], []
    for path in paths:
        front, body, digest = parse_document(path)
        title, chunks = (chunk_heading(body) if chunker == "heading"
                         else chunk_fixed(body))
        documents.append({
            "source_uri": front["source_uri"],
            "source_family": front["source_family"],
            "licence": front["licence"],
            "recorded_at": front["recorded_at"],
            "record_status": front.get("record_status", "filed"),
            "path": path,
            "sha256": digest,
        })
        for ordinal, (section, text) in enumerate(chunks):
            heading_path = f"{title} > {section}" if section else title
            passage = {
                "passage_id": passage_id(chunker, front["source_uri"],
                                         heading_path, ordinal),
                "source_uri": front["source_uri"],
                "heading_path": heading_path,
                "ordinal": ordinal,
                "text": text,
            }
            for key in CARRIED:
                if key in front and key != "source_uri":
                    passage[key] = front[key]
            passage.setdefault("record_status", "filed")
            passage.setdefault("cause_claimed", None)
            passage.setdefault("superseded_by", None)
            # A passage that cannot produce a complete citation must not be
            # retrievable at all. Refused here rather than emitted with a
            # null field, so the impossible claim cannot be constructed
            # downstream.
            if not (passage["heading_path"] and passage["source_uri"]
                    and passage["text"]):
                raise ValueError(
                    f"{path}: passage {ordinal} cannot produce a complete "
                    "citation. Give the document a title heading."
                )
            passages.append(passage)

    dates = sorted(d["recorded_at"] for d in documents)
    return {
        "_comment": (
            "Generated by corpus/ingest.py. Do not hand-edit. Synthetic and "
            "authored material only; see corpus/manifest.yaml for provenance."
        ),
        "chunker": chunker,
        # Deterministic rather than wall-clock: the corpus is current to its
        # newest document, which is a fact about the data. A build timestamp
        # would make every re-ingest look like a change.
        "corpus_current_to": dates[-1],
        "date_range": f"{dates[0]} to {dates[-1]}",
        "source_families": sorted({d["source_family"] for d in documents}),
        "document_count": len(documents),
        "passage_count": len(passages),
        "documents": documents,
        "passages": passages,
    }


def write_manifest(index):
    """The manifest is generated from what was actually ingested, never hand
    maintained. A provenance record that can drift from the corpus is a
    provenance record nobody can rely on."""
    lines = [
        "# Generated by corpus/ingest.py. Do not hand-edit.",
        "#",
        "# Provenance for everything in the archive. Synthetic and authored",
        "# material only: nothing client, employer or customer derived enters",
        "# this corpus, the eval set or any artefact derived from them.",
        "",
        f"document_count: {index['document_count']}",
        f"date_range: {index['date_range']}",
        "documents:",
    ]
    for doc in index["documents"]:
        lines += [
            f"  - source_uri: {doc['source_uri']}",
            f"    path: {doc['path']}",
            f"    source_family: {doc['source_family']}",
            f"    licence: {doc['licence']}",
            f"    recorded_at: {doc['recorded_at']}",
            f"    record_status: {doc['record_status']}",
            f"    sha256: {doc['sha256']}",
        ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunker", choices=sorted(INDEXES), default="heading")
    parser.add_argument("--check", action="store_true",
                        help="Report whether generated artefacts are current, write nothing")
    args = parser.parse_args()

    index = build(args.chunker)
    target = INDEXES[args.chunker]
    rendered = json.dumps(index, indent=2) + "\n"

    artefacts = {target: rendered}
    if args.chunker == "heading":
        artefacts[MANIFEST] = write_manifest(index)
    stale = []
    for path, content in artefacts.items():
        existing = None
        if os.path.exists(path):
            with open(path) as fh:
                existing = fh.read()
        if existing != content:
            stale.append(path)
    summary = (f"{index['document_count']} documents, "
               f"{index['passage_count']} passages, chunker={args.chunker}")
    if args.check:
        print(f"{summary}: " + (f"STALE: {', '.join(stale)}" if stale else "current"))
        return 1 if stale else 0
    for path in stale:
        with open(path, "w") as fh:
            fh.write(artefacts[path])
    print(f"{summary}: " + (f"wrote {', '.join(stale)}" if stale else
                           "unchanged, 0 new passages, nothing written"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
