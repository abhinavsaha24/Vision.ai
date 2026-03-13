import React from "react";

function NewsFeed({ items }) {
  if (!items || items.length === 0) {
    return (
      <div>
        <div className="card-title">News Feed</div>
        <div className="text-dim" style={{ fontSize: "0.8rem" }}>No news available</div>
      </div>
    );
  }

  return (
    <div>
      <div className="card-title">News Feed</div>
      <div className="space-y">
        {items.slice(0, 10).map((item, i) => (
          <div key={i} style={{ borderBottom: "1px solid var(--border)", paddingBottom: 8 }}>
            <a
              href={item.url || "#"}
              target="_blank"
              rel="noreferrer"
              style={{
                color: "var(--text-primary)",
                textDecoration: "none",
                fontSize: "0.78rem",
                lineHeight: 1.4,
                display: "block"
              }}
            >
              {item.title || item}
            </a>
            {item.source && (
              <div className="metric-label" style={{ marginTop: 2 }}>
                {item.source}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default NewsFeed;