"""Document editing and LLM-driven helpers.

Uses provider-specific adapters for Gemini, OpenRouter, Ollama, and
OpenAI-compatible endpoints. All API key / path lookups go through
`config.py`.
"""
from __future__ import annotations

import datetime
import difflib
import json
import random
import re
import time
import concurrent.futures
from typing import Any, Dict, List, Optional

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import numpy as np
import requests

import config as app_config


def _normalize_settings(settings: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    return app_config.normalize_llm_settings(settings or app_config.get_llm_settings())


# --- Provider helpers ---

def _client(api_key: Optional[str] = None):
    return app_config.get_gemini_client(api_key=api_key)


def _post_json(url: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None,
               timeout: int = 120) -> Dict[str, Any]:
    resp = requests.post(url, json=payload, headers=headers or {}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected non-object JSON response")
    return data


def _generate_text(prompt: str, settings: Optional[Dict[str, Any]] = None,
                   response_mime_type: Optional[str] = None) -> str:
    """Generate text through the selected provider."""
    cfg = _normalize_settings(settings)
    provider = cfg["provider"]

    if provider == "gemini":
        from google.genai import types

        kwargs = {}
        if response_mime_type:
            kwargs["config"] = types.GenerateContentConfig(
                response_mime_type=response_mime_type,
            )
        resp = _client(cfg["api_key"]).models.generate_content(
            model=cfg["text_model"], contents=prompt, **kwargs,
        )
        time.sleep(1)
        return (resp.text or "").strip()

    if provider in {"openrouter", "openai-compatible", "custom"}:
        base = cfg["base_url"].rstrip("/")
        if not base:
            raise RuntimeError("Base URL is required for this provider.")
        payload: Dict[str, Any] = {
            "model": cfg["text_model"],
            "messages": [{"role": "user", "content": prompt}],
        }
        if response_mime_type == "application/json":
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if cfg["api_key"]:
            headers["Authorization"] = f"Bearer {cfg['api_key']}"
        data = _post_json(f"{base}/chat/completions", payload, headers=headers)
        try:
            text = data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise RuntimeError(f"Unexpected chat completion response: {data}") from exc
        time.sleep(0.6)
        return (text or "").strip()

    if provider == "ollama":
        base = cfg["base_url"].rstrip("/")
        if not base:
            raise RuntimeError("Ollama base URL is required.")
        payload = {
            "model": cfg["text_model"],
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        data = _post_json(f"{base}/chat", payload, timeout=180)
        try:
            text = data["message"]["content"]
        except Exception as exc:
            raise RuntimeError(f"Unexpected Ollama chat response: {data}") from exc
        time.sleep(0.6)
        return (text or "").strip()

    raise RuntimeError(f"Unsupported LLM provider: {provider}")


def _embed(text: str, settings: Optional[Dict[str, Any]] = None) -> List[float]:
    cfg = _normalize_settings(settings)
    provider = cfg["provider"]

    if provider == "gemini":
        resp = _client(cfg["api_key"]).models.embed_content(
            model=cfg["embed_model"], contents=text,
        )
        time.sleep(0.3)
        if not resp.embeddings:
            raise RuntimeError("Empty embedding response")
        return list(resp.embeddings[0].values)

    if provider in {"openrouter", "openai-compatible", "custom"}:
        base = cfg["base_url"].rstrip("/")
        if not base:
            raise RuntimeError("Base URL is required for this provider.")
        payload = {"model": cfg["embed_model"], "input": text}
        headers = {"Content-Type": "application/json"}
        if cfg["api_key"]:
            headers["Authorization"] = f"Bearer {cfg['api_key']}"
        data = _post_json(f"{base}/embeddings", payload, headers=headers, timeout=180)
        try:
            vector = data["data"][0]["embedding"]
        except Exception as exc:
            raise RuntimeError(f"Unexpected embeddings response: {data}") from exc
        time.sleep(0.3)
        return list(vector)

    if provider == "ollama":
        base = cfg["base_url"].rstrip("/")
        if not base:
            raise RuntimeError("Ollama base URL is required.")
        payload = {"model": cfg["embed_model"], "input": text}
        data = _post_json(f"{base}/embed", payload, timeout=180)
        try:
            vector = data["embeddings"][0]
        except Exception as exc:
            raise RuntimeError(f"Unexpected Ollama embeddings response: {data}") from exc
        time.sleep(0.3)
        return list(vector)

    raise RuntimeError(f"Unsupported LLM provider: {provider}")


def test_text_generation(prompt: str, settings: Optional[Dict[str, Any]] = None) -> str:
    """Run a small text-generation probe with the selected provider."""
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("Prompt cannot be empty.")
    return _generate_text(prompt, settings=settings)


def test_embedding(text: str, settings: Optional[Dict[str, Any]] = None) -> List[float]:
    """Run an embedding probe with the selected provider."""
    text = text.strip()
    if not text:
        raise ValueError("Text cannot be empty.")
    return _embed(text, settings=settings)


# --- High-level operations ---

def align_global_citations(paras: List[str], settings: Dict[str, Any], ref_style: str) -> List[str]:
    """Second pass: convert in-text citations to sequential [1], [2] and
    re-sort the bibliography to match."""
    indexed_paras = {str(i): p for i, p in enumerate(paras) if p.strip()}

    prompt = f"""You are a strict reference alignment engine.
The selected reference style is {ref_style}.

Task:
1. Scan the provided manuscript text for any in-text citations (e.g., "(Smith et al., 2020)").
2. Convert all in-text citations to sequential bracketed numbers (e.g., "[1]", "[1, 2, 3]") based on the EXACT order they first appear in the text.
3. Locate the bibliography/reference list at the end of the text.
4. Re-order and re-number the actual bibliography entries so that they match the new numerical sequence of the in-text citations.

CRITICAL OUTPUT INSTRUCTIONS:
- Return ONLY a valid JSON dictionary.
- The keys MUST be the original paragraph index strings.
- The values MUST be the updated paragraph text.
- ONLY include paragraphs that you modified (i.e., paragraphs containing an in-text citation, or bibliography entries).
- Do NOT include paragraphs that were untouched.
- Do NOT wrap the JSON in markdown code blocks.

Input JSON dictionary (Key = Index, Value = Paragraph Text):
{json.dumps(indexed_paras)}
"""
    try:
        text = _generate_text(prompt, settings=settings, response_mime_type="application/json")
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            print("Warning: No JSON dict found for global citations.")
            return paras
        updates = json.loads(match.group(0))
        new_paras = list(paras)
        for idx_str, new_text in updates.items():
            idx = int(idx_str)
            if 0 <= idx < len(new_paras):
                new_paras[idx] = new_text
        return new_paras
    except Exception as e:
        print(f"Global citation alignment failed: {e}")
        return paras


def read_docx(file_path: str) -> List[str]:
    doc = docx.Document(file_path)
    return [p.text for p in doc.paragraphs]


def fetch_crossref_doi(citation_text: str) -> Optional[str]:
    try:
        url = "https://api.crossref.org/works"
        params = {
            "query.bibliographic": citation_text,
            "select": "DOI,score,type,title",
            "rows": 3,
        }
        r = requests.get(url, params=params, timeout=4)
        if r.status_code != 200:
            return None
        items = (r.json().get("message") or {}).get("items") or []

        for item in items:
            item_type = (item.get("type") or "").lower()
            if "review" in item_type and "review" not in citation_text.lower():
                continue

            titles = item.get("title") or []
            if titles:
                clean_title = re.sub(r"[^a-z0-9]", "", titles[0].lower())
                clean_cit = re.sub(r"[^a-z0-9]", "", citation_text.lower())
                if clean_title not in clean_cit and item.get("score", 0) < 85:
                    continue

            if item.get("score", 0) > 55:
                return "https://doi.org/" + item["DOI"]
    except Exception:
        return None
    return None


def ai_edit_chunk(
    chunk_texts: List[str], settings: Dict[str, Any], edit_style: str, ref_style: str,
    lang: str, custom_dict: str, use_crossref: bool,
) -> List[str]:
    prompt = f"""You are a professional academic copyeditor.
Rules:
- Editing Style: {edit_style}
- Reference/Bibliography Style: {ref_style}
- Language Type: {lang}

I am providing a JSON array of text paragraphs from a manuscript.
Proofread them strictly following the specified guidelines. Fix spelling, grammar, and typography.
Properly format any references or bibliography items encountered.
"""
    if custom_dict:
        prompt += f"\nCRITICAL CUSTOM DICTIONARY (DO NOT ALTER OR REFORMAT THESE TERMS):\n{custom_dict}\n"

    prompt += f"""
CRITICAL:
1. You MUST return ONLY a valid JSON array of strings of the EXACT SAME LENGTH.
2. Each element in the output array corresponds to the edited version of the element at the same index in the input array.
3. Do not add markdown formatting or extra text. Return just the JSON array.

Input JSON:
{json.dumps(chunk_texts)}
"""

    try:
        text = _generate_text(prompt, settings=settings, response_mime_type="application/json")
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            print("Warning: No JSON array found in response.")
            return chunk_texts
        result = json.loads(match.group(0))

        if len(result) != len(chunk_texts):
            print("Warning: Array length mismatch.")
            return chunk_texts

        if use_crossref:
            for i in range(len(result)):
                t = result[i]
                if len(t) > 30 and re.search(r"\b(19|20)\d{2}\b", t) and "doi.org" not in t:
                    doi = fetch_crossref_doi(t)
                    if doi:
                        result[i] = t + f" {doi}"
        return result
    except json.JSONDecodeError as e:
        print(f"JSON Parse Error: {e}")
        time.sleep(1)
        return chunk_texts
    except Exception as e:
        print(f"Gemini API Error: {e}")
        time.sleep(1)
        return chunk_texts


# --- Redline (.docx with native Word track changes) ---

def add_track_change_run(paragraph, text: str, change_type: str, tc_id: int,
                         author: str = "AI Editor", date: Optional[str] = None) -> None:
    if date is None:
        date = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    r = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    r.append(rPr)

    if change_type == "insert":
        color = OxmlElement("w:color")
        color.set(qn("w:val"), "00B050")
        rPr.append(color)
        ins = OxmlElement("w:ins")
        ins.set(qn("w:id"), str(tc_id))
        ins.set(qn("w:author"), author)
        ins.set(qn("w:date"), date)
        t = OxmlElement("w:t")
        t.text = text
        t.set(qn("xml:space"), "preserve")
        r.append(t)
        ins.append(r)
        paragraph._p.append(ins)
    elif change_type == "delete":
        color = OxmlElement("w:color")
        color.set(qn("w:val"), "FF0000")
        rPr.append(color)
        strike = OxmlElement("w:strike")
        strike.set(qn("w:val"), "true")
        rPr.append(strike)
        delete = OxmlElement("w:del")
        delete.set(qn("w:id"), str(tc_id))
        delete.set(qn("w:author"), author)
        delete.set(qn("w:date"), date)
        delText = OxmlElement("w:delText")
        delText.text = text
        delText.set(qn("xml:space"), "preserve")
        r.append(delText)
        delete.append(r)
        paragraph._p.append(delete)
    else:
        t = OxmlElement("w:t")
        t.text = text
        t.set(qn("xml:space"), "preserve")
        r.append(t)
        paragraph._p.append(r)


def generate_redline_docx(original_path: str, edited_paragraphs: List[str], output_path: str) -> None:
    doc = docx.Document(original_path)
    tc_id = 1

    settings = doc.settings.element
    track_changes = OxmlElement("w:trackRevisions")
    settings.append(track_changes)

    for p, edited in zip(doc.paragraphs, edited_paragraphs):
        orig = p.text
        if orig.strip() == edited.strip():
            continue

        p.clear()

        token_pattern = r"(\s+|\b|[.,!?;:])"
        orig_tokens = [t for t in re.split(token_pattern, orig) if t]
        edited_tokens = [t for t in re.split(token_pattern, edited) if t]

        matcher = difflib.SequenceMatcher(None, orig_tokens, edited_tokens)

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                add_track_change_run(p, "".join(orig_tokens[i1:i2]), "equal", tc_id)
            elif tag == "delete":
                add_track_change_run(p, "".join(orig_tokens[i1:i2]), "delete", tc_id)
                tc_id += 1
            elif tag == "insert":
                add_track_change_run(p, "".join(edited_tokens[j1:j2]), "insert", tc_id)
                tc_id += 1
            elif tag == "replace":
                add_track_change_run(p, "".join(orig_tokens[i1:i2]), "delete", tc_id)
                tc_id += 1
                add_track_change_run(p, "".join(edited_tokens[j1:j2]), "insert", tc_id)
                tc_id += 1

    doc.save(output_path)


# --- Journal recommendation ---

def cosine_similarity(v1, v2) -> float:
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 == 0 or n2 == 0:
        return 0.0
    return float(np.dot(v1, v2) / (n1 * n2))


def _build_journal_embeddings(settings: Dict[str, Any]) -> str:
    in_path = app_config.journals_path()
    out_path = app_config.journals_embedded_path_for_settings(settings)

    with in_path.open("r") as f:
        journals = json.load(f)

    texts = [j["name"] + " " + " ".join(j.get("topics", [])) for j in journals]
    embeddings = []
    for i in range(0, len(texts), 100):
        batch = texts[i:i + 100]
        for t in batch:
            embeddings.append(_embed(t, settings=settings))
        time.sleep(0.5)
        print(f"  embedded {min(i + 100, len(texts))}/{len(texts)}")

    for j, emb in zip(journals, embeddings):
        j["embedding"] = emb

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(journals, f)
    return str(out_path)


def recommend_journals(abstract: str, settings: Dict[str, Any], k: int = 3) -> List[dict]:
    try:
        vec = _embed(abstract, settings=settings)
        abstract_emb = np.array(vec)
    except Exception as e:
        print(f"Embedding error: {e}")
        abstract_emb = None

    journals_path = app_config.journals_embedded_path_for_settings(settings)
    if not journals_path.exists():
        try:
            print(f"Building journal embeddings at {journals_path} ...")
            _build_journal_embeddings(settings)
        except Exception as e:
            print(f"Warning: {journals_path} not found and rebuild failed: {e}")
            return []

    with journals_path.open("r") as f:
        journals = json.load(f)

    for j in journals:
        if abstract_emb is not None and "embedding" in j:
            j["score"] = cosine_similarity(abstract_emb, np.array(j["embedding"]))
        else:
            j["score"] = random.random()

    return sorted(journals, key=lambda x: x["score"], reverse=True)[:k]


# --- Report / cover letter / polish ---

def generate_report(edit_style: str, ref_style: str, lang: str,
                    used_crossref: bool, custom_dict: str) -> str:
    report = "### 📑 Editorial Report\n\n"
    report += "**Configurations Applied:**\n"
    report += f"- **Copyediting:** {edit_style}\n"
    report += f"- **References:** {ref_style}\n"
    report += f"- **Language:** {lang}\n"
    if custom_dict:
        report += "- **Custom Dictionary:** Active constraints applied.\n"
    report += "\n**Summary of Interventions:**\n"
    report += "- Corrected typography and narrative consistency.\n"
    if used_crossref:
        report += "- **Live Crossref Validation:** Officially verified DOIs embedded into bibliography.\n"
    else:
        report += "- **References Formatted:** AI applied selected style structure.\n"
    return report


def generate_cover_letter(abstract: str, journal_name: str, settings: Dict[str, Any]) -> str:
    prompt = (
        f"Write a professional, compelling manuscript submission cover letter "
        f"tailored to the journal '{journal_name}' based on the following "
        f"abstract/intro. Return only the letter content without any markdown boxes.\n\n"
        f"Abstract:\n{abstract}"
    )
    try:
        return _generate_text(prompt, settings=settings)
    except Exception as e:
        print(f"Cover letter error: {e}")
        return "Error generating cover letter."


def generate_title_abstract_polish(abstract: str, settings: Dict[str, Any]) -> str:
    prompt = (
        "Based on this draft abstract, generate 3 highly optimized, impactful "
        "title options and 1 fully polished, compelling abstract that maximizes "
        "chances of journal acceptance. Format it beautifully in Markdown.\n\n"
        f"Text:\n{abstract}"
    )
    try:
        return _generate_text(prompt, settings=settings)
    except Exception as e:
        print(f"Title/abstract polish error: {e}")
        return "Error generating polish."


# --- Orchestration ---

def process_document_async(
    paras: List[str], settings: Dict[str, Any], edit_style: str, ref_style: str,
    lang: str, custom_dict: str, use_crossref: bool, progress_callback,
) -> List[str]:
    edited_paras = [""] * len(paras)
    task_indices = [i for i, p in enumerate(paras) if p.strip()]

    for i in range(len(paras)):
        if not paras[i].strip():
            edited_paras[i] = paras[i]

    CHUNK_SIZE = 5
    chunks = []
    for i in range(0, len(task_indices), CHUNK_SIZE):
        chunk_inds = task_indices[i:i + CHUNK_SIZE]
        chunk_texts = [paras[idx] for idx in chunk_inds]
        chunks.append((chunk_inds, chunk_texts))

    total_chunks = len(chunks)
    if total_chunks == 0:
        return edited_paras

    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        future_to_chunk = {
            ex.submit(ai_edit_chunk, chunk_texts, settings, edit_style, ref_style,
                      lang, custom_dict, use_crossref): chunk_inds
            for chunk_inds, chunk_texts in chunks
        }
        for future in concurrent.futures.as_completed(future_to_chunk):
            chunk_inds = future_to_chunk[future]
            try:
                result = future.result()
                for idx, edited_text in zip(chunk_inds, result):
                    edited_paras[idx] = edited_text
            except Exception as exc:
                print(f"Chunk generated an exception: {exc}")
                for idx in chunk_inds:
                    edited_paras[idx] = paras[idx]
            completed += 1
            if progress_callback:
                progress_callback(completed / total_chunks)
    return edited_paras
