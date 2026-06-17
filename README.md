# SOTA Graph RAG for NCERT Math Textbooks

This project builds a proper study RAG database with:

- semantic retrieval with Gemini embeddings
- graph traversal over curriculum concepts
- PDF page image understanding with Gemini vision
- page-level text + figure summaries
- concept seed graph for Chapter 2: Polynomials
- retrieval restricted by concept neighborhood

## What the NCERT chapter contains

The uploaded chapter is Chapter 2, *Polynomials*. It defines linear, quadratic, and cubic polynomials; explains zeroes as x-axis intersections; shows line/parabola/cubic graphs; and proves coefficient relationships for quadratic and cubic polynomials. The figures and tables on pages 3 to 8 are especially important because they connect algebraic form to geometric meaning. fileciteturn6file11L1-L26 fileciteturn6file6L1-L25 fileciteturn6file1L1-L24 fileciteturn6file5L1-L20 fileciteturn6file8L1-L14

The relations between zeroes and coefficients are on pages 19 to 22, including the quadratic sum/product formulas and the cubic pairwise-sum/product formulas. fileciteturn6file9L1-L21 fileciteturn6file19L1-L19

## Install

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Authenticate

```bat
gcloud auth application-default login
set GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
set GOOGLE_CLOUD_LOCATION=global
set GOOGLE_GENAI_USE_ENTERPRISE=True
```

## Ingest your folder

```bat
python build_index.py --docs "F:\Projects\Pedagogical_study_pkg\database\Maths" --out rag_store
```

## Ask a question

```bat
python query.py --store rag_store --question "Explain zeroes of a quadratic polynomial using the graph"
```

## Why this is better than the first prototype

The architecture in your learning-system spec says the system should model cognition, use a curriculum knowledge graph, and retrieve evidence only after concept resolution. It also says the graph is not just a content index; it is the teaching-order map. This implementation follows that structure instead of doing a flat vector search over every chunk. fileciteturn6file12L1-L29 fileciteturn6file17L1-L24

## Files

- `chapter_seed_polynomials.json` — concept graph seed for Chapter 2
- `build_index.py` — builds the database
- `query.py` — queries the database
- `pdf_vision.py` — page rendering and multimodal page summaries
- `rag_core.py` — retrieval and answer orchestration
