const STEPS = [
  {
    title: 'You start a case',
    body: 'Every project lives in its own case file — a fully separate corpus, search index, and history. Switch cases from the header any time; nothing crosses between them.',
  },
  {
    title: 'You provide the evidence — or let it go find some',
    body: 'Upload or paste trusted source documents — reports, notes, research. Or hand the Research Assistant a topic: it searches the web plus arXiv, CrossRef (papers and conference papers) and, best-effort, patents, fetches and cleans the sources itself, and adds them to the corpus for you. The Verify Source page can separately check whether any URL or DOI is a real, registered publication. Either way, this becomes the only thing RAGnarok is allowed to consider "true" for this case.',
  },
  {
    title: 'Chunking',
    body: 'Each document is split into small, sentence-grouped chunks, so retrieval can point to a precise passage instead of an entire document.',
  },
  {
    title: 'Dense + sparse indexing',
    body: 'Every chunk is embedded (for meaning-based search) and separately indexed with BM25 (for exact-keyword search), so both are ready the moment you start typing.',
  },
  {
    title: 'You write',
    body: 'As you finish a sentence, it\u2019s sent to the backend automatically — no button to click, no separate fact-checking step.',
  },
  {
    title: 'Hybrid retrieval',
    body: 'The sentence is compared against the corpus using both search methods at once; their scores are normalized and blended into one ranked list of the most relevant evidence.',
  },
  {
    title: 'LLM judge',
    body: 'The sentence and its best evidence are handed to an AI model, which decides: supported, contradicted, or unverified — and explains why in one sentence.',
  },
  {
    title: 'Verdict, inline',
    body: 'The sentence is marked with a colored underline and a \u2713 / \u2715 / \u2014 mark right in your draft. Click it to see the exact source passage.',
  },
]

export default function AboutPage() {
  return (
    <main className="page-single">
      <div className="page-header">
        <h2>How RAGnarok Works</h2>
        <p className="muted page-intro">
          A writing tool that checks factual claims against a trusted document corpus in real time —
          here's the full pipeline, from source document to inline verdict.
        </p>
      </div>

      <div className="about-steps">
        {STEPS.map((step, i) => (
          <div className="about-step" key={step.title}>
            <div className="about-step-num">{i + 1}</div>
            <div className="about-step-body">
              <h3>{step.title}</h3>
              <p>{step.body}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="about-footer">
        <h3>Why hybrid retrieval?</h3>
        <p>
          Meaning-based search (dense) catches paraphrased claims that don't share exact words with
          the source. Keyword search (sparse/BM25) catches exact names, numbers, and terms that
          embeddings can sometimes blur past. Blending both catches more true matches than either one
          alone.
        </p>
        <h3>Why a database?</h3>
        <p>
          Every source document and every claim you've ever checked is stored permanently (SQLite),
          so your corpus and your case log both survive a server restart — nothing lives only in
          memory.
        </p>
        <h3>What does the Research Assistant actually do?</h3>
        <p>
          It expands your topic into a few different search queries (so it isn't just rephrasing
          the same search), fetches and cleans the resulting web pages, ingests them into the case
          exactly like a manually pasted document, and then drafts a short paragraph using only that
          evidence. The draft is meant as a rough starting point, not a finished answer — dropping it
          into Draft runs it back through the same sentence-by-sentence verification as anything you
          type yourself, so nothing it wrote gets a free pass.
        </p>
      </div>
    </main>
  )
}
