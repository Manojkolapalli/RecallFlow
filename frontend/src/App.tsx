import { Link, Route, Routes } from "react-router-dom";

function Brand() {
  return (
    <Link className="brand" to="/" aria-label="RecallFlow home">
      <span className="brand-mark" aria-hidden="true">
        r<span>.</span>
      </span>
      <span>RecallFlow</span>
    </Link>
  );
}

function ArrowIcon() {
  return (
    <svg
      aria-hidden="true"
      className="arrow-icon"
      viewBox="0 0 20 20"
      fill="none"
    >
      <path d="M3.75 10h12.5M10 3.75 16.25 10 10 16.25" />
    </svg>
  );
}

function Navigation() {
  return (
    <header className="site-header">
      <Brand />
      <nav className="main-nav" aria-label="Main navigation">
        <a href="#why-recallflow">Why RecallFlow</a>
        <a href="#how-it-works">How it works</a>
      </nav>
      <Link className="nav-cta" to="/workspace">
        Get started <ArrowIcon />
      </Link>
    </header>
  );
}

function LandingPage() {
  return (
    <div className="page-shell">
      <Navigation />
      <main>
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero-copy">
            <p className="eyebrow">
              <span className="eyebrow-line" />
              A quieter kind of intelligence
            </p>
            <h1 id="hero-title">
              Good conversations
              <br />
              <span>should stay with you.</span>
            </h1>
            <div className="hero-bottom">
              <p className="hero-description">
                RecallFlow turns the things you hear into the things you can
                find, remember, and act on.
              </p>
              <Link className="button button-primary" to="/workspace">
                Get started <ArrowIcon />
              </Link>
            </div>
          </div>

          <aside className="margin-note" aria-label="Product note">
            <span className="note-index">A note on memory</span>
            <p>
              The useful detail is rarely the loudest one. It’s the one you
              need six weeks later.
            </p>
            <span className="note-rule" />
            <span className="note-foot">Recall, without the rewind.</span>
          </aside>

          <div className="hero-meta" aria-hidden="true">
            <span>For the ideas that keep moving</span>
            <span>01 — 03</span>
          </div>
        </section>

        <section className="intro-section" id="why-recallflow">
          <p className="section-label">A little less lost</p>
          <div className="intro-content">
            <h2>
              Your best thinking
              <br />
              happens <em>together.</em>
            </h2>
            <p>
              Meetings, lectures, passing thoughts — they add up to how we
              work and what we know. RecallFlow gives those conversations a
              place to land, so their meaning doesn’t disappear when the call
              ends.
            </p>
          </div>
        </section>

        <section className="process-section" id="how-it-works">
          <div className="process-heading">
            <p className="section-label">A simple rhythm</p>
            <p className="process-aside">From conversation to clarity.</p>
          </div>
          <div className="process-grid">
            <article className="process-item">
              <span className="process-number">01</span>
              <h3>Bring it in</h3>
              <p>Save a transcript from the conversations worth keeping.</p>
            </article>
            <article className="process-item">
              <span className="process-number">02</span>
              <h3>Find the thread</h3>
              <p>Decisions, details, and next steps become easier to revisit.</p>
            </article>
            <article className="process-item">
              <span className="process-number">03</span>
              <h3>Pick up where you left off</h3>
              <p>Ask a question and return to the context behind the answer.</p>
            </article>
          </div>
        </section>

        <section className="closing-section">
          <p className="section-label">Keep the good parts close</p>
          <div className="closing-line">
            <h2>Let the conversation continue.</h2>
            <Link className="button button-secondary" to="/workspace">
              Get started <ArrowIcon />
            </Link>
          </div>
        </section>
      </main>
      <footer className="site-footer">
        <Brand />
        <span>Make room for what matters.</span>
        <span>© RecallFlow</span>
      </footer>
    </div>
  );
}

function WorkspacePlaceholder() {
  return (
    <div className="page-shell">
      <Navigation />
      <main className="placeholder-page">
        <p className="eyebrow">
          <span className="eyebrow-line" />
          Your next chapter
        </p>
        <h1>
          The workspace
          <br />
          <span>is taking shape.</span>
        </h1>
        <p className="hero-description">
          This is where your conversations will find a home. We’re getting
          things ready.
        </p>
        <Link className="text-link" to="/">
          <span aria-hidden="true">←</span> Back to RecallFlow
        </Link>
      </main>
      <footer className="site-footer">
        <Brand />
        <span>Make room for what matters.</span>
        <span>© RecallFlow</span>
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/workspace" element={<WorkspacePlaceholder />} />
      <Route path="*" element={<LandingPage />} />
    </Routes>
  );
}
